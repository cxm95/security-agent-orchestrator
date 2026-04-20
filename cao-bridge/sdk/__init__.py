"""CAO Bridge SDK integration for Python-based agent frameworks.

Provides lifecycle helpers for agents built with:
- Claude Agent SDK (anthropics/claude-agent-sdk-python)
- OpenCode SDK (anomalyco/opencode-sdk-python)
- Any Python agent that can inject system prompts programmatically

Usage:
    from sdk import CaoAgentLifecycle

    lifecycle = CaoAgentLifecycle(hub_url="http://127.0.0.1:9889")
    lifecycle.start()

    # Get context to inject into agent's initial prompt
    context = lifecycle.build_context()

    # ... run your agent with context injected ...

    lifecycle.stop()
"""

from sdk.lifecycle import CaoAgentLifecycle

__all__ = ["CaoAgentLifecycle"]
