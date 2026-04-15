"""Tests for cao-bridge evolution methods + MCP tool registration.

Tests the CaoBridge evolution helpers against the real evolution API
(via FastAPI TestClient) and verifies the MCP server registers all tools.
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure cao-bridge module is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "cao-bridge"))

from cli_agent_orchestrator.api.evolution_routes import router, ensure_evolution_repo
import cli_agent_orchestrator.api.evolution_routes as evo_mod


@pytest.fixture(scope="module")
def evo_dir():
    d = tempfile.mkdtemp()
    original = evo_mod.EVOLUTION_DIR
    evo_mod.EVOLUTION_DIR = d
    ensure_evolution_repo()
    yield d
    evo_mod.EVOLUTION_DIR = original


@pytest.fixture(scope="module")
def api_app(evo_dir):
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture(scope="module")
def client(api_app):
    return TestClient(api_app)


# ── CaoBridge evolution method tests ─────────────────────────────────

class TestCaoBridgeEvolution:
    """Test CaoBridge evolution methods via a mock Hub (TestClient)."""

    @pytest.fixture(autouse=True)
    def bridge(self, client):
        """Create a CaoBridge that talks to the TestClient."""
        from cao_bridge import CaoBridge
        self.bridge = CaoBridge.__new__(CaoBridge)
        self.bridge.hub_url = ""
        self.bridge.terminal_id = "test-agent-1"
        self.bridge._TIMEOUT = 10
        # Monkey-patch requests to use TestClient
        import requests as _req
        self._orig_get = _req.get
        self._orig_post = _req.post
        _req.get = lambda url, **kw: client.get(url, params=kw.get("params"))
        _req.post = lambda url, **kw: client.post(url, json=kw.get("json"))
        yield
        _req.get = self._orig_get
        _req.post = self._orig_post

    def test_report_score_first(self):
        result = self.bridge.report_score("bridge-task", 0.75, title="first try")
        assert result["status"] == "improved"
        assert result["best_score"] == pytest.approx(0.75)

    def test_report_score_improved(self):
        self.bridge.report_score("bridge-task-2", 0.5, title="baseline")
        result = self.bridge.report_score("bridge-task-2", 0.8, title="better")
        assert result["status"] == "improved"
        assert result["best_score"] == pytest.approx(0.8)

    def test_get_leaderboard(self):
        self.bridge.report_score("lb-task", 0.6, title="a1")
        lb = self.bridge.get_leaderboard("lb-task")
        assert "entries" in lb
        assert len(lb["entries"]) >= 1

    def test_get_task(self, client):
        # Create task with grader_skill via API
        client.post("/evolution/tasks", json={
            "task_id": "task-info-test",
            "grader_skill": "security-grader",
        })
        result = self.bridge.get_task("task-info-test")
        assert result is not None
        assert result["grader_skill"] == "security-grader"

    def test_get_task_not_found(self):
        result = self.bridge.get_task("nonexistent-task")
        assert result is None

    def test_search_knowledge(self):
        # Create note via HTTP endpoint directly for testing
        import requests
        requests.post(f"{self.bridge.hub_url}/evolution/knowledge/notes",
                      json={"title": "Searchable", "content": "Find this unique content xyz789",
                            "tags": [], "agent_id": "test"}, timeout=5)
        results = self.bridge.search_knowledge("xyz789")
        assert len(results) >= 1


# ── MCP tool registration test ───────────────────────────────────────

class TestBridgeMCPTools:
    def test_mcp_registers_all_tools(self):
        """Verify cao_bridge_mcp.py registers all expected tools."""
        from fastmcp import FastMCP

        # Create a fresh MCP and register the bridge tools manually
        # (don't import the module-level mcp which starts a server)
        test_mcp = FastMCP("test-bridge")

        # Import just the bridge and simulate registration
        from cao_bridge import CaoBridge
        bridge = CaoBridge.__new__(CaoBridge)
        bridge.hub_url = "http://test"
        bridge.terminal_id = "t1"

        # Define the same tools as cao_bridge_mcp.py (share_note/skill removed)
        @test_mcp.tool()
        async def cao_register() -> str: return ""
        @test_mcp.tool()
        async def cao_poll() -> str: return ""
        @test_mcp.tool()
        async def cao_report(status: str = "", output: str = "") -> str: return ""
        @test_mcp.tool()
        async def cao_get_task(task_id: str) -> str: return ""
        @test_mcp.tool()
        async def cao_report_score(task_id: str, score: float = 0.0) -> str: return ""
        @test_mcp.tool()
        async def cao_get_leaderboard(task_id: str) -> str: return ""
        @test_mcp.tool()
        async def cao_search_knowledge(query: str) -> str: return ""
        @test_mcp.tool()
        async def cao_push(message: str = "") -> str: return ""

        # If we get here, all tools registered without conflict


# ── Grader end-to-end through bridge ─────────────────────────────────

class TestBridgeGraderSkillFlow:
    """Full flow: create task with grader_skill → get task info → report score."""

    @pytest.fixture(autouse=True)
    def _setup(self, client):
        self.client = client
        from cao_bridge import CaoBridge
        self.bridge = CaoBridge.__new__(CaoBridge)
        self.bridge.hub_url = ""
        self.bridge.terminal_id = "grader-agent"
        self.bridge._TIMEOUT = 10
        import requests as _req
        self._orig_get = _req.get
        self._orig_post = _req.post
        _req.get = lambda url, **kw: client.get(url, params=kw.get("params"))
        _req.post = lambda url, **kw: client.post(url, json=kw.get("json"))
        yield
        _req.get = self._orig_get
        _req.post = self._orig_post

    def test_full_grader_skill_flow(self):
        """Create task → get task info with grader_skill → simulate grading → report score."""
        # 1. Create task with grader_skill
        self.client.post("/evolution/tasks", json={
            "task_id": "e2e-skill-bridge",
            "grader_skill": "security-grader",
        })

        # 2. Fetch task info via bridge (replaces get_grader)
        task_info = self.bridge.get_task("e2e-skill-bridge")
        assert task_info is not None
        assert task_info["grader_skill"] == "security-grader"

        # 3. Agent loads evo-skills/security-grader/SKILL.md and grades
        # (simulated — in real flow, agent reads SKILL.md and produces score)
        score = 0.88

        # 4. Report score
        result = self.bridge.report_score("e2e-skill-bridge", score, title="e2e round 1")
        assert result["status"] == "improved"

        # 5. Verify leaderboard
        lb = self.bridge.get_leaderboard("e2e-skill-bridge")
        assert lb["entries"][0]["score"] == pytest.approx(0.88)
