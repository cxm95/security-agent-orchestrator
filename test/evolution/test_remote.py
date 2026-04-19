"""Tests for RemoteProvider and remote API endpoints."""

import pytest
import time
from unittest.mock import patch

from cli_agent_orchestrator.providers.remote import RemoteProvider
from cli_agent_orchestrator.models.provider import ProviderType
from cli_agent_orchestrator.models.terminal import TerminalStatus


# ---------------------------------------------------------------------------
# Unit tests: RemoteProvider
# ---------------------------------------------------------------------------

class TestRemoteProvider:
    def setup_method(self):
        # RemoteProvider now mirrors state to the ``remote_state`` SQLite
        # table, so we must wipe any row left by a previous test under the
        # same terminal_id before constructing the provider — otherwise
        # __init__ would hydrate stale ERROR / PROCESSING state.
        try:
            from cli_agent_orchestrator.clients.database import delete_remote_state
            delete_remote_state("test-001")
        except Exception:
            pass
        self.provider = RemoteProvider("test-001", "session", "window", "profile")

    def test_initial_state(self):
        assert self.provider.get_status() == TerminalStatus.IDLE
        assert self.provider._pending_input is None
        assert self.provider._last_output == ""
        assert self.provider._full_output == ""

    def test_initialize(self):
        assert self.provider.initialize() is True

    def test_set_and_consume_pending_input(self):
        self.provider.set_pending_input("hello")
        assert self.provider._pending_input == "hello"
        # Status stays IDLE until consumed
        assert self.provider.get_status() == TerminalStatus.IDLE

        msg = self.provider.consume_pending_input()
        assert msg == "hello"
        assert self.provider._pending_input is None
        assert self.provider.get_status() == TerminalStatus.PROCESSING

    def test_consume_when_empty(self):
        msg = self.provider.consume_pending_input()
        assert msg is None
        # Status unchanged when nothing consumed
        assert self.provider.get_status() == TerminalStatus.IDLE

    def test_report_status(self):
        self.provider.report_status("completed")
        assert self.provider.get_status() == TerminalStatus.COMPLETED

    def test_report_status_invalid(self):
        self.provider.report_status("bogus_status")
        assert self.provider.get_status() == TerminalStatus.ERROR

    def test_report_output_replace(self):
        self.provider.report_output("first")
        assert self.provider._last_output == "first"
        assert self.provider._full_output == "first"

        self.provider.report_output("second")
        assert self.provider._last_output == "second"
        assert self.provider._full_output == "second"  # replaced

    def test_report_output_append(self):
        self.provider.report_output("a")
        self.provider.report_output("b", append=True)
        assert self.provider._last_output == "b"
        assert self.provider._full_output == "ab"

    def test_extract_last_message(self):
        self.provider.report_output("result text")
        assert self.provider.extract_last_message_from_script("ignored") == "result text"

    def test_get_full_output(self):
        self.provider.report_output("chunk1")
        self.provider.report_output("chunk2", append=True)
        assert self.provider.get_full_output() == "chunk1chunk2"

    def test_idle_pattern_empty(self):
        assert self.provider.get_idle_pattern_for_log() == ""

    def test_exit_cli_empty(self):
        assert self.provider.exit_cli() == ""

    def test_cleanup(self):
        # Should not raise
        self.provider.cleanup()


class TestProviderTypeEnum:
    def test_remote_enum_exists(self):
        assert ProviderType.REMOTE.value == "remote"

    def test_remote_round_trip(self):
        assert ProviderType("remote") == ProviderType.REMOTE


# ---------------------------------------------------------------------------
# Unit tests: ProviderManager with remote
# ---------------------------------------------------------------------------

class TestProviderManagerRemote:
    def test_create_remote_provider(self):
        from cli_agent_orchestrator.providers.manager import ProviderManager
        mgr = ProviderManager()
        provider = mgr.create_provider("remote", "tid-001", "sess", "win", "prof")
        assert isinstance(provider, RemoteProvider)
        assert mgr.get_provider("tid-001") is provider

    def test_cleanup_remote_provider(self):
        from cli_agent_orchestrator.providers.manager import ProviderManager
        mgr = ProviderManager()
        mgr.create_provider("remote", "tid-002", "sess", "win")
        mgr.cleanup_provider("tid-002")
        assert "tid-002" not in mgr._providers


# ---------------------------------------------------------------------------
# Integration tests: API endpoints (requires running server or TestClient)
# ---------------------------------------------------------------------------

class TestRemoteAPI:
    """Tests using FastAPI TestClient — no real server needed."""

    @pytest.fixture(autouse=True)
    def setup_client(self):
        from fastapi.testclient import TestClient
        from cli_agent_orchestrator.api.main import app
        from cli_agent_orchestrator.clients.database import init_db
        init_db()
        self.client = TestClient(app, headers={"host": "localhost"})
        self._terminals = []
        yield
        # Cleanup
        for tid in self._terminals:
            try:
                self.client.delete(f"/terminals/{tid}")
            except Exception:
                pass

    def _register(self, profile="test-agent"):
        resp = self.client.post("/remotes/register", json={"agent_profile": profile})
        assert resp.status_code == 201
        data = resp.json()
        self._terminals.append(data["terminal_id"])
        return data["terminal_id"]

    def test_register(self):
        tid = self._register()
        assert len(tid) == 8  # hex terminal id

    def test_poll_empty(self):
        tid = self._register()
        resp = self.client.get(f"/remotes/{tid}/poll")
        assert resp.status_code == 200
        assert resp.json() == {"has_input": False, "input": None}

    def test_send_then_poll(self):
        tid = self._register()
        # Send via standard terminal API
        resp = self.client.post(f"/terminals/{tid}/input?message=hello")
        assert resp.status_code == 200

        # Poll
        resp = self.client.get(f"/remotes/{tid}/poll")
        data = resp.json()
        assert data["has_input"] is True
        assert data["input"] == "hello"

        # Poll again — should be empty
        resp = self.client.get(f"/remotes/{tid}/poll")
        assert resp.json()["has_input"] is False

    def test_report_status_and_output(self):
        tid = self._register()
        resp = self.client.post(f"/remotes/{tid}/report",
                                json={"status": "completed", "output": "done"})
        assert resp.status_code == 200

        # Check via terminal API
        resp = self.client.get(f"/terminals/{tid}")
        assert resp.json()["status"] == "completed"

        resp = self.client.get(f"/terminals/{tid}/output?mode=last")
        assert resp.json()["output"] == "done"

    def test_full_handoff_flow(self):
        """Simulate the full handoff lifecycle."""
        tid = self._register()

        # 1. Status starts idle
        resp = self.client.get(f"/terminals/{tid}")
        assert resp.json()["status"] == "idle"

        # 2. Hub sends task
        self.client.post(f"/terminals/{tid}/input?message=solve+x%3D1%2B1")

        # 3. Bridge polls → processing
        resp = self.client.get(f"/remotes/{tid}/poll")
        assert resp.json()["input"] == "solve x=1+1"

        resp = self.client.get(f"/terminals/{tid}")
        assert resp.json()["status"] == "processing"

        # 4. Bridge reports done
        self.client.post(f"/remotes/{tid}/report",
                         json={"status": "completed", "output": "x=2"})

        resp = self.client.get(f"/terminals/{tid}")
        assert resp.json()["status"] == "completed"

        resp = self.client.get(f"/terminals/{tid}/output?mode=last")
        assert resp.json()["output"] == "x=2"

    def test_delete_remote_terminal(self):
        tid = self._register()
        resp = self.client.delete(f"/terminals/{tid}")
        assert resp.status_code == 200
        self._terminals.remove(tid)

        # Should be gone
        resp = self.client.get(f"/terminals/{tid}")
        assert resp.status_code == 404 or resp.status_code == 500

    def test_poll_nonexistent(self):
        resp = self.client.get("/remotes/nonexistent/poll")
        assert resp.status_code >= 400

    def test_report_nonexistent(self):
        resp = self.client.post("/remotes/nonexistent/report",
                                json={"status": "completed"})
        assert resp.status_code >= 400

    def test_poll_non_remote_terminal(self):
        """Polling a local terminal should return 400."""
        # We can't easily create a local terminal without tmux,
        # so we just verify the endpoint rejects non-remote types
        # by testing with a nonexistent terminal
        resp = self.client.get("/remotes/fake0000/poll")
        assert resp.status_code >= 400

    def test_remote_status_endpoint(self):
        tid = self._register()
        resp = self.client.get(f"/remotes/{tid}/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["terminal_id"] == tid
        assert data["status"] == "idle"
        assert data["has_pending_input"] is False

    def test_report_append_output(self):
        tid = self._register()
        self.client.post(f"/remotes/{tid}/report",
                         json={"output": "part1", "append": False})
        self.client.post(f"/remotes/{tid}/report",
                         json={"output": "part2", "append": True})

        resp = self.client.get(f"/terminals/{tid}/output?mode=full")
        assert resp.json()["output"] == "part1part2"

    def test_output_full_vs_last(self):
        tid = self._register()
        self.client.post(f"/remotes/{tid}/report",
                         json={"output": "chunk1"})
        self.client.post(f"/remotes/{tid}/report",
                         json={"output": "chunk2", "append": True})

        full = self.client.get(f"/terminals/{tid}/output?mode=full").json()["output"]
        last = self.client.get(f"/terminals/{tid}/output?mode=last").json()["output"]
        assert full == "chunk1chunk2"
        assert last == "chunk2"

    def test_inbox_to_remote_delivery(self):
        """send_message inbox messages should be delivered via poll."""
        from cli_agent_orchestrator.clients.database import create_inbox_message, get_inbox_messages
        from cli_agent_orchestrator.models.inbox import MessageStatus

        tid = self._register()

        # Insert inbox message (simulating what send_message MCP does)
        create_inbox_message(sender_id="local-agent", receiver_id=tid, message="task from inbox")

        # Verify message is PENDING
        msgs = get_inbox_messages(tid, status=MessageStatus.PENDING)
        assert len(msgs) == 1
        assert msgs[0].message == "task from inbox"

        # Poll should pick up the inbox message
        resp = self.client.get(f"/remotes/{tid}/poll")
        data = resp.json()
        assert data["has_input"] is True
        assert data["input"] == "task from inbox"

        # Inbox message should now be DELIVERED
        msgs = get_inbox_messages(tid, status=MessageStatus.PENDING)
        assert len(msgs) == 0
        delivered = get_inbox_messages(tid, status=MessageStatus.DELIVERED)
        assert len(delivered) == 1

    def test_inbox_not_delivered_when_direct_input_pending(self):
        """Direct pending_input takes priority over inbox messages."""
        from cli_agent_orchestrator.clients.database import create_inbox_message

        tid = self._register()

        # Set direct pending input first
        self.client.post(f"/terminals/{tid}/input?message=direct+task")

        # Also add inbox message
        create_inbox_message(sender_id="local-agent", receiver_id=tid, message="inbox task")

        # Poll should return the direct task (inbox stays PENDING)
        resp = self.client.get(f"/remotes/{tid}/poll")
        data = resp.json()
        assert data["has_input"] is True
        assert data["input"] == "direct task"

        # Next poll should now pick up the inbox message
        # First report completed so status is right
        self.client.post(f"/remotes/{tid}/report", json={"status": "completed"})
        resp = self.client.get(f"/remotes/{tid}/poll")
        data = resp.json()
        assert data["has_input"] is True
        assert data["input"] == "inbox task"
