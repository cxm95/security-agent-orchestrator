"""Script provider implementation.

A lightweight provider that runs an arbitrary shell script (or command) inside a
tmux window.  Unlike the CLI-agent providers (Claude Code, Codex, OpenCode …)
the script provider does **not** wrap an interactive TUI – it simply executes a
command, monitors whether the process is still running, and captures stdout once
it exits.

Use-cases:
- One-shot automation scripts (build, deploy, scan, …)
- Long-running batch jobs whose output you want to capture via CAO
- Any task that does not need an interactive AI agent

Key design decisions:
- Status is determined by checking whether the script process is still alive
  (shell prompt visible at the bottom → COMPLETED, otherwise PROCESSING).
- ``extract_last_message_from_script`` returns the **full** script output
  (minus the initial command line and final shell prompt).
- ``exit_cli`` returns ``C-c`` so the terminal service can interrupt a running
  script the same way it would an agent.
- Environment variables and the script command are injected during
  ``initialize()``.
"""

import logging
import re
import shlex
from typing import Dict, List, Optional

from cli_agent_orchestrator.clients.tmux import tmux_client
from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.base import BaseProvider
from cli_agent_orchestrator.utils.terminal import wait_for_shell

logger = logging.getLogger(__name__)

# ANSI escape codes
ANSI_CODE_PATTERN = r"\x1b\[[0-9;]*[a-zA-Z]"

# Shell prompt pattern – detects common Bash/Zsh prompts at the end of output.
# Matches lines ending with $ or # (optionally preceded by user@host:path).
SHELL_PROMPT_PATTERN = r"[$#]\s*$"

# Number of bottom lines to inspect for the shell prompt.
PROMPT_TAIL_LINES = 3


class ScriptProvider(BaseProvider):
    """Provider that executes a shell script / command in tmux.

    Parameters
    ----------
    terminal_id : str
        Unique terminal identifier.
    session_name : str
        Tmux session name.
    window_name : str
        Tmux window name.
    script_path : str
        Absolute path to the script **or** an inline shell command string.
    script_args : list[str] | None
        Positional arguments to pass to *script_path*.
    env_vars : dict[str, str] | None
        Extra environment variables exported before launching the script.
    agent_profile : str | None
        Unused – kept for API compatibility with other providers.
    """

    def __init__(
        self,
        terminal_id: str,
        session_name: str,
        window_name: str,
        script_path: str = "",
        script_args: Optional[List[str]] = None,
        env_vars: Optional[Dict[str, str]] = None,
        agent_profile: Optional[str] = None,
    ):
        super().__init__(terminal_id, session_name, window_name)
        self._script_path = script_path
        self._script_args = script_args or []
        self._agent_profile = agent_profile
        self._initialized = False
        if env_vars:
            self.set_env_vars(env_vars)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def paste_enter_count(self) -> int:
        """Plain shell – single Enter submits."""
        return 1

    # ------------------------------------------------------------------
    # Command building
    # ------------------------------------------------------------------

    def _build_script_command(self) -> str:
        """Build the shell command string to execute.

        Returns a properly shell-escaped command. If *script_path* looks like
        an absolute/relative path it is quoted; otherwise it is treated as a
        raw shell snippet (e.g. ``"echo hello && sleep 5"``).
        """
        if not self._script_path:
            raise ValueError("script_path must be provided for ScriptProvider")

        parts = [self._script_path] + self._script_args
        return shlex.join(parts)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Start the script inside the tmux window."""
        if not wait_for_shell(tmux_client, self.session_name, self.window_name, timeout=10.0):
            raise TimeoutError("Shell initialization timed out after 10 seconds")

        # Export environment variables first
        if self._env_vars:
            self._apply_env_vars()

        # Send the script command
        command = self._build_script_command()
        tmux_client.send_keys(self.session_name, self.window_name, command)

        self._initialized = True
        return True

    # ------------------------------------------------------------------
    # Status detection
    # ------------------------------------------------------------------

    def get_status(self, tail_lines: Optional[int] = None) -> TerminalStatus:
        """Determine whether the script is still running.

        Strategy: capture the bottom few lines of the terminal.  If a shell
        prompt (``$`` or ``#``) is visible at the very end the process has
        exited → ``COMPLETED``.  Otherwise it is still ``PROCESSING``.
        """
        output = tmux_client.get_history(
            self.session_name, self.window_name, tail_lines=tail_lines
        )

        if not output:
            return TerminalStatus.ERROR

        clean = re.sub(ANSI_CODE_PATTERN, "", output)
        lines = clean.splitlines()
        bottom = lines[-PROMPT_TAIL_LINES:] if len(lines) >= PROMPT_TAIL_LINES else lines

        # Check if any of the bottom lines looks like a shell prompt
        for line in reversed(bottom):
            stripped = line.strip()
            if stripped and re.search(SHELL_PROMPT_PATTERN, stripped):
                return TerminalStatus.COMPLETED

        return TerminalStatus.PROCESSING

    def get_idle_pattern_for_log(self) -> str:
        """Shell prompt characters for log-file pre-check."""
        return r"[$#]\s*$"

    # ------------------------------------------------------------------
    # Output extraction
    # ------------------------------------------------------------------

    def extract_last_message_from_script(self, script_output: str) -> str:
        """Return the script's stdout, stripping the command line and trailing prompt.

        The tmux capture typically looks like::

            user@host:~/dir$ /path/to/script.sh arg1
            <script output line 1>
            <script output line 2>
            user@host:~/dir$

        We strip the first line (command invocation) and the last prompt line.
        """
        clean = re.sub(ANSI_CODE_PATTERN, "", script_output)
        lines = clean.splitlines()

        if not lines:
            raise ValueError("Empty script output")

        # Find where the command starts (first line with a prompt + command).
        # The invocation line looks like "user@host:path$ /path/to/script args"
        # – the `$` or `#` is followed by the command, NOT at end-of-line.
        start = 0
        script_basename = self._script_path.split("/")[-1] if self._script_path else ""
        for i, line in enumerate(lines):
            if script_basename and script_basename in line and re.search(r"[$#]\s", line):
                start = i + 1
                break

        # Find where the trailing prompt is
        end = len(lines)
        for i in range(len(lines) - 1, start - 1, -1):
            stripped = lines[i].strip()
            if stripped and re.search(SHELL_PROMPT_PATTERN, stripped):
                end = i
                break

        result = "\n".join(lines[start:end]).strip()
        if not result:
            raise ValueError("Empty script output after stripping prompts")
        return result

    # ------------------------------------------------------------------
    # Exit / cleanup
    # ------------------------------------------------------------------

    def exit_cli(self) -> str:
        """Interrupt the running script with Ctrl-C."""
        return "C-c"

    def cleanup(self) -> None:
        """Reset provider state."""
        self._initialized = False
