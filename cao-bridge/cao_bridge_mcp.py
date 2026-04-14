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
import sys

from fastmcp import FastMCP

# Add parent dir so cao_bridge module is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cao_bridge import CaoBridge

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

hub_url = os.environ.get("CAO_HUB_URL", "http://127.0.0.1:9889")
agent_profile = os.environ.get("CAO_AGENT_PROFILE", "remote-opencode")

bridge = CaoBridge(hub_url=hub_url, agent_profile=agent_profile)

mcp = FastMCP(
    "cao-bridge",
    instructions=(
        "CAO remote bridge. Use cao_register first, then cao_poll to check for tasks, "
        "and cao_report to send back results."
    ),
)


@mcp.tool()
async def cao_register() -> str:
    """Register this agent with the CAO Hub. Call once at session start.
    Returns the assigned terminal_id."""
    tid = bridge.register()
    return json.dumps({"terminal_id": tid, "status": "registered"})


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
async def cao_get_grader(task_id: str) -> str:
    """Fetch grader source code for a task from the Hub.

    Returns JSON with grader_code (string) or null if not found.
    Download this, then run evaluate() locally to get a score.
    """
    code = bridge.get_grader(task_id)
    return json.dumps({"grader_code": code})


@mcp.tool()
async def cao_report_score(
    task_id: str,
    score: float = 0.0,
    title: str = "",
    feedback: str = "",
) -> str:
    """Report an evaluation score to the Hub.

    Args:
        task_id: The task being evaluated
        score: Numeric score (higher is better). Use 0 for crashes.
        title: Short description of this attempt
        feedback: Grader feedback text
    """
    result = bridge.report_score(task_id, score, title=title, feedback=feedback)
    return json.dumps(result)


@mcp.tool()
async def cao_get_leaderboard(task_id: str, top_n: int = 10) -> str:
    """Get the leaderboard for a task — top attempts sorted by score."""
    result = bridge.get_leaderboard(task_id, top_n=top_n)
    return json.dumps(result)


@mcp.tool()
async def cao_share_note(
    title: str,
    content: str,
    tags: str = "",
    origin_task: str = "",
    confidence: str = "medium",
) -> str:
    """Share a knowledge note with the team via the Hub.

    Args:
        title: Note title
        content: Note body (markdown)
        tags: Comma-separated tags for categorization
        origin_task: Task that produced this insight
        confidence: high/medium/low
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    result = bridge.share_note(title, content, tags=tag_list,
                               origin_task=origin_task, confidence=confidence)
    return json.dumps(result)


@mcp.tool()
async def cao_share_skill(
    name: str,
    content: str,
    tags: str = "",
) -> str:
    """Share a reusable skill with the team via the Hub.

    Args:
        name: Skill name (alphanumeric, hyphens, underscores)
        content: Skill content (markdown)
        tags: Comma-separated tags
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    result = bridge.share_skill(name, content, tags=tag_list)
    return json.dumps(result)


@mcp.tool()
async def cao_search_knowledge(
    query: str,
    tags: str = "",
    top_k: int = 10,
) -> str:
    """Search shared knowledge (notes + skills) by text and tags.

    Returns matching notes and skills with snippets.
    """
    results = bridge.search_knowledge(query, tags=tags, top_k=top_k)
    return json.dumps(results)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
