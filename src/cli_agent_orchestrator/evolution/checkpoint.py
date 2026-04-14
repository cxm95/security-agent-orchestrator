"""Checkpoint shared state using a local git repo (ported from coral/hub/checkpoint.py).

Path: .cao-evolution/ (flat multi-repo-ready layout)
Structure: tasks/ + skills/ + notes/ + attempts/ + graders/ + reports/

Remote sync: set CAO_EVOLUTION_REMOTE env var to a git remote URL to enable
automatic push/pull after each checkpoint.
"""

from __future__ import annotations

import fcntl
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_EVOLUTION_DIR = ".cao-evolution"
_REMOTE_URL = os.environ.get("CAO_EVOLUTION_REMOTE", "")


def shared_dir(evolution_dir: str | Path = DEFAULT_EVOLUTION_DIR) -> Path:
    """Return the root data directory (flat layout, no 'shared/' prefix)."""
    return Path(evolution_dir)


def init_checkpoint_repo(evolution_dir: str | Path = DEFAULT_EVOLUTION_DIR) -> Path:
    """Initialize .cao-evolution/ as a git repo with the expected directory structure.

    Flat layout: skills/, notes/, attempts/, graders/, tasks/, reports/ at root.
    Idempotent — skips if .git already exists. Returns the data dir path.
    """
    sd = shared_dir(evolution_dir)
    sd.mkdir(parents=True, exist_ok=True)

    # Create required sub-directories (flat multi-repo-ready layout)
    for sub in ["tasks", "skills", "notes", "notes/_synthesis", "attempts", "graders", "reports"]:
        (sd / sub).mkdir(parents=True, exist_ok=True)

    if (sd / ".git").exists():
        return sd

    try:
        _git(sd, "init")
        _git(sd, "config", "user.name", "cao-evolution")
        _git(sd, "config", "user.email", "cao@local")
        (sd / ".gitignore").write_text("*.lock\n__pycache__/\nheartbeat/\n")
        _git(sd, "add", "-A")
        _git(sd, "commit", "--allow-empty", "-m", "init: cao-evolution shared state")
        _setup_remote(sd)
        logger.info("Initialized checkpoint repo in %s", sd)
    except Exception:
        logger.warning("Failed to initialize checkpoint repo", exc_info=True)

    return sd


def checkpoint(
    evolution_dir: str | Path = DEFAULT_EVOLUTION_DIR,
    agent_id: str = "hub",
    message: str = "checkpoint",
) -> str | None:
    """Commit all changes in shared/ and return the commit SHA, or None if nothing changed.

    Uses file lock for concurrency safety. Never raises.
    """
    sd = shared_dir(evolution_dir)

    if not (sd / ".git").exists():
        init_checkpoint_repo(evolution_dir)

    lock_path = sd / ".git" / "cao.lock"
    try:
        lock_path.touch(exist_ok=True)
        with open(lock_path) as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            _git(sd, "add", "-A")

            result = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                cwd=str(sd), capture_output=True,
            )
            if result.returncode == 0:
                return None  # nothing to commit

            _git(sd, "commit", "-m", f"[{agent_id}] {message}")

            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(sd), capture_output=True, text=True, check=True,
            )
            sha = result.stdout.strip()

            _sync_remote(sd)  # push if remote configured

            return sha
    except Exception:
        logger.warning("Checkpoint failed", exc_info=True)
        return None


def checkpoint_history(
    evolution_dir: str | Path = DEFAULT_EVOLUTION_DIR, count: int = 20
) -> list[dict[str, str]]:
    """Return recent checkpoint entries as [{hash, date, message}]."""
    sd = shared_dir(evolution_dir)
    if not (sd / ".git").exists():
        return []

    try:
        result = subprocess.run(
            ["git", "log", "--format=%H|%ai|%s", f"-n{count}"],
            cwd=str(sd), capture_output=True, text=True, check=True,
        )
        entries = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                entries.append({"hash": parts[0], "date": parts[1], "message": parts[2]})
        return entries
    except Exception:
        logger.warning("Failed to read checkpoint history", exc_info=True)
        return []


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, check=True,
    )


def _setup_remote(sd: Path) -> None:
    """Configure git remote 'origin' if CAO_EVOLUTION_REMOTE is set."""
    remote_url = _REMOTE_URL
    if not remote_url:
        return
    try:
        _git(sd, "remote", "add", "origin", remote_url)
        logger.info("Configured remote origin: %s", remote_url)
    except subprocess.CalledProcessError:
        # Remote may already exist; update it
        try:
            _git(sd, "remote", "set-url", "origin", remote_url)
        except Exception:
            logger.warning("Failed to configure remote", exc_info=True)


def _sync_remote(sd: Path) -> None:
    """Pull (rebase) then push to remote if configured. Never raises."""
    remote_url = _REMOTE_URL
    if not remote_url:
        return
    try:
        # Ensure remote is configured
        _setup_remote(sd)
        # Pull with rebase to integrate others' changes
        try:
            _git(sd, "pull", "--rebase", "origin", "master")
        except subprocess.CalledProcessError:
            # First push or remote empty — that's ok
            pass
        _git(sd, "push", "-u", "origin", "master")
        logger.info("Synced to remote")
    except Exception:
        logger.warning("Remote sync failed (will retry next checkpoint)", exc_info=True)
