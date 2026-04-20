#!/usr/bin/env python3
"""Example: CAO-integrated agent using Claude Agent SDK.

Demonstrates how to build an SDK-based agent that:
1. Registers with CAO Hub
2. Receives L1 knowledge index
3. Polls for tasks and executes them
4. Reports results back to Hub

Prerequisites:
    pip install claude-agent-sdk
    export CAO_HUB_URL=http://127.0.0.1:9889
    export CAO_GIT_REMOTE=<your-evolution-repo>

Usage:
    python example_claude_sdk.py
    python example_claude_sdk.py --profile my-profile --hub http://localhost:9889
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure cao-bridge is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdk import CaoAgentLifecycle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


async def run_agent(lifecycle: CaoAgentLifecycle):
    """Run a single agent loop: poll → execute → report."""
    try:
        from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
    except ImportError:
        logger.error(
            "claude-agent-sdk not installed. "
            "Install with: pip install claude-agent-sdk"
        )
        return

    # Build CAO context (includes L1 index)
    cao_context = lifecycle.build_context(include_kickoff=False)
    logger.info("CAO context built (%d chars)", len(cao_context))

    # Poll for a task
    bridge = lifecycle.bridge
    task_input = bridge.poll()
    if not task_input:
        logger.info("No task available, exiting")
        return

    logger.info("Received task: %s", task_input[:100])
    bridge.report(status="processing")

    # Compose the full prompt with CAO context
    full_prompt = f"{cao_context}\n\n---\n\nTask:\n{task_input}"

    # Run Claude Agent SDK
    options = ClaudeAgentOptions(
        allowed_tools=["Bash", "Read", "Write", "Edit"],
    )

    result_text = ""
    async with ClaudeSDKClient(options=options) as client:
        await client.query(full_prompt)
        async for msg in client.receive_response():
            if hasattr(msg, "content"):
                result_text += str(msg.content)

    # Report back
    bridge.report(status="completed", output=result_text[:5000])
    logger.info("Task completed, result reported")


def main():
    parser = argparse.ArgumentParser(description="CAO + Claude Agent SDK example")
    parser.add_argument("--hub", default="", help="CAO Hub URL")
    parser.add_argument("--profile", default="sdk-claude", help="Agent profile name")
    parser.add_argument("--git-remote", default="", help="Evolution git remote URL")
    args = parser.parse_args()

    lifecycle = CaoAgentLifecycle(
        hub_url=args.hub,
        agent_profile=args.profile,
        git_remote=args.git_remote,
    )

    try:
        lifecycle.start()
        asyncio.run(run_agent(lifecycle))
    finally:
        lifecycle.stop()


if __name__ == "__main__":
    main()
