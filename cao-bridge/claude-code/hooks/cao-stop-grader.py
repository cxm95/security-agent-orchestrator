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

# Bypass proxy for local Hub communication
os.environ.setdefault("no_proxy", "127.0.0.1,localhost")
if "127.0.0.1" not in os.environ.get("no_proxy", ""):
    os.environ["no_proxy"] = os.environ.get("no_proxy", "") + ",127.0.0.1,localhost"
os.environ["NO_PROXY"] = os.environ["no_proxy"]

HUB = os.environ.get("CAO_HUB_URL", "http://127.0.0.1:9889").rstrip("/")
SESSION_STATE = os.environ.get("CAO_STATE_FILE", "")
DEBUG = os.environ.get("CAO_DEBUG", "") == "1"

# Unified kill switch — set CAO_HOOKS_ENABLED=0 to disable all CAO hooks
if os.environ.get("CAO_HOOKS_ENABLED", "1") == "0":
    json.dump({}, sys.stdout)
    sys.exit(0)

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


def poll_hub_for_task(terminal_id: str) -> str | None:
    """Poll Hub for a pending task for this terminal.

    Returns the task prompt string when Hub has queued input, or ``None``
    when the queue is empty / terminal is unknown / Hub unreachable.
    The Hub consumes the message on read, so we must ``block()`` immediately
    with the returned text to avoid dropping it.
    """
    if not terminal_id:
        return None
    resp = hub_get(f"/remotes/{terminal_id}/poll")
    if not resp:
        return None
    if not resp.get("has_input"):
        return None
    msg = resp.get("input")
    if not msg:
        return None
    dbg(f"poll returned task len={len(msg)} for {terminal_id}")
    return msg


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

    # Stable path: $CAO_CLIENT_BASE_DIR/state/claude-code-<profile>.json,
    # written by cao-session-start.sh.  Fall back to the legacy /tmp
    # pattern so pre-upgrade sessions still work while they drain.
    base = Path(os.environ.get("CAO_CLIENT_BASE_DIR", str(Path.home() / ".cao-evolution-client")))
    state_dir = base / "state"
    candidates = []
    if state_dir.exists():
        candidates.extend(sorted(state_dir.glob("claude-code-*.json"), reverse=True))
    candidates.extend(sorted(Path("/tmp").glob("cao-claude-state-*.json"), reverse=True))
    for f in candidates:
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
        if not matches:
            return ""
        tid = matches[-1].strip()
        if not re.match(r"^[a-zA-Z0-9_-]{3,}$", tid):
            return ""
        return tid
    except Exception:
        return ""


# Task ids matching this pattern are "test / dry-run" — skip grader & heartbeat.
_TEST_TASK_RE = re.compile(r"^(test|generic)(-.*)?$", re.IGNORECASE)


def is_test_task(task_id: str) -> bool:
    return bool(task_id) and bool(_TEST_TASK_RE.match(task_id))


def extract_score(text: str) -> int | None:
    m = re.search(r"CAO_SCORE\s*=\s*(\d+)", text)
    return int(m.group(1)) if m else None


def extract_feasibility(text: str) -> str:
    m = re.search(r"Feasibility:\s*(FEASIBLE|INFEASIBLE)", text, re.IGNORECASE)
    return m.group(1).upper() if m else ""


def build_grader_prompt(task_id: str, grader_skill: str, output_snippet: str) -> str:
    skill_path = Path.home() / ".claude" / "skills" / grader_skill / "SKILL.md"
    return (
        f"You just completed a task. Now grade your own output using the grader skill.\n\n"
        f"## Instructions\n"
        f"Read and follow {skill_path} to evaluate the output.\n\n"
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


def poll_or_allow(terminal_id: str, hook_input: dict):
    """Poll Hub; if a task is pending, inject it as the next turn.

    We intentionally do **not** early-return on ``stop_hook_active``:
    the whole point of this hook is to drain the Hub's work queue by
    chaining block-decisions (the heartbeat flow in this same file
    already relies on multi-block continuations).  Hub ``consume_pending_input``
    pops the queue on read, so repeat polls never see the same task
    twice — an infinite loop would require the Hub to actively
    re-queue work each cycle, which is not how it works.
    """
    _ = hook_input  # reserved for future per-chain limits
    task = poll_hub_for_task(terminal_id)
    if task:
        block(task)
        return
    allow()


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
                "agent_id": terminal_id or "hook",
                "score": score,
                "title": f"grader-skill ({feasibility})" if feasibility else "grader-skill",
                "feedback": feedback,
                "agent_profile": profile,
                "evolution_signals": {
                    "score": score,
                    "feasibility": feasibility or "UNKNOWN",
                    "source": "stop-hook-grader",
                    "agent_profile": profile,
                },
            })

            new_heartbeats = []
            if resp and resp.get("heartbeat_prompts"):
                new_heartbeats = resp["heartbeat_prompts"]
                dbg(f"heartbeats: {[h.get('name') for h in new_heartbeats]}")

            if new_heartbeats:
                state.update(phase="heartbeat", heartbeats=new_heartbeats, task_id="",
                             scored_this_session=True)
                write_state(session_id, state)
                hb = new_heartbeats[0]
                state["heartbeats"] = new_heartbeats[1:]
                write_state(session_id, state)
                block(hb.get("prompt", hb.get("name", "evolve")))
            else:
                state.update(phase="idle", task_id="", heartbeats=[],
                             scored_this_session=True)
                write_state(session_id, state)
                poll_or_allow(terminal_id, hook_input)
        else:
            dbg("grading phase but no CAO_SCORE found, allowing stop")
            state.update(phase="idle", task_id="", heartbeats=[])
            write_state(session_id, state)
            poll_or_allow(terminal_id, hook_input)
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
            poll_or_allow(terminal_id, hook_input)
        return

    # ── Phase: IDLE — detect task completion, inject grader ──────────

    # Try to find current task_id from transcript
    if not task_id:
        task_id = extract_task_id(transcript_path)
        if task_id:
            state.update(task_id=task_id, scored_this_session=False)
            write_state(session_id, state)
            dbg(f"detected task_id from transcript: {task_id}")

    if not task_id:
        # No task in-flight — this is exactly the moment to pick up queued work.
        poll_or_allow(terminal_id, hook_input)
        return

    # Test / dry-run task → skip grader, heartbeat, and score reporting entirely.
    if is_test_task(task_id):
        dbg(f"test task {task_id} detected, skipping evolution pipeline")
        state.update(phase="idle", task_id="", heartbeats=[], scored_this_session=True)
        write_state(session_id, state)
        poll_or_allow(terminal_id, hook_input)
        return

    # Check if agent self-graded (CAO_SCORE in output without us injecting grader)
    score = extract_score(last_msg)
    if score is not None:
        feasibility = extract_feasibility(last_msg)
        dbg(f"agent self-graded: score={score} task={task_id}")
        hub_post(f"/evolution/{task_id}/scores", {
            "agent_id": terminal_id or "hook",
            "score": score,
            "title": f"self-graded ({feasibility})" if feasibility else "self-graded",
            "feedback": last_msg[:500],
            "agent_profile": profile,
            "evolution_signals": {
                "score": score,
                "feasibility": feasibility or "UNKNOWN",
                "source": "stop-hook-self-graded",
                "agent_profile": profile,
            },
        })
        state.update(phase="idle", task_id="", heartbeats=[], scored_this_session=True)
        write_state(session_id, state)
        poll_or_allow(terminal_id, hook_input)
        return

    # Check Hub: does the task exist?
    task_info = hub_get(f"/evolution/{task_id}")
    if not task_info:
        dbg(f"task {task_id} not found on Hub, ignoring")
        state.update(phase="idle", task_id="", heartbeats=[])
        write_state(session_id, state)
        poll_or_allow(terminal_id, hook_input)
        return

    # Skip grading only if THIS terminal already scored in THIS session.
    # Previous attempts from other agents/sessions should not block grading.
    if state.get("scored_this_session"):
        dbg(f"task {task_id} already scored in this session, skipping grader")
        state.update(phase="idle", task_id="", heartbeats=[])
        write_state(session_id, state)
        poll_or_allow(terminal_id, hook_input)
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
        # Task still in flight — don't poll for new work, it would
        # interrupt the current task with a different one.
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
