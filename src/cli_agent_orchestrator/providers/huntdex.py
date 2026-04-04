"""Huntdex provider implementation.

A lightweight provider that submits tasks to the Huntdex API Server via
copilot-ui.py running in interactive REPL mode.  The provider does **not**
configure any MCP tools, does not manage session identifiers, and is designed
to be used exclusively as a handoff target (leaf worker).

The actual task execution is handled by whatever backend is paired with the
Huntdex API Server (e.g. copilot-fork.sh → Copilot CLI).

Lifecycle:
    1. ``initialize()`` launches copilot-ui.py, waits for ``Huntdex>`` prompt.
    2. CAO sends the handoff message as REPL input.
    3. copilot-ui.py submits the task to the API Server and blocks.
    4. When the backend completes the task, the result is displayed.
    5. ``get_status()`` detects ``COMPLETED`` when the ``Huntdex>`` prompt
       reappears after a ``✅ 任务完成`` or ``❌`` marker.
    6. ``extract_last_message_from_script()`` returns the result block.

Constraints:
    - Single instance only (API Server uses 1:1 client pairing).
    - No MCP tool configuration, no session persistence.
"""

import logging
import os
import re
from typing import Optional

from cli_agent_orchestrator.clients.tmux import tmux_client
from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.base import BaseProvider
from cli_agent_orchestrator.utils.terminal import wait_for_shell

logger = logging.getLogger(__name__)

ANSI_CODE_PATTERN = r"\x1b\[[0-9;]*[a-zA-Z]"

# Default path to copilot-ui.py; override with HUNTDEX_UI_PATH env var.
_DEFAULT_UI_PATH = "/home/ubuntu/projects/huntdex-cao/huntdex-api-server/copilot-ui.py"

# Markers in copilot-ui.py output
PROMPT_MARKER = "Huntdex>"
TASK_SUBMITTED = "📤 任务已提交"
TASK_WAITING = "⏳ 等待执行结果"
TASK_DONE = "✅ 任务完成"
TASK_ERROR = "❌"

# How many bottom lines to inspect for status detection
STATUS_TAIL_LINES = 10


class HuntdexProvider(BaseProvider):
    """Provider that delegates tasks to the Huntdex API Server via copilot-ui.py.

    Parameters
    ----------
    terminal_id : str
        Unique terminal identifier.
    session_name : str
        Tmux session name.
    window_name : str
        Tmux window name.
    agent_profile : str | None
        Ignored — Huntdex provider does not use agent profiles.
    """

    def __init__(
        self,
        terminal_id: str,
        session_name: str,
        window_name: str,
        agent_profile: Optional[str] = None,
    ):
        super().__init__(terminal_id, session_name, window_name)
        self._agent_profile = agent_profile
        self._initialized = False
        self._input_received = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def paste_enter_count(self) -> int:
        """Single Enter submits in the copilot-ui REPL."""
        return 1

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Launch copilot-ui.py and wait for the Huntdex> prompt."""
        if not wait_for_shell(tmux_client, self.session_name, self.window_name, timeout=10.0):
            raise TimeoutError("Shell initialization timed out after 10 seconds")

        if self._env_vars:
            self._apply_env_vars()

        ui_path = os.environ.get("HUNTDEX_UI_PATH", _DEFAULT_UI_PATH)
        command = f"python3 {ui_path}"
        tmux_client.send_keys(self.session_name, self.window_name, command)

        self._initialized = True
        logger.info(f"Huntdex provider initialized for terminal {self.terminal_id}")
        return True

    # ------------------------------------------------------------------
    # Status detection
    # ------------------------------------------------------------------

    def get_status(self, tail_lines: Optional[int] = None) -> TerminalStatus:
        """Detect status by parsing copilot-ui.py terminal output.

        State machine:
            - ``Huntdex>`` visible + no prior input → IDLE (ready for task)
            - ``Huntdex>`` visible + input was sent  → COMPLETED (task done)
            - ``📤`` / ``⏳`` visible                → PROCESSING
            - ``❌`` errors + ``Huntdex>``           → COMPLETED (failed)
            - Otherwise                              → PROCESSING
        """
        output = tmux_client.get_history(
            self.session_name, self.window_name,
            tail_lines=tail_lines or STATUS_TAIL_LINES,
        )

        if not output:
            return TerminalStatus.ERROR

        clean = re.sub(ANSI_CODE_PATTERN, "", output)
        lines = clean.splitlines()

        # Scan bottom lines for status markers
        has_prompt = False
        has_done_marker = False
        has_error_marker = False
        is_processing = False

        for line in reversed(lines[-STATUS_TAIL_LINES:]):
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(PROMPT_MARKER) or stripped == PROMPT_MARKER:
                has_prompt = True
            if TASK_DONE in stripped:
                has_done_marker = True
            if TASK_WAITING in stripped or TASK_SUBMITTED in stripped:
                is_processing = True
            if stripped.startswith(TASK_ERROR):
                has_error_marker = True

        # Decision logic
        if has_prompt:
            if not self._input_received:
                return TerminalStatus.IDLE
            # Input was sent — prompt reappeared means task finished
            if has_done_marker or has_error_marker:
                return TerminalStatus.COMPLETED
            # Prompt visible but no done/error marker yet — might be
            # a very fast return or initial state; be conservative
            return TerminalStatus.COMPLETED

        if is_processing or self._input_received:
            return TerminalStatus.PROCESSING

        return TerminalStatus.IDLE

    def get_idle_pattern_for_log(self) -> str:
        """Pattern for quick IDLE detection in log files."""
        return r"Huntdex>\s*$"

    def mark_input_received(self) -> None:
        """Track that a task has been submitted."""
        self._input_received = True

    # ------------------------------------------------------------------
    # Output extraction
    # ------------------------------------------------------------------

    def extract_last_message_from_script(self, script_output: str) -> str:
        """Extract the task result block from copilot-ui.py output.

        Looks for the result between ``📤 任务已提交`` and the trailing
        ``Huntdex>`` prompt, returning the complete result block including
        summary, files, output_dir, and artifact info.
        """
        clean = re.sub(ANSI_CODE_PATTERN, "", script_output)
        lines = clean.splitlines()

        if not lines:
            raise ValueError("Empty Huntdex output")

        # Find the LAST task submission marker (in case of multiple tasks)
        submit_idx = -1
        for i in range(len(lines) - 1, -1, -1):
            if TASK_SUBMITTED in lines[i]:
                submit_idx = i
                break

        if submit_idx < 0:
            # No submission found — try to return everything before the prompt
            end = len(lines)
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip().startswith(PROMPT_MARKER):
                    end = i
                    break
            result = "\n".join(lines[:end]).strip()
            if result:
                return result
            raise ValueError("No task submission marker found in output")

        # Find the trailing Huntdex> prompt after the submission
        end_idx = len(lines)
        for i in range(len(lines) - 1, submit_idx, -1):
            stripped = lines[i].strip()
            if stripped.startswith(PROMPT_MARKER) or stripped == PROMPT_MARKER:
                end_idx = i
                break

        result = "\n".join(lines[submit_idx:end_idx]).strip()
        if not result:
            raise ValueError("Empty result block after task submission")

        return result

    # ------------------------------------------------------------------
    # Exit / cleanup
    # ------------------------------------------------------------------

    def exit_cli(self) -> str:
        """Exit the copilot-ui REPL."""
        return "exit"

    def cleanup(self) -> None:
        """Reset provider state."""
        self._initialized = False
        self._input_received = False
