"""Remote provider — DB-backed virtual terminal for remote agents.

No tmux session is used. Input/output/status are stored in memory and
exchanged via HTTP poll/report endpoints.
"""

import logging
import threading
from datetime import datetime
from typing import Optional

from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class RemoteProvider(BaseProvider):
    """Provider for remote agents that communicate via HTTP bridge."""

    def __init__(self, terminal_id: str, session_name: str = "", window_name: str = "",
                 agent_profile: Optional[str] = None):
        super().__init__(terminal_id, session_name, window_name)
        self.agent_profile = agent_profile
        self._remote_status = TerminalStatus.IDLE
        self._pending_input: Optional[str] = None
        self._last_output: str = ""
        self._full_output: str = ""
        self._updated_at = datetime.now()
        self._lock = threading.Lock()

    # --- Thread-safe state ---

    def set_pending_input(self, message: str) -> None:
        with self._lock:
            self._pending_input = message
            self._remote_status = TerminalStatus.IDLE
            self._updated_at = datetime.now()

    def consume_pending_input(self) -> Optional[str]:
        with self._lock:
            msg = self._pending_input
            self._pending_input = None
            if msg:
                self._remote_status = TerminalStatus.PROCESSING
                self._updated_at = datetime.now()
            return msg

    def report_status(self, status: str) -> None:
        try:
            self._remote_status = TerminalStatus(status)
        except ValueError:
            self._remote_status = TerminalStatus.ERROR
        self._updated_at = datetime.now()

    def report_output(self, output: str, append: bool = False) -> None:
        if append:
            self._full_output += output
        else:
            self._full_output = output
        self._last_output = output
        self._updated_at = datetime.now()

    # --- BaseProvider interface ---

    def initialize(self) -> bool:
        logger.info(f"Remote provider initialized for terminal {self.terminal_id}")
        return True

    def get_status(self, tail_lines: Optional[int] = None) -> TerminalStatus:
        return self._remote_status

    def get_idle_pattern_for_log(self) -> str:
        return ""

    def extract_last_message_from_script(self, script_output: str) -> str:
        return self._last_output

    def exit_cli(self) -> str:
        return ""

    def cleanup(self) -> None:
        logger.info(f"Remote provider cleaned up for terminal {self.terminal_id}")

    def get_full_output(self) -> str:
        return self._full_output
