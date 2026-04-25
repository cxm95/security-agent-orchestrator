"""Tests for skill adoption (auto-adopt + explicit adopt).

Verifies:
- _auto_adopt_skills() copies non-cao skills with prefix, dedup works
- adopt_skill() explicit adoption with guards
- push_repo() calls auto-adopt before import_local_skills
"""

from __future__ import annotations

import importlib
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


SKILL_CONTENT = textwrap.dedent("""\
    ---
    name: "{name}"
    ---
    # {name}
    Test skill.
""")


def _make_skill(base: Path, name: str) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(SKILL_CONTENT.format(name=name))
    return d


@pytest.fixture(autouse=True)
def _cao_bridge_path(monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).parent.parent.parent / "cao-bridge")
    )


@pytest.fixture
def gs(monkeypatch):
    import git_sync
    importlib.reload(git_sync)
    return git_sync


@pytest.fixture
def bridge_cls(monkeypatch):
    import cao_bridge
    importlib.reload(cao_bridge)
    return cao_bridge


# ── _auto_adopt_skills ──────────────────────────────────────────────


class TestAutoAdoptSkills:

    def test_adopts_non_cao_skill(self, tmp_path, gs, bridge_cls, monkeypatch):
        local_dir = tmp_path / "skills"
        local_dir.mkdir()
        _make_skill(local_dir, "my-scanner")

        clone_skills = tmp_path / "clone" / "skills"
        clone_skills.mkdir(parents=True)
        monkeypatch.setattr(gs, "skills_dir", lambda cdir=None: clone_skills)

        b = bridge_cls.CaoBridge.__new__(bridge_cls.CaoBridge)
        adopted = b._auto_adopt_skills(local_dir)

        assert adopted == ["cao-my-scanner"]
        assert (local_dir / "cao-my-scanner" / "SKILL.md").exists()
        # Original still exists
        assert (local_dir / "my-scanner" / "SKILL.md").exists()

    def test_skips_already_prefixed(self, tmp_path, gs, bridge_cls, monkeypatch):
        local_dir = tmp_path / "skills"
        local_dir.mkdir()
        _make_skill(local_dir, "cao-existing")

        clone_skills = tmp_path / "clone" / "skills"
        clone_skills.mkdir(parents=True)
        monkeypatch.setattr(gs, "skills_dir", lambda cdir=None: clone_skills)

        b = bridge_cls.CaoBridge.__new__(bridge_cls.CaoBridge)
        adopted = b._auto_adopt_skills(local_dir)

        assert adopted == []

    def test_dedup_local(self, tmp_path, gs, bridge_cls, monkeypatch):
        """Skip if cao-X already exists in the same local dir."""
        local_dir = tmp_path / "skills"
        local_dir.mkdir()
        _make_skill(local_dir, "my-scanner")
        _make_skill(local_dir, "cao-my-scanner")  # already adopted

        clone_skills = tmp_path / "clone" / "skills"
        clone_skills.mkdir(parents=True)
        monkeypatch.setattr(gs, "skills_dir", lambda cdir=None: clone_skills)

        b = bridge_cls.CaoBridge.__new__(bridge_cls.CaoBridge)
        adopted = b._auto_adopt_skills(local_dir)

        assert adopted == []

    def test_dedup_clone(self, tmp_path, gs, bridge_cls, monkeypatch):
        """Skip if cao-X already exists in the shared git clone."""
        local_dir = tmp_path / "skills"
        local_dir.mkdir()
        _make_skill(local_dir, "my-scanner")

        clone_skills = tmp_path / "clone" / "skills"
        _make_skill(clone_skills, "cao-my-scanner")  # in shared pool
        monkeypatch.setattr(gs, "skills_dir", lambda cdir=None: clone_skills)

        b = bridge_cls.CaoBridge.__new__(bridge_cls.CaoBridge)
        adopted = b._auto_adopt_skills(local_dir)

        assert adopted == []

    def test_skips_dir_without_skill_md(self, tmp_path, gs, bridge_cls, monkeypatch):
        local_dir = tmp_path / "skills"
        (local_dir / "not-a-skill").mkdir(parents=True)

        clone_skills = tmp_path / "clone" / "skills"
        clone_skills.mkdir(parents=True)
        monkeypatch.setattr(gs, "skills_dir", lambda cdir=None: clone_skills)

        b = bridge_cls.CaoBridge.__new__(bridge_cls.CaoBridge)
        adopted = b._auto_adopt_skills(local_dir)

        assert adopted == []

    def test_nonexistent_dir(self, tmp_path, gs, bridge_cls, monkeypatch):
        clone_skills = tmp_path / "clone" / "skills"
        clone_skills.mkdir(parents=True)
        monkeypatch.setattr(gs, "skills_dir", lambda cdir=None: clone_skills)

        b = bridge_cls.CaoBridge.__new__(bridge_cls.CaoBridge)
        adopted = b._auto_adopt_skills(tmp_path / "nope")

        assert adopted == []

    def test_multiple_skills(self, tmp_path, gs, bridge_cls, monkeypatch):
        local_dir = tmp_path / "skills"
        local_dir.mkdir()
        _make_skill(local_dir, "alpha")
        _make_skill(local_dir, "beta")
        _make_skill(local_dir, "cao-existing")  # should be skipped

        clone_skills = tmp_path / "clone" / "skills"
        clone_skills.mkdir(parents=True)
        monkeypatch.setattr(gs, "skills_dir", lambda cdir=None: clone_skills)

        b = bridge_cls.CaoBridge.__new__(bridge_cls.CaoBridge)
        adopted = b._auto_adopt_skills(local_dir)

        assert sorted(adopted) == ["cao-alpha", "cao-beta"]


# ── adopt_skill ─────────────────────────────────────────────────────


class TestAdoptSkill:

    def test_adopt_success(self, tmp_path, gs, bridge_cls, monkeypatch):
        local_dir = tmp_path / "skills"
        _make_skill(local_dir, "my-scanner")

        clone_skills = tmp_path / "clone" / "skills"
        clone_skills.mkdir(parents=True)
        monkeypatch.setattr(gs, "skills_dir", lambda cdir=None: clone_skills)
        monkeypatch.setattr(
            bridge_cls, "_candidate_local_skill_dirs",
            lambda: [local_dir],
        )

        b = bridge_cls.CaoBridge.__new__(bridge_cls.CaoBridge)
        result = b.adopt_skill("my-scanner")

        assert result["adopted"] == "cao-my-scanner"
        assert result["source"] == "my-scanner"
        assert (local_dir / "cao-my-scanner" / "SKILL.md").exists()

    def test_adopt_custom_name(self, tmp_path, gs, bridge_cls, monkeypatch):
        local_dir = tmp_path / "skills"
        _make_skill(local_dir, "my-scanner")

        clone_skills = tmp_path / "clone" / "skills"
        clone_skills.mkdir(parents=True)
        monkeypatch.setattr(gs, "skills_dir", lambda cdir=None: clone_skills)
        monkeypatch.setattr(
            bridge_cls, "_candidate_local_skill_dirs",
            lambda: [local_dir],
        )

        b = bridge_cls.CaoBridge.__new__(bridge_cls.CaoBridge)
        result = b.adopt_skill("my-scanner", new_name="vuln-scanner")

        assert result["adopted"] == "cao-vuln-scanner"
        assert (local_dir / "cao-vuln-scanner" / "SKILL.md").exists()

    def test_reject_already_prefixed(self, tmp_path, gs, bridge_cls, monkeypatch):
        b = bridge_cls.CaoBridge.__new__(bridge_cls.CaoBridge)
        with pytest.raises(ValueError, match="already has the"):
            b.adopt_skill("cao-something")

    def test_reject_local_duplicate(self, tmp_path, gs, bridge_cls, monkeypatch):
        local_dir = tmp_path / "skills"
        _make_skill(local_dir, "my-scanner")
        _make_skill(local_dir, "cao-my-scanner")

        clone_skills = tmp_path / "clone" / "skills"
        clone_skills.mkdir(parents=True)
        monkeypatch.setattr(gs, "skills_dir", lambda cdir=None: clone_skills)
        monkeypatch.setattr(
            bridge_cls, "_candidate_local_skill_dirs",
            lambda: [local_dir],
        )

        b = bridge_cls.CaoBridge.__new__(bridge_cls.CaoBridge)
        with pytest.raises(ValueError, match="already exists"):
            b.adopt_skill("my-scanner")

    def test_reject_clone_duplicate(self, tmp_path, gs, bridge_cls, monkeypatch):
        local_dir = tmp_path / "skills"
        _make_skill(local_dir, "my-scanner")

        clone_skills = tmp_path / "clone" / "skills"
        _make_skill(clone_skills, "cao-my-scanner")
        monkeypatch.setattr(gs, "skills_dir", lambda cdir=None: clone_skills)
        monkeypatch.setattr(
            bridge_cls, "_candidate_local_skill_dirs",
            lambda: [local_dir],
        )

        b = bridge_cls.CaoBridge.__new__(bridge_cls.CaoBridge)
        with pytest.raises(ValueError, match="already exists in shared pool"):
            b.adopt_skill("my-scanner")

    def test_not_found(self, tmp_path, gs, bridge_cls, monkeypatch):
        local_dir = tmp_path / "skills"
        local_dir.mkdir()

        monkeypatch.setattr(
            bridge_cls, "_candidate_local_skill_dirs",
            lambda: [local_dir],
        )

        b = bridge_cls.CaoBridge.__new__(bridge_cls.CaoBridge)
        with pytest.raises(ValueError, match="not found"):
            b.adopt_skill("nonexistent")


# ── push_repo auto-adopt ordering ──────────────────────────────────


class TestPushRepoAdoptOrdering:

    def test_auto_adopt_runs_before_import(self, tmp_path, gs, bridge_cls, monkeypatch):
        """Verify push_repo calls _auto_adopt_skills before import_local_skills."""
        call_order = []

        local_dir = tmp_path / "skills"
        local_dir.mkdir()
        monkeypatch.setattr(
            bridge_cls, "_candidate_local_skill_dirs",
            lambda: [local_dir],
        )

        original_adopt = bridge_cls.CaoBridge._auto_adopt_skills

        def mock_adopt(self, d):
            call_order.append("adopt")
            return original_adopt(self, d)

        def mock_import(d, cdir=None):
            call_order.append("import")
            return 0

        def mock_push(cdir=None, message=""):
            call_order.append("push")
            return True

        monkeypatch.setattr(bridge_cls.CaoBridge, "_auto_adopt_skills", mock_adopt)
        monkeypatch.setattr(gs, "import_local_skills", mock_import)
        monkeypatch.setattr(gs, "push", mock_push)

        b = bridge_cls.CaoBridge.__new__(bridge_cls.CaoBridge)
        b.push_repo("test")

        assert call_order == ["adopt", "import", "push"]
