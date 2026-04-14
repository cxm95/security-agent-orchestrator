"""TIP.md: persistent evolution learnings per skill.

Each skill can have a TIP.md file that records what the agent
learned during skill evolution — what worked, what didn't,
strategies that helped, etc. This is read by the evolve_skill
prompt to provide context for future evolution attempts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def tip_path(skill_dir: str | Path, skill_name: str) -> Path:
    """Return path to TIP.md for a given skill."""
    return Path(skill_dir) / skill_name / "TIP.md"


def read_tip(skill_dir: str | Path, skill_name: str) -> str:
    """Read TIP.md content for a skill. Returns empty string if absent."""
    p = tip_path(skill_dir, skill_name)
    if not p.exists():
        return ""
    try:
        return p.read_text()
    except OSError as e:
        logger.warning("Failed to read TIP.md for %s: %s", skill_name, e)
        return ""


def write_tip(skill_dir: str | Path, skill_name: str, content: str) -> Path:
    """Write TIP.md for a skill. Overwrites existing content."""
    p = tip_path(skill_dir, skill_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def append_tip(
    skill_dir: str | Path,
    skill_name: str,
    entry: str,
) -> Path:
    """Append a timestamped learning entry to TIP.md."""
    existing = read_tip(skill_dir, skill_name)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    new_entry = f"\n## {ts}\n{entry}\n"
    content = existing + new_entry if existing else f"# Evolution Tips for {skill_name}\n{new_entry}"
    return write_tip(skill_dir, skill_name, content)
