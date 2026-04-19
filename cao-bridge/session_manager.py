"""Session-based isolation for multi-instance remote agents.

Each agent instance gets its own session directory under
``~/.cao-evolution-client/sessions/<session_id>/``, containing an
independent git clone, report registry, and runtime state.

Session lifecycle:
    create  → active (git clone, .session.json written)
    touch   → refreshes last_update timestamp
    deactivate → status set to "inactive" (agent normal exit)
    cleanup → removes expired inactive sessions

Session ID format: ``YYYYMMDDTHHMMSS-<uuid4_hex[:8]>``
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_BASE_DIR = Path.home() / ".cao-evolution-client"
_SESSION_META = ".session.json"


def _base_dir() -> Path:
    return Path(os.environ.get("CAO_CLIENT_BASE_DIR", str(DEFAULT_BASE_DIR)))


def sessions_root() -> Path:
    """Return ``~/.cao-evolution-client/sessions/``."""
    d = _base_dir() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate_session_id() -> str:
    """Generate a session ID like ``20260416T103000-a3f2b1c8``."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    suffix = uuid.uuid4().hex[:8]
    return f"{ts}-{suffix}"


def create_session(
    git_remote: str,
    agent_profile: str = "",
    session_id: str = "",
) -> Path:
    """Create a new session directory with an independent git clone.

    Returns the session directory path.
    """
    import subprocess

    sid = session_id or generate_session_id()
    sdir = sessions_root() / sid

    if sdir.exists():
        try:
            meta = _read_meta(sdir)
            if meta.get("status") == "active":
                logger.info("Session %s already exists and is active", sid)
                return sdir
        except Exception:
            pass  # corrupt or vanished — recreate below

    sdir.mkdir(parents=True, exist_ok=True)

    if git_remote and not (sdir / ".git").exists():
        try:
            subprocess.run(
                ["git", "clone", "--filter=blob:none", git_remote, str(sdir)],
                capture_output=True, text=True, check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "cao-agent"],
                cwd=str(sdir), capture_output=True, check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "cao-agent@local"],
                cwd=str(sdir), capture_output=True, check=True,
            )
            logger.info("Cloned evolution repo into session %s", sid)
        except subprocess.CalledProcessError as exc:
            logger.error("git clone failed for session %s: %s", sid, exc.stderr)
            raise RuntimeError(f"git clone failed: {exc.stderr}") from exc

    _ensure_subdirs(sdir)
    _ensure_local_excludes(sdir)

    now = datetime.now(timezone.utc).isoformat()
    _write_meta(sdir, {
        "session_id": sid,
        "created_at": now,
        "last_update": now,
        "status": "active",
        "agent_profile": agent_profile,
        "terminal_id": "",
        "pid": os.getpid(),
    })

    return sdir


def get_session_dir(session_id: str) -> Path:
    """Return the directory for a given session ID."""
    return sessions_root() / session_id


def touch_session(session_dir: Path) -> None:
    """Refresh ``last_update`` in .session.json."""
    meta = _read_meta(session_dir)
    if not meta:
        return
    meta["last_update"] = datetime.now(timezone.utc).isoformat()
    _write_meta(session_dir, meta)


def set_terminal_id(session_dir: Path, terminal_id: str) -> None:
    """Store the Hub-assigned terminal_id in session metadata."""
    meta = _read_meta(session_dir)
    if not meta:
        return
    meta["terminal_id"] = terminal_id
    meta["last_update"] = datetime.now(timezone.utc).isoformat()
    _write_meta(session_dir, meta)


def get_terminal_id(session_dir: Path) -> str:
    """Return the Hub-assigned terminal_id stored in session metadata.

    Empty string when the session doesn't exist, the metadata is
    missing/corrupt, or no terminal_id has been written yet.
    """
    meta = _read_meta(session_dir)
    if not meta:
        return ""
    return meta.get("terminal_id", "") or ""


def deactivate_session(session_dir: Path) -> None:
    """Mark session as inactive (called on normal agent exit)."""
    meta = _read_meta(session_dir)
    if not meta:
        return
    meta["status"] = "inactive"
    meta["last_update"] = datetime.now(timezone.utc).isoformat()
    _write_meta(session_dir, meta)
    logger.info("Session %s deactivated", meta.get("session_id", "?"))


def list_sessions(status: str | None = None) -> list[dict]:
    """List all sessions, optionally filtered by status."""
    root = sessions_root()
    results = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        meta = _read_meta(child)
        if not meta:
            continue
        if status and meta.get("status") != status:
            continue
        results.append(meta)
    return results


def cleanup_sessions(max_age_hours: int = 24) -> list[str]:
    """Remove expired inactive sessions. Returns list of removed IDs.

    - inactive + last_update older than max_age_hours -> rm -rf
    - active + last_update older than max_age_hours + pid dead -> mark inactive
    """
    root = sessions_root()
    removed: list[str] = []
    now = datetime.now(timezone.utc)

    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        meta = _read_meta(child)
        if not meta:
            continue

        last = _parse_iso(meta.get("last_update", ""))
        if not last:
            continue

        age_hours = (now - last).total_seconds() / 3600
        sid = meta.get("session_id", child.name)
        st = meta.get("status", "")

        if st == "inactive" and age_hours > max_age_hours:
            logger.info("Removing expired session %s (age=%.1fh)", sid, age_hours)
            shutil.rmtree(child, ignore_errors=True)
            removed.append(sid)
        elif st == "active" and age_hours > max_age_hours:
            pid = meta.get("pid")
            if pid and not _pid_alive(pid):
                logger.info("Session %s stale (pid %s dead), marking inactive", sid, pid)
                try:
                    deactivate_session(child)
                except Exception:
                    logger.debug("Failed to deactivate %s", sid, exc_info=True)

    return removed


# -- Internal helpers ----------------------------------------------------------

_SUBDIRS = [
    "tasks", "skills", "notes", "notes/_synthesis",
    "attempts", "graders", "reports",
]


def _ensure_subdirs(sdir: Path) -> None:
    for sub in _SUBDIRS:
        (sdir / sub).mkdir(parents=True, exist_ok=True)


def _ensure_local_excludes(sdir: Path) -> None:
    exclude_file = sdir / ".git" / "info" / "exclude"
    required = [
        "# cao-bridge: agent-local runtime state (do not track)",
        "reports/",
        ".session.json",
    ]
    try:
        exclude_file.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude_file.read_text().splitlines() if exclude_file.exists() else []
        missing = [line for line in required if line not in existing]
        if missing:
            with exclude_file.open("a", encoding="utf-8") as fh:
                if existing and existing[-1] != "":
                    fh.write("\n")
                fh.write("\n".join(missing) + "\n")
    except OSError as exc:
        logger.warning("Could not update %s: %s", exclude_file, exc)


def _read_meta(sdir: Path) -> dict:
    meta_path = sdir / _SESSION_META
    if not meta_path.exists():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_meta(sdir: Path, data: dict) -> None:
    meta_path = sdir / _SESSION_META
    meta_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
