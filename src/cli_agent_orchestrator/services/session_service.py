"""Session service for session-level operations.

This module provides session management functionality for CAO, where a "session"
corresponds to a tmux session that may contain multiple terminal windows (agents).

Session Hierarchy:
- Session: A tmux session (e.g., "cao-my-project")
  - Terminal: A tmux window within the session (e.g., "developer-abc123")
    - Provider: The CLI agent running in the terminal (e.g., KiroCliProvider)

Key Operations:
- list_sessions(): Get all CAO-managed sessions (filtered by SESSION_PREFIX)
- get_session(): Get session details including all terminal metadata
- delete_session(): Clean up session, providers, database records, and tmux session

Session Lifecycle:
1. create_terminal() with new_session=True creates a new tmux session
2. Additional terminals are added via create_terminal() with new_session=False
3. delete_session() removes the entire session and all contained terminals
"""

import logging
from typing import Dict, List

from cli_agent_orchestrator.clients.database import (
    delete_terminals_by_session,
    list_all_terminals,
    list_terminals_by_session,
)
from cli_agent_orchestrator.clients.tmux import tmux_client
from cli_agent_orchestrator.constants import SESSION_PREFIX
from cli_agent_orchestrator.models.provider import ProviderType
from cli_agent_orchestrator.providers.manager import provider_manager

logger = logging.getLogger(__name__)


def _remote_session_names() -> List[str]:
    """Collect distinct tmux_session values for DB terminals that have no tmux session.

    Remote terminals persist a synthetic session_name in the ``tmux_session``
    column even though no tmux session is ever created.  List them so callers
    can see remote-only sessions alongside local tmux ones.
    """
    seen: List[str] = []
    for t in list_all_terminals():
        if t["provider"] != ProviderType.REMOTE.value:
            continue
        name = t["tmux_session"]
        if name and name not in seen:
            seen.append(name)
    return seen


def list_sessions() -> List[Dict]:
    """List all sessions — tmux-backed and remote-only (DB-backed).

    Each entry gets a ``kind`` field of ``"local"`` (tmux session exists) or
    ``"remote"`` (no tmux, all terminals are remote providers).  Existing
    callers that only read ``id``/``name``/``status`` are unaffected.
    """
    try:
        sessions: List[Dict] = []
        seen_names: set = set()

        for s in tmux_client.list_sessions():
            if not s["id"].startswith(SESSION_PREFIX):
                continue
            sessions.append({**s, "kind": "local"})
            seen_names.add(s["id"])

        for name in _remote_session_names():
            if name in seen_names:
                continue
            sessions.append({"id": name, "name": name, "status": "detached", "kind": "remote"})

        return sessions
    except Exception as e:
        logger.error(f"Failed to list sessions: {e}")
        return []


def get_session(session_name: str) -> Dict:
    """Get session with terminals — falls back to DB for remote-only sessions."""
    try:
        if tmux_client.session_exists(session_name):
            tmux_sessions = tmux_client.list_sessions()
            session_data = next((s for s in tmux_sessions if s["id"] == session_name), None)
            if session_data:
                session_data = {**session_data, "kind": "local"}
                terminals = list_terminals_by_session(session_name)
                return {"session": session_data, "terminals": terminals}

        # Fall back: DB-only (remote) session
        terminals = list_terminals_by_session(session_name)
        if not terminals:
            raise ValueError(f"Session '{session_name}' not found")

        session_data = {
            "id": session_name,
            "name": session_name,
            "status": "detached",
            "kind": "remote",
        }
        return {"session": session_data, "terminals": terminals}

    except Exception as e:
        logger.error(f"Failed to get session {session_name}: {e}")
        raise


def delete_session(session_name: str) -> Dict:
    """Delete session and cleanup.

    Returns:
        Dict with 'deleted' (list of deleted session names) and 'errors' (list of error dicts).
    """
    result: Dict = {"deleted": [], "errors": []}
    try:
        tmux_exists = tmux_client.session_exists(session_name)
        terminals = list_terminals_by_session(session_name)

        if not tmux_exists and not terminals:
            raise ValueError(f"Session '{session_name}' not found")

        # Cleanup providers (non-blocking — don't let failures stop deletion)
        for terminal in terminals:
            try:
                provider_manager.cleanup_provider(terminal["id"])
            except Exception as e:
                logger.warning(f"Provider cleanup failed for {terminal['id']}: {e}")

        # Kill tmux session if it exists (remote-only sessions have none)
        if tmux_exists:
            tmux_client.kill_session(session_name)

        # Delete terminal metadata
        delete_terminals_by_session(session_name)

        result["deleted"].append(session_name)
        logger.info(f"Deleted session: {session_name}")
        return result

    except Exception as e:
        logger.error(f"Failed to delete session {session_name}: {e}")
        raise
