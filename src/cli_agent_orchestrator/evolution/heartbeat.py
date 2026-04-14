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
    """Return sensible defaults: reflect every 1, consolidate every 5, pivot after 5 stalls."""
    return [
        {"name": "reflect", "every": 1, "trigger": "interval", "is_global": False},
        {"name": "consolidate", "every": 5, "trigger": "interval", "is_global": True},
        {"name": "pivot", "every": 5, "trigger": "plateau", "is_global": False},
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
                  leaderboard: str = "") -> str:
    """Fill template variables in a heartbeat prompt."""
    return (action.prompt
            .replace("{agent_id}", agent_id)
            .replace("{task_id}", task_id)
            .replace("{leaderboard}", leaderboard))


# ── Integration: check_triggers ───────────────────────────────────────

def check_triggers(
    evo_dir: str,
    agent_id: str,
    task_id: str,
    local_eval_count: int,
    global_eval_count: int = 0,
    evals_since_improvement: int = 0,
    leaderboard: str = "",
) -> list[dict]:
    """Check heartbeat triggers and return rendered prompts to send.

    Called by submit_score after processing an attempt.
    Returns list of {"name": str, "prompt": str} for each triggered action.
    """
    runner = build_runner(evo_dir, agent_id)
    triggered = runner.check(
        local_eval_count=local_eval_count,
        global_eval_count=global_eval_count,
        evals_since_improvement=evals_since_improvement,
    )
    results = []
    for action in triggered:
        prompt = render_prompt(action, agent_id, task_id, leaderboard)
        results.append({"name": action.name, "prompt": prompt})
        logger.info(f"Heartbeat triggered: {action.name} for agent={agent_id} task={task_id}")
    return results
