"""CAO co-evolution plugin for Hermes Agent.

Reuses the same CaoBridge class as the MCP server and other agent plugins,
ensuring hermes data flows through the identical path:
  CaoBridge → HTTP API → Hub writes files → git checkpoint → git push/pull

Hooks:
  on_session_start — register + inject shared knowledge
  on_session_end   — push hermes skills + MEMORY.md entries to shared pool
  pre_llm_call     — inject heartbeat prompt if pending
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# CaoBridge lives one directory up (cao-bridge/)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cao_bridge import CaoBridge  # noqa: E402

from .memory_parser import parse_memory  # noqa: E402

logger = logging.getLogger("cao-evolution")

DEFAULT_HERMES_SKILLS = Path.home() / ".hermes" / "skills"
DEFAULT_HERMES_MEMORY = Path.home() / ".hermes" / "memories" / "MEMORY.md"


def register(ctx):
    """Entry point called by Hermes plugin system."""
    hub_url = ctx.settings.get("hub_url", "http://127.0.0.1:9889")
    agent_profile = "remote-hermes"
    if ctx.settings.get("agent_id"):
        agent_profile = f"remote-hermes-{ctx.settings['agent_id']}"

    bridge = CaoBridge(hub_url=hub_url, agent_profile=agent_profile)

    # Buffer for heartbeat prompts received from score reports
    pending_heartbeats: list[str] = []

    def on_start(session):
        """Register with Hub and inject shared knowledge as context."""
        try:
            bridge.register()
            logger.info("Registered with CAO Hub: %s", bridge.terminal_id)
        except Exception:
            logger.warning("Failed to register with CAO Hub", exc_info=True)
            return None

        try:
            results = bridge.search_knowledge(query="", tags="", top_k=5)
            if results:
                return _format_knowledge(results)
        except Exception:
            logger.debug("Failed to fetch shared knowledge", exc_info=True)
        return None

    def on_end(session):
        """Push hermes skills and MEMORY.md entries to Hub."""
        if not bridge.terminal_id:
            # Register failed in on_start; retry once
            try:
                bridge.register()
            except Exception:
                logger.warning("on_end: register retry failed, skipping push")
                return
        pushed_skills = 0
        pushed_memory = 0
        if ctx.settings.get("push_skills", True):
            pushed_skills = _push_skills(bridge)
        if ctx.settings.get("push_memory", True):
            pushed_memory = _push_memory(bridge)

        # After push, report a summary score to trigger heartbeat mechanism
        # The heartbeat prompts come back in the score response
        if pushed_skills + pushed_memory > 0:
            try:
                resp = bridge.report_score(
                    task_id="hermes-sync",
                    score=None,
                    title=f"hermes sync: {pushed_skills} skills, {pushed_memory} notes",
                )
                # Extract heartbeat prompts from response (same as opencode plugin)
                hb_list = resp.get("heartbeat_prompts", [])
                for hb in hb_list:
                    prompt = hb.get("prompt", "") if isinstance(hb, dict) else str(hb)
                    if prompt:
                        pending_heartbeats.append(prompt)
            except Exception:
                logger.debug("Score report for heartbeat failed", exc_info=True)

    def pre_llm(messages, tools):
        """Inject heartbeat prompt if available from score report responses."""
        if not ctx.settings.get("heartbeat_enabled", True):
            return None
        if pending_heartbeats:
            return pending_heartbeats.pop(0)
        return None

    ctx.register_hook("on_session_start", on_start)
    ctx.register_hook("on_session_end", on_end)
    ctx.register_hook("pre_llm_call", pre_llm)


def _push_skills(bridge: CaoBridge) -> int:
    """Scan ~/.hermes/skills/ and push each to Hub. Returns count pushed."""
    skills_dir = Path(os.environ.get("HERMES_SKILLS_DIR", str(DEFAULT_HERMES_SKILLS)))
    if not skills_dir.exists():
        return 0

    count = 0
    for skill_dir in skills_dir.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            content = skill_md.read_text(encoding="utf-8", errors="replace")
            bridge.share_skill(
                name=skill_dir.name,
                content=content,
                tags=["hermes", skill_dir.name],
            )
            count += 1
            logger.debug("Pushed skill: %s", skill_dir.name)
        except Exception:
            logger.warning("Failed to push skill %s", skill_dir.name, exc_info=True)
    logger.info("Pushed %d hermes skills to Hub", count)
    return count


def _push_memory(bridge: CaoBridge) -> int:
    """Parse MEMORY.md and push entries as notes. Returns count pushed."""
    mem_path = Path(os.environ.get("HERMES_MEMORY_PATH", str(DEFAULT_HERMES_MEMORY)))

    count = 0
    for title, content in parse_memory(mem_path):
        try:
            bridge.share_note(
                title=title,
                content=content,
                tags=["hermes", "memory"],
            )
            count += 1
        except Exception:
            logger.warning("Failed to push memory entry: %s", title, exc_info=True)
    logger.info("Pushed %d memory entries to Hub", count)
    return count


def _format_knowledge(results: list) -> str:
    """Format search results for session context injection."""
    lines = ["[CAO Shared Knowledge — recent notes from the team]"]
    for item in results[:5]:
        if isinstance(item, dict):
            title = item.get("title", item.get("name", ""))
            snippet = item.get("content", item.get("snippet", ""))[:200]
            lines.append(f"- **{title}**: {snippet}")
    return "\n".join(lines) if len(lines) > 1 else ""
