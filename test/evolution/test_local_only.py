"""Tests for CAO_LOCAL_ONLY mode.

Verifies that when CAO_LOCAL_ONLY=1:
- Local bare repo is auto-created
- git_sync._git_remote() returns file:// URL
- CaoBridge Hub methods return no-op values
- _local_search() finds notes by keyword
- fetch_index() reads local index.md
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest


# ── git_sync local-only helpers ──────────────────────────────────────


class TestGitSyncLocalOnly:
    """Test git_sync local-only mode helpers."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        import importlib
        monkeypatch.syspath_prepend(
            str(Path(__file__).parent.parent.parent / "cao-bridge")
        )
        import git_sync
        importlib.reload(git_sync)
        self.gs = git_sync
        self.tmp = tmp_path

    def test_is_local_only_default(self, monkeypatch):
        monkeypatch.delenv("CAO_LOCAL_ONLY", raising=False)
        assert not self.gs._is_local_only()

    def test_is_local_only_enabled(self, monkeypatch):
        monkeypatch.setenv("CAO_LOCAL_ONLY", "1")
        assert self.gs._is_local_only()

    def test_ensure_local_shared_repo(self, monkeypatch):
        bare = self.tmp / "shared.git"
        monkeypatch.setattr(self.gs, "LOCAL_SHARED_REPO", bare)
        url = self.gs.ensure_local_shared_repo()
        assert url == f"file://{bare}"
        assert bare.exists()
        assert (bare / "HEAD").exists()  # bare repo marker

    def test_ensure_local_shared_repo_idempotent(self, monkeypatch):
        bare = self.tmp / "shared.git"
        monkeypatch.setattr(self.gs, "LOCAL_SHARED_REPO", bare)
        url1 = self.gs.ensure_local_shared_repo()
        url2 = self.gs.ensure_local_shared_repo()
        assert url1 == url2

    def test_git_remote_local_only(self, monkeypatch):
        bare = self.tmp / "shared.git"
        monkeypatch.setattr(self.gs, "LOCAL_SHARED_REPO", bare)
        monkeypatch.setenv("CAO_LOCAL_ONLY", "1")
        monkeypatch.delenv("CAO_GIT_REMOTE", raising=False)
        url = self.gs._git_remote()
        assert url.startswith("file://")
        assert bare.exists()

    def test_git_remote_explicit_override(self, monkeypatch):
        monkeypatch.setenv("CAO_LOCAL_ONLY", "1")
        monkeypatch.setenv("CAO_GIT_REMOTE", "git@host:repo.git")
        assert self.gs._git_remote() == "git@host:repo.git"

    def test_git_remote_normal_mode(self, monkeypatch):
        monkeypatch.delenv("CAO_LOCAL_ONLY", raising=False)
        monkeypatch.delenv("CAO_GIT_REMOTE", raising=False)
        assert self.gs._git_remote() == ""

    def test_local_index_path(self, monkeypatch):
        monkeypatch.setattr(self.gs, "_current_session_dir", self.tmp)
        p = self.gs.local_index_path()
        assert p == self.tmp / "index.md"


# ── CaoBridge local-only bypass ──────────────────────────────────────


class TestCaoBridgeLocalOnly:
    """Test CaoBridge methods return no-op values when CAO_LOCAL_ONLY=1."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        monkeypatch.syspath_prepend(
            str(Path(__file__).parent.parent.parent / "cao-bridge")
        )
        monkeypatch.setenv("CAO_LOCAL_ONLY", "1")
        from cao_bridge import CaoBridge
        self.bridge = CaoBridge(hub_url="http://should-not-be-called:9999")

    def test_register_local(self):
        tid = self.bridge.register()
        assert tid.startswith("local-")
        assert self.bridge.terminal_id == tid

    def test_reattach_local(self):
        assert self.bridge.reattach("some-id") is None

    def test_poll_local(self):
        assert self.bridge.poll() is None

    def test_report_local(self):
        self.bridge.report("completed", "output")  # should not raise

    def test_report_score_local(self):
        result = self.bridge.report_score("task-1", 85.0)
        assert result == {}

    def test_get_leaderboard_local(self):
        result = self.bridge.get_leaderboard("task-1")
        assert result == {"scores": []}

    def test_create_task_local(self):
        result = self.bridge.create_task("task-1")
        assert result["status"] == "local_only"

    def test_get_task_local(self):
        assert self.bridge.get_task("task-1") is None

    def test_list_tasks_local(self):
        assert self.bridge.list_tasks() == []

    def test_submit_report_local(self):
        result = self.bridge.submit_report("task-1", [{"description": "test"}])
        assert result == {"status": "local_only"}

    def test_fetch_feedbacks_local(self):
        result = self.bridge.fetch_feedbacks()
        assert result["fetched"] == []
        assert result["pending"] == []


# ── Local search ─────────────────────────────────────────────────────


class TestLocalSearch:
    """Test _local_search over local notes directory."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        monkeypatch.syspath_prepend(
            str(Path(__file__).parent.parent.parent / "cao-bridge")
        )
        monkeypatch.setenv("CAO_LOCAL_ONLY", "1")
        import git_sync
        monkeypatch.setattr(git_sync, "_current_session_dir", tmp_path)
        notes = tmp_path / "notes"
        notes.mkdir()
        (notes / "vuln-sqli.md").write_text("SQL injection found in login handler")
        (notes / "vuln-xss.md").write_text("XSS vulnerability in search page")
        (notes / "config-note.md").write_text("Database configuration review")
        from cao_bridge import CaoBridge
        self.bridge = CaoBridge()

    def test_search_finds_matching(self):
        results = self.bridge._local_search("SQL injection")
        assert len(results) >= 1
        assert results[0]["title"] == "vuln-sqli"

    def test_search_no_match(self):
        results = self.bridge._local_search("buffer overflow")
        assert results == []

    def test_search_multiple_matches(self):
        results = self.bridge._local_search("vulnerability")
        assert len(results) >= 1

    def test_search_respects_top_k(self):
        results = self.bridge._local_search("in", top_k=1)
        assert len(results) == 1

    def test_search_knowledge_delegates(self):
        results = self.bridge.search_knowledge("SQL")
        assert len(results) >= 1

    def test_recall_knowledge_delegates(self):
        results = self.bridge.recall_knowledge("SQL")
        assert len(results) >= 1


# ── Local L1 index ───────────────────────────────────────────────────


class TestLocalIndex:
    """Test fetch_index reads from local index.md."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        monkeypatch.syspath_prepend(
            str(Path(__file__).parent.parent.parent / "cao-bridge")
        )
        monkeypatch.setenv("CAO_LOCAL_ONLY", "1")
        import git_sync
        monkeypatch.setattr(git_sync, "_current_session_dir", tmp_path)
        self.tmp = tmp_path
        from cao_bridge import CaoBridge
        self.bridge = CaoBridge()

    def test_fetch_index_missing(self):
        assert self.bridge.fetch_index() == ""

    def test_fetch_index_exists(self):
        idx = self.tmp / "index.md"
        idx.write_text("# Knowledge Index\nTest content")
        assert "Test content" in self.bridge.fetch_index()

    def test_fetch_document_local(self):
        notes = self.tmp / "notes"
        notes.mkdir()
        (notes / "my-note.md").write_text("Note content here")
        result = self.bridge.fetch_document("my-note")
        assert result["content"] == "Note content here"

    def test_fetch_document_missing(self):
        (self.tmp / "notes").mkdir()
        result = self.bridge.fetch_document("nonexistent")
        assert result == {}
