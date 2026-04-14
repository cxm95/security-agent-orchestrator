"""Tests for grader_base and evolution MCP tool registration."""

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cli_agent_orchestrator.evolution.grader_base import (
    GraderBase,
    load_grader_from_source,
)


# ── GraderBase unit tests ────────────────────────────────────────────────

class TestGraderBase:
    def test_simple_float_grader(self):
        class G(GraderBase):
            def evaluate(self, result):
                return result["score"]

        g = G()
        score, feedback = g.grade({"score": 0.85})
        assert score == 0.85
        assert feedback == "ok"

    def test_multi_metric_grader(self):
        class G(GraderBase):
            def evaluate(self, result):
                return {"accuracy": 0.9, "coverage": 0.7}

        g = G()
        score, feedback = g.grade({})
        assert abs(score - 0.8) < 1e-9  # mean of 0.9 and 0.7
        assert "accuracy=0.9" in feedback
        assert "coverage=0.7" in feedback

    def test_grader_error_handling(self):
        class G(GraderBase):
            def evaluate(self, result):
                raise ValueError("bad input")

        g = G()
        score, feedback = g.grade({})
        assert score is None
        assert "grader error" in feedback

    def test_grade_returns_none_on_exception(self):
        class G(GraderBase):
            def evaluate(self, result):
                return 1 / 0

        score, feedback = G().grade({})
        assert score is None


# ── load_grader_from_source ──────────────────────────────────────────────

class TestLoadGrader:
    def test_load_simple_grader(self):
        source = '''
class Grader(GraderBase):
    def evaluate(self, result):
        return result.get("vuln_count", 0) * 0.1
'''
        grader = load_grader_from_source(source)
        score, _ = grader.grade({"vuln_count": 5})
        assert score == 0.5

    def test_load_no_grader_class(self):
        with pytest.raises(ValueError, match="must define a class named 'Grader'"):
            load_grader_from_source("x = 1")

    def test_load_wrong_base_class(self):
        source = "class Grader: pass"
        with pytest.raises(TypeError, match="must inherit from GraderBase"):
            load_grader_from_source(source)

    def test_load_grader_with_multi_metric(self):
        source = '''
class Grader(GraderBase):
    def evaluate(self, result):
        return {"vuln": result.get("vuln_count", 0) * 0.1,
                "coverage": result.get("lines_checked", 0) / 100.0}
'''
        grader = load_grader_from_source(source)
        score, feedback = grader.grade({"vuln_count": 3, "lines_checked": 80})
        assert abs(score - 0.55) < 1e-9  # mean of 0.3 and 0.8
        assert "vuln=" in feedback

    def test_blocks_os_import(self):
        source = '''
import os
class Grader(GraderBase):
    def evaluate(self, result):
        os.system("echo pwned")
        return 0.0
'''
        with pytest.raises(ValueError, match="blocked module"):
            load_grader_from_source(source)

    def test_blocks_subprocess_import(self):
        source = '''
import subprocess
class Grader(GraderBase):
    def evaluate(self, result):
        return 0.0
'''
        with pytest.raises(ValueError, match="blocked module"):
            load_grader_from_source(source)

    def test_blocks_from_os_import(self):
        source = '''
from os.path import join
class Grader(GraderBase):
    def evaluate(self, result):
        return 0.0
'''
        with pytest.raises(ValueError, match="blocked module"):
            load_grader_from_source(source)

    def test_allows_safe_imports(self):
        source = '''
import math
class Grader(GraderBase):
    def evaluate(self, result):
        return math.sqrt(result.get("x", 0))
'''
        grader = load_grader_from_source(source)
        score, _ = grader.grade({"x": 4.0})
        assert abs(score - 2.0) < 1e-9

    def test_rejects_syntax_error(self):
        source = 'def broken(:'
        with pytest.raises(ValueError, match="syntax error"):
            load_grader_from_source(source)


# ── MCP tool registration test ───────────────────────────────────────────
# MCP tools are thin HTTP wrappers. We verify they register successfully
# and have the correct signatures. The actual HTTP calls are tested in
# test_evolution_api.py against the FastAPI TestClient.

class TestMCPToolRegistration:
    def test_tools_register_without_error(self):
        """Verify register_evolution_tools() doesn't raise."""
        from fastmcp import FastMCP
        from cli_agent_orchestrator.mcp_server.evolution_tools import register_evolution_tools
        test_mcp = FastMCP("test-evolution")
        register_evolution_tools(test_mcp)
        # If we get here, registration succeeded

    def test_module_level_http_is_patchable(self):
        """Verify _http and API_BASE_URL can be patched for testing."""
        import cli_agent_orchestrator.mcp_server.evolution_tools as evo_tools
        from cli_agent_orchestrator.mcp_server.evolution_tools import register_evolution_tools

        mock_http = MagicMock()
        original_http = evo_tools._http
        original_base = evo_tools.API_BASE_URL
        evo_tools._http = mock_http
        evo_tools.API_BASE_URL = "http://test:9889"
        try:
            assert evo_tools._http is mock_http
            assert evo_tools.API_BASE_URL == "http://test:9889"
        finally:
            evo_tools._http = original_http
            evo_tools.API_BASE_URL = original_base


# ── End-to-end: grader + API score report ────────────────────────────────
# Simulates what a remote agent actually does: grade locally, then report.

class TestGraderToAPIFlow:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self._test_evo_dir = tempfile.mkdtemp()
        import cli_agent_orchestrator.api.evolution_routes as evo_mod
        self._original_dir = evo_mod.EVOLUTION_DIR
        evo_mod.EVOLUTION_DIR = self._test_evo_dir
        evo_mod.ensure_evolution_repo()
        yield
        evo_mod.EVOLUTION_DIR = self._original_dir

    def test_grade_then_report(self):
        """Full flow: load grader → evaluate → report score → get leaderboard."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from cli_agent_orchestrator.api.evolution_routes import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        # 1. Create task with grader
        grader_code = '''
class Grader(GraderBase):
    def evaluate(self, result):
        return result.get("vuln_count", 0) * 0.1
'''
        r = client.post("/evolution/tasks", json={
            "task_id": "sec-audit",
            "grader_code": grader_code,
        })
        assert r.status_code == 201

        # 2. Remote agent pulls grader
        r = client.get("/evolution/sec-audit/grader")
        source = r.json()["grader_code"]

        # 3. Load and run grader locally
        grader = load_grader_from_source(source)
        score, feedback = grader.grade({"vuln_count": 7})
        assert score == pytest.approx(0.7)

        # 4. Report score to Hub
        r = client.post("/evolution/sec-audit/scores", json={
            "agent_id": "remote-1",
            "score": score,
            "title": "scan round 1",
            "feedback": feedback,
        })
        data = r.json()
        assert data["status"] == "improved"
        assert data["best_score"] == pytest.approx(0.7)

        # 5. Check leaderboard
        r = client.get("/evolution/sec-audit/leaderboard")
        lb = r.json()
        assert len(lb["entries"]) == 1
        assert lb["entries"][0]["score"] == pytest.approx(0.7)
