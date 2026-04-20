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
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_EVOLUTION_DIR = ".cao-evolution"
_REMOTE_URL = os.environ.get("CAO_EVOLUTION_REMOTE", "")
_SUBDIRS = ["tasks", "skills", "notes", "notes/_synthesis", "attempts", "graders", "reports"]


def shared_dir(evolution_dir: str | Path = DEFAULT_EVOLUTION_DIR) -> Path:
    """Return the root data directory (flat layout, no 'shared/' prefix)."""
    return Path(evolution_dir)


def init_checkpoint_repo(evolution_dir: str | Path = DEFAULT_EVOLUTION_DIR) -> Path:
    """Initialize .cao-evolution/ as a git repo with the expected directory structure.

    Flat layout: skills/, notes/, attempts/, graders/, tasks/, reports/ at root.
    Idempotent — skips if .git already exists.  When a remote is configured,
    clones from it first so Hub and remote always share commit history.
    Returns the data dir path.
    """
    sd = shared_dir(evolution_dir)

    if (sd / ".git").exists():
        for sub in _SUBDIRS:
            (sd / sub).mkdir(parents=True, exist_ok=True)
        return sd

    # If a remote is configured, clone it to avoid divergent histories
    remote_url = _REMOTE_URL
    if remote_url:
        try:
            sd.parent.mkdir(parents=True, exist_ok=True)
            _git(
                sd.parent,
                "clone", "--filter=blob:none", remote_url, str(sd),
            )
            _git(sd, "config", "user.name", "cao-evolution")
            _git(sd, "config", "user.email", "cao@local")
            for sub in _SUBDIRS:
                (sd / sub).mkdir(parents=True, exist_ok=True)
            logger.info("Cloned remote into Hub repo %s (branch=%s)", sd, _current_branch(sd))
            return sd
        except subprocess.CalledProcessError:
            # Clone failed (empty remote, network error) — fall back to init
            logger.info("Remote clone failed, falling back to git init")
            # Clean up partial clone
            import shutil
            if sd.exists() and not (sd / ".git").exists():
                shutil.rmtree(sd, ignore_errors=True)

    # Fallback: fresh git init (first-time use or no remote)
    sd.mkdir(parents=True, exist_ok=True)
    for sub in _SUBDIRS:
        (sd / sub).mkdir(parents=True, exist_ok=True)

    try:
        # Try `git init -b main` (git >= 2.28). Fall back to `git init` +
        # symbolic-ref for older git so the initial branch is always `main`
        # — this matches GitHub's default and avoids a master/main mismatch
        # when a remote is configured later.
        try:
            _git(sd, "init", "-b", "main")
        except subprocess.CalledProcessError:
            _git(sd, "init")
            try:
                _git(sd, "symbolic-ref", "HEAD", "refs/heads/main")
            except subprocess.CalledProcessError:
                pass
        _git(sd, "config", "user.name", "cao-evolution")
        _git(sd, "config", "user.email", "cao@local")
        (sd / ".gitignore").write_text("*.lock\n__pycache__/\nheartbeat/\n")
        _git(sd, "add", "-A")
        _git(sd, "commit", "--allow-empty", "-m", "init: cao-evolution shared state")
        # If the initial commit landed on `master` (older git without -b support
        # and no symbolic-ref), rename to `main` to keep parity with the remote.
        if _current_branch(sd) == "master":
            try:
                _git(sd, "branch", "-M", "main")
            except subprocess.CalledProcessError:
                pass
        _setup_remote(sd)
        # For fresh init with remote, do initial push to establish remote branch
        if remote_url:
            branch = _current_branch(sd)
            try:
                _git(sd, "push", "-u", "origin", branch)
            except subprocess.CalledProcessError:
                logger.info("Initial push failed (remote may be non-empty)")
        logger.info("Initialized checkpoint repo in %s", sd)
    except Exception:
        logger.warning("Failed to initialize checkpoint repo", exc_info=True)

    return sd


def checkpoint(
    evolution_dir: str | Path = DEFAULT_EVOLUTION_DIR,
    agent_id: str = "hub",
    message: str = "checkpoint",
    on_commit: Callable[[str, list[str]], None] | None = None,
) -> str | None:
    """Commit all changes in shared/ and return the commit SHA, or None if nothing changed.

    Uses file lock for concurrency safety. Never raises.
    Args:
        on_commit: Optional callback(evolution_dir, changed_files) called after
                   successful commit with the list of changed file paths (relative).
    """
    sd = shared_dir(evolution_dir)

    if not (sd / ".git").exists():
        init_checkpoint_repo(evolution_dir)

    sha = None
    changed: list[str] = []
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
                # Nothing local to commit, but still sync remote
                # to pick up agent pushes
                _pulled = _sync_remote(sd)
                if on_commit is not None and _pulled:
                    knowledge = [
                        f for f in _pulled
                        if f.startswith("notes/") or f.startswith("skills/")
                    ]
                    if knowledge:
                        try:
                            on_commit(str(evolution_dir), _pulled)
                        except Exception:
                            logger.debug("on_commit callback failed", exc_info=True)
                return None

            _git(sd, "commit", "-m", f"[{agent_id}] {message}")

            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(sd), capture_output=True, text=True, check=True,
            )
            sha = result.stdout.strip()

            # Collect changed files while still under lock
            try:
                count_result = subprocess.run(
                    ["git", "rev-list", "--count", "HEAD"],
                    cwd=str(sd), capture_output=True, text=True,
                )
                commit_count = int(count_result.stdout.strip())
                if commit_count <= 1:
                    diff_result = subprocess.run(
                        ["git", "show", "--name-only", "--format=", "HEAD"],
                        cwd=str(sd), capture_output=True, text=True,
                    )
                else:
                    diff_result = subprocess.run(
                        ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
                        cwd=str(sd), capture_output=True, text=True,
                    )
                changed = [
                    f for f in diff_result.stdout.strip().splitlines() if f
                ]
            except Exception:
                logger.debug("Failed to get changed files", exc_info=True)

            _pulled = _sync_remote(sd)  # push if remote configured

        # Release lock BEFORE calling on_commit callback
        # Merge local changed files with files pulled from remote
        all_changed = changed + [f for f in _pulled if f not in changed]
        if on_commit is not None and all_changed:
            try:
                on_commit(str(evolution_dir), all_changed)
            except Exception:
                logger.debug("on_commit callback failed", exc_info=True)

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


def _current_branch(sd: Path) -> str:
    """Return the current branch name (e.g. 'master' or 'main')."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(sd), capture_output=True, text=True, check=True,
        )
        branch = r.stdout.strip()
        if branch and branch != "HEAD":
            return branch
    except Exception:
        pass
    return "main"


def _setup_remote(sd: Path) -> None:
    """Configure git remote 'origin' if CAO_EVOLUTION_REMOTE is set."""
    remote_url = _REMOTE_URL
    if not remote_url:
        return
    try:
        _git(sd, "remote", "add", "origin", remote_url)
        logger.info("Configured remote origin: %s", remote_url)
    except subprocess.CalledProcessError:
        try:
            _git(sd, "remote", "set-url", "origin", remote_url)
        except Exception:
            logger.warning("Failed to configure remote", exc_info=True)


def _sync_remote(sd: Path) -> list[str]:
    """Pull (rebase) then push to remote if configured. Never raises.

    Returns a list of file paths that were pulled from remote (i.e. files
    pushed by agents).  Empty list if no remote or nothing new.
    """
    remote_url = _REMOTE_URL
    if not remote_url:
        return []
    pulled_files: list[str] = []
    try:
        _setup_remote(sd)
        branch = _current_branch(sd)

        # Record HEAD before pull so we can diff afterwards
        pre_pull = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(sd), capture_output=True, text=True, check=False,
        )
        pre_sha = pre_pull.stdout.strip() if pre_pull.returncode == 0 else ""

        try:
            _git(sd, "pull", "--rebase", "origin", branch)
        except subprocess.CalledProcessError:
            pass

        # Detect files introduced by pull (agent pushes)
        if pre_sha:
            post_pull = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(sd), capture_output=True, text=True, check=False,
            )
            post_sha = post_pull.stdout.strip() if post_pull.returncode == 0 else ""
            if post_sha and post_sha != pre_sha:
                diff_result = subprocess.run(
                    ["git", "diff", "--name-only", pre_sha, post_sha],
                    cwd=str(sd), capture_output=True, text=True, check=False,
                )
                if diff_result.returncode == 0:
                    pulled_files = [
                        f for f in diff_result.stdout.strip().splitlines() if f
                    ]
                    if pulled_files:
                        logger.info(
                            "Pulled %d files from remote: %s",
                            len(pulled_files),
                            ", ".join(pulled_files[:5]),
                        )

        _git(sd, "push", "-u", "origin", branch)
        logger.info("Synced to remote (branch=%s)", branch)
    except Exception:
        logger.warning("Remote sync failed (will retry next checkpoint)", exc_info=True)
    return pulled_files
