"""Tests for Steps 14b-14f: skill evolution pipeline."""

import json
import os
import tempfile
import pytest
from pathlib import Path

from cli_agent_orchestrator.evolution.evals import (
    read_evals,
    write_evals,
    add_eval_case,
    seed_from_failure,
    remove_eval_case,
    evals_path,
)
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


# ── Evals CRUD ────────────────────────────────────────────────────────

class TestEvals:
    def test_read_empty(self, tmp_path):
        assert read_evals(tmp_path, "nonexistent") == []

    def test_write_and_read(self, tmp_path):
        cases = [
            {"id": "c1", "input": "hello", "expected": "world", "source": "manual"},
        ]
        write_evals(tmp_path, "my-skill", cases)
        loaded = read_evals(tmp_path, "my-skill")
        assert len(loaded) == 1
        assert loaded[0]["id"] == "c1"
        assert loaded[0]["input"] == "hello"

    def test_add_case_dedup(self, tmp_path):
        add_eval_case(tmp_path, "sk", "c1", "in1", "out1")
        result = add_eval_case(tmp_path, "sk", "c1", "in2", "out2")
        assert len(result) == 1  # dedup by id
        assert result[0]["input"] == "in1"

    def test_seed_from_failure(self, tmp_path):
        case_id = seed_from_failure(tmp_path, "sk", "bad input", "expected output")
        assert case_id.startswith("auto-")
        assert len(case_id) == 13  # "auto-" + 8 hex chars
        cases = read_evals(tmp_path, "sk")
        assert len(cases) == 1
        assert cases[0]["source"] == "auto"

    def test_seed_from_failure_dedup(self, tmp_path):
        """Same input/expected → same ID → no duplicate."""
        id1 = seed_from_failure(tmp_path, "sk", "x", "y")
        id2 = seed_from_failure(tmp_path, "sk", "x", "y")
        assert id1 == id2
        assert len(read_evals(tmp_path, "sk")) == 1

    def test_remove_case(self, tmp_path):
        add_eval_case(tmp_path, "sk", "c1", "a", "b")
        add_eval_case(tmp_path, "sk", "c2", "c", "d")
        result = remove_eval_case(tmp_path, "sk", "c1")
        assert len(result) == 1
        assert result[0]["id"] == "c2"

    def test_evals_path(self, tmp_path):
        p = evals_path(tmp_path, "my-skill")
        assert p == tmp_path / "my-skill" / "evals.json"

    def test_corrupt_evals_returns_empty(self, tmp_path):
        p = tmp_path / "bad-skill" / "evals.json"
        p.parent.mkdir(parents=True)
        p.write_text("not json")
        assert read_evals(tmp_path, "bad-skill") == []


# ── evolve_skill prompt ──────────────────────────────────────────────

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
        assert "agent-1" not in result or "{agent_id}" not in result
        assert '"judge"' in result
        assert '"score": 5' in result


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
        # No custom config → uses defaults including evolve_skill
        runner = build_runner(evo_dir, "test-agent")
        action_names = [a.name for a in runner.actions]
        assert "evolve_skill" in action_names

        # Plateau of 3 evals → should trigger evolve_skill
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
            evals_since_improvement=2,  # only 2, need 3
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
            evals_since_improvement=4,  # > 3 → triggers evolve_skill
            evolution_signals=signals,
        )
        names = [r["name"] for r in results]
        assert "evolve_skill" in names
        es_prompt = next(r["prompt"] for r in results if r["name"] == "evolve_skill")
        assert '"eval"' in es_prompt
        assert "Skill Evolution" in es_prompt


# ── LLM-as-Judge (Step 14c) ─────────────────────────────────────────

from cli_agent_orchestrator.evolution.judge import (
    evaluate_with_judge,
    evaluate_batch,
    judge_summary,
)


def _mock_judge(prompt: str) -> str:
    """Mock judge that always returns a valid JSON response."""
    return json.dumps({
        "is_correct": True,
        "confidence": 0.85,
        "score": 7,
        "strengths": ["concise", "accurate"],
        "weaknesses": ["missing edge case"],
    })


def _mock_judge_incorrect(prompt: str) -> str:
    return json.dumps({
        "is_correct": False,
        "confidence": 0.9,
        "score": 3,
        "strengths": [],
        "weaknesses": ["wrong answer"],
    })


class TestJudge:
    def test_basic_evaluation(self):
        result = evaluate_with_judge("1+1", "2", "2", judge_fn=_mock_judge)
        assert result["is_correct"] is True
        assert result["confidence"] == 0.85
        assert result["score"] == 7
        assert "concise" in result["strengths"]
        assert "missing edge case" in result["weaknesses"]

    def test_incorrect_evaluation(self):
        result = evaluate_with_judge("1+1", "3", "2", judge_fn=_mock_judge_incorrect)
        assert result["is_correct"] is False
        assert result["score"] == 3

    def test_judge_failure_returns_degraded(self):
        def bad_judge(prompt):
            raise RuntimeError("API error")
        result = evaluate_with_judge("x", "y", "z", judge_fn=bad_judge)
        assert result["is_correct"] is False
        assert result["score"] == 0
        assert any("Judge failed" in w for w in result["weaknesses"])

    def test_judge_bad_json_returns_degraded(self):
        def bad_json_judge(prompt):
            return "not json at all"
        result = evaluate_with_judge("x", "y", "z", judge_fn=bad_json_judge)
        assert result["is_correct"] is False
        assert result["score"] == 0

    def test_judge_with_markdown_fences(self):
        def fenced_judge(prompt):
            return '```json\n{"is_correct": true, "confidence": 0.7, "score": 6, "strengths": [], "weaknesses": []}\n```'
        result = evaluate_with_judge("a", "b", "b", judge_fn=fenced_judge)
        assert result["is_correct"] is True
        assert result["score"] == 6


class TestBatchJudge:
    def test_evaluate_batch(self):
        cases = [
            {"id": "c1", "input": "1+1", "actual": "2", "expected": "2"},
            {"id": "c2", "input": "2+2", "actual": "5", "expected": "4"},
        ]
        results = evaluate_batch(cases, judge_fn=_mock_judge)
        assert len(results) == 2
        assert results[0]["case_id"] == "c1"
        assert results[1]["case_id"] == "c2"

    def test_judge_summary(self):
        results = [
            {"is_correct": True, "score": 8, "confidence": 0.9},
            {"is_correct": False, "score": 3, "confidence": 0.7},
            {"is_correct": True, "score": 9, "confidence": 0.95},
        ]
        summary = judge_summary(results)
        assert summary["source"] == "llm-as-judge"
        assert summary["total"] == 3
        assert summary["correct"] == 2
        assert abs(summary["accuracy"] - 2/3) < 0.01
        assert abs(summary["avg_score"] - 20/3) < 0.1

    def test_judge_summary_empty(self):
        summary = judge_summary([])
        assert summary["total"] == 0


# ── Structured retry (Step 14d) ─────────────────────────────────────

from cli_agent_orchestrator.evolution.evolve import evolve_with_retry, EvolutionResult


class TestEvolveWithRetry:
    def test_success_on_first_attempt(self):
        """evolve_fn produces improvement on first try."""
        def evolve_fn(content, attempt, feedback, signals):
            return content + "\n# improved"

        def validate_fn(content):
            if "improved" in content:
                return {"passed": 5, "failed": 0, "details": "all pass"}
            return {"passed": 3, "failed": 2, "details": "some fail"}

        result = evolve_with_retry("original", evolve_fn, validate_fn)
        assert result.success is True
        assert result.attempts == 1
        assert "improved" in result.final_content

    def test_revert_on_regression(self):
        """Regression detected → revert and retry."""
        call_count = [0]

        def evolve_fn(content, attempt, feedback, signals):
            call_count[0] += 1
            if call_count[0] == 1:
                return "worse version"  # will regress
            return content + "\n# fixed"

        def validate_fn(content):
            if "worse" in content:
                return {"passed": 1, "failed": 4, "details": "regression"}
            if "fixed" in content:
                return {"passed": 5, "failed": 0, "details": "all pass"}
            return {"passed": 3, "failed": 2, "details": "baseline"}

        result = evolve_with_retry("original", evolve_fn, validate_fn)
        assert result.success is True
        assert result.attempts == 2
        assert "fixed" in result.final_content

    def test_all_retries_exhausted(self):
        """All retries fail → keep original."""
        def evolve_fn(content, attempt, feedback, signals):
            return "still bad"

        def validate_fn(content):
            if content == "still bad":
                return {"passed": 1, "failed": 4}
            return {"passed": 3, "failed": 2}

        result = evolve_with_retry("original", evolve_fn, validate_fn)
        assert result.success is False
        assert result.final_content == "original"
        assert result.attempts == 2

    def test_evolve_fn_exception_handled(self):
        """evolve_fn raises → caught, retry continues."""
        call_count = [0]

        def evolve_fn(content, attempt, feedback, signals):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("API timeout")
            return content + "\n# recovered"

        def validate_fn(content):
            if "recovered" in content:
                return {"passed": 5, "failed": 0}
            return {"passed": 3, "failed": 2}

        result = evolve_with_retry("original", evolve_fn, validate_fn)
        assert result.success is True
        assert result.attempts == 2
        assert any(h.get("type") == "evolve_failed" for h in result.history)

    def test_no_improvement_no_regression(self):
        """Same score → not success, feedback given for next attempt."""
        def evolve_fn(content, attempt, feedback, signals):
            return content + f"\n# tweak{attempt}"

        def validate_fn(content):
            return {"passed": 3, "failed": 2, "details": "unchanged"}

        result = evolve_with_retry("original", evolve_fn, validate_fn)
        assert result.success is False
        assert result.final_content == "original"

    def test_result_to_dict(self):
        result = EvolutionResult(
            success=True, original_content="a", final_content="b",
            attempts=1, history=[{"attempt": 1, "type": "evolved"}],
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["attempts"] == 1
        assert len(d["history"]) == 1


# ── TIP.md (Step 14e) ───────────────────────────────────────────────

from cli_agent_orchestrator.evolution.tip import read_tip, write_tip, append_tip, tip_path


class TestTip:
    def test_read_empty(self, tmp_path):
        assert read_tip(tmp_path, "nonexistent") == ""

    def test_write_and_read(self, tmp_path):
        write_tip(tmp_path, "my-skill", "# Tips\nDon't forget X.")
        content = read_tip(tmp_path, "my-skill")
        assert "Don't forget X" in content

    def test_append(self, tmp_path):
        append_tip(tmp_path, "sk", "First learning")
        append_tip(tmp_path, "sk", "Second learning")
        content = read_tip(tmp_path, "sk")
        assert "First learning" in content
        assert "Second learning" in content
        assert content.count("##") == 2  # Two timestamped entries

    def test_tip_path(self, tmp_path):
        p = tip_path(tmp_path, "my-skill")
        assert p == tmp_path / "my-skill" / "TIP.md"


# ── Evolution modes (Step 14e) ──────────────────────────────────────

from cli_agent_orchestrator.evolution.modes import (
    get_mode,
    get_mode_config,
    is_feature_enabled,
    DEFAULT_MODE,
    ModeConfig,
)


class TestModes:
    def test_default_is_local(self, monkeypatch):
        monkeypatch.delenv("CAO_EVOLUTION_MODE", raising=False)
        assert get_mode() == "local"

    def test_local_mode_config(self):
        cfg = get_mode_config("local")
        assert cfg.mode == "local"
        assert cfg.judge_enabled is True
        assert cfg.local_evolution is True
        assert cfg.bridge_enabled is False
        assert cfg.heartbeat_enabled is False

    def test_distributed_mode_config(self):
        cfg = get_mode_config("distributed")
        assert cfg.mode == "distributed"
        assert cfg.bridge_enabled is True
        assert cfg.heartbeat_enabled is True
        assert cfg.grader_enabled is True
        assert cfg.judge_enabled is False
        assert cfg.local_evolution is False

    def test_hybrid_mode_config(self):
        cfg = get_mode_config("hybrid")
        assert cfg.mode == "hybrid"
        assert cfg.bridge_enabled is True
        assert cfg.judge_enabled is True
        assert cfg.local_evolution is True
        assert cfg.git_sync_enabled is True

    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("CAO_EVOLUTION_MODE", "distributed")
        assert get_mode() == "distributed"

    def test_invalid_mode_fallback(self, monkeypatch):
        monkeypatch.setenv("CAO_EVOLUTION_MODE", "invalid")
        assert get_mode() == DEFAULT_MODE

    def test_is_feature_enabled(self):
        assert is_feature_enabled("judge_enabled", "local") is True
        assert is_feature_enabled("bridge_enabled", "local") is False
        assert is_feature_enabled("bridge_enabled", "distributed") is True


# ── E2E Integration: Full Local Skill Evolution Flow (Step 14f) ─────

class TestLocalEvolutionE2E:
    """End-to-end test: local mode skill evolution cycle.

    Simulates: create skill → add evals → judge → evolve_with_retry → TIP.md → signals.
    """

    def test_full_local_evolution_cycle(self, tmp_path):
        """Complete local evolution flow without Hub."""
        skill_dir = tmp_path / "skills"

        # 1. Create a skill
        skill_name = "detect-sqli"
        skill_path = skill_dir / skill_name
        skill_path.mkdir(parents=True)
        (skill_path / "SKILL.md").write_text("# SQL Injection Detection\nCheck for basic patterns.")

        # 2. Seed evals from failures
        from cli_agent_orchestrator.evolution.evals import seed_from_failure, read_evals
        seed_from_failure(str(skill_dir), skill_name, "SELECT * FROM users WHERE id='1' OR '1'='1'", "sqli_detected")
        seed_from_failure(str(skill_dir), skill_name, "SELECT name FROM products", "clean")
        cases = read_evals(str(skill_dir), skill_name)
        assert len(cases) == 2

        # 3. Judge evaluation (mock)
        from cli_agent_orchestrator.evolution.judge import evaluate_batch, judge_summary
        eval_cases = [
            {"id": c["id"], "input": c["input"], "actual": "sqli_detected", "expected": c["expected"]}
            for c in cases
        ]
        judge_results = evaluate_batch(eval_cases, judge_fn=_mock_judge)
        summary = judge_summary(judge_results)
        assert summary["total"] == 2
        assert summary["source"] == "llm-as-judge"

        # 4. Build evolution signals
        signals = {"judge": summary}

        # 5. Evolve with retry
        original_content = (skill_path / "SKILL.md").read_text()

        def evolve_fn(content, attempt, feedback, signals):
            return content + "\n## Enhanced\nAdded UNION-based detection."

        def validate_fn(content):
            if "Enhanced" in content:
                return {"passed": 2, "failed": 0}
            return {"passed": 1, "failed": 1}

        result = evolve_with_retry(original_content, evolve_fn, validate_fn)
        assert result.success is True

        # Write evolved skill back
        (skill_path / "SKILL.md").write_text(result.final_content)
        assert "Enhanced" in (skill_path / "SKILL.md").read_text()

        # 6. Record in TIP.md
        from cli_agent_orchestrator.evolution.tip import append_tip, read_tip
        append_tip(str(skill_dir), skill_name, "Added UNION-based detection. Improved from 1/2 to 2/2 passing.")
        tip = read_tip(str(skill_dir), skill_name)
        assert "UNION-based" in tip

        # 7. Verify evolution signals are injectable into heartbeat
        from cli_agent_orchestrator.evolution.heartbeat import render_prompt, HeartbeatAction, DEFAULT_PROMPTS
        action = HeartbeatAction(
            name="evolve_skill", every=3,
            prompt=DEFAULT_PROMPTS["evolve_skill"], trigger="plateau",
        )
        rendered = render_prompt(action, "agent-1", "task-1", evolution_signals=signals)
        assert "llm-as-judge" in rendered
        assert "Skill Evolution" in rendered

        # 8. Mode check — local mode should have judge + local_evolution enabled
        from cli_agent_orchestrator.evolution.modes import get_mode_config
        cfg = get_mode_config("local")
        assert cfg.judge_enabled is True
        assert cfg.local_evolution is True
        assert cfg.bridge_enabled is False

    def test_api_signals_flow(self, client):
        """E2E: submit score with signals → heartbeat returns signals in prompts."""
        tid = "e2e-evo-test"
        client.post("/evolution/tasks", json={"task_id": tid})
        signals = {
            "judge": {"source": "llm-as-judge", "accuracy": 0.8, "avg_score": 7},
            "grader": {"source": "grader.py", "score": 0.75},
        }
        # Submit multiple scores to trigger plateau
        for i in range(4):
            r = client.post(f"/evolution/{tid}/scores", json={
                "agent_id": "agent-e2e",
                "score": 0.5,  # same score → plateau
                "evolution_signals": signals,
            })
        data = r.json()
        assert data["evolution_signals"] == signals
        # After 3+ stalls, evolve_skill should trigger
        prompts = data.get("heartbeat_prompts", [])
        es_prompts = [p for p in prompts if p["name"] == "evolve_skill"]
        if es_prompts:
            assert "llm-as-judge" in es_prompts[0]["prompt"]


# ── evolve_with_retry signals forwarding ─────────────────────────────

class TestEvolveSignalsForwarding:
    def test_signals_reach_evolve_fn(self):
        """evolve_with_retry passes signals to evolve_fn."""
        received = {}

        def evolve_fn(content, attempt, feedback, signals):
            received.update(signals)
            return content + "\n# improved"

        def validate_fn(content):
            if "improved" in content:
                return {"passed": 5, "failed": 0}
            return {"passed": 3, "failed": 2}

        signals = {"judge": {"score": 8}, "grader": {"score": 0.9}}
        result = evolve_with_retry("orig", evolve_fn, validate_fn, evolution_signals=signals)
        assert result.success
        assert received["judge"]["score"] == 8
        assert received["grader"]["score"] == 0.9
