"""CAO Remote Bridge — shared HTTP client for all bridge variants.

This module talks to the CAO Hub server's /remotes/ endpoints.
"""

import logging
import time
from typing import Optional
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)


class CaoBridge:
    """HTTP client that registers with CAO Hub and exchanges input/output."""

    def __init__(self, hub_url: str = "http://127.0.0.1:9889",
                 agent_profile: str = "remote-agent"):
        self.hub_url = hub_url.rstrip("/")
        self.agent_profile = agent_profile
        self.terminal_id: Optional[str] = None

    _TIMEOUT = 30  # seconds

    def register(self) -> str:
        """Register with Hub, returns terminal_id."""
        resp = requests.post(f"{self.hub_url}/remotes/register",
                             json={"agent_profile": self.agent_profile},
                             timeout=self._TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        self.terminal_id = data["terminal_id"]
        logger.info(f"Registered with Hub: terminal_id={self.terminal_id}")
        return self.terminal_id

    def poll(self) -> Optional[str]:
        """Poll Hub for pending input. Returns message or None."""
        if not self.terminal_id:
            raise RuntimeError("Not registered")
        resp = requests.get(f"{self.hub_url}/remotes/{self.terminal_id}/poll",
                            timeout=self._TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if data.get("has_input"):
            return data["input"]
        return None

    def report(self, status: Optional[str] = None, output: Optional[str] = None,
               append: bool = False) -> None:
        """Report status and/or output to Hub."""
        if not self.terminal_id:
            raise RuntimeError("Not registered")
        body = {}
        if status:
            body["status"] = status
        if output is not None:
            body["output"] = output
            body["append"] = append
        requests.post(f"{self.hub_url}/remotes/{self.terminal_id}/report",
                      json=body, timeout=self._TIMEOUT).raise_for_status()

    def poll_loop(self, interval: float = 2.0):
        """Generator that yields input messages as they arrive."""
        while True:
            try:
                msg = self.poll()
            except requests.RequestException as e:
                logger.warning(f"Poll error (will retry): {e}")
                time.sleep(interval)
                continue
            if msg is not None:
                yield msg
            else:
                time.sleep(interval)

    # ── Evolution endpoints ──────────────────────────────────────────

    def get_grader(self, task_id: str) -> Optional[str]:
        """Fetch grader source code for a task. Returns None if not found."""
        resp = requests.get(f"{self.hub_url}/evolution/{task_id}/grader",
                            timeout=self._TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("grader_code")

    def report_score(self, task_id: str, score: Optional[float],
                     title: str = "", feedback: str = "") -> dict:
        """Report an evaluation score to the Hub."""
        agent_id = self.terminal_id or "anonymous"
        resp = requests.post(
            f"{self.hub_url}/evolution/{task_id}/scores",
            json={"agent_id": agent_id, "score": score,
                   "title": title, "feedback": feedback},
            timeout=self._TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def get_leaderboard(self, task_id: str, top_n: int = 10) -> dict:
        """Get the leaderboard for a task."""
        resp = requests.get(
            f"{self.hub_url}/evolution/{task_id}/leaderboard",
            params={"top_n": top_n}, timeout=self._TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def share_note(self, title: str, content: str,
                   tags: Optional[list] = None, origin_task: str = "",
                   origin_score: Optional[float] = None,
                   confidence: str = "medium") -> dict:
        """Share a knowledge note to the Hub."""
        resp = requests.post(
            f"{self.hub_url}/evolution/knowledge/notes",
            json={"title": title, "content": content,
                   "tags": tags or [], "agent_id": self.terminal_id or "",
                   "origin_task": origin_task, "origin_score": origin_score,
                   "confidence": confidence},
            timeout=self._TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def share_skill(self, name: str, content: str,
                    tags: Optional[list] = None) -> dict:
        """Share a reusable skill to the Hub."""
        resp = requests.post(
            f"{self.hub_url}/evolution/knowledge/skills",
            json={"name": name, "content": content,
                   "tags": tags or [], "agent_id": self.terminal_id or ""},
            timeout=self._TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def search_knowledge(self, query: str, tags: str = "",
                         top_k: int = 10) -> list:
        """Search shared knowledge (notes + skills)."""
        resp = requests.get(
            f"{self.hub_url}/evolution/knowledge/search",
            params={"query": query, "tags": tags, "top_k": top_k},
            timeout=self._TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
