"""Evolution MCP tools — appended to the CAO MCP server.

Provides: cao_report_score, cao_get_leaderboard, cao_search_knowledge,
cao_get_shared_notes, cao_get_shared_skills,
cao_create_task, cao_list_tasks, cao_submit_report, cao_fetch_feedback, cao_list_reports,
cao_recall, cao_fetch_document.

All tools call the Hub HTTP API (same pattern as existing MCP tools).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests
from fastmcp import FastMCP
from pydantic import Field

from cli_agent_orchestrator.constants import API_BASE_URL

logger = logging.getLogger(__name__)

_http = requests.Session()
_http.trust_env = False


def register_evolution_tools(mcp: FastMCP) -> None:
    """Register all evolution MCP tools onto the given FastMCP instance."""

    @mcp.tool()
    def cao_report_score(
        task_id: str = Field(description="Task identifier"),
        agent_id: str = Field(description="This agent's terminal ID"),
        score: Optional[float] = Field(default=None, description="Evaluation score (None if crashed)"),
        title: str = Field(default="", description="Short description of the attempt"),
        feedback: str = Field(default="", description="Grader feedback text"),
        agent_profile: str = Field(default="", description="Agent profile name, e.g. 'remote-opencode'"),
        batch: str = Field(default="", description="Batch identifier, e.g. 'batch-1'"),
    ) -> Dict[str, Any]:
        """Report a task evaluation score to the Hub.

        Returns status (improved/baseline/regressed/crashed), best score,
        leaderboard position, and evals since last improvement.
        """
        try:
            body: Dict[str, Any] = {"agent_id": agent_id, "score": score, "title": title, "feedback": feedback}
            if agent_profile:
                body["agent_profile"] = agent_profile
            if batch:
                body["batch"] = batch
            r = _http.post(
                f"{API_BASE_URL}/evolution/{task_id}/scores",
                json=body,
                timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def cao_get_leaderboard(
        task_id: str = Field(description="Task identifier"),
        top_n: int = Field(default=10, description="Number of top entries to return"),
    ) -> Dict[str, Any]:
        """Get the leaderboard for a task — top attempts sorted by score."""
        try:
            r = _http.get(
                f"{API_BASE_URL}/evolution/{task_id}/leaderboard",
                params={"top_n": top_n},
                timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def cao_search_knowledge(
        query: str = Field(description="Search query text"),
        tags: str = Field(default="", description="Comma-separated tags to filter"),
        top_k: int = Field(default=10, description="Max results"),
    ) -> List[Dict[str, Any]]:
        """Search shared knowledge (notes + skills) by text and tags.

        Phase 1: text grep + tag filtering.
        Returns list of matching notes/skills with snippets.
        """
        try:
            r = _http.get(
                f"{API_BASE_URL}/evolution/knowledge/search",
                params={"query": query, "tags": tags, "top_k": top_k},
                timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return [{"error": str(e)}]

    @mcp.tool()
    def cao_get_shared_notes(
        tags: str = Field(default="", description="Comma-separated tags to filter"),
    ) -> List[Dict[str, Any]]:
        """Get shared knowledge notes, optionally filtered by tags."""
        try:
            r = _http.get(
                f"{API_BASE_URL}/evolution/knowledge/notes",
                params={"tags": tags},
                timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return [{"error": str(e)}]

    @mcp.tool()
    def cao_get_shared_skills() -> List[Dict[str, Any]]:
        """Get all shared skills from the Hub."""
        try:
            r = _http.get(
                f"{API_BASE_URL}/evolution/knowledge/skills",
                timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return [{"error": str(e)}]

    # ── Report / Human Feedback tools ────────────────────────────────────

    @mcp.tool()
    def cao_submit_report(
        task_id: str = Field(description="Task identifier"),
        agent_id: str = Field(description="This agent's terminal ID"),
        findings: str = Field(description="JSON array of findings [{description, severity?, file_path?, line?, category?}]"),
        terminal_id: str = Field(default="", description="Terminal/session ID for this agent"),
        auto_score: Optional[float] = Field(default=None, description="Automated score from grader"),
    ) -> Dict[str, Any]:
        """Submit a vulnerability report to the Hub. Returns report_id.

        findings should be a JSON string of an array, e.g.:
        [{"description": "SQL injection", "severity": "high", "file_path": "login.py"}]
        """
        import json as _json
        try:
            findings_list = _json.loads(findings) if isinstance(findings, str) else findings
            r = _http.post(
                f"{API_BASE_URL}/evolution/{task_id}/reports",
                json={
                    "agent_id": agent_id,
                    "terminal_id": terminal_id or agent_id,
                    "findings": findings_list,
                    "auto_score": auto_score,
                },
                timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def cao_fetch_feedback(
        task_id: str = Field(description="Task identifier"),
        terminal_id: str = Field(default="", description="Terminal ID to filter reports by"),
    ) -> Dict[str, Any]:
        """Fetch annotated human feedback for this terminal's reports.

        Returns count and list of annotated reports with human_score and labels (tp/fp/uncertain).
        """
        try:
            params: dict[str, str] = {"status": "annotated"}
            if terminal_id:
                params["terminal_id"] = terminal_id
            r = _http.get(
                f"{API_BASE_URL}/evolution/{task_id}/reports",
                params=params,
                timeout=10,
            )
            r.raise_for_status()
            reports = r.json()
            return {"count": len(reports), "reports": reports}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def cao_list_reports(
        task_id: str = Field(description="Task identifier"),
        terminal_id: str = Field(default="", description="Filter by terminal ID"),
        status: str = Field(default="", description="Filter by status: pending|annotated"),
    ) -> Dict[str, Any]:
        """List reports for a task, optionally filtered by terminal_id or status."""
        try:
            params: dict[str, str] = {}
            if terminal_id:
                params["terminal_id"] = terminal_id
            if status:
                params["status"] = status
            r = _http.get(
                f"{API_BASE_URL}/evolution/{task_id}/reports",
                params=params,
                timeout=10,
            )
            r.raise_for_status()
            return {"reports": r.json()}
        except Exception as e:
            return {"error": str(e)}

    # ── Task management tools ────────────────────────────────────────────

    @mcp.tool()
    def cao_create_task(
        task_id: str = Field(description="Task identifier (alphanumeric, hyphens, underscores)"),
        name: str = Field(default="", description="Human-readable task name"),
        description: str = Field(default="", description="Task description"),
        grader_skill: str = Field(default="", description="Name of evo-skill used for grading, e.g. 'security-grader'"),
        tips: str = Field(default="", description="Comma-separated tips for agents"),
        group: str = Field(default="", description="Task group for cross-task aggregation, e.g. 'poc-experiment-1'"),
        group_tags: str = Field(default="", description="Comma-separated group tags"),
        force: bool = Field(default=False, description="Overwrite existing task (agent-side wins)"),
    ) -> Dict[str, Any]:
        """Create or update a task on the Hub. Remote agents can register tasks.

        grader_skill names an evo-skill that the agent loads to grade its own output.
        group enables cross-task aggregation (e.g. all tasks in an experiment).
        Use force=true to update an existing task (agent-side takes precedence).
        """
        try:
            tips_list = [t.strip() for t in tips.split(",") if t.strip()] if tips else []
            tags_list = [t.strip() for t in group_tags.split(",") if t.strip()] if group_tags else []
            body: Dict[str, Any] = {
                "task_id": task_id, "name": name or task_id,
                "description": description, "grader_skill": grader_skill,
                "tips": tips_list, "created_by": "mcp-agent",
                "force": force,
            }
            if group:
                body["group"] = group
            if tags_list:
                body["group_tags"] = tags_list
            r = _http.post(
                f"{API_BASE_URL}/evolution/tasks",
                json=body,
                timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def cao_list_tasks() -> List[Dict[str, Any]]:
        """List all available tasks on the Hub."""
        try:
            r = _http.get(f"{API_BASE_URL}/evolution/tasks", timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return [{"error": str(e)}]

    # ── Recall (BM25-ranked search) ──────────────────────────────────────

    @mcp.tool()
    def cao_recall(
        query: str = Field(description="Search query text"),
        tags: str = Field(default="", description="Comma-separated tags to filter"),
        top_k: int = Field(default=10, description="Max results"),
        include_content: bool = Field(
            default=False,
            description="Include full document content in results",
        ),
    ) -> List[Dict[str, Any]]:
        """BM25-ranked knowledge recall — more precise than cao_search_knowledge.

        Results sorted by relevance score.
        Set include_content=True to get full document body inline.
        """
        try:
            r = _http.get(
                f"{API_BASE_URL}/evolution/knowledge/recall",
                params={
                    "query": query, "tags": tags,
                    "top_k": top_k, "include_content": include_content,
                },
                timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return [{"error": str(e)}]

    @mcp.tool()
    def cao_fetch_document(
        doc_id: str = Field(description="Document ID (e.g. 'note:finding-1' or 'skill:scanner')"),
    ) -> Dict[str, Any]:
        """Fetch a specific knowledge document by ID (selective sync).

        Use doc_id from cao_recall results to fetch full content.
        """
        try:
            r = _http.get(
                f"{API_BASE_URL}/evolution/knowledge/document/{doc_id}",
                timeout=10,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"error": str(e)}
