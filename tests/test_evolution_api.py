"""Tests for evolution API routes (/evolution/*)."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Patch EVOLUTION_DIR before importing the routes
_test_evo_dir = tempfile.mkdtemp()


def _patched_evo_dir():
    return _test_evo_dir


@pytest.fixture(autouse=True, scope="module")
def _setup_evo_dir():
    """Set evolution dir to a temp directory for all tests in this module."""
    import cli_agent_orchestrator.api.evolution_routes as evo_mod
    original = evo_mod.EVOLUTION_DIR
    evo_mod.EVOLUTION_DIR = _test_evo_dir
    evo_mod.ensure_evolution_repo()
    yield
    evo_mod.EVOLUTION_DIR = original


@pytest.fixture(scope="module")
def client():
    """Create a TestClient using only the evolution router (no full app lifespan)."""
    from fastapi import FastAPI
    from cli_agent_orchestrator.api.evolution_routes import router
    test_app = FastAPI()
    test_app.include_router(router)
    return TestClient(test_app)


# ── Task CRUD ────────────────────────────────────────────────────────────

class TestTaskEndpoints:
    def test_create_task(self, client):
        r = client.post("/evolution/tasks", json={
            "task_id": "test-scan",
            "name": "Security Scan",
            "description": "Scan repos for vulns",
            "grader_code": "def grade(result): return 0.5\n",
        })
        assert r.status_code == 201
        assert r.json()["task_id"] == "test-scan"

    def test_create_task_duplicate(self, client):
        r = client.post("/evolution/tasks", json={"task_id": "test-scan"})
        assert r.status_code == 409

    def test_list_tasks(self, client):
        r = client.get("/evolution/tasks")
        assert r.status_code == 200
        ids = [t["task_id"] for t in r.json()]
        assert "test-scan" in ids

    def test_get_task(self, client):
        r = client.get("/evolution/test-scan")
        assert r.status_code == 200
        data = r.json()
        assert data["task_id"] == "test-scan"
        assert data["has_grader"] is True
        assert data["attempt_count"] == 0

    def test_get_task_not_found(self, client):
        r = client.get("/evolution/nonexistent-task")
        assert r.status_code == 404

    def test_get_grader(self, client):
        r = client.get("/evolution/test-scan/grader")
        assert r.status_code == 200
        assert "def grade" in r.json()["grader_code"]

    def test_get_grader_not_found(self, client):
        # Create a task without grader
        client.post("/evolution/tasks", json={"task_id": "no-grader"})
        r = client.get("/evolution/no-grader/grader")
        assert r.status_code == 404


# ── Score reporting ──────────────────────────────────────────────────────

class TestScoreEndpoints:
    def test_submit_first_score(self, client):
        r = client.post("/evolution/test-scan/scores", json={
            "agent_id": "agent-1",
            "score": 0.72,
            "title": "first attempt",
            "feedback": "found 3 vulns",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "improved"  # first score is always improved
        assert data["score"] == 0.72
        assert data["best_score"] == 0.72
        assert data["leaderboard_position"] == 1
        assert data["evals_since_improvement"] == 0

    def test_submit_better_score(self, client):
        r = client.post("/evolution/test-scan/scores", json={
            "agent_id": "agent-1",
            "score": 0.85,
            "title": "improved attempt",
        })
        data = r.json()
        assert data["status"] == "improved"
        assert data["best_score"] == 0.85

    def test_submit_worse_score(self, client):
        r = client.post("/evolution/test-scan/scores", json={
            "agent_id": "agent-1",
            "score": 0.60,
            "title": "regression",
        })
        data = r.json()
        assert data["status"] == "regressed"
        assert data["best_score"] == 0.85  # best unchanged
        assert data["evals_since_improvement"] == 1

    def test_submit_equal_score(self, client):
        r = client.post("/evolution/test-scan/scores", json={
            "agent_id": "agent-1",
            "score": 0.85,
            "title": "same as best",
        })
        assert r.json()["status"] == "baseline"

    def test_submit_crashed(self, client):
        r = client.post("/evolution/test-scan/scores", json={
            "agent_id": "agent-1",
            "score": None,
            "title": "crashed run",
        })
        assert r.json()["status"] == "crashed"

    def test_submit_auto_creates_task(self, client):
        r = client.post("/evolution/auto-created/scores", json={
            "agent_id": "agent-1",
            "score": 0.5,
        })
        assert r.status_code == 200
        assert r.json()["status"] == "improved"


# ── Leaderboard & attempts ──────────────────────────────────────────────

class TestLeaderboardEndpoints:
    def test_leaderboard(self, client):
        r = client.get("/evolution/test-scan/leaderboard")
        assert r.status_code == 200
        data = r.json()
        assert data["task_id"] == "test-scan"
        assert len(data["entries"]) >= 3
        # Sorted by score descending
        scores = [e["score"] for e in data["entries"] if e["score"] is not None]
        assert scores == sorted(scores, reverse=True)

    def test_leaderboard_formatted(self, client):
        r = client.get("/evolution/test-scan/leaderboard")
        assert "Rank" in r.json()["formatted"]

    def test_attempts(self, client):
        r = client.get("/evolution/test-scan/attempts")
        assert r.status_code == 200
        assert len(r.json()) >= 3


# ── Knowledge: notes ─────────────────────────────────────────────────────

class TestNoteEndpoints:
    def test_create_note(self, client):
        r = client.post("/evolution/knowledge/notes", json={
            "title": "iptables check method",
            "content": "Use iptables -L -n for fast listing.",
            "tags": ["security", "linux"],
            "agent_id": "agent-1",
            "origin_task": "test-scan",
            "origin_score": 0.85,
        })
        assert r.status_code == 201
        assert r.json()["filename"].endswith(".md")

    def test_list_notes(self, client):
        r = client.get("/evolution/knowledge/notes")
        assert r.status_code == 200
        assert len(r.json()) >= 1
        note = r.json()[0]
        assert "meta" in note
        assert "content" in note

    def test_filter_notes_by_tag(self, client):
        # Create another note with different tag
        client.post("/evolution/knowledge/notes", json={
            "title": "Java heap tuning",
            "content": "Use -Xmx for max heap.",
            "tags": ["java", "performance"],
        })
        r = client.get("/evolution/knowledge/notes?tags=security")
        notes = r.json()
        assert any("security" in n["meta"].get("tags", "") for n in notes)
        assert not any("java" in n["meta"].get("tags", "") and "security" not in n["meta"].get("tags", "") for n in notes)


# ── Knowledge: skills ────────────────────────────────────────────────────

class TestSkillEndpoints:
    def test_create_skill(self, client):
        r = client.post("/evolution/knowledge/skills", json={
            "name": "vuln-scanner",
            "content": "# Vulnerability Scanner\n\nUse nmap for port scanning.",
            "tags": ["security"],
            "agent_id": "agent-1",
        })
        assert r.status_code == 201
        assert r.json()["name"] == "vuln-scanner"

    def test_list_skills(self, client):
        r = client.get("/evolution/knowledge/skills")
        assert r.status_code == 200
        skills = r.json()
        assert len(skills) >= 1
        assert skills[0]["name"] == "vuln-scanner"
        assert "content" in skills[0]


# ── Knowledge: search ────────────────────────────────────────────────────

class TestSearchEndpoints:
    def test_search_notes(self, client):
        r = client.get("/evolution/knowledge/search?query=iptables")
        assert r.status_code == 200
        results = r.json()
        assert len(results) >= 1
        assert results[0]["type"] == "note"

    def test_search_skills(self, client):
        r = client.get("/evolution/knowledge/search?query=nmap")
        results = r.json()
        assert any(r["type"] == "skill" for r in results)

    def test_search_with_tag_filter(self, client):
        r = client.get("/evolution/knowledge/search?query=check&tags=security")
        results = r.json()
        # Should find the iptables note but not unrelated ones
        assert all("security" in r.get("meta", {}).get("tags", "") for r in results if r["type"] == "note")

    def test_search_no_results(self, client):
        r = client.get("/evolution/knowledge/search?query=xyznonexistent")
        assert r.status_code == 200
        assert r.json() == []


# ── Regression tests for code-review fixes ───────────────────────────────

class TestCodeReviewFixes:
    """Tests for bugs found during code review."""

    def test_shared_state_hash_persisted(self, client):
        """Bug: shared_state_hash was set in memory but never written back."""
        tid = "hash-test"
        client.post("/evolution/tasks", json={"task_id": tid})
        client.post(f"/evolution/{tid}/scores", json={
            "agent_id": "agent-h", "score": 0.5, "title": "test",
        })
        # Read attempt from disk
        r = client.get(f"/evolution/{tid}/attempts")
        assert r.status_code == 200
        attempts = r.json()
        assert len(attempts) >= 1
        # The latest attempt should have a non-null shared_state_hash
        latest = attempts[-1]
        assert latest.get("shared_state_hash") is not None, \
            "shared_state_hash should be persisted to disk after checkpoint"

    def test_global_heartbeat_consolidate_triggers(self, client):
        """Bug: global_eval_count was never passed, so consolidate never fired."""
        tid = "global-hb-test"
        client.post("/evolution/tasks", json={"task_id": tid})
        # Submit 5 scores to trigger consolidate (default every=5, is_global=True)
        hb_names = []
        for i in range(5):
            r = client.post(f"/evolution/{tid}/scores", json={
                "agent_id": "agent-ghb", "score": float(i) * 0.1,
            })
            hb_names.extend(r.json().get("heartbeat_triggered", []))
        assert "consolidate" in hb_names, \
            f"consolidate should trigger after 5 global evals, got: {hb_names}"


# ── Multi-dimension score_detail API tests ─────────────────────────────

class TestScoreDetailAPI:
    def test_submit_with_score_detail(self, client):
        tid = "score-detail-test"
        client.post("/evolution/tasks", json={"task_id": tid})
        detail = {"accuracy": 0.92, "speed": 0.78, "coverage": 0.85}
        r = client.post(f"/evolution/{tid}/scores", json={
            "agent_id": "agent-sd",
            "score": 0.85,
            "score_detail": detail,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["score_detail"] == detail
        assert data["score"] == 0.85

    def test_submit_without_score_detail(self, client):
        tid = "no-detail-test"
        client.post("/evolution/tasks", json={"task_id": tid})
        r = client.post(f"/evolution/{tid}/scores", json={
            "agent_id": "agent-nd", "score": 0.5,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["score_detail"] is None

    def test_score_detail_persisted_in_attempts(self, client):
        tid = "persist-detail-test"
        client.post("/evolution/tasks", json={"task_id": tid})
        detail = {"dim_a": 0.7, "dim_b": 0.9}
        client.post(f"/evolution/{tid}/scores", json={
            "agent_id": "agent-pd", "score": 0.8, "score_detail": detail,
        })
        r = client.get(f"/evolution/{tid}/leaderboard")
        data = r.json()
        entries = data["entries"]
        assert len(entries) >= 1
        top = entries[0]
        assert top.get("score_detail") == detail


# ── Evolution signals API ────────────────────────────────────────────────

class TestEvolutionSignalsAPI:
    def test_submit_with_signals(self, client):
        tid = "signals-test"
        client.post("/evolution/tasks", json={"task_id": tid})
        signals = {
            "grader": {"source": "grader.py", "score": 0.75},
            "judge": {"source": "llm", "score": 8, "confidence": 0.9},
        }
        r = client.post(f"/evolution/{tid}/scores", json={
            "agent_id": "agent-sig",
            "score": 0.75,
            "evolution_signals": signals,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["evolution_signals"] == signals

    def test_submit_without_signals(self, client):
        tid = "no-signals-test"
        client.post("/evolution/tasks", json={"task_id": tid})
        r = client.post(f"/evolution/{tid}/scores", json={
            "agent_id": "agent-ns", "score": 0.5,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["evolution_signals"] is None

    def test_signals_in_heartbeat_prompts(self, client):
        """Heartbeat prompts should include evolution signals JSON."""
        tid = "sig-hb-test"
        client.post("/evolution/tasks", json={"task_id": tid})
        signals = {"eval": {"passed": 3, "total": 5}}
        r = client.post(f"/evolution/{tid}/scores", json={
            "agent_id": "agent-shb",
            "score": 0.6,
            "evolution_signals": signals,
        })
        data = r.json()
        prompts = data.get("heartbeat_prompts", [])
        # At least one prompt should contain the signals JSON
        has_signals = any('"eval"' in p["prompt"] for p in prompts)
        assert has_signals, "Heartbeat prompts should contain evolution signals"


# ── Heartbeat prompts in score response ─────────────────────────────────

class TestHeartbeatPrompts:
    def test_heartbeat_prompts_returned(self, client):
        """Score response should include full heartbeat prompt content."""
        tid = "hb-prompt-test"
        client.post("/evolution/tasks", json={"task_id": tid})
        # Submit 1 score — reflect triggers every 1 eval (default)
        r = client.post(f"/evolution/{tid}/scores", json={
            "agent_id": "agent-hbp", "score": 0.5,
        })
        data = r.json()
        assert "heartbeat_prompts" in data
        # reflect should be triggered on first eval
        if "reflect" in data["heartbeat_triggered"]:
            prompts = data["heartbeat_prompts"]
            assert any(p["name"] == "reflect" for p in prompts)
            reflect_prompt = next(p for p in prompts if p["name"] == "reflect")
            assert len(reflect_prompt["prompt"]) > 0

    def test_heartbeat_prompts_contain_agent_id(self, client):
        """Heartbeat prompts should have agent_id interpolated."""
        tid = "hb-agent-test"
        client.post("/evolution/tasks", json={"task_id": tid})
        r = client.post(f"/evolution/{tid}/scores", json={
            "agent_id": "agent-xyz", "score": 0.5,
        })
        data = r.json()
        prompts = data.get("heartbeat_prompts", [])
        for p in prompts:
            # Default prompts reference agent_id
            assert "agent_id" not in p["prompt"] or "{agent_id}" not in p["prompt"]


# ── Task upsert + enhanced fields ────────────────────────────────────────


class TestTaskUpsert:
    def test_create_with_enhanced_fields(self, client):
        r = client.post("/evolution/tasks", json={
            "task_id": "enhanced-1",
            "name": "Enhanced Task",
            "description": "A test task",
            "grader": "security/sql-grader.py",
            "tips": ["Use parameterised queries", "Check auth"],
            "eval_data_path": "/data/sqli.json",
            "created_by": "test-agent",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["task_id"] == "enhanced-1"
        assert data["created"] is True

    def test_upsert_with_force(self, client):
        tid = "upsert-task"
        r1 = client.post("/evolution/tasks", json={"task_id": tid, "name": "v1"})
        assert r1.status_code == 201
        # Without force → 409
        r2 = client.post("/evolution/tasks", json={"task_id": tid, "name": "v2"})
        assert r2.status_code == 409
        # With force → 201 (update)
        r3 = client.post("/evolution/tasks", json={"task_id": tid, "name": "v2", "force": True})
        assert r3.status_code == 201
        assert r3.json()["updated"] is True

    def test_task_yaml_contains_enhanced_fields(self, client):
        """Verify that task.yaml on disk contains all enhanced fields."""
        import cli_agent_orchestrator.api.evolution_routes as evo_mod
        from cli_agent_orchestrator.evolution.checkpoint import shared_dir
        tid = "yaml-fields-test"
        client.post("/evolution/tasks", json={
            "task_id": tid,
            "grader": "general/default.py",
            "tips": ["tip-a", "tip-b"],
            "created_by": "mcp-agent",
        })
        sd = shared_dir(evo_mod.EVOLUTION_DIR)
        yaml_text = (sd / "tasks" / tid / "task.yaml").read_text()
        assert "grader: general/default.py" in yaml_text
        assert "tip-a" in yaml_text
        assert "created_by: mcp-agent" in yaml_text
        assert "last_updated:" in yaml_text

    def test_grader_reference_resolution(self, client):
        """Grader in graders/ dir should be resolved via task.yaml grader field."""
        import cli_agent_orchestrator.api.evolution_routes as evo_mod
        from cli_agent_orchestrator.evolution.checkpoint import shared_dir
        sd = shared_dir(evo_mod.EVOLUTION_DIR)
        # Create a grader file in graders/
        grader_dir = sd / "graders" / "security"
        grader_dir.mkdir(parents=True, exist_ok=True)
        (grader_dir / "test-grader.py").write_text("class Grader: pass\n")
        # Create task referencing it
        tid = "grader-ref-test"
        client.post("/evolution/tasks", json={
            "task_id": tid,
            "grader": "security/test-grader.py",
        })
        r = client.get(f"/evolution/{tid}/grader")
        assert r.status_code == 200
        assert "class Grader" in r.json()["grader_code"]
