"""CAO Agent Lifecycle — unified session management for SDK-based agents.

Wraps CaoBridge to provide a clean start/stop lifecycle with automatic:
- Hub registration (with reattach support)
- Git session initialization
- L1 knowledge index injection
- Knowledge context building
- Session teardown on exit
"""

import atexit
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Ensure cao-bridge root is importable
_bridge_root = str(Path(__file__).resolve().parent.parent)
if _bridge_root not in sys.path:
    sys.path.insert(0, _bridge_root)

from cao_bridge import CaoBridge

logger = logging.getLogger(__name__)


class CaoAgentLifecycle:
    """Manages the full CAO lifecycle for an SDK-based agent.

    Example::

        lifecycle = CaoAgentLifecycle(
            hub_url="http://127.0.0.1:9889",
            agent_profile="sdk-claude",
            git_remote="ssh://git@host/evolution.git",
        )
        lifecycle.start()
        context = lifecycle.build_context()
        # inject `context` into your agent's system prompt
        # ... run agent ...
        lifecycle.stop()
    """

    def __init__(
        self,
        hub_url: str = "",
        agent_profile: str = "",
        git_remote: str = "",
        auto_cleanup: bool = True,
    ):
        self._hub_url = hub_url or os.environ.get("CAO_HUB_URL", "http://127.0.0.1:9889")
        self._agent_profile = agent_profile or os.environ.get("CAO_AGENT_PROFILE", "remote-sdk")
        self._git_remote = git_remote or os.environ.get("CAO_GIT_REMOTE", "")
        self._auto_cleanup = auto_cleanup

        self._bridge = CaoBridge(
            hub_url=self._hub_url,
            agent_profile=self._agent_profile,
            git_remote=self._git_remote,
        )
        self._started = False

    @property
    def bridge(self) -> CaoBridge:
        """Access the underlying CaoBridge for advanced operations."""
        return self._bridge

    @property
    def terminal_id(self) -> Optional[str]:
        return self._bridge.terminal_id

    @property
    def session_dir(self) -> Optional[Path]:
        return self._bridge.session_dir

    def start(self) -> str:
        """Initialize session, register with Hub, return terminal_id.

        Call this once before running the agent. Sets up git session
        isolation and Hub registration.
        """
        if self._started:
            return self._bridge.terminal_id or ""

        # 1. Git session init (if remote configured)
        if self._git_remote:
            try:
                self._bridge.init_session(git_remote=self._git_remote)
                logger.info("Session initialized: %s", self._bridge.session_dir)
            except Exception:
                logger.warning("Session init failed, continuing without git sync", exc_info=True)

        # 2. Register with Hub (or reattach)
        cached_tid = self._read_cached_tid()
        tid = self._bridge.register_or_reattach(cached_tid)
        self._save_cached_tid(tid)

        # 3. Auto-cleanup on exit
        if self._auto_cleanup:
            atexit.register(self.stop)

        self._started = True
        logger.info("CAO lifecycle started: tid=%s profile=%s", tid, self._agent_profile)
        return tid

    def stop(self) -> None:
        """Push pending changes and close session. Safe to call multiple times."""
        if not self._started:
            return
        self._started = False
        try:
            self._bridge.close_session()
            logger.info("CAO lifecycle stopped")
        except Exception:
            logger.warning("Error during lifecycle stop", exc_info=True)

    def build_context(self, include_kickoff: bool = True) -> str:
        """Build the context string to inject into the agent's initial prompt.

        This is the SDK equivalent of what cao-session-start.sh does for
        CLI-based agents: registration info + L1 knowledge index.

        Args:
            include_kickoff: If True, include the cao_poll instruction.

        Returns:
            Context string ready for injection into system prompt or first message.
        """
        tid = self._bridge.terminal_id or "unknown"
        session_dir = self._bridge.session_dir or ""

        # Count available notes
        note_count = 0
        try:
            notes = self._bridge.search_knowledge("", top_k=100)
            note_count = len(notes)
        except Exception:
            pass

        parts = [
            f"[CAO] Registered as {tid}.",
            f"{note_count} shared knowledge notes available.",
            f"Session dir: {session_dir}.",
            "Use cao_poll to check for tasks, cao_search_knowledge to find relevant insights.",
        ]

        if include_kickoff:
            parts.append(
                "Your first action in this session MUST be to call the cao_poll MCP tool "
                "to check for queued tasks; if has_input is true, execute the returned task. "
                "Do not wait for a user message — call cao_poll immediately."
            )

        ctx = " ".join(parts)

        # L1 Knowledge Index — skipped in push-only mode (default).
        # Set CAO_PUSH_ONLY=0 to re-enable.
        if os.environ.get("CAO_PUSH_ONLY", "1") == "0":
            l1_index = self.fetch_index()
            if l1_index:
                ctx += f"\n\n== Knowledge Index ==\n{l1_index}\n== End Knowledge Index =="

        return ctx

    def fetch_index(self) -> str:
        """Fetch L1 knowledge index from Hub. Returns empty string if unavailable."""
        try:
            return self._bridge.fetch_index()
        except Exception:
            logger.debug("Failed to fetch L1 index", exc_info=True)
            return ""

    # ── State persistence ────────────────────────────────────────────

    def _state_file(self) -> Path:
        client_dir = os.environ.get(
            "CAO_CLIENT_BASE_DIR",
            str(Path.home() / ".cao-evolution-client"),
        )
        state_dir = Path(client_dir) / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / f"sdk-{self._agent_profile}.json"

    def _read_cached_tid(self) -> str:
        import json
        sf = self._state_file()
        if not sf.exists():
            return ""
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
            return data.get("terminal_id", "")
        except Exception:
            return ""

    def _save_cached_tid(self, tid: str) -> None:
        import json
        sf = self._state_file()
        sf.write_text(json.dumps({"terminal_id": tid}), encoding="utf-8")
