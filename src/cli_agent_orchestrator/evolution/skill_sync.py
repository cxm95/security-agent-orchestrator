"""Bidirectional skill sync between local agent dirs and CAO shared pool.

Push: scan local agent skill dirs → copy new/updated skills to shared pool.
Pull: copy shared pool skills back to preferred local dir (with backup on conflict).

Supports two pool sources:
  1. Hub-side pool (same machine): ~/.cao-evolution/skills/
  2. Agent-side clone (remote): ~/.cao-evolution-client/skills/

Env vars:
    CAO_SKILL_DIRS       — extra comma-separated dirs to scan (beyond defaults)
    CAO_SKILL_WRITEBACK  — "1" to enable pull/write-back (default off)
    CAO_SKILL_WRITEBACK_TARGET — preferred pull target: "claude-code" | "opencode" | "hermes"
    CAO_CLIENT_DIR       — agent-side clone path (default ~/.cao-evolution-client)
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from cli_agent_orchestrator.evolution.checkpoint import shared_dir

logger = logging.getLogger(__name__)

# Well-known local skill directories per agent type
_DEFAULT_DIRS: dict[str, list[Path]] = {
    "opencode": [
        Path.home() / ".config" / "opencode" / "skills",
        Path.cwd() / ".opencode" / "skills",
    ],
    "claude-code": [
        Path.home() / ".claude" / "skills",
    ],
    "hermes": [
        Path.home() / ".hermes" / "skills",
    ],
}


@dataclass
class SyncResult:
    """Outcome of a sync operation."""
    pushed: list[str] = field(default_factory=list)
    pulled: list[str] = field(default_factory=list)
    backed_up: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _file_hash(path: Path) -> str:
    """SHA-256 hex digest of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def discover_skill_dirs() -> dict[str, Path]:
    """Return {agent_type: path} for all existing local skill dirs."""
    dirs: dict[str, Path] = {}
    for agent, paths in _DEFAULT_DIRS.items():
        for p in paths:
            if p.exists() and p.is_dir():
                dirs[agent] = p
                break  # first existing path wins per agent type

    extra = os.environ.get("CAO_SKILL_DIRS", "")
    if extra:
        for i, raw in enumerate(extra.split(",")):
            p = Path(raw.strip()).expanduser()
            if p.exists() and p.is_dir():
                dirs[f"custom-{i}"] = p

    return dirs


def scan_skills(skill_dir: Path) -> dict[str, Path]:
    """Scan a directory for skills. Returns {skill_name: SKILL.md path}."""
    skills: dict[str, Path] = {}
    if not skill_dir.exists():
        return skills
    for child in skill_dir.iterdir():
        if child.is_dir():
            md = child / "SKILL.md"
            if md.is_file():
                skills[child.name] = md
    return skills


def resolve_writeback_target(
    preferred: str = "claude-code",
    fallback_order: tuple[str, ...] = ("claude-code", "opencode", "hermes"),
) -> Path | None:
    """Resolve the preferred write-back directory.

    Creates the directory if the parent exists (e.g. ~/.claude exists → create ~/.claude/skills).
    Returns None if no suitable location found.
    """
    order = [preferred] + [a for a in fallback_order if a != preferred]
    for agent in order:
        candidates = _DEFAULT_DIRS.get(agent, [])
        for p in candidates:
            if p.exists():
                return p
            # Create if parent exists (e.g. ~/.claude exists)
            if p.parent.exists():
                p.mkdir(parents=True, exist_ok=True)
                return p
    return None


def push_skills(
    evolution_dir: str | Path,
    source_dirs: dict[str, Path] | None = None,
) -> SyncResult:
    """Push local skills into the shared pool. Only copies new/changed skills."""
    result = SyncResult()
    pool = shared_dir(evolution_dir) / "skills"
    pool.mkdir(parents=True, exist_ok=True)

    if source_dirs is None:
        source_dirs = discover_skill_dirs()

    for agent, sdir in source_dirs.items():
        for name, md_path in scan_skills(sdir).items():
            target_dir = pool / name
            target_md = target_dir / "SKILL.md"
            try:
                if target_md.exists() and _file_hash(md_path) == _file_hash(target_md):
                    continue  # unchanged
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(md_path.parent, target_dir, dirs_exist_ok=True)
                result.pushed.append(f"{agent}:{name}")
                logger.info("Pushed skill %s from %s", name, agent)
            except Exception as exc:
                result.errors.append(f"push {agent}:{name}: {exc}")
                logger.warning("Failed to push %s from %s: %s", name, agent, exc)

    return result


def pull_skills(
    evolution_dir: str | Path,
    target_dir: Path | None = None,
    backup: bool = True,
    use_client_clone: bool = False,
) -> SyncResult:
    """Pull shared pool skills to local directory.

    Only runs if CAO_SKILL_WRITEBACK=1 (unless target_dir is explicitly given).

    Parameters
    ----------
    use_client_clone : bool
        If True, read from ~/.cao-evolution-client/skills/ (agent-side git clone)
        instead of the Hub's evolution_dir/skills/.
    """
    result = SyncResult()

    if target_dir is None:
        if os.environ.get("CAO_SKILL_WRITEBACK") != "1":
            return result  # write-back disabled
        preferred = os.environ.get("CAO_SKILL_WRITEBACK_TARGET", "claude-code")
        target_dir = resolve_writeback_target(preferred)
        if target_dir is None:
            result.errors.append("No writable target directory found")
            return result

    if use_client_clone:
        client = Path(os.environ.get("CAO_CLIENT_DIR",
                                     str(Path.home() / ".cao-evolution-client")))
        pool = client / "skills"
    else:
        pool = shared_dir(evolution_dir) / "skills"

    if not pool.exists():
        return result

    for name, pool_md in scan_skills(pool).items():
        local_skill = target_dir / name
        local_md = local_skill / "SKILL.md"
        try:
            if local_md.exists():
                if _file_hash(pool_md) == _file_hash(local_md):
                    continue  # unchanged
                if backup:
                    bak = local_skill / "SKILL.md.bak"
                    shutil.copy2(local_md, bak)
                    result.backed_up.append(name)
                    logger.info("Backed up %s/SKILL.md → SKILL.md.bak", name)

            local_skill.mkdir(parents=True, exist_ok=True)
            shutil.copytree(pool_md.parent, local_skill, dirs_exist_ok=True)
            result.pulled.append(name)
            logger.info("Pulled skill %s to %s", name, target_dir)
        except Exception as exc:
            result.errors.append(f"pull {name}: {exc}")
            logger.warning("Failed to pull %s: %s", name, exc)

    return result


def sync_all(
    evolution_dir: str | Path,
    source_dirs: dict[str, Path] | None = None,
) -> SyncResult:
    """Full bidirectional sync: push locals → pool, then pull pool → preferred local."""
    push_r = push_skills(evolution_dir, source_dirs)
    pull_r = pull_skills(evolution_dir)
    return SyncResult(
        pushed=push_r.pushed,
        pulled=pull_r.pulled,
        backed_up=pull_r.backed_up,
        errors=push_r.errors + pull_r.errors,
    )


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    evo = os.environ.get("CAO_EVOLUTION_DIR", str(Path.home() / ".cao-evolution"))
    r = sync_all(evo)
    print(f"Pushed: {r.pushed}")
    print(f"Pulled: {r.pulled}")
    print(f"Backed up: {r.backed_up}")
    if r.errors:
        print(f"Errors: {r.errors}", file=sys.stderr)
        sys.exit(1)
