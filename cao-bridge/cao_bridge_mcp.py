#!/usr/bin/env python3
"""CAO Bridge — MCP Server variant.

Exposes cao_poll and cao_report as MCP tools that OpenCode/Claude Code/Codex
can call. The agent loads this as an MCP server and actively calls tools.

Usage in opencode.json:
  "mcp": {
    "cao-bridge": {
      "type": "local",
      "command": ["python3", "<path>/cao_bridge_mcp.py"],
      "environment": {
        "CAO_HUB_URL": "http://127.0.0.1:9889",
        "CAO_AGENT_PROFILE": "remote-opencode"
      }
    }
  }
"""

import json
import logging
import os
import atexit
import sys
from typing import Optional

from fastmcp import FastMCP

# Add parent dir so cao_bridge module is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cao_bridge import CaoBridge

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

hub_url = os.environ.get("CAO_HUB_URL", "http://127.0.0.1:9889")
agent_profile = os.environ.get("CAO_AGENT_PROFILE", "remote-opencode")

bridge = CaoBridge(hub_url=hub_url, agent_profile=agent_profile)

# Initialize per-session isolation (git clone into session directory)
git_remote = os.environ.get("CAO_GIT_REMOTE", "")
if git_remote:
    try:
        bridge.init_session(git_remote=git_remote)
        atexit.register(bridge.close_session)
        logger.info("Session initialized: %s", bridge.session_dir)
    except Exception:
        logger.warning("Session init failed, falling back to legacy mode", exc_info=True)

# Recall mode: "full" = git clone + text grep; "selective" = BM25 recall + on-demand fetch
RECALL_MODE = os.environ.get("CAO_RECALL_MODE", "full")


def _read_hook_state_tid() -> str:
    """Read terminal_id from the SessionStart hook's state file.

    The hook writes JSON to:
      ~/.cao-evolution-client/state/claude-code-{profile}.json
    containing {"terminal_id": "...", "session_dir": "..."}.

    Returns the terminal_id if found, empty string otherwise.
    """
    from pathlib import Path

    client_dir = os.environ.get(
        "CAO_CLIENT_DIR",
        str(Path.home() / ".cao-evolution-client"),
    )
    state_file = Path(client_dir).expanduser() / "state" / f"claude-code-{agent_profile}.json"
    if not state_file.exists():
        return ""
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        return data.get("terminal_id", "")
    except Exception:
        return ""

mcp = FastMCP(
    "cao-bridge",
    instructions=(
        "CAO remote bridge. Use cao_register first, then cao_poll to check for tasks, "
        "and cao_report to send back results."
    ),
)


@mcp.tool()
async def cao_register() -> str:
    """Register or reattach this agent with the CAO Hub.

    Call once at session start. Checks multiple sources for a cached
    terminal_id (session metadata, hook state file) and reattaches if
    found. Falls back to a fresh register when the cached id is stale.
    """
    cached = ""
    # Source 1: session_manager metadata (git-based sessions)
    if bridge.session_dir:
        try:
            from session_manager import get_terminal_id
            cached = get_terminal_id(bridge.session_dir)
        except Exception:
            cached = ""

    # Source 2: SessionStart hook state file (Claude Code hooks)
    if not cached:
        cached = _read_hook_state_tid()

    tid = bridge.register_or_reattach(cached_terminal_id=cached)
    status = "reattached" if cached and cached == tid else "registered"
    return json.dumps({"terminal_id": tid, "status": status})


@mcp.tool()
async def cao_poll() -> str:
    """Poll the CAO Hub for pending input/tasks.
    Returns {"has_input": true, "input": "..."} or {"has_input": false}."""
    msg = bridge.poll()
    return json.dumps({"has_input": msg is not None, "input": msg})


@mcp.tool()
async def cao_report(
    status: str = "completed",
    output: str = "",
) -> str:
    """Report status and output back to the CAO Hub.

    Args:
        status: One of "idle", "processing", "completed", "error"
        output: The result text to send back
    """
    bridge.report(status=status, output=output)
    return json.dumps({"ok": True})


# ── Evolution tools ──────────────────────────────────────────────────

@mcp.tool()
async def cao_create_task(
    task_id: str,
    name: str = "",
    description: str = "",
    grader_skill: str = "",
    tips: str = "",
    group: str = "",
    group_tags: str = "",
) -> str:
    """Create a task on the Hub for evolution tracking.

    Call this when the user starts a local task that should be tracked by CAO.
    Args:
        task_id: Unique task identifier (e.g., "sec-audit-2025")
        name: Human-readable task name
        description: What the task involves
        grader_skill: Evo-skill name for grading (e.g., "security-grader")
        tips: Comma-separated hints for agents
        group: Task group for cross-task aggregation (e.g., "poc-experiment-1")
        group_tags: Comma-separated group tags
    Returns JSON with task_id and created status.
    """
    tips_list = [t.strip() for t in tips.split(",") if t.strip()] if tips else []
    tags_list = [t.strip() for t in group_tags.split(",") if t.strip()] if group_tags else []
    result = bridge.create_task(
        task_id=task_id, name=name or task_id, description=description,
        grader_skill=grader_skill, tips=tips_list, group=group,
        group_tags=tags_list or None,
    )
    return json.dumps(result)


@mcp.tool()
async def cao_get_task(task_id: str) -> str:
    """Fetch task info from the Hub, including grader_skill name.

    Returns JSON with task_id, task_yaml, grader_skill, attempt_count, best_score.
    Use grader_skill to know which evo-skill to load for grading.
    """
    info = bridge.get_task(task_id)
    if info is None:
        return json.dumps({"error": f"Task '{task_id}' not found"})
    return json.dumps(info)


@mcp.tool()
async def cao_report_score(
    task_id: str,
    score: float = 0.0,
    title: str = "",
    feedback: str = "",
    agent_profile: str = "",
    batch: str = "",
    evolution_signals: Optional[dict] = None,
) -> str:
    """Report an evaluation score to the Hub.

    Args:
        task_id: The task being evaluated
        score: Numeric score (higher is better). Use 0 for crashes.
        title: Short description of this attempt
        feedback: Grader feedback text
        agent_profile: Agent profile name (e.g., "remote-opencode")
        batch: Batch identifier (e.g., "batch-1")
        evolution_signals: Optional structured context (score, feasibility, etc)
            passed to heartbeat prompts (e.g., cao-reflect).
    """
    result = bridge.report_score(
        task_id, score, title=title, feedback=feedback,
        agent_profile=agent_profile, batch=batch,
        evolution_signals=evolution_signals,
    )
    return json.dumps(result)


@mcp.tool()
async def cao_get_leaderboard(task_id: str, top_n: int = 10) -> str:
    """Get the leaderboard for a task — top attempts sorted by score."""
    result = bridge.get_leaderboard(task_id, top_n=top_n)
    return json.dumps(result)


@mcp.tool()
async def cao_search_knowledge(
    query: str,
    tags: str = "",
    top_k: int = 10,
) -> str:
    """Search shared knowledge (notes + skills) by text and tags.

    Returns matching notes and skills with snippets.
    In selective mode, automatically uses BM25-ranked recall for better results.
    """
    if RECALL_MODE == "selective":
        results = bridge.recall_knowledge(query, tags=tags, top_k=top_k)
    else:
        results = bridge.search_knowledge(query, tags=tags, top_k=top_k)
    return json.dumps(results)


@mcp.tool()
async def cao_recall(
    query: str,
    tags: str = "",
    top_k: int = 10,
    include_content: bool = False,
) -> str:
    """BM25-ranked knowledge recall — more precise than cao_search_knowledge.

    Results are sorted by relevance score. Set include_content=True to get
    full document body inline (no need for separate cao_sync).

    Args:
        query: Search query text.
        tags: Comma-separated tags to filter by.
        top_k: Maximum number of results.
        include_content: If True, include full document content in results.
    """
    results = bridge.recall_knowledge(
        query, tags=tags, top_k=top_k, include_content=include_content,
    )
    return json.dumps(results)


@mcp.tool()
async def cao_fetch_document(doc_id: str) -> str:
    """Fetch a specific knowledge document by ID (selective sync).

    Use doc_id from cao_recall results to fetch full content.
    Format: 'note:<stem>' or 'skill:<name>'.
    """
    result = bridge.fetch_document(doc_id)
    return json.dumps(result)


# ── Report / human-feedback tools ────────────────────────────────────

@mcp.tool()
async def cao_submit_report(
    task_id: str,
    findings: str,
    auto_score: float | None = None,
) -> str:
    """Submit a vulnerability report to the Hub and locally register its id.

    Human annotation is asynchronous — the id is stored in the local
    registry at ~/.cao-evolution-client/reports/registry.json so that
    cao_fetch_feedbacks can later pick up the result.

    Args:
        task_id:   Task identifier.
        findings:  JSON array of findings
                   [{"description": "...", "severity": "high",
                     "file_path": "x.py", "line": 42, "category": "sqli"}]
        auto_score: Optional self-grader score.
    Returns JSON with ``report_id`` and ``finding_count``.
    """
    try:
        findings_list = json.loads(findings) if isinstance(findings, str) else findings
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"findings must be JSON: {e}"})
    try:
        result = bridge.submit_report(
            task_id=task_id, findings=findings_list, auto_score=auto_score,
        )
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def cao_fetch_feedbacks(
    task_id: str = "",
    template_path: str = "",
    output_dir: str = "",
) -> str:
    """Try to pull human annotations for reports this agent has submitted.

    Walks the local registry of pending report ids, asks the Hub whether
    each has been annotated yet, and for any that are ready:
      1. Writes ``<client_dir>/reports/<report_id>.result`` with the
         annotation payload.
      2. Updates the registry entry to status=annotated.
      3. Renders ``evolve_from_feedback.md`` into ``output_dir`` (default:
         current working directory) using the feedback-fetch skill
         template. The agent should then read that file to drive the
         secskill-evo flow.

    Args:
        task_id:       Restrict to a single task; empty = all tasks.
        template_path: Explicit path to the markdown template. If empty,
                       searches env var CAO_FEEDBACK_TEMPLATE, then the
                       installed feedback-fetch skill, then the in-repo
                       evo-skills/feedback-fetch/templates/.
        output_dir:    Directory to write evolve_from_feedback.md into.
                       Default: current working directory.

    Returns JSON:
      ``feedback_md_path``  Empty string if nothing new was fetched.
      ``fetched``           Report ids with freshly pulled annotations.
      ``pending``           Report ids still awaiting annotation.
      ``result_files``      Absolute paths to the .result files written.
    """
    try:
        result = bridge.fetch_feedbacks(
            task_id=task_id,
            template_path=template_path,
            output_dir=output_dir,
        )
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Git sync tools ───────────────────────────────────────────────────

@mcp.tool()
async def cao_sync() -> str:
    """Bidirectional sync: push local changes then pull latest from Hub.

    Call at session start and after writing notes/skills locally.
    Performs: git add + commit + push, then pull from remote.
    Returns sync status.
    """
    try:
        # Push any local changes first
        pushed = bridge.push_repo(message="agent sync")
        # Then pull latest
        cdir = bridge.sync_repo()
        return json.dumps({"ok": True, "pushed": pushed, "client_dir": str(cdir)})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


@mcp.tool()
async def cao_push(message: str = "agent sync") -> str:
    """Push local changes from ~/.cao-evolution-client/ to the remote.

    Call after writing notes or skills locally (e.g. after cao-reflect).
    Stages all changes, commits, and pushes to the shared remote.

    Args:
        message: Commit message describing what changed.
    """
    try:
        ok = bridge.push_repo(message=message)
        return json.dumps({"ok": ok})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


@mcp.tool()
async def cao_pull_skills(target_dir: str = "") -> str:
    """Pull shared skills from the evolution repo into a local directory.

    After cao_sync, this copies skills from the session's skills/
    directory into the agent's local skills directory for automatic loading.

    Args:
        target_dir: Local directory to write skills into.
                    Defaults to ~/.config/opencode/skills if empty.
    """
    from pathlib import Path

    tdir = Path(target_dir) if target_dir else (
        Path.home() / ".config" / "opencode" / "skills"
    )
    try:
        bridge.pull_repo()
        synced = bridge.pull_skills_to_local(tdir)
        return json.dumps({"ok": True, "synced": synced, "target": str(tdir)})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


@mcp.tool()
async def cao_adopt_skill(skill_name: str, new_name: str = "") -> str:
    """Adopt a non-cao-prefixed local skill into the shared pipeline.

    Copies the skill with a ``cao-`` prefix so it participates in
    cross-agent sync.  The original skill is kept unchanged.

    Args:
        skill_name: Local skill directory name (e.g. "my-scanner").
        new_name: Optional custom name (without cao- prefix).
                  Defaults to skill_name → "cao-my-scanner".
    """
    try:
        result = bridge.adopt_skill(skill_name, new_name)
        return json.dumps({"ok": True, **result})
    except ValueError as e:
        return json.dumps({"ok": False, "error": str(e)})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


@mcp.tool()
async def cao_session_info() -> str:
    """Return current session metadata (session_id, directory, status).

    Useful for debugging multi-instance setups.
    """
    if bridge.session_dir:
        try:
            from session_manager import _read_meta
            meta = _read_meta(bridge.session_dir)
            meta["session_dir"] = str(bridge.session_dir)
            return json.dumps(meta)
        except Exception as e:
            return json.dumps({"session_dir": str(bridge.session_dir), "error": str(e)})
    return json.dumps({"session_dir": None, "message": "No session initialized"})


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
