"""Tests for cao-bridge/session_manager.py — session-based isolation."""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

# Add cao-bridge to path so session_manager is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "cao-bridge"))

import session_manager as sm

_OK = subprocess.CompletedProcess([], 0, "", "")


@pytest.fixture(autouse=True)
def tmp_base_dir(tmp_path, monkeypatch):
    """Redirect all session_manager operations to a temp directory."""
    monkeypatch.setenv("CAO_CLIENT_BASE_DIR", str(tmp_path))
    return tmp_path


def _create(sid="", profile="test-agent"):
    """Helper: create a session with subprocess mocked."""
    return sm.create_session(
        git_remote="file:///tmp/fake-repo",
        agent_profile=profile,
        session_id=sid,
    )


# ---------------------------------------------------------------------------
# generate_session_id
# ---------------------------------------------------------------------------

class TestGenerateSessionId:
    def test_format(self):
        sid = sm.generate_session_id()
        assert re.match(r"^\d{8}T\d{6}-[0-9a-f]{8}$", sid), f"bad format: {sid}"

    def test_uniqueness(self):
        ids = {sm.generate_session_id() for _ in range(50)}
        assert len(ids) == 50


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------

@patch("subprocess.run", return_value=_OK)
class TestCreateSession:
    def test_creates_directory_and_meta(self, mock_run, tmp_base_dir):
        sdir = _create()
        assert sdir.exists()
        meta = json.loads((sdir / ".session.json").read_text())
        assert meta["status"] == "active"
        assert meta["agent_profile"] == "test-agent"
        assert meta["pid"] == os.getpid()
        assert re.match(r"^\d{8}T\d{6}-[0-9a-f]{8}$", meta["session_id"])

    def test_creates_subdirs(self, mock_run, tmp_base_dir):
        sdir = _create()
        for sub in sm._SUBDIRS:
            assert (sdir / sub).is_dir(), f"missing subdir: {sub}"

    def test_custom_session_id(self, mock_run, tmp_base_dir):
        sdir = _create(sid="20260416T120000-deadbeef")
        assert sdir.name == "20260416T120000-deadbeef"

    def test_reuse_active_session(self, mock_run, tmp_base_dir):
        s1 = _create(sid="reuse-test-00000000")
        s2 = _create(sid="reuse-test-00000000")
        assert s1 == s2


# ---------------------------------------------------------------------------
# touch_session
# ---------------------------------------------------------------------------

@patch("subprocess.run", return_value=_OK)
class TestTouchSession:
    def test_updates_last_update(self, mock_run, tmp_base_dir):
        sdir = _create()
        old_ts = sm._read_meta(sdir)["last_update"]
        time.sleep(0.05)
        sm.touch_session(sdir)
        meta = sm._read_meta(sdir)
        assert meta["last_update"] > old_ts
        assert meta["status"] == "active"

    def test_noop_on_missing_dir(self, mock_run, tmp_base_dir):
        sm.touch_session(tmp_base_dir / "nonexistent")


# ---------------------------------------------------------------------------
# set_terminal_id
# ---------------------------------------------------------------------------

@patch("subprocess.run", return_value=_OK)
class TestSetTerminalId:
    def test_stores_terminal_id(self, mock_run, tmp_base_dir):
        sdir = _create()
        sm.set_terminal_id(sdir, "abc123")
        assert sm._read_meta(sdir)["terminal_id"] == "abc123"


# ---------------------------------------------------------------------------
# deactivate_session
# ---------------------------------------------------------------------------

@patch("subprocess.run", return_value=_OK)
class TestDeactivateSession:
    def test_marks_inactive(self, mock_run, tmp_base_dir):
        sdir = _create()
        assert sm._read_meta(sdir)["status"] == "active"
        sm.deactivate_session(sdir)
        assert sm._read_meta(sdir)["status"] == "inactive"

    def test_noop_on_missing_dir(self, mock_run, tmp_base_dir):
        sm.deactivate_session(tmp_base_dir / "nonexistent")


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------

@patch("subprocess.run", return_value=_OK)
class TestListSessions:
    def test_list_all(self, mock_run, tmp_base_dir):
        _create(sid="s1-00000001")
        _create(sid="s2-00000002")
        assert len(sm.list_sessions()) == 2

    def test_filter_by_status(self, mock_run, tmp_base_dir):
        s1 = _create(sid="s1-00000001")
        _create(sid="s2-00000002")
        sm.deactivate_session(s1)

        active = sm.list_sessions(status="active")
        assert len(active) == 1
        assert active[0]["session_id"] == "s2-00000002"

        inactive = sm.list_sessions(status="inactive")
        assert len(inactive) == 1
        assert inactive[0]["session_id"] == "s1-00000001"


# ---------------------------------------------------------------------------
# cleanup_sessions
# ---------------------------------------------------------------------------

@patch("subprocess.run", return_value=_OK)
class TestCleanupSessions:
    def test_removes_expired_inactive(self, mock_run, tmp_base_dir):
        sdir = _create(sid="old-00000001")
        sm.deactivate_session(sdir)
        meta = sm._read_meta(sdir)
        meta["last_update"] = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        sm._write_meta(sdir, meta)

        removed = sm.cleanup_sessions(max_age_hours=24)
        assert "old-00000001" in removed
        assert not sdir.exists()

    def test_keeps_recent_inactive(self, mock_run, tmp_base_dir):
        sdir = _create(sid="new-00000001")
        sm.deactivate_session(sdir)
        assert len(sm.cleanup_sessions(max_age_hours=24)) == 0
        assert sdir.exists()

    def test_marks_stale_active_as_inactive(self, mock_run, tmp_base_dir):
        sdir = _create(sid="stale-00000001")
        meta = sm._read_meta(sdir)
        meta["last_update"] = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        meta["pid"] = 99999999
        sm._write_meta(sdir, meta)

        removed = sm.cleanup_sessions(max_age_hours=24)
        assert len(removed) == 0
        assert sdir.exists()
        assert sm._read_meta(sdir)["status"] == "inactive"


# ---------------------------------------------------------------------------
# Two sessions are isolated
# ---------------------------------------------------------------------------

@patch("subprocess.run", return_value=_OK)
class TestSessionIsolation:
    def test_two_sessions_have_separate_dirs(self, mock_run, tmp_base_dir):
        s1 = _create(sid="iso-a0000001")
        s2 = _create(sid="iso-b0000002")
        assert s1 != s2
        assert s1.exists() and s2.exists()
        (s1 / "notes" / "test.md").write_text("hello from s1")
        assert not (s2 / "notes" / "test.md").exists()
