#!/usr/bin/env python3
"""CAO Bridge — Claude Code Stop hook.

Implements auto-grading + heartbeat injection as a state machine.
Mirrors the OpenCode cao-bridge.ts plugin behavior.

State machine:
  idle → (task completed) → grading → (score parsed) → heartbeat → idle

Configure in .claude/settings.local.json:
  { "hooks": { "Stop": [{ "matcher":"",
      "hooks":[{"type":"command",
        "command":"python3 /path/to/cao-stop-grader.py"}]}]}}

Env: CAO_HUB_URL, CAO_STATE_FILE (shared with session-start hook)
"""

import json
import os
import re
import sys
from pathlib import Path

HUB = os.environ.get("CAO_HUB_URL", "http://127.0.0.1:9889").rstrip("/")
SESSION_STATE = os.environ.get("CAO_STATE_FILE", "")
DEBUG = os.environ.get("CAO_DEBUG", "") == "1"

GRADER_STATE_DIR = Path("/tmp/cao-grader")
GRADER_STATE_DIR.mkdir(exist_ok=True)


def dbg(msg: str):
    if not DEBUG:
        return
    with open("/tmp/cao-stop-grader-debug.log", "a") as f:
        from datetime import datetime
        f.write(f"{datetime.now().isoformat()} {msg}\n")


def hub_get(path: str):
    import urllib.request
    try:
        req = urllib.request.Request(HUB + path)
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        dbg(f"hub GET {path} failed: {e}")
        return None


def hub_post(path: str, body: dict):
    import urllib.request
    data = json.dumps(body).encode()
    try:
        req = urllib.request.Request(
            HUB + path, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        dbg(f"hub POST {path} failed: {e}")
        return None


def read_state(session_id: str) -> dict:
    p = GRADER_STATE_DIR / f"{session_id}.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {"phase": "idle", "task_id": "", "heartbeats": []}


def write_state(session_id: str, state: dict):
    p = GRADER_STATE_DIR / f"{session_id}.json"
    p.write_text(json.dumps(state))


def get_terminal_id() -> str:
    if SESSION_STATE and Path(SESSION_STATE).exists():
        try:
            data = json.loads(Path(SESSION_STATE).read_text())
            return data.get("terminal_id", "")
        except Exception:
            pass
    for f in sorted(Path("/tmp").glob("cao-claude-state-*.json"), reverse=True):
        try:
            data = json.loads(f.read_text())
            tid = data.get("terminal_id", "")
            if tid:
                return tid
        except Exception:
            continue
    return ""


def extract_task_id(transcript_path: str) -> str:
    if not transcript_path or not Path(transcript_path).exists():
        return ""
    try:
        text = Path(transcript_path).read_text()
        matches = re.findall(r"\[CAO Task ID:\s*([^\]]+)\]", text)
        return matches[-1].strip() if matches else ""
    except Exception:
        return ""


def extract_score(text: str) -> int | None:
    m = re.search(r"CAO_SCORE\s*=\s*(\d+)", text)
    return int(m.group(1)) if m else None


def extract_feasibility(text: str) -> str:
    m = re.search(r"Feasibility:\s*(FEASIBLE|INFEASIBLE)", text, re.IGNORECASE)
    return m.group(1).upper() if m else ""


def build_grader_prompt(task_id: str, grader_skill: str, output_snippet: str) -> str:
    return (
        f"You just completed a task. Now grade your own output using the grader skill.\n\n"
        f"## Instructions\n"
        f"Load and follow evo-skills/{grader_skill}/SKILL.md to evaluate the output.\n\n"
        f"## Task ID\n{task_id}\n\n"
        f"## Your Output to Grade\n"
        f"{output_snippet[:3000]}\n\n"
        f"## Required Output Format\n"
        f"After evaluation, print exactly one line: CAO_SCORE=<integer 0-100>\n"
        f"Then state Feasibility: FEASIBLE or INFEASIBLE, followed by a brief rationale."
    )


def block(reason: str):
    """Return decision=block to force Claude to continue with the given reason."""
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
    sys.exit(2)


def allow():
    """Allow Claude to stop normally."""
    json.dump({}, sys.stdout)
    sys.exit(0)


def main():
    hook_input = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
    session_id = hook_input.get("session_id", "unknown")
    last_msg = hook_input.get("last_assistant_message", "")
    transcript_path = hook_input.get("transcript_path", "")

    state = read_state(session_id)
    phase = state.get("phase", "idle")
    task_id = state.get("task_id", "")
    heartbeats = state.get("heartbeats", [])
    terminal_id = get_terminal_id()
    profile = os.environ.get("CAO_AGENT_PROFILE", "remote-claude-code")

    dbg(f"phase={phase} task={task_id} tid={terminal_id} msg_len={len(last_msg)}")

    # ── Phase: GRADING — parse CAO_SCORE from grader output ──────────
    if phase == "grading":
        score = extract_score(last_msg)
        if score is not None:
            feasibility = extract_feasibility(last_msg)
            feedback = last_msg[:500]
            dbg(f"score={score} feasibility={feasibility} task={task_id}")

            resp = hub_post(f"/evolution/{task_id}/scores", {
                "score": score,
                "title": f"grader-skill ({feasibility})" if feasibility else "grader-skill",
                "feedback": feedback,
                "agent_profile": profile,
            })

            new_heartbeats = []
            if resp and resp.get("heartbeat_prompts"):
                new_heartbeats = resp["heartbeat_prompts"]
                dbg(f"heartbeats: {[h.get('name') for h in new_heartbeats]}")

            if new_heartbeats:
                state.update(phase="heartbeat", heartbeats=new_heartbeats, task_id="")
                write_state(session_id, state)
                hb = new_heartbeats[0]
                state["heartbeats"] = new_heartbeats[1:]
                write_state(session_id, state)
                block(hb.get("prompt", hb.get("name", "evolve")))
            else:
                state.update(phase="idle", task_id="", heartbeats=[])
                write_state(session_id, state)
                allow()
        else:
            dbg("grading phase but no CAO_SCORE found, allowing stop")
            state.update(phase="idle", task_id="", heartbeats=[])
            write_state(session_id, state)
            allow()
        return

    # ── Phase: HEARTBEAT — inject next heartbeat or go idle ──────────
    if phase == "heartbeat":
        if heartbeats:
            hb = heartbeats[0]
            state["heartbeats"] = heartbeats[1:]
            write_state(session_id, state)
            dbg(f"injecting heartbeat: {hb.get('name', '?')}")
            block(hb.get("prompt", hb.get("name", "evolve")))
        else:
            state.update(phase="idle", task_id="", heartbeats=[])
            write_state(session_id, state)
            allow()
        return

    # ── Phase: IDLE — detect task completion, inject grader ──────────

    # Try to find current task_id from transcript
    if not task_id:
        task_id = extract_task_id(transcript_path)
        if task_id:
            state["task_id"] = task_id
            write_state(session_id, state)
            dbg(f"detected task_id from transcript: {task_id}")

    if not task_id:
        allow()
        return

    # Check if agent self-graded (CAO_SCORE in output without us injecting grader)
    score = extract_score(last_msg)
    if score is not None:
        feasibility = extract_feasibility(last_msg)
        dbg(f"agent self-graded: score={score} task={task_id}")
        hub_post(f"/evolution/{task_id}/scores", {
            "score": score,
            "title": f"self-graded ({feasibility})" if feasibility else "self-graded",
            "feedback": last_msg[:500],
            "agent_profile": profile,
        })
        state.update(phase="idle", task_id="", heartbeats=[])
        write_state(session_id, state)
        allow()
        return

    # Check Hub: has the task been scored already?
    task_info = hub_get(f"/evolution/{task_id}")
    if task_info and task_info.get("attempt_count", 0) > 0:
        dbg(f"task {task_id} already has scores, skipping grader")
        allow()
        return

    # Check if the agent seems to have completed the task
    # Look for completion signals in the last message
    completion_signals = [
        r"cao_report.*completed",
        r"任务完成", r"已完成", r"报告已生成", r"PoC.*完成",
        r"task.*completed", r"report.*generated", r"poc.*generated",
        r"status.*completed",
    ]
    is_completed = any(
        re.search(pat, last_msg, re.IGNORECASE) for pat in completion_signals
    )

    if not is_completed:
        # Also check Hub terminal status
        if terminal_id:
            status = hub_get(f"/remotes/{terminal_id}/status")
            if status and status.get("status") == "completed":
                is_completed = True

    if not is_completed:
        allow()
        return

    # Task completed, no score yet → inject grader
    grader_skill = ""
    if task_info:
        yaml_str = task_info.get("task_yaml", "")
        m = re.search(r"grader_skill:\s*(\S+)", yaml_str)
        if m:
            grader_skill = m.group(1)
    if not grader_skill:
        grader_skill = "grader-oh-poc"

    dbg(f"injecting grader: skill={grader_skill} task={task_id}")
    state.update(phase="grading", task_id=task_id)
    write_state(session_id, state)
    block(build_grader_prompt(task_id, grader_skill, last_msg))


if __name__ == "__main__":
    main()
