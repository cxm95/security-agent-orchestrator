"""OpenCode CLI provider implementation.

OpenCode is an open-source AI coding agent with a TUI interface.
This provider wraps the OpenCode TUI in tmux for CAO integration.

Key characteristics of OpenCode v1.3.x:
- Full TUI using alternate screen buffer (no ``--no-alt-screen`` option)
- tmux ``capture-pane`` reliably reads the alternate screen content
- Input: bracketed paste + 1 Enter to submit
- Exit: Ctrl-C (C-c)
- Processing indicator: spinner at bottom line with "esc interrupt"
- Completed indicator: "▣  Build · model-name · Ns" with timing
- User messages prefixed with ┃ (vertical bar)
- Thinking blocks: "┃  Thinking: ..."
- Session restore: after exit, output contains "opencode -s ses_xxx" for resuming

Permission / yolo mode:
  OpenCode does **not** have a ``--yolo`` CLI flag.  Auto-approve is
  enabled by setting ``"permission": "allow"`` in the config.  The
  easiest way to inject this at runtime is via the
  ``OPENCODE_CONFIG_CONTENT`` environment variable which accepts inline
  JSON.

System prompt:
  System prompts are NOT injected via CLI flags.  Instead, the MCP
  server prepends the agent profile's ``system_prompt`` to the first
  message sent via tmux (handoff/assign).  This avoids shell-escaping
  issues with long, multi-line prompts.

Model selection:
  ``opencode -m provider/model``  (e.g. ``closeai/glm-5``)

Non-interactive run mode:
  ``opencode run "message"``  (one-shot execution, used by phase scripts)
"""

import json
import logging
import re
import shlex
from typing import Dict, Optional

from cli_agent_orchestrator.clients.tmux import tmux_client
from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.base import BaseProvider
from cli_agent_orchestrator.utils.agent_profiles import load_agent_profile
from cli_agent_orchestrator.utils.terminal import wait_for_shell, wait_until_status

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """Exception raised for provider-specific errors."""

    pass


# Regex patterns for OpenCode output analysis
ANSI_CODE_PATTERN = r"\x1b\[[0-9;]*[a-zA-Z]"

# === IDLE detection ===
# Welcome screen placeholder text (initial idle)
WELCOME_PATTERN = r"Ask anything\.\.\."
# Empty input area: ┃ followed by only whitespace on the line
INPUT_IDLE_PATTERN = r"^\s*┃\s*$"

# === PROCESSING detection ===
# Spinner line at the very bottom: diamond/block characters + "esc interrupt"
SPINNER_PATTERN = r"esc\s+interrupt"

# === COMPLETED detection ===
# Completed marker with timing: ▣  Build · model-name · 5.2s
COMPLETED_MARKER_PATTERN = r"▣\s+Build\s+·\s+\S+.*·\s+[\d.]+s"
# Build marker without timing (still processing or just started)
BUILD_MARKER_PATTERN = r"▣\s+Build\s+·\s+\S+"

# === User message detection ===
# User messages have ┃ followed by non-whitespace content
USER_MESSAGE_PATTERN = r"^\s*┃\s+\S"

# === Thinking block ===
THINKING_PATTERN = r"┃\s+Thinking:"

# === Tool execution markers ===
TOOL_WRITE_PATTERN = r"┃\s+#\s+Wrote\s+"
TOOL_BASH_PATTERN = r"┃\s+\$\s+"

# === Footer patterns ===
# Initial footer: "tab agents  ctrl+p commands"
# After response footer: "25.7K (13%)  ctrl+p commands" (token count replaces tab info)
# Match either variant via the common suffix.
FOOTER_PATTERN = r"ctrl\+p\s+commands"
FOOTER_VERSION_PATTERN = r"OpenCode\s+[\d.]+"
# Footer model info bar (bottom of input area)
FOOTER_MODEL_PATTERN = r"Build\s+\S+\s+\S+"

# === Log file idle pattern (pipe-pane raw output) ===
IDLE_PATTERN_LOG = r"ctrl\+p\s+commands"

# === Session ID pattern (appears after Ctrl-C exit) ===
# After opencode exits, it prints a session restore hint like:
#   Session   Greeting
#   Continue  opencode -s ses_2c57b2436ffepiOds7uuqq2hHd
SESSION_ID_PATTERN = r"opencode\s+-s\s+(ses_\w+)"

# Number of lines from bottom to check for status indicators
STATUS_TAIL_LINES = 5


class OpenCodeProvider(BaseProvider):
    """Provider for OpenCode CLI tool integration."""

    # Default env-var config that enables auto-approve (permission: allow)
    # and extends bash tool timeout to 12 hours.
    _DEFAULT_CONFIG = {
        "permission": "allow",
    }
    _DEFAULT_ENV_VARS = {
        "OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS": "43200000",
    }

    def __init__(
        self,
        terminal_id: str,
        session_name: str,
        window_name: str,
        agent_profile: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
    ):
        super().__init__(terminal_id, session_name, window_name)
        self._initialized = False
        self._agent_profile = agent_profile
        self._input_received = False
        if env_vars:
            self.set_env_vars(env_vars)

    @property
    def paste_enter_count(self) -> int:
        """OpenCode TUI submits on single Enter after bracketed paste."""
        return 1

    def _build_opencode_command(self) -> str:
        """Build OpenCode command with optional agent profile.

        The command structure is::

            OPENCODE_CONFIG_CONTENT='{"permission":"allow",...}' \
            OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS=43200000 \
            opencode [-m provider/model]

        OpenCode's ``--prompt`` flag auto-submits its value as the first
        user message (not a true system prompt).  When the agent profile
        contains a ``system_prompt``, the provider injects it via
        ``--prompt`` so the model receives the instructions before any
        task message arrives from handoff/assign.

        Returns a fully escaped shell command string for tmux.
        """
        command_parts = ["opencode"]

        # Merge runtime config: start with defaults, allow caller overrides
        runtime_config: dict = dict(self._DEFAULT_CONFIG)

        if self._agent_profile is not None:
            try:
                profile = load_agent_profile(self._agent_profile)

                if profile.model:
                    command_parts.extend(["-m", profile.model])

                # NOTE: system_prompt is NOT injected here via --prompt.
                # It is prepended to the first message by the MCP server
                # (handoff/assign) to avoid shell-escaping issues.

                # Translate agent profile mcpServers into OpenCode's mcp config.
                # Agent profile format:  {name: {command, args, env, type}}
                # OpenCode format:       {name: {type:"local", command:[cmd, ...args], environment:{...}}}
                if profile.mcpServers:
                    mcp_section: dict = {}
                    for srv_name, srv_cfg in profile.mcpServers.items():
                        if isinstance(srv_cfg, dict):
                            cfg = srv_cfg
                        else:
                            cfg = srv_cfg.model_dump(exclude_none=True)

                        srv_type = cfg.get("type", "local")

                        if srv_type == "remote":
                            # Remote/SSE server — only needs url
                            oc_entry: dict = {
                                "type": "remote",
                                "enabled": True,
                                "url": cfg["url"],
                                "oauth": False,
                            }
                            if "timeout" in cfg:
                                oc_entry["timeout"] = cfg["timeout"]
                        else:
                            # Local stdio server
                            oc_entry = {"type": "local", "enabled": True}
                            cmd_list = [cfg["command"]] if "command" in cfg else []
                            if "args" in cfg and cfg["args"]:
                                cmd_list.extend(cfg["args"])
                            oc_entry["command"] = cmd_list
                            # Translate env → environment
                            env = dict(cfg.get("env", {}) or {})
                            # Always forward CAO_TERMINAL_ID so MCP servers can
                            # identify the calling terminal.
                            env["CAO_TERMINAL_ID"] = "{env:CAO_TERMINAL_ID}"
                            if env:
                                oc_entry["environment"] = env
                            if "timeout" in cfg:
                                oc_entry["timeout"] = cfg["timeout"]

                        mcp_section[srv_name] = oc_entry
                    runtime_config["mcp"] = mcp_section

            except Exception as e:
                raise ProviderError(f"Failed to load agent profile '{self._agent_profile}': {e}")

        # Build the env-var prefix that injects runtime config + bash timeout
        env_prefix_parts: list[str] = []

        # Only inject OPENCODE_CONFIG_CONTENT if caller hasn't explicitly set it
        if "OPENCODE_CONFIG_CONTENT" not in self._env_vars:
            config_json = json.dumps(runtime_config)
            env_prefix_parts.append(
                f"OPENCODE_CONFIG_CONTENT={shlex.quote(config_json)}"
            )

        for key, default_val in self._DEFAULT_ENV_VARS.items():
            if key not in self._env_vars:
                env_prefix_parts.append(f"{key}={shlex.quote(default_val)}")

        opencode_cmd = shlex.join(command_parts)

        # Ensure localhost API calls bypass any HTTP proxy
        proxy_unset = "unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy;"

        if env_prefix_parts:
            return proxy_unset + " " + " ".join(env_prefix_parts) + " " + opencode_cmd
        return proxy_unset + " " + opencode_cmd

    def initialize(self) -> bool:
        """Initialize OpenCode provider by starting opencode TUI."""
        if not wait_for_shell(tmux_client, self.session_name, self.window_name, timeout=10.0):
            raise TimeoutError("Shell initialization timed out after 10 seconds")

        # Apply environment variables before launching CLI
        if self._env_vars:
            self._apply_env_vars()

        # Build command with flags
        command = self._build_opencode_command()
        tmux_client.send_keys(self.session_name, self.window_name, command)

        # Wait for OpenCode TUI to be ready (IDLE = input prompt visible)
        if not wait_until_status(
            self,
            {TerminalStatus.IDLE},
            timeout=60.0,
            polling_interval=1.0,
        ):
            raise TimeoutError("OpenCode initialization timed out after 60 seconds")

        self._initialized = True
        return True

    def get_status(self, tail_lines: Optional[int] = None) -> TerminalStatus:
        """Get OpenCode status by analyzing terminal output.

        OpenCode TUI layout (captured by tmux capture-pane):
        - Main area: message history with ┃ markers
        - Bottom: input area + footer bar
        - During processing: spinner with "esc interrupt" at very bottom
        - After completion: "▣  Build · model · Ns" with timing
        """
        output = tmux_client.get_history(
            self.session_name, self.window_name, tail_lines=tail_lines
        )

        if not output:
            return TerminalStatus.ERROR

        # Strip ANSI codes for reliable matching
        clean_output = re.sub(ANSI_CODE_PATTERN, "", output)

        # Get bottom lines for status bar analysis
        all_lines = clean_output.splitlines()
        bottom_lines = all_lines[-STATUS_TAIL_LINES:] if len(all_lines) >= STATUS_TAIL_LINES else all_lines
        bottom_text = "\n".join(bottom_lines)

        # 1) PROCESSING: spinner with "esc interrupt" at the bottom
        if re.search(SPINNER_PATTERN, bottom_text):
            return TerminalStatus.PROCESSING

        # 2) Check for welcome screen (initial IDLE before any input)
        if re.search(WELCOME_PATTERN, clean_output):
            return TerminalStatus.IDLE

        # 3) COMPLETED: has completed build marker with timing + footer visible
        #    The completed marker "▣  Build · model · Ns" appears in the main area.
        #    The footer "tab agents  ctrl+p commands" appears at the bottom.
        has_completed_marker = bool(re.search(COMPLETED_MARKER_PATTERN, clean_output))
        has_footer = bool(re.search(FOOTER_PATTERN, bottom_text))

        if has_completed_marker and has_footer:
            # Check if there's user input in the input area (bottom lines with ┃)
            # If input area has text, it means user typed but hasn't submitted yet
            # If input area is empty, agent has completed and is waiting for next input
            if self._input_received:
                return TerminalStatus.COMPLETED
            return TerminalStatus.IDLE

        # 4) If footer is visible but no completed marker, could be idle or processing
        if has_footer and not has_completed_marker:
            # Check if there's a build marker without timing (still processing)
            if re.search(BUILD_MARKER_PATTERN, clean_output) and not has_completed_marker:
                return TerminalStatus.PROCESSING
            return TerminalStatus.IDLE

        # 5) If we see thinking blocks, agent is processing
        if re.search(THINKING_PATTERN, clean_output):
            return TerminalStatus.PROCESSING

        # Default: if we can't determine state, assume processing
        return TerminalStatus.PROCESSING

    def get_idle_pattern_for_log(self) -> str:
        """Return OpenCode IDLE pattern for log files.

        In pipe-pane raw output, the footer text "ctrl+p commands" is reliably
        present when the TUI is in idle state.
        """
        return IDLE_PATTERN_LOG

    def extract_last_message_from_script(self, script_output: str) -> str:
        """Extract OpenCode's final response from terminal output.

        OpenCode TUI output structure:
          ┃
          ┃  user message
          ┃

          ┃  Thinking: ...

             response text here
             more response...

             ▣  Build · model-name · 5.2s

          ┃
          ┃
          ┃  Build  model-name provider (url)      /path
          ╹▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀...

        Strategy:
        1. Find the last user message block (┃ + non-empty text)
        2. Find the completed marker (▣  Build · model · Ns) after it
        3. Extract text between user message end and completed marker
        4. Strip thinking blocks and tool markers
        """
        clean_output = re.sub(ANSI_CODE_PATTERN, "", script_output)
        lines = clean_output.splitlines()

        # Find the last user message block
        last_user_line_idx = -1
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i]
            # User message: ┃ followed by non-whitespace, not a Thinking block,
            # not a tool marker, not the footer model bar
            if re.match(r"\s*┃\s+\S", line):
                stripped = line.strip().lstrip("┃").strip()
                # Skip thinking blocks
                if stripped.startswith("Thinking:"):
                    continue
                # Skip tool output lines ($ commands, # Wrote, etc.)
                if re.match(r"^[$#→←✱◇◈%]", stripped):
                    continue
                # Skip footer model bar
                if re.match(r"^Build\s+\S+\s+\S+", stripped):
                    continue
                # Skip lines that are part of tool output (indented content after $)
                if re.match(r"^┃\s+[a-z]", line) and i > 0:
                    prev = lines[i - 1].strip().lstrip("┃").strip()
                    if prev.startswith("$"):
                        continue
                last_user_line_idx = i
                break

        if last_user_line_idx == -1:
            raise ValueError("No user message found in OpenCode output")

        # Find content after the user message block
        # Skip past the user message and any empty ┃ lines following it
        content_start = last_user_line_idx + 1
        while content_start < len(lines):
            line = lines[content_start].strip()
            if line == "┃" or line == "" or re.match(r"^\s*┃\s*$", lines[content_start]):
                content_start += 1
            else:
                break

        # Find the completed marker after user message
        completed_marker_idx = -1
        for i in range(content_start, len(lines)):
            if re.search(COMPLETED_MARKER_PATTERN, lines[i]):
                completed_marker_idx = i
                # Use the LAST completed marker (in case of multiple rounds)
                # Keep searching for a later one
        # Re-search: find the last completed marker after content_start
        for i in range(len(lines) - 1, content_start - 1, -1):
            if re.search(COMPLETED_MARKER_PATTERN, lines[i]):
                completed_marker_idx = i
                break

        if completed_marker_idx == -1:
            # No completed marker; take everything until the footer
            end_idx = len(lines)
            for i in range(content_start, len(lines)):
                if re.search(FOOTER_PATTERN, lines[i]):
                    end_idx = i
                    break
                # Stop at input area (empty ┃ lines at bottom)
                if re.match(r"^\s*╹", lines[i]):
                    end_idx = i
                    break
        else:
            end_idx = completed_marker_idx

        # Extract response lines
        response_lines = []
        for i in range(content_start, end_idx):
            line = lines[i]
            # Strip the ┃ prefix if present
            stripped = re.sub(r"^\s*┃\s?", "", line)
            # Strip the right-side panel (█ column and everything after)
            stripped = re.sub(r"\s*█.*$", "", stripped)
            response_lines.append(stripped)

        response_text = "\n".join(response_lines).strip()

        if not response_text:
            raise ValueError("Empty OpenCode response - no content found")

        return response_text

    def exit_cli(self) -> str:
        """Get the command to exit OpenCode CLI.

        OpenCode TUI exits on Ctrl-C, but exit_cli returns a string command.
        The terminal service will send this via send_keys.
        For OpenCode, we use C-c which tmux interprets as Ctrl-C.
        """
        return "C-c"

    def graceful_exit(self) -> Optional[str]:
        """Gracefully exit OpenCode and extract the session ID for resuming.

        Sends Ctrl-C to exit the TUI, waits for the shell to return, then
        parses the exit output for the session restore hint:
            Session   Greeting
            Continue  opencode -s ses_2c57b2436ffepiOds7uuqq2hHd

        Returns:
            The session identifier (e.g. ``ses_2c57b2436ffepiOds7uuqq2hHd``),
            or ``None`` if the pattern was not found.
        """
        # Send Ctrl-C to exit the TUI
        tmux_client.send_special_key(self.session_name, self.window_name, "C-c")

        # Wait for the shell prompt to reappear (up to 10 s)
        if not wait_for_shell(tmux_client, self.session_name, self.window_name, timeout=10.0):
            logger.warning("OpenCode did not exit within 10 s after Ctrl-C")
            self._initialized = False
            return None

        # Capture terminal output (the exit message is in the scrollback buffer)
        output = tmux_client.get_history(
            self.session_name, self.window_name, tail_lines=30
        )

        session_id = self.extract_session_id(output)
        self._initialized = False
        return session_id

    @staticmethod
    def extract_session_id(output: str) -> Optional[str]:
        """Extract OpenCode session ID from terminal output after exit.

        Looks for the pattern ``opencode -s ses_xxx`` in the output.

        Args:
            output: Terminal output captured after OpenCode exits.

        Returns:
            Session ID string, or ``None`` if not found.
        """
        if not output:
            return None
        clean_output = re.sub(ANSI_CODE_PATTERN, "", output)
        match = re.search(SESSION_ID_PATTERN, clean_output)
        return match.group(1) if match else None

    def cleanup(self) -> None:
        """Clean up OpenCode CLI provider."""
        self._initialized = False
        self._input_received = False

    def mark_input_received(self) -> None:
        """Track that user input has been sent for status detection.

        After input is sent, get_status() should return COMPLETED (not IDLE)
        when a response with a completed marker is visible.
        """
        self._input_received = True
