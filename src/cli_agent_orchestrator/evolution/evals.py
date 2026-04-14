"""Evals: per-skill evaluation case management for skill evolution.

Each skill can have an `evals.json` file that tracks test cases.
Cases are auto-seeded from failures and used to prevent regressions
when evolving skills.

File format:
{
  "skill_name": "my-skill",
  "cases": [
    {"id": "c1", "input": "...", "expected": "...", "source": "auto|manual"},
    ...
  ]
}
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def evals_path(skill_dir: str | Path, skill_name: str) -> Path:
    """Return path to evals.json for a given skill."""
    return Path(skill_dir) / skill_name / "evals.json"


def read_evals(skill_dir: str | Path, skill_name: str) -> list[dict[str, Any]]:
    """Read eval cases for a skill. Returns empty list if no evals file."""
    p = evals_path(skill_dir, skill_name)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
        return data.get("cases", [])
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read evals for %s: %s", skill_name, e)
        return []


def write_evals(
    skill_dir: str | Path,
    skill_name: str,
    cases: list[dict[str, Any]],
) -> Path:
    """Write eval cases for a skill. Returns path to the evals file."""
    p = evals_path(skill_dir, skill_name)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"skill_name": skill_name, "cases": cases}
    p.write_text(json.dumps(data, indent=2) + "\n")
    return p


def add_eval_case(
    skill_dir: str | Path,
    skill_name: str,
    case_id: str,
    input_data: str,
    expected: str,
    source: str = "auto",
) -> list[dict[str, Any]]:
    """Add an eval case (dedup by id). Returns updated cases list."""
    cases = read_evals(skill_dir, skill_name)
    existing_ids = {c["id"] for c in cases}
    if case_id in existing_ids:
        return cases
    cases.append({
        "id": case_id,
        "input": input_data,
        "expected": expected,
        "source": source,
    })
    write_evals(skill_dir, skill_name, cases)
    return cases


def seed_from_failure(
    skill_dir: str | Path,
    skill_name: str,
    failure_input: str,
    failure_expected: str,
) -> str:
    """Auto-seed an eval case from a failure. Returns the generated case ID."""
    content_hash = hashlib.sha256(f"{failure_input}:{failure_expected}".encode()).hexdigest()[:8]
    case_id = f"auto-{content_hash}"
    add_eval_case(skill_dir, skill_name, case_id, failure_input, failure_expected, "auto")
    return case_id


def remove_eval_case(
    skill_dir: str | Path,
    skill_name: str,
    case_id: str,
) -> list[dict[str, Any]]:
    """Remove an eval case by id. Returns updated cases list."""
    cases = read_evals(skill_dir, skill_name)
    cases = [c for c in cases if c["id"] != case_id]
    write_evals(skill_dir, skill_name, cases)
    return cases
