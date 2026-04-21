"""Tests for MCP server handoff logic."""

import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest

from cli_agent_orchestrator.mcp_server.server import _handoff_impl


class TestHandoffMessageContext:
    """Tests for handoff message context prepended to worker agents."""

    @patch("cli_agent_orchestrator.mcp_server.server._load_system_prompt", return_value="")
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_all_providers_get_handoff_context(self, mock_create, mock_wait, mock_send, _):
        """All providers should receive [CAO Handoff] prefix."""
        for provider_name in ("codex", "opencode", "claude_code", "claude_code"):
            mock_send.reset_mock()
            mock_create.return_value = ("dev-terminal-1", provider_name)
            mock_wait.side_effect = [True, True]
            mock_send.return_value = None

            with patch.dict(os.environ, {"CAO_TERMINAL_ID": "supervisor-abc123"}):
                with patch("cli_agent_orchestrator.mcp_server.server._http") as mock_http:
                    mock_response = MagicMock()
                    mock_response.json.return_value = {"output": "task done"}
                    mock_response.raise_for_status.return_value = None
                    mock_http.get.return_value = mock_response
                    mock_http.post.return_value = mock_response

                    asyncio.get_event_loop().run_until_complete(
                        _handoff_impl("developer", "Implement hello world")
                    )

            mock_send.assert_called_once()
            sent_message = mock_send.call_args[0][1]
            assert sent_message.startswith("[CAO Handoff]"), f"Failed for {provider_name}"
            assert "supervisor-abc123" in sent_message
            assert "Implement hello world" in sent_message
            assert "Do NOT use send_message" in sent_message

    @patch("cli_agent_orchestrator.mcp_server.server._load_system_prompt", return_value="")
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_handoff_context_includes_supervisor_id_from_env(
        self, mock_create, mock_wait, mock_send, _
    ):
        """Supervisor terminal ID should come from CAO_TERMINAL_ID env var."""
        mock_create.return_value = ("dev-terminal-4", "opencode")
        mock_wait.side_effect = [True, True]
        mock_send.return_value = None

        with patch.dict(os.environ, {"CAO_TERMINAL_ID": "sup-xyz789"}):
            with patch("cli_agent_orchestrator.mcp_server.server._http") as mock_http:
                mock_response = MagicMock()
                mock_response.json.return_value = {"output": "done"}
                mock_response.raise_for_status.return_value = None
                mock_http.get.return_value = mock_response
                mock_http.post.return_value = mock_response

                asyncio.get_event_loop().run_until_complete(
                    _handoff_impl("developer", "Build feature X")
                )

        sent_message = mock_send.call_args[0][1]
        assert "sup-xyz789" in sent_message
        assert "Build feature X" in sent_message

    @patch("cli_agent_orchestrator.mcp_server.server._load_system_prompt", return_value="")
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_handoff_context_fallback_when_no_env(self, mock_create, mock_wait, mock_send, _):
        """When CAO_TERMINAL_ID is not set, supervisor ID should be 'unknown'."""
        mock_create.return_value = ("dev-terminal-5", "codex")
        mock_wait.side_effect = [True, True]
        mock_send.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            with patch("cli_agent_orchestrator.mcp_server.server._http") as mock_http:
                mock_response = MagicMock()
                mock_response.json.return_value = {"output": "done"}
                mock_response.raise_for_status.return_value = None
                mock_http.get.return_value = mock_response
                mock_http.post.return_value = mock_response

                asyncio.get_event_loop().run_until_complete(_handoff_impl("developer", "Do task"))

        sent_message = mock_send.call_args[0][1]
        assert "unknown" in sent_message
        assert "[CAO Handoff]" in sent_message
        assert "Do task" in sent_message

    @patch("cli_agent_orchestrator.mcp_server.server._load_system_prompt", return_value="")
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_handoff_original_message_preserved(self, mock_create, mock_wait, mock_send, _):
        """Original message should appear in full after the handoff prefix."""
        mock_create.return_value = ("dev-terminal-6", "codex")
        mock_wait.side_effect = [True, True]
        mock_send.return_value = None

        original = "Implement the task described in /path/to/task.md. Write tests."
        with patch.dict(os.environ, {"CAO_TERMINAL_ID": "sup-111"}):
            with patch("cli_agent_orchestrator.mcp_server.server._http") as mock_http:
                mock_response = MagicMock()
                mock_response.json.return_value = {"output": "done"}
                mock_response.raise_for_status.return_value = None
                mock_http.get.return_value = mock_response
                mock_http.post.return_value = mock_response

                asyncio.get_event_loop().run_until_complete(_handoff_impl("developer", original))

        sent_message = mock_send.call_args[0][1]
        assert sent_message.endswith(original)

    @patch("cli_agent_orchestrator.mcp_server.server._load_system_prompt")
    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_handoff_prepends_system_prompt(self, mock_create, mock_wait, mock_send, mock_prompt):
        """System prompt should be prepended before [CAO Handoff]."""
        mock_create.return_value = ("dev-terminal-7", "opencode")
        mock_wait.side_effect = [True, True]
        mock_send.return_value = None
        mock_prompt.return_value = "[System Prompt]\nYou are a dev.\n[/System Prompt]\n\n"

        with patch.dict(os.environ, {"CAO_TERMINAL_ID": "sup-444"}):
            with patch("cli_agent_orchestrator.mcp_server.server._http") as mock_http:
                mock_response = MagicMock()
                mock_response.json.return_value = {"output": "done"}
                mock_response.raise_for_status.return_value = None
                mock_http.get.return_value = mock_response
                mock_http.post.return_value = mock_response

                asyncio.get_event_loop().run_until_complete(
                    _handoff_impl("developer", "Fix bugs")
                )

        sent_message = mock_send.call_args[0][1]
        # [CAO Handoff] wraps the full_message which starts with [System Prompt]
        assert "[CAO Handoff]" in sent_message
        assert "[System Prompt]" in sent_message
        assert "You are a dev." in sent_message
        assert "Fix bugs" in sent_message
