"""Tests for evolution/skill_sync.py — bidirectional skill sync."""

import os
import textwrap
import tempfile
from pathlib import Path

import pytest

from cli_agent_orchestrator.evolution.skill_sync import (
    SyncResult,
    _file_hash,
    discover_skill_dirs,
    pull_skills,
    push_skills,
    resolve_writeback_target,
    scan_skills,
    sync_all,
)


def _make_skill(base: Path, name: str, content: str = "default") -> Path:
    """Helper: create a skill dir with SKILL.md."""
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    md = d / "SKILL.md"
    md.write_text(textwrap.dedent(f"""\
        ---
        name: "{name}"
        tags: [test]
        ---
        # {name}
        {content}
    """))
    return d


@pytest.fixture
def evo_dir(tmp_path):
    """Set up a minimal evolution directory structure."""
    sd = tmp_path / "shared" / "knowledge" / "skills"
    sd.mkdir(parents=True)
    return tmp_path


# ── scan_skills ──────────────────────────────────────────────────────────


class TestScanSkills:
    def test_empty_dir(self, tmp_path):
        assert scan_skills(tmp_path) == {}

    def test_nonexistent_dir(self, tmp_path):
        assert scan_skills(tmp_path / "nope") == {}

    def test_finds_skills(self, tmp_path):
        _make_skill(tmp_path, "skill-a")
        _make_skill(tmp_path, "skill-b")
        (tmp_path / "not-a-skill").mkdir()  # no SKILL.md
        result = scan_skills(tmp_path)
        assert set(result.keys()) == {"skill-a", "skill-b"}
        assert result["skill-a"].name == "SKILL.md"


# ── _file_hash ───────────────────────────────────────────────────────────


class TestFileHash:
    def test_same_content_same_hash(self, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("hello")
        b.write_text("hello")
        assert _file_hash(a) == _file_hash(b)

    def test_different_content_different_hash(self, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("hello")
        b.write_text("world")
        assert _file_hash(a) != _file_hash(b)


# ── push_skills ──────────────────────────────────────────────────────────


class TestPushSkills:
    def test_push_new_skill(self, evo_dir, tmp_path):
        local = tmp_path / "local"
        _make_skill(local, "scan-tool", "scan logic")
        result = push_skills(evo_dir, {"opencode": local})
        assert "opencode:scan-tool" in result.pushed
        pool_md = evo_dir / "shared" / "knowledge" / "skills" / "scan-tool" / "SKILL.md"
        assert pool_md.exists()
        assert "scan logic" in pool_md.read_text()

    def test_push_skips_unchanged(self, evo_dir, tmp_path):
        local = tmp_path / "local"
        _make_skill(local, "x")
        push_skills(evo_dir, {"opencode": local})
        # Push again — should skip
        result = push_skills(evo_dir, {"opencode": local})
        assert result.pushed == []

    def test_push_updates_changed(self, evo_dir, tmp_path):
        local = tmp_path / "local"
        _make_skill(local, "y", "v1")
        push_skills(evo_dir, {"opencode": local})
        # Modify local skill
        (local / "y" / "SKILL.md").write_text("v2 content")
        result = push_skills(evo_dir, {"opencode": local})
        assert "opencode:y" in result.pushed
        pool_md = evo_dir / "shared" / "knowledge" / "skills" / "y" / "SKILL.md"
        assert "v2 content" in pool_md.read_text()

    def test_push_from_multiple_sources(self, evo_dir, tmp_path):
        src1 = tmp_path / "opencode"
        src2 = tmp_path / "claude"
        _make_skill(src1, "skill-a")
        _make_skill(src2, "skill-b")
        result = push_skills(evo_dir, {"opencode": src1, "claude-code": src2})
        assert len(result.pushed) == 2
        assert (evo_dir / "shared" / "knowledge" / "skills" / "skill-a" / "SKILL.md").exists()
        assert (evo_dir / "shared" / "knowledge" / "skills" / "skill-b" / "SKILL.md").exists()


# ── pull_skills ──────────────────────────────────────────────────────────


class TestPullSkills:
    def test_pull_disabled_by_default(self, evo_dir, monkeypatch):
        monkeypatch.delenv("CAO_SKILL_WRITEBACK", raising=False)
        result = pull_skills(evo_dir)
        assert result.pulled == []

    def test_pull_to_explicit_target(self, evo_dir, tmp_path):
        _make_skill(evo_dir / "shared" / "knowledge" / "skills", "pool-skill", "shared content")
        target = tmp_path / "target"
        target.mkdir()
        result = pull_skills(evo_dir, target_dir=target)
        assert "pool-skill" in result.pulled
        assert (target / "pool-skill" / "SKILL.md").exists()
        assert "shared content" in (target / "pool-skill" / "SKILL.md").read_text()

    def test_pull_skips_unchanged(self, evo_dir, tmp_path):
        pool = evo_dir / "shared" / "knowledge" / "skills"
        _make_skill(pool, "z", "content")
        target = tmp_path / "target"
        target.mkdir()
        pull_skills(evo_dir, target_dir=target)
        # Pull again — should skip
        result = pull_skills(evo_dir, target_dir=target)
        assert result.pulled == []

    def test_pull_backups_on_conflict(self, evo_dir, tmp_path):
        pool = evo_dir / "shared" / "knowledge" / "skills"
        _make_skill(pool, "conflict-skill", "pool version")
        target = tmp_path / "target"
        _make_skill(target, "conflict-skill", "local version")

        result = pull_skills(evo_dir, target_dir=target)
        assert "conflict-skill" in result.pulled
        assert "conflict-skill" in result.backed_up
        # Backup should contain old content
        bak = target / "conflict-skill" / "SKILL.md.bak"
        assert bak.exists()
        assert "local version" in bak.read_text()
        # Main file should have pool content
        assert "pool version" in (target / "conflict-skill" / "SKILL.md").read_text()

    def test_pull_no_backup_flag(self, evo_dir, tmp_path):
        pool = evo_dir / "shared" / "knowledge" / "skills"
        _make_skill(pool, "nb", "new")
        target = tmp_path / "target"
        _make_skill(target, "nb", "old")

        result = pull_skills(evo_dir, target_dir=target, backup=False)
        assert "nb" in result.pulled
        assert result.backed_up == []
        assert not (target / "nb" / "SKILL.md.bak").exists()

    def test_pull_via_env_writeback(self, evo_dir, tmp_path, monkeypatch):
        pool = evo_dir / "shared" / "knowledge" / "skills"
        _make_skill(pool, "env-skill", "from pool")
        target = tmp_path / "claude" / "skills"
        target.mkdir(parents=True)
        monkeypatch.setenv("CAO_SKILL_WRITEBACK", "1")
        monkeypatch.setenv("CAO_SKILL_WRITEBACK_TARGET", "claude-code")
        # Patch _DEFAULT_DIRS so resolve_writeback_target finds our tmp dir
        import cli_agent_orchestrator.evolution.skill_sync as mod
        original = mod._DEFAULT_DIRS.copy()
        mod._DEFAULT_DIRS["claude-code"] = [target]
        try:
            result = pull_skills(evo_dir)
            assert "env-skill" in result.pulled
            assert (target / "env-skill" / "SKILL.md").exists()
        finally:
            mod._DEFAULT_DIRS.update(original)


# ── resolve_writeback_target ─────────────────────────────────────────────


class TestResolveWritebackTarget:
    def test_creates_dir_if_parent_exists(self, tmp_path, monkeypatch):
        import cli_agent_orchestrator.evolution.skill_sync as mod
        original = mod._DEFAULT_DIRS.copy()
        skills_dir = tmp_path / "claude-skills"
        # Parent (tmp_path) exists, so skills_dir should be created
        mod._DEFAULT_DIRS["claude-code"] = [skills_dir]
        try:
            result = resolve_writeback_target("claude-code")
            assert result == skills_dir
            assert skills_dir.exists()
        finally:
            mod._DEFAULT_DIRS.update(original)

    def test_falls_back_if_preferred_missing(self, tmp_path, monkeypatch):
        import cli_agent_orchestrator.evolution.skill_sync as mod
        original = mod._DEFAULT_DIRS.copy()
        oc = tmp_path / "opencode-skills"
        oc.mkdir()
        mod._DEFAULT_DIRS["claude-code"] = [Path("/nonexistent/claude")]
        mod._DEFAULT_DIRS["opencode"] = [oc]
        try:
            result = resolve_writeback_target("claude-code")
            assert result == oc
        finally:
            mod._DEFAULT_DIRS.update(original)


# ── sync_all ─────────────────────────────────────────────────────────────


class TestSyncAll:
    def test_full_round_trip(self, evo_dir, tmp_path, monkeypatch):
        import cli_agent_orchestrator.evolution.skill_sync as mod
        local_src = tmp_path / "src-skills"
        local_tgt = tmp_path / "tgt-skills"
        local_tgt.mkdir()

        # Create a local skill
        _make_skill(local_src, "my-skill", "my logic")

        # Enable write-back to target
        monkeypatch.setenv("CAO_SKILL_WRITEBACK", "1")
        monkeypatch.setenv("CAO_SKILL_WRITEBACK_TARGET", "claude-code")
        original = mod._DEFAULT_DIRS.copy()
        mod._DEFAULT_DIRS["claude-code"] = [local_tgt]
        try:
            result = sync_all(evo_dir, source_dirs={"opencode": local_src})
            assert "opencode:my-skill" in result.pushed
            assert "my-skill" in result.pulled
            # Pool has it
            assert (evo_dir / "shared" / "knowledge" / "skills" / "my-skill" / "SKILL.md").exists()
            # Target has it
            assert (local_tgt / "my-skill" / "SKILL.md").exists()
            assert "my logic" in (local_tgt / "my-skill" / "SKILL.md").read_text()
        finally:
            mod._DEFAULT_DIRS.update(original)


# ── discover_skill_dirs ──────────────────────────────────────────────────


class TestDiscoverSkillDirs:
    def test_includes_custom_from_env(self, tmp_path, monkeypatch):
        custom = tmp_path / "my-skills"
        custom.mkdir()
        monkeypatch.setenv("CAO_SKILL_DIRS", str(custom))
        # Patch defaults to avoid picking up real home dirs
        import cli_agent_orchestrator.evolution.skill_sync as mod
        original = mod._DEFAULT_DIRS.copy()
        mod._DEFAULT_DIRS = {"opencode": [], "claude-code": [], "hermes": []}
        try:
            dirs = discover_skill_dirs()
            assert "custom-0" in dirs
            assert dirs["custom-0"] == custom
        finally:
            mod._DEFAULT_DIRS.update(original)

    def test_skips_nonexistent(self, monkeypatch):
        import cli_agent_orchestrator.evolution.skill_sync as mod
        original = mod._DEFAULT_DIRS.copy()
        mod._DEFAULT_DIRS = {
            "opencode": [Path("/nonexistent/a")],
            "claude-code": [Path("/nonexistent/b")],
            "hermes": [Path("/nonexistent/c")],
        }
        monkeypatch.delenv("CAO_SKILL_DIRS", raising=False)
        try:
            dirs = discover_skill_dirs()
            assert dirs == {}
        finally:
            mod._DEFAULT_DIRS.update(original)
