"""Attempt CRUD and leaderboard (ported from coral/hub/attempts.py).

Storage: .cao-evolution/attempts/{task_id}/{run_id}.json
Added: task_id partitioning, compare_to_history() for status determination.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from cli_agent_orchestrator.evolution.types import Attempt


def _attempts_dir(evolution_dir: str | Path, task_id: str) -> Path:
    d = Path(evolution_dir) / "attempts" / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_attempt(evolution_dir: str | Path, attempt: Attempt) -> Path:
    """Write an attempt record. Returns the file path."""
    path = _attempts_dir(evolution_dir, attempt.task_id) / f"{attempt.run_id}.json"
    path.write_text(json.dumps(attempt.to_dict(), indent=2))
    return path


def read_attempts(evolution_dir: str | Path, task_id: str) -> list[Attempt]:
    """Read all attempts for a task, sorted by timestamp ascending."""
    d = _attempts_dir(evolution_dir, task_id)
    attempts = []
    for f in sorted(d.glob("*.json")):
        try:
            attempts.append(Attempt.from_dict(json.loads(f.read_text())))
        except (json.JSONDecodeError, KeyError):
            continue
    attempts.sort(key=lambda a: a.timestamp)
    return attempts


def get_best_score(evolution_dir: str | Path, task_id: str, agent_id: str | None = None) -> float | None:
    """Get the best (highest) score for a task, optionally filtered by agent."""
    attempts = read_attempts(evolution_dir, task_id)
    if agent_id:
        attempts = [a for a in attempts if a.agent_id == agent_id]
    scored = [a.score for a in attempts if a.score is not None]
    return max(scored) if scored else None


def compare_to_history(
    evolution_dir: str | Path, task_id: str, agent_id: str, new_score: float | None
) -> str:
    """Compare a new score to agent's history on this task. Returns status string."""
    if new_score is None:
        return "crashed"
    best = get_best_score(evolution_dir, task_id, agent_id)
    if best is None:
        return "improved"  # first scored attempt
    if new_score > best:
        return "improved"
    if new_score == best:
        return "baseline"
    return "regressed"


def get_leaderboard(
    evolution_dir: str | Path, task_id: str, top_n: int = 20
) -> list[Attempt]:
    """Top N attempts for a task, sorted by score descending."""
    attempts = read_attempts(evolution_dir, task_id)
    scored = [a for a in attempts if a.score is not None]
    scored.sort(key=lambda a: a.score, reverse=True)  # type: ignore[arg-type]
    return scored[:top_n]


def count_evals_since_improvement(
    evolution_dir: str | Path, task_id: str, agent_id: str
) -> int:
    """Count consecutive evaluations since last improvement for an agent on a task."""
    attempts = read_attempts(evolution_dir, task_id)
    agent_attempts = [a for a in attempts if a.agent_id == agent_id and a.score is not None]
    count = 0
    for a in reversed(agent_attempts):
        if a.status == "improved":
            break
        count += 1
    return count


def format_leaderboard(attempts: list[Attempt]) -> str:
    """Format attempts as a markdown leaderboard table."""
    if not attempts:
        return "No attempts yet."

    lines = [
        "| Rank | Score | Agent | Title | Time | Run ID |",
        "|------|-------|-------|-------|------|--------|",
    ]
    for i, a in enumerate(attempts, 1):
        score_s = f"{a.score:.4f}" if a.score is not None else "—"
        title = (a.title[:30] + "…") if len(a.title) > 30 else a.title
        time_s = _fmt_time(a.timestamp)
        lines.append(f"| {i} | {score_s} | {a.agent_id} | {title} | {time_s} | {a.run_id[:8]} |")
    return "\n".join(lines)


def _fmt_time(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        return ts[:16] if ts else "—"
