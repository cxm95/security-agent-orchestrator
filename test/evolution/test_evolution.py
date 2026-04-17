"""Tests for evolution core: types, checkpoint, attempts."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from cli_agent_orchestrator.evolution.types import Attempt, Score, ScoreBundle
from cli_agent_orchestrator.evolution.checkpoint import (
    checkpoint,
    checkpoint_history,
    init_checkpoint_repo,
    shared_dir,
)
from cli_agent_orchestrator.evolution.attempts import (
    compare_to_history,
    count_evals_since_improvement,
    format_leaderboard,
    get_best_score,
    get_leaderboard,
    group_summary,
    read_all_group_attempts,
    read_attempts,
    write_attempt,
)


# ── types ────────────────────────────────────────────────────────────────

class TestScore:
    def test_roundtrip(self):
        s = Score(value=0.85, name="accuracy", explanation="good")
        d = s.to_dict()
        s2 = Score.from_dict(d)
        assert s2.value == 0.85
        assert s2.name == "accuracy"
        assert s2.explanation == "good"

    def test_none_value(self):
        s = Score(value=None, name="x")
        assert s.to_dict()["value"] is None


class TestScoreBundle:
    def test_aggregate_equal_weights(self):
        b = ScoreBundle(scores={
            "a": Score(value=0.8, name="a"),
            "b": Score(value=0.6, name="b"),
        })
        assert abs(b.compute_aggregated() - 0.7) < 1e-9

    def test_aggregate_weighted(self):
        b = ScoreBundle(scores={
            "a": Score(value=1.0, name="a"),
            "b": Score(value=0.0, name="b"),
        })
        assert abs(b.compute_aggregated({"a": 3.0, "b": 1.0}) - 0.75) < 1e-9

    def test_roundtrip(self):
        b = ScoreBundle(
            scores={"x": Score(value=0.5, name="x")},
            aggregated=0.5,
            feedback="ok",
        )
        b2 = ScoreBundle.from_dict(b.to_dict())
        assert b2.aggregated == 0.5
        assert b2.feedback == "ok"
        assert b2.scores["x"].value == 0.5


class TestAttempt:
    def test_roundtrip_dict(self):
        a = Attempt(
            run_id="r1", agent_id="a1", task_id="t1",
            title="test", score=0.9, status="improved",
            timestamp="2026-01-01T00:00:00Z",
        )
        a2 = Attempt.from_dict(a.to_dict())
        assert a2.run_id == "r1"
        assert a2.task_id == "t1"
        assert a2.score == 0.9

    def test_roundtrip_json(self):
        a = Attempt(
            run_id="r2", agent_id="a1", task_id="t1",
            title="json test", score=0.5, status="baseline",
            timestamp="2026-01-01T00:00:00Z", feedback="meh",
        )
        a2 = Attempt.from_json(a.to_json())
        assert a2.feedback == "meh"

    def test_shared_state_hash_optional(self):
        a = Attempt(
            run_id="r3", agent_id="a1", task_id="t1",
            title="no hash", score=None, status="crashed",
            timestamp="2026-01-01T00:00:00Z",
        )
        d = a.to_dict()
        assert "shared_state_hash" not in d

        a2 = Attempt(
            run_id="r4", agent_id="a1", task_id="t1",
            title="with hash", score=0.1, status="regressed",
            timestamp="2026-01-01T00:00:00Z",
            shared_state_hash="abc123",
        )
        assert a2.to_dict()["shared_state_hash"] == "abc123"

    def test_agent_profile_and_batch_roundtrip(self):
        a = Attempt(
            run_id="r5", agent_id="a1", task_id="t1",
            title="with profile", score=0.7, status="improved",
            timestamp="2026-01-01T00:00:00Z",
            agent_profile="remote-opencode", batch="batch-1",
        )
        d = a.to_dict()
        assert d["agent_profile"] == "remote-opencode"
        assert d["batch"] == "batch-1"
        a2 = Attempt.from_dict(d)
        assert a2.agent_profile == "remote-opencode"
        assert a2.batch == "batch-1"

    def test_agent_profile_and_batch_optional(self):
        a = Attempt(
            run_id="r6", agent_id="a1", task_id="t1",
            title="no profile", score=0.5, status="baseline",
            timestamp="2026-01-01T00:00:00Z",
        )
        d = a.to_dict()
        assert "agent_profile" not in d
        assert "batch" not in d
        a2 = Attempt.from_dict(d)
        assert a2.agent_profile == ""
        assert a2.batch == ""


# ── checkpoint ───────────────────────────────────────────────────────────

class TestCheckpoint:
    @pytest.fixture(autouse=True)
    def _tmpdir(self, tmp_path):
        self.evo_dir = tmp_path / ".cao-evolution"
        self.evo_dir.mkdir()

    def test_init_creates_structure(self):
        sd = init_checkpoint_repo(str(self.evo_dir))
        assert (sd / ".git").is_dir()
        assert (sd / "tasks").is_dir()
        assert (sd / "notes").is_dir()
        assert (sd / "skills").is_dir()
        assert (sd / "notes" / "_synthesis").is_dir()
        assert (sd / "graders").is_dir()
        assert (sd / "reports").is_dir()
        assert (sd / "attempts").is_dir()

    def test_init_idempotent(self):
        sd1 = init_checkpoint_repo(str(self.evo_dir))
        sd2 = init_checkpoint_repo(str(self.evo_dir))
        assert sd1 == sd2

    def test_checkpoint_returns_none_when_no_changes(self):
        init_checkpoint_repo(str(self.evo_dir))
        sha = checkpoint(str(self.evo_dir), "agent-1", "empty")
        assert sha is None

    def test_checkpoint_returns_sha_on_change(self):
        sd = init_checkpoint_repo(str(self.evo_dir))
        (sd / "tasks" / "test-task").mkdir(parents=True)
        (sd / "tasks" / "test-task" / "task.yaml").write_text("name: test\n")
        sha = checkpoint(str(self.evo_dir), "agent-1", "added task")
        assert sha is not None
        assert len(sha) == 40  # full SHA

    def test_checkpoint_history(self):
        sd = init_checkpoint_repo(str(self.evo_dir))
        (sd / "tasks" / "t1").mkdir(parents=True)
        (sd / "tasks" / "t1" / "f.txt").write_text("v1")
        checkpoint(str(self.evo_dir), "a1", "first")
        (sd / "tasks" / "t1" / "f.txt").write_text("v2")
        checkpoint(str(self.evo_dir), "a1", "second")

        history = checkpoint_history(str(self.evo_dir))
        assert len(history) >= 3  # init + first + second
        assert "second" in history[0]["message"]


# ── attempts ─────────────────────────────────────────────────────────────

class TestAttempts:
    @pytest.fixture(autouse=True)
    def _tmpdir(self, tmp_path):
        self.evo_dir = str(tmp_path / ".cao-evolution")
        Path(self.evo_dir).mkdir()

    def _make_attempt(self, run_id: str, score: float | None, status: str = "improved",
                      agent_id: str = "a1", task_id: str = "t1", ts: str = "2026-01-01T00:00:00Z"):
        return Attempt(
            run_id=run_id, agent_id=agent_id, task_id=task_id,
            title=f"attempt {run_id}", score=score, status=status,
            timestamp=ts,
        )

    def test_write_and_read(self):
        a = self._make_attempt("r1", 0.8)
        write_attempt(self.evo_dir, a)
        attempts = read_attempts(self.evo_dir, "t1")
        assert len(attempts) == 1
        assert attempts[0].score == 0.8

    def test_task_partitioning(self):
        write_attempt(self.evo_dir, self._make_attempt("r1", 0.5, task_id="t1"))
        write_attempt(self.evo_dir, self._make_attempt("r2", 0.9, task_id="t2"))
        assert len(read_attempts(self.evo_dir, "t1")) == 1
        assert len(read_attempts(self.evo_dir, "t2")) == 1

    def test_get_best_score(self):
        write_attempt(self.evo_dir, self._make_attempt("r1", 0.5))
        write_attempt(self.evo_dir, self._make_attempt("r2", 0.9))
        write_attempt(self.evo_dir, self._make_attempt("r3", 0.7))
        assert get_best_score(self.evo_dir, "t1") == 0.9

    def test_get_best_score_by_agent(self):
        write_attempt(self.evo_dir, self._make_attempt("r1", 0.9, agent_id="a1"))
        write_attempt(self.evo_dir, self._make_attempt("r2", 0.3, agent_id="a2"))
        assert get_best_score(self.evo_dir, "t1", agent_id="a2") == 0.3

    def test_compare_to_history(self):
        # First attempt = always improved
        assert compare_to_history(self.evo_dir, "t1", "a1", 0.5) == "improved"

        write_attempt(self.evo_dir, self._make_attempt("r1", 0.5, status="improved"))
        assert compare_to_history(self.evo_dir, "t1", "a1", 0.8) == "improved"
        assert compare_to_history(self.evo_dir, "t1", "a1", 0.5) == "baseline"
        assert compare_to_history(self.evo_dir, "t1", "a1", 0.3) == "regressed"
        assert compare_to_history(self.evo_dir, "t1", "a1", None) == "crashed"

    def test_leaderboard(self):
        write_attempt(self.evo_dir, self._make_attempt("r1", 0.3))
        write_attempt(self.evo_dir, self._make_attempt("r2", 0.9))
        write_attempt(self.evo_dir, self._make_attempt("r3", 0.6))
        lb = get_leaderboard(self.evo_dir, "t1")
        assert lb[0].score == 0.9
        assert lb[1].score == 0.6
        assert lb[2].score == 0.3

    def test_count_evals_since_improvement(self):
        write_attempt(self.evo_dir, self._make_attempt("r1", 0.5, status="improved",
                                                        ts="2026-01-01T01:00:00Z"))
        write_attempt(self.evo_dir, self._make_attempt("r2", 0.4, status="regressed",
                                                        ts="2026-01-01T02:00:00Z"))
        write_attempt(self.evo_dir, self._make_attempt("r3", 0.45, status="regressed",
                                                        ts="2026-01-01T03:00:00Z"))
        assert count_evals_since_improvement(self.evo_dir, "t1", "a1") == 2

    def test_format_leaderboard(self):
        write_attempt(self.evo_dir, self._make_attempt("r1", 0.8))
        lb = get_leaderboard(self.evo_dir, "t1")
        text = format_leaderboard(lb)
        assert "0.8000" in text
        assert "r1" in text

    def test_format_leaderboard_empty(self):
        assert format_leaderboard([]) == "No attempts yet."


# ── score_detail (multi-dimension) ──────────────────────────────────────

class TestScoreDetail:
    def test_score_detail_roundtrip(self):
        detail = {"accuracy": 0.9, "speed": 0.7, "coverage": 0.85}
        a = Attempt(
            run_id="sd1", agent_id="a1", task_id="t1",
            title="multi-dim", score=0.82, status="improved",
            timestamp="2026-01-01T00:00:00Z",
            score_detail=detail,
        )
        d = a.to_dict()
        assert d["score_detail"] == detail
        a2 = Attempt.from_dict(d)
        assert a2.score_detail == detail

    def test_score_detail_json_roundtrip(self):
        detail = {"recall": 0.95, "precision": 0.88}
        a = Attempt(
            run_id="sd2", agent_id="a1", task_id="t1",
            title="json", score=0.9, status="improved",
            timestamp="2026-01-01T00:00:00Z",
            score_detail=detail,
        )
        a2 = Attempt.from_json(a.to_json())
        assert a2.score_detail == detail

    def test_score_detail_none_omitted(self):
        a = Attempt(
            run_id="sd3", agent_id="a1", task_id="t1",
            title="no detail", score=0.5, status="baseline",
            timestamp="2026-01-01T00:00:00Z",
        )
        d = a.to_dict()
        assert "score_detail" not in d

    def test_score_detail_persisted_on_disk(self, tmp_path):
        evo_dir = str(tmp_path / ".cao-evo")
        init_checkpoint_repo(evo_dir)
        detail = {"dim1": 0.6, "dim2": 0.9}
        a = Attempt(
            run_id="sd4", agent_id="a1", task_id="t1",
            title="persist", score=0.75, status="improved",
            timestamp="2026-01-01T00:00:00Z",
            score_detail=detail,
        )
        write_attempt(evo_dir, a)
        loaded = read_attempts(evo_dir, "t1")
        assert len(loaded) == 1
        assert loaded[0].score_detail == detail


class TestEvolutionSignals:
    def test_signals_roundtrip(self):
        signals = {
            "grader_skill": {"skill": "security-grader", "score": 0.75, "dimensions": {"precision": 0.8}},
            "judge": {"source": "llm-as-judge", "score": 7, "confidence": 0.85},
        }
        a = Attempt(
            run_id="es1", agent_id="a1", task_id="t1",
            title="sig", score=0.75, status="improved",
            timestamp="2026-01-01T00:00:00Z",
            evolution_signals=signals,
        )
        d = a.to_dict()
        assert d["evolution_signals"]["grader_skill"]["score"] == 0.75
        assert d["evolution_signals"]["judge"]["confidence"] == 0.85
        a2 = Attempt.from_dict(d)
        assert a2.evolution_signals == signals

    def test_signals_none_omitted(self):
        a = Attempt(
            run_id="es2", agent_id="a1", task_id="t1",
            title="no sig", score=0.5, status="baseline",
            timestamp="2026-01-01T00:00:00Z",
        )
        assert "evolution_signals" not in a.to_dict()

    def test_signals_persisted_on_disk(self, tmp_path):
        evo_dir = str(tmp_path / ".cao-evo")
        init_checkpoint_repo(evo_dir)
        signals = {"custom": {"source": "my-evaluator", "value": 42}}
        a = Attempt(
            run_id="es3", agent_id="a1", task_id="t1",
            title="persist", score=0.8, status="improved",
            timestamp="2026-01-01T00:00:00Z",
            evolution_signals=signals,
        )
        write_attempt(evo_dir, a)
        loaded = read_attempts(evo_dir, "t1")
        assert loaded[0].evolution_signals == signals

    def test_signals_injected_in_prompt(self, tmp_path):
        from cli_agent_orchestrator.evolution.heartbeat import render_prompt, HeartbeatAction
        signals = {"judge": {"score": 8, "confidence": 0.9}}
        action = HeartbeatAction(
            name="reflect", every=1,
            prompt="Signals:\n{evolution_signals_json}\nDone.",
        )
        result = render_prompt(action, "agent-1", "task-1", evolution_signals=signals)
        assert '"judge"' in result
        assert '"score": 8' in result
        assert '"confidence": 0.9' in result

    def test_signals_empty_when_none(self, tmp_path):
        from cli_agent_orchestrator.evolution.heartbeat import render_prompt, HeartbeatAction
        action = HeartbeatAction(
            name="reflect", every=1,
            prompt="Signals: {evolution_signals_json}",
        )
        result = render_prompt(action, "a", "t", evolution_signals=None)
        assert "{}" in result


# ── git remote sync ─────────────────────────────────────────────────────

class TestGitRemoteSync:
    @pytest.fixture(autouse=True)
    def _tmpdir(self, tmp_path):
        self.evo_dir = str(tmp_path / ".cao-evolution")
        os.makedirs(self.evo_dir)

    def test_sync_noop_when_no_remote(self):
        """Without CAO_EVOLUTION_REMOTE, _sync_remote is a no-op."""
        from cli_agent_orchestrator.evolution.checkpoint import _sync_remote
        sd = init_checkpoint_repo(self.evo_dir)
        # Should not raise
        _sync_remote(sd)

    def test_setup_remote_adds_origin(self, tmp_path):
        """_setup_remote adds git remote when URL provided."""
        from cli_agent_orchestrator.evolution import checkpoint as cp_mod
        sd = init_checkpoint_repo(self.evo_dir)
        original = cp_mod._REMOTE_URL
        try:
            cp_mod._REMOTE_URL = "https://example.com/repo.git"
            from cli_agent_orchestrator.evolution.checkpoint import _setup_remote
            _setup_remote(sd)
            result = subprocess.run(
                ["git", "remote", "-v"], cwd=str(sd),
                capture_output=True, text=True,
            )
            assert "example.com/repo.git" in result.stdout
        finally:
            cp_mod._REMOTE_URL = original

    def test_sync_remote_handles_unreachable(self, tmp_path):
        """_sync_remote doesn't crash when remote is unreachable."""
        from cli_agent_orchestrator.evolution import checkpoint as cp_mod
        sd = init_checkpoint_repo(self.evo_dir)
        original = cp_mod._REMOTE_URL
        try:
            cp_mod._REMOTE_URL = "https://unreachable.invalid/repo.git"
            from cli_agent_orchestrator.evolution.checkpoint import _sync_remote
            # Should not raise — logs warning internally
            _sync_remote(sd)
        finally:
            cp_mod._REMOTE_URL = original


# ── RepoManager ──────────────────────────────────────────────────────────


class TestRepoManager:
    def test_get_dir_returns_correct_paths(self, tmp_path):
        from cli_agent_orchestrator.evolution.repo_manager import RepoManager
        rm = RepoManager(tmp_path)
        assert rm.get_dir("skills") == tmp_path / "skills"
        assert rm.get_dir("notes") == tmp_path / "notes"
        assert rm.get_dir("attempts") == tmp_path / "attempts"
        assert rm.get_dir("graders") == tmp_path / "graders"
        assert rm.get_dir("tasks") == tmp_path / "tasks"
        assert rm.get_dir("reports") == tmp_path / "reports"

    def test_get_dir_raises_on_unknown_type(self, tmp_path):
        from cli_agent_orchestrator.evolution.repo_manager import RepoManager
        rm = RepoManager(tmp_path)
        with pytest.raises(ValueError, match="Unknown content type"):
            rm.get_dir("bogus")

    def test_ensure_dirs_creates_all_directories(self, tmp_path):
        from cli_agent_orchestrator.evolution.repo_manager import RepoManager, CONTENT_TYPES
        rm = RepoManager(tmp_path / "new")
        rm.ensure_dirs()
        for ct in CONTENT_TYPES:
            assert (tmp_path / "new" / ct).is_dir()
        assert (tmp_path / "new" / "notes" / "_synthesis").is_dir()

    def test_git_root_single_mode(self, tmp_path):
        from cli_agent_orchestrator.evolution.repo_manager import RepoManager
        rm = RepoManager(tmp_path, mode="single")
        assert rm.git_root() == tmp_path
        assert rm.git_root("skills") == tmp_path
        assert rm.git_root("notes") == tmp_path

    def test_git_root_multi_mode(self, tmp_path):
        from cli_agent_orchestrator.evolution.repo_manager import RepoManager
        rm = RepoManager(tmp_path, mode="multi")
        assert rm.git_root("skills") == tmp_path / "skills"
        assert rm.git_root("notes") == tmp_path / "notes"
        assert rm.git_root("tasks") == tmp_path  # tasks stay in root


# ── group aggregation ──────────────────────────────────────────────────

class TestGroupAggregation:
    @pytest.fixture(autouse=True)
    def _tmpdir(self, tmp_path):
        self.evo_dir = str(tmp_path / ".cao-evolution")
        sd = init_checkpoint_repo(self.evo_dir)
        import yaml
        for tid, grp in [("cve-1", "exp-1"), ("cve-2", "exp-1"), ("cve-3", "exp-2")]:
            task_dir = sd / "tasks" / tid
            task_dir.mkdir(parents=True, exist_ok=True)
            (task_dir / "task.yaml").write_text(
                yaml.dump({"name": tid, "group": grp})
            )

    def _write(self, run_id, score, task_id="cve-1", agent_profile="", batch=""):
        a = Attempt(
            run_id=run_id, agent_id="a1", task_id=task_id,
            title=f"attempt {run_id}", score=score, status="improved",
            timestamp="2026-01-01T00:00:00Z",
            agent_profile=agent_profile, batch=batch,
        )
        write_attempt(self.evo_dir, a)

    def test_read_all_group_attempts(self):
        self._write("r1", 50, task_id="cve-1")
        self._write("r2", 80, task_id="cve-2")
        self._write("r3", 90, task_id="cve-3")  # different group
        attempts = read_all_group_attempts(self.evo_dir, "exp-1")
        assert len(attempts) == 2
        task_ids = {a.task_id for a in attempts}
        assert task_ids == {"cve-1", "cve-2"}

    def test_read_all_group_attempts_empty(self):
        attempts = read_all_group_attempts(self.evo_dir, "nonexistent")
        assert attempts == []

    def test_group_summary_by_profile(self):
        self._write("r1", 50, task_id="cve-1", agent_profile="opencode")
        self._write("r2", 80, task_id="cve-1", agent_profile="claude-code")
        self._write("r3", 70, task_id="cve-2", agent_profile="opencode")
        self._write("r4", 90, task_id="cve-2", agent_profile="claude-code")
        attempts = read_all_group_attempts(self.evo_dir, "exp-1")
        summary = group_summary(attempts)
        assert summary["total_attempts"] == 4
        profiles = summary["profiles"]
        assert profiles["opencode"]["avg_score"] == 60.0
        assert profiles["opencode"]["max_score"] == 70
        assert profiles["opencode"]["count"] == 2
        assert profiles["claude-code"]["avg_score"] == 85.0
        assert profiles["claude-code"]["max_score"] == 90

    def test_group_summary_per_task_breakdown(self):
        self._write("r1", 50, task_id="cve-1", agent_profile="opencode")
        self._write("r2", 70, task_id="cve-2", agent_profile="opencode")
        attempts = read_all_group_attempts(self.evo_dir, "exp-1")
        summary = group_summary(attempts)
        per_task = summary["profiles"]["opencode"]["per_task"]
        assert "cve-1" in per_task
        assert "cve-2" in per_task
        assert per_task["cve-1"]["avg_score"] == 50.0
        assert per_task["cve-2"]["avg_score"] == 70.0

    def test_format_leaderboard_includes_profile(self):
        self._write("r1", 80, agent_profile="opencode")
        lb = get_leaderboard(self.evo_dir, "cve-1")
        text = format_leaderboard(lb)
        assert "Profile" in text
        assert "opencode" in text
