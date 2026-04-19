"""Startup recovery service.

Runs on every Hub boot (from ``lifespan`` in ``api/main.py``) to re-attach
to terminals that persisted in the SQLite database from the previous run.

Responsibilities, by terminal kind:

* **Local tmux terminals** — verify that the associated tmux session/window
  still exist.  When they do, re-install the ``pipe-pane`` so inbox
  watchdog monitoring keeps working.  When the tmux session is gone
  (e.g. the host machine rebooted) the DB row is marked stale: we leave
  the row in place but do not lazily recreate the provider.

* **Remote terminals** — rehydrate the ``RemoteProvider`` from
  ``remote_state`` by warming the provider cache.  The ``__init__`` of
  RemoteProvider already calls ``_hydrate_from_db()``, so a simple
  ``provider_manager.get_provider(tid)`` is enough.  Any pending
  ``inbox`` messages are flushed so the agent sees them on its next
  poll.

The recovery routine must tolerate partial DB corruption and missing
tmux sessions.  Every per-terminal step is wrapped in try/except so one
bad row cannot abort boot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from cli_agent_orchestrator.clients.database import (
    get_pending_messages,
    list_all_terminals,
)
from cli_agent_orchestrator.clients.tmux import tmux_client
from cli_agent_orchestrator.constants import TERMINAL_LOG_DIR
from cli_agent_orchestrator.models.provider import ProviderType
from cli_agent_orchestrator.providers.manager import provider_manager
from cli_agent_orchestrator.providers.remote import RemoteProvider

logger = logging.getLogger(__name__)


@dataclass
class RecoveryReport:
    """Summary returned by ``recover_on_startup`` for logging/debugging."""

    total: int = 0
    local_alive: int = 0
    local_stale: int = 0
    remote_rehydrated: int = 0
    errors: List[str] = field(default_factory=list)
    pending_inbox_flushed: int = 0

    def summary(self) -> str:
        return (
            f"total={self.total} local_alive={self.local_alive} "
            f"local_stale={self.local_stale} remote={self.remote_rehydrated} "
            f"inbox_flushed={self.pending_inbox_flushed} errors={len(self.errors)}"
        )


def _recover_local(terminal: dict) -> bool:
    """Re-attach to an existing tmux-backed terminal.

    Returns True if the tmux session/window exists and pipe-pane was
    re-armed; False if the session is gone (row should be treated as
    stale until the user explicitly deletes or recreates it).
    """
    session_name = terminal["tmux_session"]
    window_name = terminal["tmux_window"]
    terminal_id = terminal["id"]

    if not tmux_client.session_exists(session_name):
        logger.info(
            f"Recovery: tmux session '{session_name}' for terminal {terminal_id} no longer exists"
        )
        return False

    windows = tmux_client.get_session_windows(session_name)
    if not any(w.get("name") == window_name for w in windows):
        logger.info(
            f"Recovery: tmux window '{window_name}' missing in session '{session_name}' "
            f"for terminal {terminal_id}"
        )
        return False

    log_path = TERMINAL_LOG_DIR / f"{terminal_id}.log"
    log_path.touch()
    try:
        tmux_client.pipe_pane(session_name, window_name, str(log_path))
    except Exception as e:
        # pipe-pane is idempotent in tmux; a failure here is unusual but
        # should not stop recovery.  Log and move on.
        logger.warning(f"Recovery: failed to re-arm pipe-pane for {terminal_id}: {e}")

    # Warm the provider cache so future HTTP calls don't race on lazy creation.
    try:
        provider_manager.get_provider(terminal_id)
    except Exception as e:
        logger.warning(f"Recovery: provider warm-up failed for {terminal_id}: {e}")

    return True


def _recover_remote(terminal: dict) -> bool:
    """Warm a RemoteProvider so its persisted state is ready for polling."""
    terminal_id = terminal["id"]
    try:
        provider = provider_manager.get_provider(terminal_id)
    except Exception as e:
        logger.warning(f"Recovery: get_provider failed for remote {terminal_id}: {e}")
        return False
    if not isinstance(provider, RemoteProvider):
        logger.warning(
            f"Recovery: expected RemoteProvider for {terminal_id}, got {type(provider).__name__}"
        )
        return False
    return True


def _flush_pending_inbox(terminal_id: str) -> int:
    """Count pending inbox messages for a terminal.

    We deliberately do **not** actively deliver here.  The inbox watchdog
    will pick them up once the terminal is idle — or, for remote
    terminals, ``remote_poll`` bridges inbox → pending_input on the next
    agent poll.  This function exists so the recovery report surfaces
    the count for observability.
    """
    try:
        pending = get_pending_messages(terminal_id, limit=100)
    except Exception as e:
        logger.warning(f"Recovery: pending inbox count failed for {terminal_id}: {e}")
        return 0
    return len(pending)


def recover_on_startup() -> RecoveryReport:
    """Walk all persisted terminals and reattach what we still can."""
    report = RecoveryReport()

    try:
        terminals = list_all_terminals()
    except Exception as e:
        logger.error(f"Recovery: unable to list terminals from DB: {e}")
        report.errors.append(f"list_all_terminals: {e}")
        return report

    report.total = len(terminals)
    logger.info(f"Recovery: inspecting {report.total} persisted terminals")

    for terminal in terminals:
        terminal_id = terminal["id"]
        provider = terminal["provider"]
        try:
            if provider == ProviderType.REMOTE.value:
                if _recover_remote(terminal):
                    report.remote_rehydrated += 1
            else:
                if _recover_local(terminal):
                    report.local_alive += 1
                else:
                    report.local_stale += 1

            report.pending_inbox_flushed += _flush_pending_inbox(terminal_id)
        except Exception as e:
            msg = f"{terminal_id}: {e}"
            logger.error(f"Recovery error for {msg}")
            report.errors.append(msg)

    logger.info(f"Recovery complete: {report.summary()}")
    return report


__all__ = ["RecoveryReport", "recover_on_startup"]
