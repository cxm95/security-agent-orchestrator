"""Tests for assign MCP tool."""

import os
from unittest.mock import patch

import pytest

from cli_agent_orchestrator.mcp_server.server import _assign_description, _build_context_header


class TestAssignSenderIdInjection:
    """Tests for sender ID injection in _assign_impl."""

    @patch("cli_agent_orchestrator.mcp_server.server.ENABLE_SENDER_ID_INJECTION", True)
    @patch("cli_agent_orchestrator.mcp_server.server._load_system_prompt", return_value="")
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_assign_appends_sender_id_when_injection_enabled(self, mock_create, mock_send, _):
        """When injection is enabled, assign should append sender ID suffix."""
        from cli_agent_orchestrator.mcp_server.server import _assign_impl

        mock_create.return_value = ("worker-1", "claude_code")
        mock_send.return_value = None

        with patch.dict(os.environ, {"CAO_TERMINAL_ID": "supervisor-abc123"}):
            result = _assign_impl("developer", "Analyze the logs")

        assert result["success"] is True
        sent_message = mock_send.call_args[0][1]
        assert sent_message.startswith("Analyze the logs")
        assert "[CAO Assign] supervisor_terminal_id=supervisor-abc123" in sent_message
        assert 'send_message(receiver_id="supervisor-abc123"' in sent_message

    @patch("cli_agent_orchestrator.mcp_server.server.ENABLE_SENDER_ID_INJECTION", False)
    @patch("cli_agent_orchestrator.mcp_server.server._load_system_prompt", return_value="")
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_assign_no_suffix_when_injection_disabled(self, mock_create, mock_send, _):
        """When injection is disabled, assign should send the message unchanged."""
        from cli_agent_orchestrator.mcp_server.server import _assign_impl

        mock_create.return_value = ("worker-2", "claude_code")
        mock_send.return_value = None

        with patch.dict(os.environ, {"CAO_TERMINAL_ID": "supervisor-abc123"}):
            result = _assign_impl("developer", "Analyze the logs")

        assert result["success"] is True
        sent_message = mock_send.call_args[0][1]
        assert sent_message == "Analyze the logs"

    @patch("cli_agent_orchestrator.mcp_server.server.ENABLE_SENDER_ID_INJECTION", True)
    @patch("cli_agent_orchestrator.mcp_server.server._load_system_prompt", return_value="")
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_assign_sender_id_fallback_unknown(self, mock_create, mock_send, _):
        """When CAO_TERMINAL_ID is not set, suffix should use 'unknown'."""
        from cli_agent_orchestrator.mcp_server.server import _assign_impl

        mock_create.return_value = ("worker-3", "codex")
        mock_send.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = _assign_impl("developer", "Build feature X")

        sent_message = mock_send.call_args[0][1]
        assert "[CAO Assign] supervisor_terminal_id=unknown" in sent_message

    @patch("cli_agent_orchestrator.mcp_server.server.ENABLE_SENDER_ID_INJECTION", True)
    @patch("cli_agent_orchestrator.mcp_server.server._load_system_prompt", return_value="")
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_assign_suffix_is_appended_not_prepended(self, mock_create, mock_send, _):
        """The sender ID should be a suffix, not a prefix."""
        from cli_agent_orchestrator.mcp_server.server import _assign_impl

        mock_create.return_value = ("worker-4", "claude_code")
        mock_send.return_value = None
        original = "Do the task described in /path/to/task.md"

        with patch.dict(os.environ, {"CAO_TERMINAL_ID": "sup-111"}):
            _assign_impl("developer", original)

        sent_message = mock_send.call_args[0][1]
        assert sent_message.startswith(original)
        assert sent_message.index("[CAO Assign]") > len(original)


class TestAssignDescription:
    """Tests for the static _assign_description string."""

    def test_starts_with_action_sentence(self):
        assert _assign_description.startswith("Assigns a task to another agent without blocking.")

    def test_contains_args_section(self):
        assert "Args:" in _assign_description
        assert "agent_profile:" in _assign_description
        assert "message:" in _assign_description

    def test_contains_returns_section(self):
        assert "Returns:" in _assign_description
        assert "Dict with success status" in _assign_description


class TestAssignContextHeader:
    """Tests for _build_context_header used by _assign_impl."""

    @patch("cli_agent_orchestrator.mcp_server.server.ENABLE_SENDER_ID_INJECTION", False)
    @patch("cli_agent_orchestrator.mcp_server.server._load_system_prompt", return_value="")
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input_assign")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_assign_with_context_params_prepends_header(self, mock_create, mock_send, _mock_prompt):
        """Context params should be prepended as [CAO Context] header."""
        from cli_agent_orchestrator.mcp_server.server import _assign_impl

        mock_create.return_value = ("worker-5", "claude_code")
        mock_send.return_value = None

        with patch.dict(os.environ, {"CAO_TERMINAL_ID": "sup-222"}):
            _assign_impl(
                "developer",
                "Analyze logs",
                global_folder="/tmp/global",
                output_folder="/tmp/out",
            )

        sent_message = mock_send.call_args[0][1]
        assert "[CAO Context]" in sent_message
        assert "/tmp/global" in sent_message
        assert "/tmp/out" in sent_message
        assert sent_message.endswith("Analyze logs")

    @patch("cli_agent_orchestrator.mcp_server.server.ENABLE_SENDER_ID_INJECTION", False)
    @patch("cli_agent_orchestrator.mcp_server.server._load_system_prompt")
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input_assign")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_assign_prepends_system_prompt(self, mock_create, mock_send, mock_prompt):
        """System prompt should be prepended to the message."""
        from cli_agent_orchestrator.mcp_server.server import _assign_impl

        mock_create.return_value = ("worker-6", "opencode")
        mock_send.return_value = None
        mock_prompt.return_value = "[System Prompt]\nYou are a dev.\n[/System Prompt]\n\n"

        with patch.dict(os.environ, {"CAO_TERMINAL_ID": "sup-333"}):
            _assign_impl("developer", "Fix bugs")

        sent_message = mock_send.call_args[0][1]
        assert sent_message.startswith("[System Prompt]")
        assert "You are a dev." in sent_message
        assert sent_message.endswith("Fix bugs")

    def test_build_context_header_empty_when_no_params(self):
        assert _build_context_header() == ""

    def test_build_context_header_with_all_params(self):
        header = _build_context_header(
            global_folder="/g", output_folder="/o", input_folder="/i",
            input_folders={"phase1": "/i1"}, metadata_folder="/m",
            session_root="/sr",
        )
        assert "[CAO Context]" in header
        assert "[/CAO Context]" in header
        assert "/sr" in header
        assert "/g" in header
        assert "/o" in header
        assert "/i" in header
        assert "phase1" in header
        assert "/m" in header

    def test_build_context_header_session_root_only(self):
        header = _build_context_header(session_root="/sessions/abc")
        assert "[CAO Context]" in header
        assert '"session_root": "/sessions/abc"' in header

    def test_build_context_header_session_root_appears_first_in_json(self):
        import json as _json
        header = _build_context_header(
            global_folder="/g", session_root="/sr",
        )
        # Extract JSON between [CAO Context] markers
        start = header.index("{")
        end = header.rindex("}") + 1
        ctx = _json.loads(header[start:end])
        keys = list(ctx.keys())
        assert keys[0] == "session_root"


class TestAssignSessionRoot:
    """Tests for session_root parameter in _assign_impl."""

    @patch("cli_agent_orchestrator.mcp_server.server.ENABLE_SENDER_ID_INJECTION", False)
    @patch("cli_agent_orchestrator.mcp_server.server._load_system_prompt", return_value="")
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input_assign")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_assign_with_session_root_includes_in_context(self, mock_create, mock_send, _):
        """session_root param should appear in [CAO Context] header."""
        from cli_agent_orchestrator.mcp_server.server import _assign_impl

        mock_create.return_value = ("worker-sr", "claude_code")
        mock_send.return_value = None

        with patch.dict(os.environ, {"CAO_TERMINAL_ID": "sup-sr"}):
            _assign_impl(
                "developer", "Do work",
                session_root="/sessions/test-123",
                global_folder="/sessions/test-123/global",
            )

        sent = mock_send.call_args[0][1]
        assert "[CAO Context]" in sent
        assert "/sessions/test-123" in sent
        assert '"session_root"' in sent

    @patch("cli_agent_orchestrator.mcp_server.server.ENABLE_SENDER_ID_INJECTION", False)
    @patch("cli_agent_orchestrator.mcp_server.server._load_system_prompt", return_value="")
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input_assign")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_assign_without_session_root_no_key(self, mock_create, mock_send, _):
        """When session_root is None, it should not appear in context."""
        from cli_agent_orchestrator.mcp_server.server import _assign_impl

        mock_create.return_value = ("worker-nsr", "claude_code")
        mock_send.return_value = None

        with patch.dict(os.environ, {"CAO_TERMINAL_ID": "sup-nsr"}):
            _assign_impl("developer", "Do work", global_folder="/g")

        sent = mock_send.call_args[0][1]
        assert '"session_root"' not in sent
