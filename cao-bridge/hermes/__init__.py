"""CAO co-evolution plugin for Hermes Agent.

Reuses the same CaoBridge class as the MCP server and other agent plugins,
ensuring hermes data flows through the identical path:
  Agent writes files locally → git push → Hub git pull → BM25 reindex
  Agent-side: git pull from shared repo → ~/.cao-evolution-client/

Hooks:
  on_session_start — git pull + register + inject shared knowledge + pull skills
  on_session_end   — write hermes skills + MEMORY.md to local git, push, pull
  pre_llm_call     — inject heartbeat prompt if pending
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# CaoBridge and git_sync live one directory up (cao-bridge/)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cao_bridge import CaoBridge  # noqa: E402
from git_sync import push as git_push, skills_dir as client_skills_dir, notes_dir as client_notes_dir, set_session_dir  # noqa: E402
from session_manager import create_session, deactivate_session, touch_session  # noqa: E402

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
        """Git pull → register → inject shared knowledge → pull skills to local."""
        # 1. Session init — creates isolated session dir and git sync
        try:
            sdir = bridge.init_session()
            logger.info("Session initialized: %s", sdir)
        except Exception:
            logger.warning("Session init failed", exc_info=True)

        # 2. Pull shared skills into hermes local dir
        _pull_skills_from_clone()

        # 3. Register with Hub
        try:
            bridge.register()
            logger.info("Registered with CAO Hub: %s", bridge.terminal_id)
        except Exception:
            logger.warning("Failed to register with CAO Hub", exc_info=True)
            return None

        # 4. Inject shared knowledge as context
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

        # Git push local writes to Hub
        if pushed_skills + pushed_memory > 0:
            git_push(message=f"hermes sync: {pushed_skills} skills, {pushed_memory} notes")

        # Trigger grader skill if a task context is available
        task_id = ctx.settings.get("task_id", "hermes-sync")
        if task_id != "hermes-sync":
            try:
                task_info = bridge.get_task(task_id)
                grader_skill = (task_info or {}).get("grader_skill", "")
                if grader_skill:
                    # Queue grader prompt for next pre_llm injection
                    grader_prompt = (
                        f"Grade this session's output using evo-skills/{grader_skill}/SKILL.md.\n"
                        f"Task: {task_id}\n"
                        f"After evaluation, print: CAO_SCORE=<float between 0.0 and 1.0>\n"
                    )
                    pending_heartbeats.insert(0, grader_prompt)
                    logger.info("Queued grader skill prompt for task %s", task_id)
            except Exception:
                logger.debug("Failed to fetch task info for grading", exc_info=True)

        # After push, report a summary score to trigger heartbeat mechanism
        if pushed_skills + pushed_memory > 0:
            try:
                resp = bridge.report_score(
                    task_id=task_id,
                    score=None,
                    title=f"hermes sync: {pushed_skills} skills, {pushed_memory} notes",
                )
                # Extract heartbeat prompts from response
                hb_list = resp.get("heartbeat_prompts", [])
                for hb in hb_list:
                    prompt = hb.get("prompt", "") if isinstance(hb, dict) else str(hb)
                    if prompt:
                        pending_heartbeats.append(prompt)
            except Exception:
                logger.debug("Score report for heartbeat failed", exc_info=True)

        bridge.close_session()

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


def _pull_skills_from_clone() -> int:
    """Copy skills from ~/.cao-evolution-client/skills/ → ~/.hermes/skills/.

    Returns the number of skills synced.
    """
    import shutil

    src = client_skills_dir()
    if not src.exists():
        return 0

    target = Path(os.environ.get("HERMES_SKILLS_DIR", str(DEFAULT_HERMES_SKILLS)))
    target.mkdir(parents=True, exist_ok=True)

    count = 0
    for child in src.iterdir():
        if child.is_dir() and (child / "SKILL.md").exists():
            dest = target / child.name
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copytree(child, dest, dirs_exist_ok=True)
            count += 1
            logger.debug("Pulled skill %s → %s", child.name, dest)

    if count:
        logger.info("Pulled %d shared skills into hermes local dir", count)
    return count


def _push_skills(bridge: CaoBridge) -> int:
    """Copy hermes skills to local git clone. Returns count written."""
    skills_src = Path(os.environ.get("HERMES_SKILLS_DIR", str(DEFAULT_HERMES_SKILLS)))
    if not skills_src.exists():
        return 0

    dest = client_skills_dir()
    dest.mkdir(parents=True, exist_ok=True)

    count = 0
    for skill_dir in skills_src.iterdir():
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            content = skill_md.read_text(encoding="utf-8", errors="replace")
            target = dest / skill_dir.name
            target.mkdir(parents=True, exist_ok=True)
            (target / "SKILL.md").write_text(content, encoding="utf-8")
            count += 1
            logger.debug("Wrote skill to local clone: %s", skill_dir.name)
        except Exception:
            logger.warning("Failed to write skill %s", skill_dir.name, exc_info=True)
    logger.info("Wrote %d hermes skills to local clone", count)
    return count


def _push_memory(bridge: CaoBridge) -> int:
    """Parse MEMORY.md and write entries as note files locally. Returns count written."""
    mem_path = Path(os.environ.get("HERMES_MEMORY_PATH", str(DEFAULT_HERMES_MEMORY)))

    dest = client_notes_dir()
    dest.mkdir(parents=True, exist_ok=True)

    count = 0
    for title, content in parse_memory(mem_path):
        try:
            import time
            slug = title[:40].replace(" ", "-").replace("/", "-").lower()
            fname = f"hermes-{slug}-{int(time.time())}-{count:03d}.md"
            (dest / fname).write_text(
                f"---\ntitle: \"{title}\"\ntags: [hermes, memory]\n---\n{content}",
                encoding="utf-8",
            )
            count += 1
        except Exception:
            logger.warning("Failed to write memory entry: %s", title, exc_info=True)
    logger.info("Wrote %d memory entries to local clone", count)
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
