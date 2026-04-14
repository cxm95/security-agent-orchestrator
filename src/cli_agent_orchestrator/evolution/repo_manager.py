"""RepoManager — path abstraction layer for CAO evolution data.

Phase A (current): single git repo, flat directory layout under evolution_dir.
Phase B (future):  each content type in its own git repo.

All code accesses content directories through RepoManager.get_dir(), enabling
zero-change migration from single-repo to multi-repo layout.

Directory structure (Phase A):
    ~/.cao-evolution/
    ├── .git/                # single git repo at root
    ├── skills/              # shared skills (SKILL.md per subdirectory)
    ├── notes/               # knowledge notes (.md files)
    │   └── _synthesis/
    ├── attempts/            # scored attempts, partitioned by task_id
    │   └── {task_id}/
    ├── graders/             # reusable grader scripts, by category
    │   ├── security/
    │   └── general/
    ├── tasks/               # task definitions (task.yaml per subdirectory)
    │   └── {task_id}/
    ├── reports/             # human-feedback reports, by task_id
    │   └── {task_id}/
    └── heartbeat/           # runtime heartbeat config (git-ignored)
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CONTENT_TYPES = frozenset({
    "skills", "notes", "attempts", "graders", "tasks", "reports",
})


class RepoManager:
    """Manage paths for evolution data content types.

    Args:
        evolution_dir: Root directory (e.g. ~/.cao-evolution).
        mode: "single" (one git repo) or "multi" (per-type git repos, Phase B).
    """

    def __init__(
        self,
        evolution_dir: str | Path,
        mode: str = "single",
    ) -> None:
        self.base = Path(evolution_dir)
        self.mode = mode

    def get_dir(self, content_type: str) -> Path:
        """Return the directory for a given content type.

        Raises ValueError for unknown content types.
        """
        if content_type not in CONTENT_TYPES:
            raise ValueError(
                f"Unknown content type '{content_type}'. "
                f"Valid types: {sorted(CONTENT_TYPES)}"
            )
        return self.base / content_type

    def git_root(self, content_type: str | None = None) -> Path:
        """Return the git root that manages a content type.

        Phase A (single): always returns self.base.
        Phase B (multi):  returns per-type repo root for git-managed types.
        """
        if self.mode == "single":
            return self.base
        # Phase B: skills, notes, attempts, graders each have own git
        if content_type in ("skills", "notes", "attempts", "graders"):
            return self.base / content_type
        return self.base

    def ensure_dirs(self) -> None:
        """Create all required subdirectories. Idempotent."""
        self.base.mkdir(parents=True, exist_ok=True)
        for ct in sorted(CONTENT_TYPES):
            (self.base / ct).mkdir(parents=True, exist_ok=True)
        # Extra subdirectories
        (self.base / "notes" / "_synthesis").mkdir(parents=True, exist_ok=True)
