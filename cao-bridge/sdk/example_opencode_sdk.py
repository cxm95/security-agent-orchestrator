#!/usr/bin/env python3
"""Example: CAO-integrated agent using OpenCode SDK.

Demonstrates how to build an SDK-based agent that:
1. Registers with CAO Hub
2. Receives L1 knowledge index
3. Polls for tasks and executes them
4. Reports results back to Hub

Prerequisites:
    pip install opencode-ai
    export CAO_HUB_URL=http://127.0.0.1:9889
    export CAO_GIT_REMOTE=<your-evolution-repo>

Usage:
    python example_opencode_sdk.py
    python example_opencode_sdk.py --profile my-profile --hub http://localhost:9889
"""

import argparse
import logging
import sys
from pathlib import Path

# Ensure cao-bridge is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdk import CaoAgentLifecycle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def run_agent(lifecycle: CaoAgentLifecycle, model_id: str, provider_id: str):
    """Run a single agent loop: poll → execute → report."""
    try:
        from opencode_ai import Opencode
    except ImportError:
        logger.error(
            "opencode-ai SDK not installed. "
            "Install with: pip install opencode-ai"
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

    # Run OpenCode SDK
    client = Opencode()
    session = client.session.create()
    logger.info("OpenCode session created: %s", session.id)

    # Send task with CAO context as system prompt
    response = client.session.chat(
        id=session.id,
        model_id=model_id,
        provider_id=provider_id,
        system=cao_context,
        parts=[{"type": "text", "text": task_input}],
    )

    # Extract result
    result_text = ""
    if hasattr(response, "parts"):
        for part in response.parts:
            if hasattr(part, "text"):
                result_text += part.text

    # Report back
    bridge.report(status="completed", output=result_text[:5000])
    logger.info("Task completed, result reported")


def main():
    parser = argparse.ArgumentParser(description="CAO + OpenCode SDK example")
    parser.add_argument("--hub", default="", help="CAO Hub URL")
    parser.add_argument("--profile", default="sdk-opencode", help="Agent profile name")
    parser.add_argument("--git-remote", default="", help="Evolution git remote URL")
    parser.add_argument("--model", default="gpt-4", help="Model ID")
    parser.add_argument("--provider", default="openai", help="Provider ID")
    args = parser.parse_args()

    lifecycle = CaoAgentLifecycle(
        hub_url=args.hub,
        agent_profile=args.profile,
        git_remote=args.git_remote,
    )

    try:
        lifecycle.start()
        run_agent(lifecycle, model_id=args.model, provider_id=args.provider)
    finally:
        lifecycle.stop()


if __name__ == "__main__":
    main()
