"""Remote provider — DB-backed virtual terminal for remote agents.

No tmux session is used. Input/output/status are stored in memory and
exchanged via HTTP poll/report endpoints.

In-memory state is mirrored to the ``remote_state`` table on every
mutation so that an unexpected Hub restart can rehydrate a RemoteProvider
with the last known status / pending_input / full_output. DB errors are
swallowed: standalone unit tests construct RemoteProvider without
``init_db()`` and must keep working.
"""

import logging
import threading
from datetime import datetime
from typing import Any, Optional

from cli_agent_orchestrator.clients.database import (
    get_remote_state,
    upsert_remote_state,
)
from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.base import BaseProvider

logger = logging.getLogger(__name__)

# Cap the amount of output we mirror to SQLite so a long-running agent
# can't bloat the DB when it streams large buffers every report call.
# In-memory ``_full_output`` is unbounded; only the persisted copy is
# trimmed to the tail, which is what a restart actually needs to show.
_MAX_PERSISTED_OUTPUT = 128 * 1024


def _clip(output: str) -> str:
    if len(output) <= _MAX_PERSISTED_OUTPUT:
        return output
    return output[-_MAX_PERSISTED_OUTPUT:]


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
        self._hydrate_from_db()

    # --- Persistence helpers ---

    def _hydrate_from_db(self) -> None:
        """Load any persisted state for this terminal_id into memory."""
        try:
            row = get_remote_state(self.terminal_id)
        except Exception as e:  # pragma: no cover - defensive
            logger.debug(f"remote_state hydrate skipped for {self.terminal_id}: {e}")
            return
        if not row:
            return
        try:
            self._remote_status = TerminalStatus(row.get("status") or TerminalStatus.IDLE.value)
        except ValueError:
            self._remote_status = TerminalStatus.IDLE
        self._pending_input = row.get("pending_input")
        self._last_output = row.get("last_output") or ""
        self._full_output = row.get("full_output") or ""
        self._updated_at = row.get("updated_at") or datetime.now()
        logger.info(
            f"Rehydrated RemoteProvider {self.terminal_id} from DB: "
            f"status={self._remote_status.value} pending={'yes' if self._pending_input else 'no'}"
        )

    def _persist(self, **fields: Any) -> None:
        """Write the given fields to remote_state. Best-effort."""
        try:
            upsert_remote_state(self.terminal_id, **fields)
        except Exception as e:  # pragma: no cover - defensive
            logger.debug(f"remote_state persist skipped for {self.terminal_id}: {e}")

    # --- Thread-safe state ---
    #
    # DB writes happen **inside** the lock so concurrent callers
    # (set_pending_input from the Hub side, consume_pending_input from
    # an agent poll) can't interleave a persist-after-other-thread-ran
    # and leave SQLite with a view that disagrees with memory.  The
    # upsert is a single SQLite transaction and finishes in <1 ms in
    # practice; holding the lock that long is fine for a virtual
    # terminal with two real callers.

    def set_pending_input(self, message: str) -> None:
        with self._lock:
            self._pending_input = message
            self._remote_status = TerminalStatus.IDLE
            self._updated_at = datetime.now()
            self._persist(
                pending_input=message,
                status=TerminalStatus.IDLE.value,
                last_seen_at=self._updated_at,
            )

    def consume_pending_input(self) -> Optional[str]:
        with self._lock:
            msg = self._pending_input
            self._pending_input = None
            if msg:
                self._remote_status = TerminalStatus.PROCESSING
                self._updated_at = datetime.now()
                self._persist(
                    pending_input=None,
                    status=TerminalStatus.PROCESSING.value,
                    last_seen_at=self._updated_at,
                )
            else:
                # Empty poll still counts as a heartbeat from the agent.
                self._persist(last_seen_at=datetime.now())
        return msg

    def report_status(self, status: str) -> None:
        with self._lock:
            try:
                self._remote_status = TerminalStatus(status)
            except ValueError:
                self._remote_status = TerminalStatus.ERROR
            self._updated_at = datetime.now()
            self._persist(
                status=self._remote_status.value,
                last_seen_at=self._updated_at,
            )

    def report_output(self, output: str, append: bool = False) -> None:
        with self._lock:
            if append:
                self._full_output += output
            else:
                self._full_output = output
            self._last_output = output
            self._updated_at = datetime.now()
            self._persist(
                last_output=_clip(self._last_output),
                full_output=_clip(self._full_output),
                last_seen_at=self._updated_at,
            )

    def reset_for_reattach(self) -> None:
        """Return to a clean, ready-to-work state after an agent reattach.

        If the previous session crashed mid-task the persisted status
        would be ``processing``; that state blocks inbox delivery until
        the agent reports something, but the agent-side bridge doesn't
        auto-report on startup.  We solve the chicken-and-egg by
        flipping status back to ``idle`` here unless there is a real
        pending_input still waiting (in which case the next consume
        will transition to ``processing`` anyway).
        """
        with self._lock:
            if self._pending_input is None and self._remote_status in (
                TerminalStatus.PROCESSING,
                TerminalStatus.ERROR,
            ):
                self._remote_status = TerminalStatus.IDLE
                self._updated_at = datetime.now()
                self._persist(
                    status=TerminalStatus.IDLE.value,
                    last_seen_at=self._updated_at,
                )

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
