"""Tests for skill evolution heartbeat integration.

Tests that heartbeat prompts load, render, and trigger correctly.
The actual evolution logic (judge, evals, evolve_with_retry, tip, modes)
has been migrated to platform-agnostic SKILL.md files in evo-skills/.
"""

import json
import tempfile
import pytest

from cli_agent_orchestrator.evolution.heartbeat import (
    HeartbeatAction,
    HeartbeatRunner,
    DEFAULT_PROMPTS,
    get_default_actions,
    render_prompt,
    check_triggers,
    build_runner,
)


# ── API client fixture for E2E tests ─────────────────────────────────

_test_evo_dir = tempfile.mkdtemp()


@pytest.fixture(autouse=True, scope="module")
def _setup_evo_dir():
    import cli_agent_orchestrator.api.evolution_routes as evo_mod
    original = evo_mod.EVOLUTION_DIR
    evo_mod.EVOLUTION_DIR = _test_evo_dir
    evo_mod.ensure_evolution_repo()
    yield
    evo_mod.EVOLUTION_DIR = original


@pytest.fixture(scope="module")
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from cli_agent_orchestrator.api.evolution_routes import router
    test_app = FastAPI()
    test_app.include_router(router)
    return TestClient(test_app)


# ── Heartbeat prompt loading & rendering ─────────────────────────────


class TestEvolveSkillPrompt:
    def test_prompt_loaded(self):
        assert "evolve_skill" in DEFAULT_PROMPTS
        prompt = DEFAULT_PROMPTS["evolve_skill"]
        assert len(prompt) > 100
        assert "{evolution_signals_json}" in prompt
        assert "Skill Evolution" in prompt

    def test_prompt_renders(self):
        action = HeartbeatAction(
            name="evolve_skill",
            every=3,
            prompt=DEFAULT_PROMPTS["evolve_skill"],
            trigger="plateau",
        )
        signals = {"judge": {"score": 5}}
        result = render_prompt(action, "agent-1", "task-1", evolution_signals=signals)
        assert '"judge"' in result
        assert '"score": 5' in result

    def test_all_prompts_reference_skills(self):
        """After refactoring, all heartbeat prompts should reference evo-skills."""
        for name in ("reflect", "consolidate", "pivot", "evolve_skill"):
            prompt = DEFAULT_PROMPTS.get(name, "")
            assert "skill" in prompt.lower() or "SKILL" in prompt, (
                f"Prompt '{name}' should reference an evo-skill after refactoring"
            )


# ── evolve_skill in default actions ──────────────────────────────────


class TestEvolveSkillTrigger:
    def test_evolve_skill_in_defaults(self):
        defaults = get_default_actions()
        names = [a["name"] for a in defaults]
        assert "evolve_skill" in names
        es = next(a for a in defaults if a["name"] == "evolve_skill")
        assert es["trigger"] == "plateau"
        assert es["every"] == 3

    def test_evolve_skill_triggers_on_plateau(self, tmp_path):
        evo_dir = str(tmp_path / ".evo")
        runner = build_runner(evo_dir, "test-agent")
        action_names = [a.name for a in runner.actions]
        assert "evolve_skill" in action_names

        triggered = runner.check(
            local_eval_count=5,
            evals_since_improvement=3,
        )
        triggered_names = [a.name for a in triggered]
        assert "evolve_skill" in triggered_names

    def test_evolve_skill_not_triggered_early(self, tmp_path):
        evo_dir = str(tmp_path / ".evo")
        runner = build_runner(evo_dir, "test-agent")
        triggered = runner.check(
            local_eval_count=5,
            evals_since_improvement=2,
        )
        triggered_names = [a.name for a in triggered]
        assert "evolve_skill" not in triggered_names

    def test_evolve_skill_prompt_in_check_triggers(self, tmp_path):
        evo_dir = str(tmp_path / ".evo")
        signals = {"eval": {"passed": 2, "failed": 3}}
        results = check_triggers(
            evo_dir=evo_dir,
            agent_id="a1",
            task_id="t1",
            local_eval_count=10,
            evals_since_improvement=4,
            evolution_signals=signals,
        )
        names = [r["name"] for r in results]
        assert "evolve_skill" in names
        es_prompt = next(r["prompt"] for r in results if r["name"] == "evolve_skill")
        assert '"eval"' in es_prompt
        assert "Skill Evolution" in es_prompt


# ── E2E: API signals flow ────────────────────────────────────────────


class TestApiSignalsFlow:
    def test_api_signals_flow(self, client):
        """E2E: submit score with signals -> heartbeat returns signals in prompts."""
        tid = "e2e-evo-test"
        client.post("/evolution/tasks", json={"task_id": tid})
        signals = {
            "judge": {"source": "llm-as-judge", "accuracy": 0.8, "avg_score": 7},
            "grader_skill": {"skill": "security-grader", "score": 0.75},
        }
        for i in range(4):
            r = client.post(f"/evolution/{tid}/scores", json={
                "agent_id": "agent-e2e",
                "score": 0.5,
                "evolution_signals": signals,
            })
        data = r.json()
        assert data["evolution_signals"] == signals
        prompts = data.get("heartbeat_prompts", [])
        es_prompts = [p for p in prompts if p["name"] == "evolve_skill"]
        if es_prompts:
            assert "secskill-evo" in es_prompts[0]["prompt"]
