"""Unit tests for cao_mcp_task_context.server."""

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Import the internal functions directly for testing
from cao_mcp_task_context.server import (
    _cleanup_phase,
    _cleanup_task,
    _get_required_skills_impl,
    _init_session,
    _list_tasks,
    _load_workflow,
    _prepare_phase_context,
    _prepare_task,
    _resolve_session_root,
    _validate_name,
    _validate_task_index,
    _write_meta,
)


@pytest.fixture(autouse=True)
def tmp_session_root(tmp_path, monkeypatch):
    """Set CAO_SESSION_ROOT to a temp directory for every test."""
    session_root = tmp_path / "sessions"
    session_root.mkdir()
    monkeypatch.setenv("CAO_SESSION_ROOT", str(session_root))
    return session_root


SAMPLE_PHASES = [
    {"name": "phase1", "agent": "phase1_agent", "depends_on": []},
    {"name": "phase2", "agent": "phase2_agent", "depends_on": ["phase1"]},
    {"name": "phase3", "agent": "phase3_agent", "depends_on": ["phase1", "phase2"]},
]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_validate_name_ok(self):
        assert _validate_name("my-agent_1.0", "test") == "my-agent_1.0"

    def test_validate_name_empty(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_name("", "test")

    def test_validate_name_special_chars(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_name("bad/name", "test")

    def test_validate_name_spaces(self):
        with pytest.raises(ValueError, match="Invalid"):
            _validate_name("has space", "test")

    def test_validate_task_index_ok(self):
        assert _validate_task_index("0") == "0"
        assert _validate_task_index("42") == "42"

    def test_validate_task_index_not_digit(self):
        with pytest.raises(ValueError, match="non-negative integer"):
            _validate_task_index("abc")

    def test_validate_task_index_negative(self):
        with pytest.raises(ValueError, match="non-negative integer"):
            _validate_task_index("-1")


# ---------------------------------------------------------------------------
# init_session
# ---------------------------------------------------------------------------

class TestInitSession:
    def test_basic(self, tmp_session_root):
        result = _init_session("test-session", SAMPLE_PHASES)

        assert result["phases"] == ["phase1", "phase2", "phase3"]
        assert Path(result["session_root"]).exists()
        assert Path(result["global_folder"]).exists()
        assert Path(result["tasks_folder"]).exists()
        assert Path(result["tasks_folder"]).name == "tasks"
        assert Path(result["workflow_path"]).exists()

        # Verify workflow.json content
        wf = json.loads(Path(result["workflow_path"]).read_text())
        assert wf["session_name"] == "test-session"
        assert len(wf["phases"]) == 3
        assert "_created_at" in wf

    def test_invalid_session_name(self):
        with pytest.raises(ValueError, match="Invalid session_name"):
            _init_session("bad name!", SAMPLE_PHASES)

    def test_invalid_dependency_order(self):
        bad_phases = [
            {"name": "phase2", "agent": "agent2", "depends_on": ["phase1"]},
            {"name": "phase1", "agent": "agent1", "depends_on": []},
        ]
        with pytest.raises(ValueError, match="not defined before"):
            _init_session("test", bad_phases)

    def test_idempotent(self, tmp_session_root):
        _init_session("test-session", SAMPLE_PHASES)
        result = _init_session("test-session", SAMPLE_PHASES)
        assert Path(result["workflow_path"]).exists()


# ---------------------------------------------------------------------------
# get_workflow
# ---------------------------------------------------------------------------

class TestGetWorkflow:
    def test_load(self, tmp_session_root):
        _init_session("test-session", SAMPLE_PHASES)
        wf = _load_workflow()
        assert wf["session_name"] == "test-session"
        assert len(wf["phases"]) == 3

    def test_not_initialized(self, tmp_session_root):
        with pytest.raises(ValueError, match="workflow.json not found"):
            _load_workflow()


# ---------------------------------------------------------------------------
# prepare_task
# ---------------------------------------------------------------------------

class TestPrepareTask:
    def test_basic(self, tmp_session_root):
        result = _prepare_task("0")
        assert result["task_index"] == "0"
        assert Path(result["task_dir"]).exists()
        assert Path(result["metadata_folder"]).exists()
        assert Path(result["metadata_folder"]).name == "meta"

    def test_multiple_tasks(self, tmp_session_root):
        for i in range(5):
            result = _prepare_task(str(i))
            assert Path(result["task_dir"]).exists()

    def test_invalid_index(self):
        with pytest.raises(ValueError, match="non-negative integer"):
            _prepare_task("abc")


# ---------------------------------------------------------------------------
# prepare_phase_context
# ---------------------------------------------------------------------------

class TestPreparePhaseContext:
    def test_phase1_no_deps(self, tmp_session_root):
        _init_session("test-session", SAMPLE_PHASES)
        _prepare_task("0")

        ctx = _prepare_phase_context("0", "phase1", target_id="target-A")

        assert ctx["task_index"] == "0"
        assert ctx["phase"] == "phase1"
        assert ctx["agent"] == "phase1_agent"
        assert ctx["target_id"] == "target-A"
        assert ctx["input_folder"] is None
        assert ctx["input_folders"] == {}

        # Directories created
        assert Path(ctx["working_directory"]).exists()
        assert Path(ctx["output_folder"]).exists()
        assert Path(ctx["global_folder"]).exists()
        assert Path(ctx["metadata_folder"]).exists()

    def test_phase2_depends_on_phase1(self, tmp_session_root):
        _init_session("test-session", SAMPLE_PHASES)
        _prepare_task("0")
        ctx1 = _prepare_phase_context("0", "phase1", target_id="target-A")

        # Simulate phase1 producing output
        (Path(ctx1["output_folder"]) / "result.json").write_text('{"ok": true}')

        ctx2 = _prepare_phase_context("0", "phase2", target_id="target-A")
        assert ctx2["input_folder"] == ctx1["output_folder"]
        assert "phase1" in ctx2["input_folders"]
        assert ctx2["input_folders"]["phase1"] == ctx1["output_folder"]

    def test_phase3_depends_on_phase1_and_phase2(self, tmp_session_root):
        _init_session("test-session", SAMPLE_PHASES)
        _prepare_task("0")

        ctx1 = _prepare_phase_context("0", "phase1")
        (Path(ctx1["output_folder"]) / "result.json").write_text("{}")

        ctx2 = _prepare_phase_context("0", "phase2")
        (Path(ctx2["output_folder"]) / "result.json").write_text("{}")

        ctx3 = _prepare_phase_context("0", "phase3")
        assert "phase1" in ctx3["input_folders"]
        assert "phase2" in ctx3["input_folders"]
        # primary input = last dependency
        assert ctx3["input_folder"] == ctx2["output_folder"]

    def test_missing_upstream(self, tmp_session_root):
        _init_session("test-session", SAMPLE_PHASES)
        _prepare_task("0")
        # phase2 depends on phase1, but phase1 not prepared yet
        # Code logs a warning and skips the missing upstream rather than raising
        ctx = _prepare_phase_context("0", "phase2")
        assert ctx["input_folder"] is None
        assert ctx["input_folders"] == {}

    def test_undefined_phase(self, tmp_session_root):
        _init_session("test-session", SAMPLE_PHASES)
        _prepare_task("0")
        with pytest.raises(ValueError, match="not defined in workflow.json"):
            _prepare_phase_context("0", "nonexistent")


# ---------------------------------------------------------------------------
# write_task_meta
# ---------------------------------------------------------------------------

class TestWriteMeta:
    def test_basic(self, tmp_session_root):
        _prepare_task("0")
        result = _write_meta("0", "progress", {"status": "running", "phase": "phase1"})
        assert result["written"] is True
        assert Path(result["path"]).exists()

        data = json.loads(Path(result["path"]).read_text())
        assert data["status"] == "running"
        assert data["phase"] == "phase1"
        assert "_assigned_at" in data
        assert "_updated_at" in data

    def test_merge_update(self, tmp_session_root):
        _prepare_task("0")
        _write_meta("0", "progress", {"v": 1, "status": "in_progress"})
        result = _write_meta("0", "progress", {"v": 2, "status": "success"})
        data = json.loads(Path(result["path"]).read_text())
        # New fields overwrite old ones
        assert data["v"] == 2
        assert data["status"] == "success"
        # _assigned_at from first write is preserved
        assert "_assigned_at" in data
        assert "_updated_at" in data

    def test_merge_preserves_assigned_at(self, tmp_session_root):
        _prepare_task("0")
        r1 = _write_meta("0", "task_meta", {"target_id": "x", "status": "in_progress"})
        d1 = json.loads(Path(r1["path"]).read_text())
        assigned_at = d1["_assigned_at"]

        import time; time.sleep(0.01)
        r2 = _write_meta("0", "task_meta", {"status": "success"})
        d2 = json.loads(Path(r2["path"]).read_text())
        # _assigned_at stays the same, _updated_at changes
        assert d2["_assigned_at"] == assigned_at
        assert d2["target_id"] == "x"  # merged from first write
        assert d2["status"] == "success"  # overwritten by second write


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------

class TestCleanup:
    def test_cleanup_phase(self, tmp_session_root):
        _init_session("test-session", SAMPLE_PHASES)
        _prepare_task("0")
        _prepare_phase_context("0", "phase1")

        result = _cleanup_phase("0", "phase1")
        assert result["deleted"] is True
        assert not Path(result["path"]).exists()

    def test_cleanup_phase_nonexistent(self, tmp_session_root):
        result = _cleanup_phase("0", "phase1")
        assert result["deleted"] is False

    def test_cleanup_task(self, tmp_session_root):
        _init_session("test-session", SAMPLE_PHASES)
        _prepare_task("0")
        _prepare_phase_context("0", "phase1")

        result = _cleanup_task("0")
        assert result["deleted"] is True
        assert not Path(result["path"]).exists()

    def test_cleanup_task_nonexistent(self, tmp_session_root):
        result = _cleanup_task("99")
        assert result["deleted"] is False


# ---------------------------------------------------------------------------
# list_tasks
# ---------------------------------------------------------------------------

class TestListTasks:
    def test_empty(self, tmp_session_root):
        result = _list_tasks()
        assert result["tasks"] == []

    def test_with_tasks(self, tmp_session_root):
        _init_session("test-session", SAMPLE_PHASES)
        _prepare_task("0")
        _prepare_task("1")
        _prepare_phase_context("0", "phase1")

        # Write an output file to phase1
        root = tmp_session_root
        (root / "0" / "phase1" / "out" / "result.json").write_text("{}")

        result = _list_tasks()
        assert len(result["tasks"]) == 2

        task0 = result["tasks"][0]
        assert task0["task_index"] == "0"
        assert len(task0["phases"]) == 1
        assert task0["phases"][0]["phase"] == "phase1"
        assert task0["phases"][0]["has_output"] is True

        task1 = result["tasks"][1]
        assert task1["task_index"] == "1"
        assert task1["phases"] == []

    def test_ignores_non_digit_dirs(self, tmp_session_root):
        _init_session("test-session", SAMPLE_PHASES)
        # global/ should not appear in tasks
        result = _list_tasks()
        assert all(t["task_index"].isdigit() for t in result["tasks"])


# ---------------------------------------------------------------------------
# Full workflow simulation
# ---------------------------------------------------------------------------

class TestFullWorkflow:
    """Simulate a complete 3-phase workflow for 3 tasks."""

    def test_full_lifecycle(self, tmp_session_root):
        # 1. Init session
        session = _init_session("cao-task-test", SAMPLE_PHASES)
        assert len(session["phases"]) == 3

        # 2. Run 3 tasks through all phases
        for task_idx in range(3):
            idx = str(task_idx)
            _prepare_task(idx)

            # Phase 1
            ctx1 = _prepare_phase_context(idx, "phase1", target_id=f"target-{task_idx}")
            # Simulate output
            (Path(ctx1["output_folder"]) / "result.json").write_text(
                json.dumps({"phase": "phase1", "count": task_idx * 10})
            )
            _write_meta(idx, "progress", {"last_phase": "phase1", "status": "done"})

            # Phase 2
            ctx2 = _prepare_phase_context(idx, "phase2", target_id=f"target-{task_idx}")
            assert ctx2["input_folder"] is not None
            (Path(ctx2["output_folder"]) / "result.json").write_text(
                json.dumps({"phase": "phase2", "count": task_idx * 20})
            )
            _write_meta(idx, "progress", {"last_phase": "phase2", "status": "done"})

            # Phase 3
            ctx3 = _prepare_phase_context(idx, "phase3", target_id=f"target-{task_idx}")
            assert len(ctx3["input_folders"]) == 2
            (Path(ctx3["output_folder"]) / "result.json").write_text(
                json.dumps({"phase": "phase3", "total": task_idx * 30})
            )
            _write_meta(idx, "progress", {"last_phase": "phase3", "status": "done"})

        # 3. Verify list_tasks
        listing = _list_tasks()
        assert len(listing["tasks"]) == 3
        for t in listing["tasks"]:
            assert len(t["phases"]) == 3
            assert all(p["has_output"] for p in t["phases"])

        # 4. Cleanup one task
        _cleanup_task("1")
        listing2 = _list_tasks()
        assert len(listing2["tasks"]) == 2
        indices = [t["task_index"] for t in listing2["tasks"]]
        assert "1" not in indices


# ---------------------------------------------------------------------------
# get_required_skills
# ---------------------------------------------------------------------------

class TestGetRequiredSkills:
    def test_skills_all_missing(self, tmp_path, monkeypatch):
        """Skills not installed in any provider → reported as missing."""
        workflow_root = tmp_path / "project"
        skills_dir = workflow_root / "skills"
        skills_dir.mkdir(parents=True)

        (skills_dir / "skills.json").write_text(json.dumps({
            "skills": [
                {"name": "my-skill", "type": "local_folder", "description": "A test skill"},
            ]
        }))
        skill_md_dir = skills_dir / "my-skill"
        skill_md_dir.mkdir()
        (skill_md_dir / "SKILL.md").write_text("# My Skill\nDoes stuff.")

        # Point all providers to empty dirs so nothing is installed
        import cao_mcp_task_context.server as srv
        empty = tmp_path / "empty_providers"
        empty.mkdir()
        monkeypatch.setattr(srv, "PROVIDER_SKILL_PATHS", {"claude": empty, "opencode": empty})
        monkeypatch.setenv("WORKFLOW_ROOT_DIR", str(workflow_root))

        result = _get_required_skills_impl("any-session")
        assert result["success"] is True
        assert result["missing"] == ["my-skill"]
        assert result["installed"] == []
        assert "my-skill" in result["message"]
        assert "❌" in result["message"]

    def test_no_skills_json(self, tmp_path, monkeypatch):
        """Returns failure when skills.json does not exist."""
        workflow_root = tmp_path / "empty_project"
        workflow_root.mkdir()
        monkeypatch.setenv("WORKFLOW_ROOT_DIR", str(workflow_root))
        result = _get_required_skills_impl("any-session")
        assert result["success"] is False

    def test_param_overrides_env(self, tmp_path, monkeypatch):
        """workflow_root parameter takes priority over env var."""
        monkeypatch.setenv("WORKFLOW_ROOT_DIR", str(tmp_path / "wrong"))

        workflow_root = tmp_path / "correct"
        skills_dir = workflow_root / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "skills.json").write_text(json.dumps({"skills": []}))

        result = _get_required_skills_impl("s", workflow_root=str(workflow_root))
        assert result["success"] is True
        assert result["installed"] == []
        assert result["missing"] == []

    def test_installed_status_detection(self, tmp_path, monkeypatch):
        """Skill installed in at least one provider → reported as installed."""
        workflow_root = tmp_path / "project"
        skills_dir = workflow_root / "skills"
        skills_dir.mkdir(parents=True)
        (skills_dir / "skills.json").write_text(json.dumps({
            "skills": [{"name": "test-skill", "description": "x"}]
        }))
        (skills_dir / "test-skill").mkdir()
        (skills_dir / "test-skill" / "SKILL.md").write_text("# Test")

        # Simulate claude provider has it installed
        claude_skills = tmp_path / "claude_skills"
        claude_skills.mkdir()
        (claude_skills / "test-skill").mkdir()
        (claude_skills / "test-skill" / "SKILL.md").write_text("# Installed")

        import cao_mcp_task_context.server as srv
        monkeypatch.setattr(srv, "PROVIDER_SKILL_PATHS", {
            "claude": claude_skills,
            "opencode": claude_skills,
        })
        monkeypatch.setenv("WORKFLOW_ROOT_DIR", str(workflow_root))

        result = _get_required_skills_impl("s")
        assert result["success"] is True
        assert "test-skill" in result["installed"]
        assert result["missing"] == []
        assert "✅" in result["message"]


# ---------------------------------------------------------------------------
# Explicit session_root parameter
# ---------------------------------------------------------------------------

class TestExplicitSessionRoot:
    """Tests for passing session_root explicitly instead of relying on env."""

    def test_resolve_session_root_param_overrides_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CAO_SESSION_ROOT", "/should/not/use")
        explicit = tmp_path / "explicit"
        explicit.mkdir()
        resolved = _resolve_session_root(str(explicit))
        assert resolved == explicit.resolve()

    def test_resolve_session_root_falls_back_to_env(self, tmp_session_root):
        resolved = _resolve_session_root(None)
        assert resolved == tmp_session_root.resolve()

    def test_init_session_with_explicit_root(self, tmp_path):
        root = tmp_path / "my_session"
        root.mkdir()
        result = _init_session("test-sess", SAMPLE_PHASES, session_root=str(root))
        assert result["session_root"] == str(root.resolve())
        assert Path(result["global_folder"]).exists()

    def test_prepare_task_with_explicit_root(self, tmp_path):
        root = tmp_path / "sr"
        root.mkdir()
        _init_session("test-sess", SAMPLE_PHASES, session_root=str(root))
        result = _prepare_task("0", session_root=str(root))
        assert str(root.resolve()) in result["task_dir"]

    def test_full_workflow_with_explicit_root(self, tmp_path):
        root = tmp_path / "explicit_root"
        root.mkdir()
        sr = str(root)

        _init_session("test-sess", SAMPLE_PHASES, session_root=sr)
        _prepare_task("0", session_root=sr)
        ctx = _prepare_phase_context("0", "phase1", target_id="t-0", session_root=sr)
        assert str(root.resolve()) in ctx["global_folder"]

        (Path(ctx["output_folder"]) / "result.json").write_text("{}")
        _write_meta("0", "progress", {"status": "done"}, session_root=sr)
        listing = _list_tasks(session_root=sr)
        assert len(listing["tasks"]) == 1

        _cleanup_task("0", session_root=sr)
        listing2 = _list_tasks(session_root=sr)
        assert len(listing2["tasks"]) == 0

    def test_two_sessions_isolated(self, tmp_path):
        """Two explicit session roots should not interfere with each other."""
        root_a = tmp_path / "session_a"
        root_b = tmp_path / "session_b"
        root_a.mkdir()
        root_b.mkdir()

        _init_session("sess-a", SAMPLE_PHASES, session_root=str(root_a))
        _init_session("sess-b", SAMPLE_PHASES, session_root=str(root_b))

        _prepare_task("0", session_root=str(root_a))
        _prepare_task("0", session_root=str(root_b))

        ctx_a = _prepare_phase_context("0", "phase1", session_root=str(root_a))
        ctx_b = _prepare_phase_context("0", "phase1", session_root=str(root_b))

        assert ctx_a["working_directory"] != ctx_b["working_directory"]
        assert str(root_a.resolve()) in ctx_a["working_directory"]
        assert str(root_b.resolve()) in ctx_b["working_directory"]
