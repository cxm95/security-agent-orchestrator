"""End-to-end evolution cycle test.

Simulates the full distributed evolution flow in a single process:
1. Hub starts (FastAPI TestClient)
2. Task created with grader code
3. Remote agent registers via bridge
4. Agent receives task via poll
5. Agent runs grader locally
6. Agent reports score
7. Agent shares note + skill
8. Second agent joins, reports worse score
9. Leaderboard shows correct ranking
10. Knowledge search returns shared items
"""

import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure cao-bridge is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cao-bridge"))

from cli_agent_orchestrator.api.evolution_routes import router as evo_router
from cli_agent_orchestrator.api.evolution_routes import ensure_evolution_repo
import cli_agent_orchestrator.api.evolution_routes as evo_mod
from cli_agent_orchestrator.evolution.grader_base import load_grader_from_source


GRADER_CODE = '''
class Grader(GraderBase):
    """Security audit grader: checks vuln count and coverage."""
    def evaluate(self, result):
        vuln_score = max(0, 1.0 - result.get("vuln_count", 0) * 0.1)
        coverage = result.get("coverage", 0.0)
        return {"vulnerability_reduction": vuln_score, "scan_coverage": coverage}
'''


@pytest.fixture(scope="module")
def hub():
    """Set up Hub with evolution API."""
    test_dir = tempfile.mkdtemp()
    original = evo_mod.EVOLUTION_DIR
    evo_mod.EVOLUTION_DIR = test_dir
    ensure_evolution_repo()

    # Include remote API for register/poll/report
    from cli_agent_orchestrator.api.main import app as real_app
    # Instead of importing the full app (which has complex lifespan),
    # build a minimal app with just what we need
    app = FastAPI()
    app.include_router(evo_router)

    # Add remote endpoints manually
    from cli_agent_orchestrator.providers.remote import RemoteProvider
    _remotes: dict[str, RemoteProvider] = {}

    @app.post("/remotes/register")
    def register(body: dict):
        import uuid
        tid = f"remote-{uuid.uuid4().hex[:8]}"
        _remotes[tid] = RemoteProvider(terminal_id=tid, agent_profile=body.get("agent_profile", "default"))
        return {"terminal_id": tid, "status": "registered"}

    @app.get("/remotes/{tid}/poll")
    def poll(tid: str):
        if tid not in _remotes:
            return {"error": "not found"}
        rp = _remotes[tid]
        msg = rp.consume_pending_input()
        return {"has_input": msg is not None, "input": msg}

    @app.post("/remotes/{tid}/report")
    def report(tid: str, body: dict):
        if tid not in _remotes:
            return {"error": "not found"}
        rp = _remotes[tid]
        if "status" in body:
            rp.report_status(body["status"])
        if "output" in body:
            rp.report_output(body["output"])
        return {"ok": True}

    # Helper to send input to a remote agent
    def send_task(tid: str, task: str):
        _remotes[tid].set_pending_input(task)

    client = TestClient(app)
    yield client, send_task

    evo_mod.EVOLUTION_DIR = original


@pytest.fixture
def patch_requests(hub):
    """Patch requests module to use TestClient."""
    client, _ = hub
    import requests as _req
    orig_get, orig_post = _req.get, _req.post
    _req.get = lambda url, **kw: client.get(url, params=kw.get("params"))
    _req.post = lambda url, **kw: client.post(url, json=kw.get("json"))
    yield
    _req.get, _req.post = orig_get, orig_post


def _make_bridge():
    """Create a CaoBridge that talks to a patched requests."""
    from cao_bridge import CaoBridge
    return CaoBridge(hub_url="", agent_profile="test-agent")


class TestFullEvolutionCycle:
    """End-to-end: two agents compete on a security audit task."""

    def test_complete_evolution_flow(self, hub, patch_requests):
        client, send_task = hub

        # ── Phase 1: Hub creates task with grader ─────────────────
        r = client.post("/evolution/tasks", json={
            "task_id": "sec-audit-e2e",
            "name": "Security Audit E2E",
            "description": "Find vulns and maximize coverage",
            "grader_code": GRADER_CODE,
        })
        assert r.status_code == 201

        # ── Phase 2: Agent A registers + gets task ────────────────
        agent_a = _make_bridge()
        tid_a = agent_a.register()
        assert tid_a.startswith("remote-")

        # Hub sends task to Agent A
        send_task(tid_a, "Run security audit on target repo")
        msg = agent_a.poll()
        assert msg is not None
        assert "security audit" in msg.lower()

        # ── Phase 3: Agent A runs grader locally ──────────────────
        grader_code = agent_a.get_grader("sec-audit-e2e")
        assert grader_code is not None

        grader = load_grader_from_source(grader_code)
        score_a, feedback_a = grader.grade({
            "vuln_count": 2,   # 1.0 - 0.2 = 0.8
            "coverage": 0.9,   # 0.9
        })
        # Mean of 0.8 and 0.9 = 0.85
        assert score_a == pytest.approx(0.85)

        # ── Phase 4: Agent A reports score ────────────────────────
        result = agent_a.report_score("sec-audit-e2e", score_a,
                                      title="initial scan", feedback=feedback_a)
        assert result["status"] == "improved"
        assert result["best_score"] == pytest.approx(0.85)
        assert result["evals_since_improvement"] == 0

        # Report task completion
        agent_a.report(status="completed", output="Found 2 vulns, 90% coverage")

        # ── Phase 5: Agent A shares knowledge ─────────────────────
        note_result = agent_a.share_note(
            "SQL injection pattern",
            "Found parameterized query bypass via UNION SELECT in login handler",
            tags=["sql-injection", "java"],
            origin_task="sec-audit-e2e",
            origin_score=score_a,
        )
        assert "filename" in note_result

        skill_result = agent_a.share_skill(
            "java-sqli-scan",
            "# Java SQL Injection Scanner\n\nGrep for string concat in PreparedStatement...",
            tags=["java", "sql-injection"],
        )
        assert skill_result["name"] == "java-sqli-scan"

        # ── Phase 6: Agent B joins ────────────────────────────────
        agent_b = _make_bridge()
        tid_b = agent_b.register()

        # Agent B searches knowledge before starting
        results = agent_b.search_knowledge("SQL injection")
        assert len(results) >= 1
        assert any("sql-injection" in str(r.get("tags", "")) or
                    "SQL" in r.get("snippet", "") or
                    "SQL" in r.get("title", "")
                    for r in results)

        # Agent B runs grader — worse result
        grader_b = load_grader_from_source(grader_code)
        score_b, feedback_b = grader_b.grade({
            "vuln_count": 5,   # 1.0 - 0.5 = 0.5
            "coverage": 0.6,   # 0.6
        })
        # Mean of 0.5 and 0.6 = 0.55
        assert score_b == pytest.approx(0.55)

        result_b = agent_b.report_score("sec-audit-e2e", score_b,
                                        title="agent-b scan", feedback=feedback_b)
        assert result_b["status"] == "improved"  # First for this agent
        assert result_b["best_score"] == pytest.approx(0.55)

        # ── Phase 7: Leaderboard ──────────────────────────────────
        lb = agent_a.get_leaderboard("sec-audit-e2e")
        entries = lb["entries"]
        assert len(entries) >= 2
        # Agent A should be ranked higher
        assert entries[0]["score"] >= entries[1]["score"]

        # ── Phase 8: Agent A improves ─────────────────────────────
        score_a2, feedback_a2 = grader.grade({
            "vuln_count": 0,   # 1.0
            "coverage": 0.95,  # 0.95
        })
        # Mean = 0.975
        assert score_a2 == pytest.approx(0.975)

        result_a2 = agent_a.report_score("sec-audit-e2e", score_a2,
                                         title="improved scan")
        assert result_a2["status"] == "improved"
        assert result_a2["best_score"] == pytest.approx(0.975)

        # Final leaderboard
        lb_final = client.get("/evolution/sec-audit-e2e/leaderboard").json()
        assert lb_final["entries"][0]["score"] == pytest.approx(0.975)

    def test_crashed_grader_flow(self, hub, patch_requests):
        """Test the flow when a grader crashes."""
        client, send_task = hub

        client.post("/evolution/tasks", json={
            "task_id": "crash-test",
            "grader_code": (
                "class Grader(GraderBase):\n"
                "    def evaluate(self, result):\n"
                "        raise RuntimeError('grader exploded')\n"
            ),
        })

        agent = _make_bridge()
        agent.terminal_id = agent.register()

        grader_code = agent.get_grader("crash-test")
        grader = load_grader_from_source(grader_code)
        score, feedback = grader.grade({})
        assert score is None
        assert "grader error" in feedback

        # Report crash
        result = agent.report_score("crash-test", None, title="crashed", feedback=feedback)
        assert result["status"] == "crashed"

    def test_multi_task_isolation(self, hub, patch_requests):
        """Scores for different tasks don't interfere."""
        client, _ = hub

        agent = _make_bridge()
        agent.terminal_id = agent.register()

        # Report scores for two different tasks
        r1 = agent.report_score("task-alpha", 0.9, title="alpha")
        r2 = agent.report_score("task-beta", 0.3, title="beta")

        lb_alpha = agent.get_leaderboard("task-alpha")
        lb_beta = agent.get_leaderboard("task-beta")

        assert lb_alpha["entries"][0]["score"] == pytest.approx(0.9)
        assert lb_beta["entries"][0]["score"] == pytest.approx(0.3)
