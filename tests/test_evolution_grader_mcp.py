"""Tests for grader_base and evolution MCP tool registration."""

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cli_agent_orchestrator.evolution.grader_base import (
    GraderBase,
    load_grader_from_source,
    feedback_stats,
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


# ── MCP report tools registration test ──────────────────────────────────

class TestReportMCPTools:
    def test_report_tools_registered(self):
        """Verify report MCP tools register and have correct names."""
        import asyncio
        from fastmcp import FastMCP
        from cli_agent_orchestrator.mcp_server.evolution_tools import register_evolution_tools
        mcp = FastMCP("test-report-tools")
        register_evolution_tools(mcp)
        tools = asyncio.run(mcp.list_tools())
        tool_names = {t.name for t in tools}
        assert "cao_submit_report" in tool_names
        assert "cao_fetch_feedback" in tool_names
        assert "cao_list_reports" in tool_names


# ── has_pending_feedback test ────────────────────────────────────────────

class TestHasPendingFeedback:
    def test_no_dir(self, tmp_path):
        from cli_agent_orchestrator.evolution.heartbeat import has_pending_feedback
        assert has_pending_feedback(tmp_path / "nope") is False

    def test_no_reports(self, tmp_path):
        from cli_agent_orchestrator.evolution.heartbeat import has_pending_feedback
        assert has_pending_feedback(tmp_path) is False

    def test_report_without_result(self, tmp_path):
        from cli_agent_orchestrator.evolution.heartbeat import has_pending_feedback
        (tmp_path / "r-1.report").write_text("{}")
        assert has_pending_feedback(tmp_path) is True

    def test_report_with_result(self, tmp_path):
        from cli_agent_orchestrator.evolution.heartbeat import has_pending_feedback
        (tmp_path / "r-1.report").write_text("{}")
        (tmp_path / "r-1.result").write_text("{}")
        assert has_pending_feedback(tmp_path) is False

    def test_mixed(self, tmp_path):
        from cli_agent_orchestrator.evolution.heartbeat import has_pending_feedback
        (tmp_path / "r-1.report").write_text("{}")
        (tmp_path / "r-1.result").write_text("{}")
        (tmp_path / "r-2.report").write_text("{}")
        # r-2 has no .result → pending
        assert has_pending_feedback(tmp_path) is True


class TestHasNewFeedback:
    def test_no_dir(self, tmp_path):
        from cli_agent_orchestrator.evolution.heartbeat import has_new_feedback
        assert has_new_feedback(tmp_path / "nope") is False

    def test_no_results(self, tmp_path):
        from cli_agent_orchestrator.evolution.heartbeat import has_new_feedback
        (tmp_path / "r-1.report").write_text("{}")
        assert has_new_feedback(tmp_path) is False

    def test_result_without_consumed(self, tmp_path):
        from cli_agent_orchestrator.evolution.heartbeat import has_new_feedback
        (tmp_path / "r-1.result").write_text("{}")
        assert has_new_feedback(tmp_path) is True

    def test_result_with_consumed(self, tmp_path):
        from cli_agent_orchestrator.evolution.heartbeat import has_new_feedback, mark_feedback_consumed
        (tmp_path / "r-1.result").write_text("{}")
        mark_feedback_consumed(tmp_path, "r-1")
        assert has_new_feedback(tmp_path) is False

    def test_mixed_consumed(self, tmp_path):
        from cli_agent_orchestrator.evolution.heartbeat import has_new_feedback, mark_feedback_consumed
        (tmp_path / "r-1.result").write_text("{}")
        (tmp_path / "r-2.result").write_text("{}")
        mark_feedback_consumed(tmp_path, "r-1")
        # r-2 not consumed yet
        assert has_new_feedback(tmp_path) is True


class TestCheckTriggersWithFeedback:
    def test_feedback_reflect_triggered(self, tmp_path):
        from cli_agent_orchestrator.evolution.heartbeat import check_triggers
        evo_dir = str(tmp_path / "evo")
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "r-1.result").write_text("{}")

        results = check_triggers(
            evo_dir=evo_dir,
            agent_id="agent-x",
            task_id="task-1",
            local_eval_count=0,
            reports_dir=str(reports_dir),
        )
        names = [r["name"] for r in results]
        assert "feedback_reflect" in names

    def test_no_feedback_reflect_when_consumed(self, tmp_path):
        from cli_agent_orchestrator.evolution.heartbeat import check_triggers, mark_feedback_consumed
        evo_dir = str(tmp_path / "evo")
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        (reports_dir / "r-1.result").write_text("{}")
        mark_feedback_consumed(reports_dir, "r-1")

        results = check_triggers(
            evo_dir=evo_dir,
            agent_id="agent-x",
            task_id="task-1",
            local_eval_count=0,
            reports_dir=str(reports_dir),
        )
        names = [r["name"] for r in results]
        assert "feedback_reflect" not in names

    def test_no_feedback_reflect_without_reports_dir(self, tmp_path):
        from cli_agent_orchestrator.evolution.heartbeat import check_triggers
        evo_dir = str(tmp_path / "evo")

        results = check_triggers(
            evo_dir=evo_dir,
            agent_id="agent-x",
            task_id="task-1",
            local_eval_count=0,
        )
        names = [r["name"] for r in results]
        assert "feedback_reflect" not in names


# ── feedback_stats + grade_with_feedback tests ─────────────────────────

class TestFeedbackStats:
    def test_empty_dir(self, tmp_path):
        s = feedback_stats(tmp_path)
        assert s == {"annotated": 0, "tp": 0, "fp": 0, "uncertain": 0, "precision": None}

    def test_nonexistent_dir(self, tmp_path):
        s = feedback_stats(tmp_path / "nope")
        assert s["annotated"] == 0

    def test_single_result_tp(self, tmp_path):
        import json
        (tmp_path / "r-1.result").write_text(json.dumps({"human_labels": [
            {"finding_id": "f-0", "verdict": "tp"},
            {"finding_id": "f-1", "verdict": "tp"},
        ]}))
        s = feedback_stats(tmp_path)
        assert s["annotated"] == 1
        assert s["tp"] == 2
        assert s["fp"] == 0
        assert s["precision"] == 1.0

    def test_mixed_verdicts(self, tmp_path):
        import json
        (tmp_path / "r-1.result").write_text(json.dumps({"human_labels": [
            {"finding_id": "f-0", "verdict": "tp"},
            {"finding_id": "f-1", "verdict": "fp"},
        ]}))
        (tmp_path / "r-2.result").write_text(json.dumps({"human_labels": [
            {"finding_id": "f-0", "verdict": "fp"},
        ]}))
        s = feedback_stats(tmp_path)
        assert s["annotated"] == 2
        assert s["tp"] == 1
        assert s["fp"] == 2
        assert abs(s["precision"] - 1/3) < 1e-9

    def test_list_format(self, tmp_path):
        """Result file can be a bare list of labels."""
        import json
        (tmp_path / "r-1.result").write_text(json.dumps([
            {"finding_id": "f-0", "verdict": "tp"},
        ]))
        s = feedback_stats(tmp_path)
        assert s["tp"] == 1


class TestGradeWithFeedback:
    def test_without_reports_dir(self):
        class G(GraderBase):
            def evaluate(self, result):
                return 0.8

        g = G()
        score, feedback, detail = g.grade_with_feedback({"x": 1})
        assert score == 0.8
        assert detail == {}

    def test_with_empty_reports_dir(self, tmp_path):
        class G(GraderBase):
            def evaluate(self, result):
                return 0.8

        g = G()
        score, feedback, detail = g.grade_with_feedback({"x": 1}, reports_dir=tmp_path)
        assert score == 0.8
        assert detail == {}

    def test_blends_human_precision(self, tmp_path):
        import json
        (tmp_path / "r-1.result").write_text(json.dumps({"human_labels": [
            {"finding_id": "f-0", "verdict": "tp"},
            {"finding_id": "f-1", "verdict": "fp"},
        ]}))

        class G(GraderBase):
            def evaluate(self, result):
                return 1.0

        g = G()
        score, feedback, detail = g.grade_with_feedback({}, reports_dir=tmp_path)
        # 70% * 1.0 + 30% * 0.5 = 0.85
        assert abs(score - 0.85) < 1e-9
        assert "human_precision" in detail
        assert detail["raw_score"] == 1.0
        assert "blended" in feedback
