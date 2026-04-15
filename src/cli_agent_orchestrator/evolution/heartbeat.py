"""Heartbeat: trigger reflect/consolidate/pivot prompts based on eval history.

Ported from CORAL's agent/heartbeat.py + hub/heartbeat.py, simplified for CAO.
The Hub calls check_triggers() after each score submission. Triggered prompts
are delivered to the remote agent via the inbox mechanism.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _load_prompt(name: str) -> str:
    p = _PROMPTS_DIR / f"{name}.md"
    return p.read_text() if p.exists() else ""


DEFAULT_PROMPTS = {
    "reflect": _load_prompt("reflect"),
    "consolidate": _load_prompt("consolidate"),
    "pivot": _load_prompt("pivot"),
    "feedback_reflect": _load_prompt("feedback_reflect"),
    "evolve_skill": _load_prompt("evolve_skill"),
}


# ── Data types ────────────────────────────────────────────────────────

@dataclasses.dataclass
class HeartbeatAction:
    name: str        # "reflect", "consolidate", "pivot", or custom
    every: int       # interval (evals) or plateau threshold
    prompt: str      # prompt template (may contain {task_id}, {agent_id}, {leaderboard})
    trigger: str = "interval"  # "interval" or "plateau"
    is_global: bool = False    # True = use global eval count


class HeartbeatRunner:
    """Check actions against eval counts and plateau state."""

    def __init__(self, actions: list[HeartbeatAction]) -> None:
        self.actions = actions
        self._plateau_fired_at: dict[str, int] = {}

    def check(
        self,
        *,
        local_eval_count: int,
        global_eval_count: int = 0,
        evals_since_improvement: int = 0,
    ) -> list[HeartbeatAction]:
        triggered = []
        for action in self.actions:
            if action.trigger == "plateau":
                if self._check_plateau(action, evals_since_improvement):
                    triggered.append(action)
            else:
                count = global_eval_count if action.is_global else local_eval_count
                if count > 0 and count % action.every == 0:
                    triggered.append(action)
        return triggered

    def _check_plateau(self, action: HeartbeatAction, evals_since: int) -> bool:
        if evals_since < action.every:
            if evals_since == 0:
                self._plateau_fired_at.pop(action.name, None)
            return False
        last = self._plateau_fired_at.get(action.name)
        if last is not None and evals_since - last < action.every:
            return False
        self._plateau_fired_at[action.name] = evals_since
        return True


# ── Config persistence ────────────────────────────────────────────────

def _hb_path(evo_dir: str, agent_id: str) -> Path:
    return Path(evo_dir) / "heartbeat" / f"{agent_id}.json"


def read_heartbeat_config(evo_dir: str, agent_id: str) -> list[dict]:
    p = _hb_path(evo_dir, agent_id)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text()).get("actions", [])
    except (json.JSONDecodeError, OSError):
        return []


def write_heartbeat_config(evo_dir: str, agent_id: str, actions: list[dict]) -> None:
    p = _hb_path(evo_dir, agent_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"actions": actions}, indent=2) + "\n")


def get_default_actions() -> list[dict]:
    """Return sensible defaults: reflect every 1, consolidate every 5, pivot after 5, evolve_skill after 3."""
    return [
        {"name": "reflect", "every": 1, "trigger": "interval", "is_global": False},
        {"name": "consolidate", "every": 5, "trigger": "interval", "is_global": True},
        {"name": "pivot", "every": 5, "trigger": "plateau", "is_global": False},
        {"name": "evolve_skill", "every": 3, "trigger": "plateau", "is_global": False},
    ]


def build_runner(evo_dir: str, agent_id: str) -> HeartbeatRunner:
    """Build a HeartbeatRunner from persisted config (or defaults)."""
    agent_actions = read_heartbeat_config(evo_dir, agent_id)
    global_actions = read_heartbeat_config(evo_dir, "_global")
    raw = agent_actions + global_actions
    if not raw:
        raw = get_default_actions()

    actions = []
    for a in raw:
        prompt = a.get("prompt") or DEFAULT_PROMPTS.get(a["name"], "")
        actions.append(HeartbeatAction(
            name=a["name"],
            every=a.get("every", 1),
            prompt=prompt,
            trigger=a.get("trigger", "interval"),
            is_global=a.get("is_global", False),
        ))
    return HeartbeatRunner(actions)


def render_prompt(action: HeartbeatAction, agent_id: str, task_id: str,
                  leaderboard: str = "",
                  evolution_signals: dict | None = None,
                  evals_since_improvement: int = 0) -> str:
    """Fill template variables in a heartbeat prompt."""
    signals_json = json.dumps(evolution_signals, indent=2) if evolution_signals else "{}"
    return (action.prompt
            .replace("{agent_id}", agent_id)
            .replace("{task_id}", task_id)
            .replace("{leaderboard}", leaderboard)
            .replace("{evolution_signals_json}", signals_json)
            .replace("{evals_since_improvement}", str(evals_since_improvement)))


# ── Integration: check_triggers ───────────────────────────────────────

def check_triggers(
    evo_dir: str,
    agent_id: str,
    task_id: str,
    local_eval_count: int,
    global_eval_count: int = 0,
    evals_since_improvement: int = 0,
    leaderboard: str = "",
    reports_dir: str | Path | None = None,
    evolution_signals: dict | None = None,
) -> list[dict]:
    """Check heartbeat triggers and return rendered prompts to send.

    Called by submit_score after processing an attempt.
    Returns list of {"name": str, "prompt": str} for each triggered action.
    If reports_dir is provided and has new .result files, a feedback_reflect action is injected.
    """
    runner = build_runner(evo_dir, agent_id)
    triggered = runner.check(
        local_eval_count=local_eval_count,
        global_eval_count=global_eval_count,
        evals_since_improvement=evals_since_improvement,
    )
    results = []
    for action in triggered:
        prompt = render_prompt(action, agent_id, task_id, leaderboard, evolution_signals, evals_since_improvement)
        results.append({"name": action.name, "prompt": prompt})
        logger.info(f"Heartbeat triggered: {action.name} for agent={agent_id} task={task_id}")

    # Inject feedback_reflect if there are new .result files
    if reports_dir and has_new_feedback(reports_dir):
        prompt = DEFAULT_PROMPTS.get("feedback_reflect", "")
        signals_json = json.dumps(evolution_signals, indent=2) if evolution_signals else "{}"
        prompt = (prompt
                  .replace("{task_id}", task_id)
                  .replace("{agent_id}", agent_id)
                  .replace("{evolution_signals_json}", signals_json))
        results.append({"name": "feedback_reflect", "prompt": prompt})
        logger.info(f"Heartbeat triggered: feedback_reflect for agent={agent_id} task={task_id}")

    return results


def has_pending_feedback(reports_dir: str | Path) -> bool:
    """Check if there are .report files without corresponding .result files.

    Used by heartbeat to decide if a feedback-reflect should be triggered.
    """
    rdir = Path(reports_dir)
    if not rdir.exists():
        return False
    report_ids = {f.stem for f in rdir.glob("*.report")}
    result_ids = {f.stem for f in rdir.glob("*.result")}
    return bool(report_ids - result_ids)


def has_new_feedback(reports_dir: str | Path) -> bool:
    """Check if there are .result files not yet consumed (no .consumed marker).

    A .result file means human annotation arrived. After the agent processes it,
    we write a .consumed marker so we don't re-trigger feedback_reflect.
    """
    rdir = Path(reports_dir)
    if not rdir.exists():
        return False
    result_ids = {f.stem for f in rdir.glob("*.result")}
    consumed_ids = {f.stem for f in rdir.glob("*.consumed")}
    return bool(result_ids - consumed_ids)


def mark_feedback_consumed(reports_dir: str | Path, report_id: str) -> None:
    """Mark a .result file as consumed so feedback_reflect won't re-trigger."""
    rdir = Path(reports_dir)
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / f"{report_id}.consumed").write_text("")
