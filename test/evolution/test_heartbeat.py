"""Tests for heartbeat: HeartbeatRunner, config persistence, API integration."""

import tempfile
from pathlib import Path

import pytest

from cli_agent_orchestrator.evolution.heartbeat import (
    HeartbeatAction,
    HeartbeatRunner,
    build_runner,
    check_triggers,
    get_default_actions,
    read_heartbeat_config,
    render_prompt,
    write_heartbeat_config,
)


# ── HeartbeatRunner unit tests ────────────────────────────────────────

class TestHeartbeatRunner:
    def test_interval_triggers(self):
        runner = HeartbeatRunner([
            HeartbeatAction(name="reflect", every=1, prompt="reflect now"),
            HeartbeatAction(name="consolidate", every=3, prompt="consolidate"),
        ])
        # eval 1: reflect triggers (1%1==0), consolidate not (1%3!=0)
        t = runner.check(local_eval_count=1, global_eval_count=1)
        assert [a.name for a in t] == ["reflect"]

        # eval 3: both trigger
        t = runner.check(local_eval_count=3, global_eval_count=3)
        assert sorted(a.name for a in t) == ["consolidate", "reflect"]

    def test_interval_zero_never_triggers(self):
        runner = HeartbeatRunner([
            HeartbeatAction(name="reflect", every=1, prompt="x"),
        ])
        t = runner.check(local_eval_count=0, global_eval_count=0)
        assert t == []

    def test_global_uses_global_count(self):
        runner = HeartbeatRunner([
            HeartbeatAction(name="consolidate", every=5, prompt="x", is_global=True),
        ])
        # local=2, global=5 → triggers (uses global)
        t = runner.check(local_eval_count=2, global_eval_count=5)
        assert [a.name for a in t] == ["consolidate"]

        # local=5, global=3 → no trigger
        t = runner.check(local_eval_count=5, global_eval_count=3)
        assert t == []

    def test_plateau_triggers_at_threshold(self):
        runner = HeartbeatRunner([
            HeartbeatAction(name="pivot", every=3, prompt="pivot", trigger="plateau"),
        ])
        # Not stuck enough
        assert runner.check(local_eval_count=5, evals_since_improvement=2) == []
        # Just enough
        t = runner.check(local_eval_count=6, evals_since_improvement=3)
        assert [a.name for a in t] == ["pivot"]

    def test_plateau_cooldown(self):
        runner = HeartbeatRunner([
            HeartbeatAction(name="pivot", every=3, prompt="p", trigger="plateau"),
        ])
        # First fire at evals_since=3
        t = runner.check(local_eval_count=5, evals_since_improvement=3)
        assert len(t) == 1

        # Cooldown: should NOT fire at evals_since=4 (only 1 since last fire)
        t = runner.check(local_eval_count=6, evals_since_improvement=4)
        assert len(t) == 0

        # Should fire again at evals_since=6 (3 since last fire)
        t = runner.check(local_eval_count=8, evals_since_improvement=6)
        assert len(t) == 1

    def test_plateau_resets_on_improvement(self):
        runner = HeartbeatRunner([
            HeartbeatAction(name="pivot", every=3, prompt="p", trigger="plateau"),
        ])
        # Fire
        runner.check(local_eval_count=5, evals_since_improvement=3)
        # Agent improves (evals_since=0)
        runner.check(local_eval_count=6, evals_since_improvement=0)
        # Should fire again at 3
        t = runner.check(local_eval_count=9, evals_since_improvement=3)
        assert len(t) == 1


# ── Config persistence ────────────────────────────────────────────────

class TestHeartbeatConfig:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.evo_dir = tempfile.mkdtemp()

    def test_defaults(self):
        defaults = get_default_actions()
        assert len(defaults) == 5
        names = {a["name"] for a in defaults}
        assert names == {"reflect", "consolidate", "pivot", "evolve_skill", "generate_skill"}

    def test_write_and_read(self):
        actions = [{"name": "reflect", "every": 2, "trigger": "interval"}]
        write_heartbeat_config(self.evo_dir, "agent-1", actions)
        read = read_heartbeat_config(self.evo_dir, "agent-1")
        assert len(read) == 1
        assert read[0]["name"] == "reflect"
        assert read[0]["every"] == 2

    def test_read_missing_returns_empty(self):
        assert read_heartbeat_config(self.evo_dir, "nonexistent") == []

    def test_build_runner_uses_defaults(self):
        runner = build_runner(self.evo_dir, "new-agent")
        assert len(runner.actions) == 4


# ── Prompt rendering ─────────────────────────────────────────────────

class TestRenderPrompt:
    def test_renders_variables(self):
        action = HeartbeatAction(
            name="test", every=1,
            prompt="Agent {agent_id} on {task_id}: {leaderboard}",
        )
        result = render_prompt(action, "a1", "task-x", "1. score=0.9")
        assert result == "Agent a1 on task-x: 1. score=0.9"

    def test_missing_variables_left_as_is(self):
        action = HeartbeatAction(name="test", every=1, prompt="No vars here")
        assert render_prompt(action, "a", "t") == "No vars here"


# ── check_triggers integration ────────────────────────────────────────

class TestCheckTriggers:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.evo_dir = tempfile.mkdtemp()

    def test_triggers_reflect_on_every_eval(self):
        # defaults: reflect every=1
        results = check_triggers(self.evo_dir, "a1", "task-1",
                                 local_eval_count=1)
        names = [r["name"] for r in results]
        assert "reflect" in names

    def test_triggers_pivot_on_plateau(self):
        # defaults: pivot every=5 plateau
        results = check_triggers(self.evo_dir, "a1", "task-1",
                                 local_eval_count=10,
                                 evals_since_improvement=5)
        names = [r["name"] for r in results]
        assert "pivot" in names

    def test_prompt_has_task_id(self):
        results = check_triggers(self.evo_dir, "a1", "my-task",
                                 local_eval_count=1)
        reflect = next(r for r in results if r["name"] == "reflect")
        assert "my-task" in reflect["prompt"]


# ── API integration ───────────────────────────────────────────────────

class TestHeartbeatAPI:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self._test_dir = tempfile.mkdtemp()
        import cli_agent_orchestrator.api.evolution_routes as evo_mod
        self._orig = evo_mod.EVOLUTION_DIR
        evo_mod.EVOLUTION_DIR = self._test_dir
        evo_mod.ensure_evolution_repo()
        yield
        evo_mod.EVOLUTION_DIR = self._orig

    @pytest.fixture
    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from cli_agent_orchestrator.api.evolution_routes import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_score_response_includes_heartbeat(self, client):
        """submit_score should return heartbeat_triggered field."""
        r = client.post("/evolution/hb-task/scores", json={
            "agent_id": "a1", "score": 0.5, "title": "test",
        })
        data = r.json()
        assert "heartbeat_triggered" in data
        # Default: reflect triggers on eval 1
        assert "reflect" in data["heartbeat_triggered"]

    def test_heartbeat_config_endpoints(self, client):
        # Get defaults
        r = client.get("/evolution/heartbeat/test-agent")
        data = r.json()
        assert len(data["actions"]) == 4

        # Set custom
        custom = [{"name": "reflect", "every": 3, "trigger": "interval"}]
        r = client.put("/evolution/heartbeat/test-agent",
                       json={"actions": custom})
        assert r.json()["status"] == "ok"

        # Read back
        r = client.get("/evolution/heartbeat/test-agent")
        assert r.json()["actions"][0]["every"] == 3

    def test_pivot_triggers_on_plateau(self, client):
        """After enough non-improving evals, pivot should trigger."""
        # Submit 6 identical scores (no improvement after first)
        for i in range(6):
            r = client.post("/evolution/plateau-task/scores", json={
                "agent_id": "a1", "score": 0.5, "title": f"eval {i}",
            })
        data = r.json()
        # Default pivot every=5 plateau → should trigger after 5 non-improvements
        assert "pivot" in data["heartbeat_triggered"]
