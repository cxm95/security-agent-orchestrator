"""Agent-side git sync — clone/pull Hub's evolution repo to ~/.cao-evolution-client/.

Every remote agent (opencode, claude-code, codex, hermes) uses git to
synchronise shared knowledge with the Hub.  This module provides the
low-level git primitives; higher-level bridge code calls these during
session start/end.

Environment variables
---------------------
CAO_GIT_REMOTE       Git URL of the shared evolution repo.
                     Same URL the Hub pushes to via CAO_EVOLUTION_REMOTE.
                     For same-machine setups: file://<hub-dir>/.cao-evolution
                     For remote setups: git@host:org/evolution.git
CAO_CLIENT_DIR       Override the local clone path (default ~/.cao-evolution-client)
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CLIENT_DIR = Path.home() / ".cao-evolution-client"

# Per-session directory override (set by session_manager at init time)
_current_session_dir: Path | None = None


def set_session_dir(path: Path) -> None:
    """Set the per-session working directory for this process.

    Called by CaoBridge.init_session() after session_manager.create_session().
    All subsequent git operations will target this directory.
    """
    global _current_session_dir
    _current_session_dir = path
    logger.info("Session dir set to %s", path)


def client_dir() -> Path:
    """Return the agent-side clone directory.

    Resolution order:
    1. _current_session_dir (set via set_session_dir — per-session isolation)
    2. CAO_CLIENT_DIR env var (full override, backward compat)
    3. DEFAULT_CLIENT_DIR (legacy single-instance fallback)
    """
    if _current_session_dir is not None:
        return _current_session_dir
    return Path(os.environ.get("CAO_CLIENT_DIR", str(DEFAULT_CLIENT_DIR)))


def _git_remote() -> str:
    """Return the configured git remote URL (empty string if unset)."""
    return os.environ.get("CAO_GIT_REMOTE", "")


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a git command, capturing output as text."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
    )


def _current_branch(cdir: Path) -> str:
    """Return the current branch name."""
    try:
        r = _git(cdir, "rev-parse", "--abbrev-ref", "HEAD", check=False)
        branch = r.stdout.strip() if r.returncode == 0 else ""
        if branch and branch != "HEAD":
            return branch
    except Exception:
        pass
    return "main"


def init_client_repo(remote_url: str | None = None) -> Path:
    """Clone the Hub repo if not present; pull if it already exists.

    Parameters
    ----------
    remote_url : str, optional
        Explicit remote URL.  Falls back to CAO_GIT_REMOTE env var.

    Returns
    -------
    Path  – the local clone directory.

    Raises
    ------
    RuntimeError  if no remote URL is available.
    """
    url = remote_url or _git_remote()
    cdir = client_dir()

    if not url:
        raise RuntimeError(
            "No git remote configured.  Set CAO_GIT_REMOTE env var "
            "to the Hub's evolution repo URL."
        )

    if (cdir / ".git").exists():
        _ensure_remote(cdir, url)
        _ensure_local_excludes(cdir)
        pull(cdir)
        logger.info("Pulled latest into %s", cdir)
        return cdir

    # First-time clone (partial clone for efficiency)
    cdir.mkdir(parents=True, exist_ok=True)
    try:
        _git(
            cdir.parent,
            "clone",
            "--filter=blob:none",
            url,
            str(cdir),
        )
        _git(cdir, "config", "user.name", "cao-agent")
        _git(cdir, "config", "user.email", "cao-agent@local")
        _ensure_local_excludes(cdir)
        logger.info("Cloned evolution repo to %s (branch=%s)", cdir, _current_branch(cdir))
    except subprocess.CalledProcessError as exc:
        logger.error("git clone failed: %s", exc.stderr)
        raise RuntimeError(f"git clone failed: {exc.stderr}") from exc

    return cdir


def pull(cdir: Path | None = None) -> bool:
    """Pull latest changes (rebase).  Returns True on success."""
    cdir = cdir or client_dir()
    if not (cdir / ".git").exists():
        logger.warning("pull: %s is not a git repo — call init_client_repo first", cdir)
        return False

    try:
        branch = _current_branch(cdir)
        _git(cdir, "fetch", "--all", check=False)
        result = _git(cdir, "pull", "--rebase", "origin", branch, check=False)
        if result.returncode != 0:
            # Try the other common branch name
            alt = "master" if branch == "main" else "main"
            result = _git(cdir, "pull", "--rebase", "origin", alt, check=False)
        if result.returncode == 0:
            logger.debug("pull ok: %s", cdir)
            return True
        logger.warning("pull failed: %s", result.stderr.strip())
        return False
    except Exception:
        logger.warning("pull failed", exc_info=True)
        return False


def push(cdir: Path | None = None, message: str = "agent sync") -> bool:
    """Stage all changes, commit and push.  Returns True on success.

    Always does pull --rebase before push to avoid non-fast-forward rejects.
    """
    cdir = cdir or client_dir()
    if not (cdir / ".git").exists():
        return False

    try:
        _git(cdir, "add", "-A")
        # Check if there's anything to commit
        result = _git(cdir, "diff", "--cached", "--quiet", check=False)
        if result.returncode == 0:
            return True  # nothing to commit — still success

        _git(cdir, "commit", "-m", f"[agent] {message}")

        # Pull before push to integrate Hub's concurrent writes
        branch = _current_branch(cdir)
        _git(cdir, "pull", "--rebase", "origin", branch, check=False)

        result = _git(cdir, "push", "origin", branch, check=False)
        if result.returncode != 0:
            logger.warning("push failed: %s", result.stderr.strip())
            return False
        logger.info("Pushed agent changes (branch=%s)", branch)
        return True
    except Exception:
        logger.warning("push failed", exc_info=True)
        return False


def skills_dir(cdir: Path | None = None) -> Path:
    """Return <client_dir>/skills/."""
    return (cdir or client_dir()) / "skills"


def notes_dir(cdir: Path | None = None) -> Path:
    """Return <client_dir>/notes/."""
    return (cdir or client_dir()) / "notes"


def tasks_dir(cdir: Path | None = None) -> Path:
    """Return <client_dir>/tasks/."""
    return (cdir or client_dir()) / "tasks"


def _ensure_local_excludes(cdir: Path) -> None:
    """Write local-only gitignore rules to ``.git/info/exclude``.

    Agent-local runtime state (report registry, fetched annotation
    ``.result`` files) lives under the clone but must never be pushed
    to the shared evolution repo. Using ``.git/info/exclude`` keeps the
    tracked ``.gitignore`` untouched.
    """
    exclude_file = cdir / ".git" / "info" / "exclude"
    required = [
        "# cao-bridge: agent-local runtime state (do not track)",
        "reports/",
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
            logger.debug("Added %d lines to %s", len(missing), exclude_file)
    except OSError as exc:
        logger.warning("Could not update %s: %s", exclude_file, exc)


def _ensure_remote(cdir: Path, url: str) -> None:
    """Ensure origin points to the right URL."""
    result = _git(cdir, "remote", "get-url", "origin", check=False)
    current = result.stdout.strip() if result.returncode == 0 else ""
    if current == url:
        return
    if current:
        _git(cdir, "remote", "set-url", "origin", url, check=False)
    else:
        _git(cdir, "remote", "add", "origin", url, check=False)
    logger.debug("Remote origin set to %s", url)
