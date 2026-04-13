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


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
