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
