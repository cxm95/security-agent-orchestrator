"""Unit tests for OpenCode provider."""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.opencode import (
    COMPLETED_MARKER_PATTERN,
    FOOTER_PATTERN,
    IDLE_PATTERN_LOG,
    SESSION_ID_PATTERN,
    SPINNER_PATTERN,
    WELCOME_PATTERN,
    OpenCodeProvider,
    ProviderError,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(filename: str) -> str:
    with open(FIXTURES_DIR / filename, "r") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
class TestOpenCodeProviderInitialization:
    @patch("cli_agent_orchestrator.providers.opencode.wait_until_status")
    @patch("cli_agent_orchestrator.providers.opencode.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_initialize_success(self, mock_tmux, mock_wait_shell, mock_wait_status):
        mock_wait_shell.return_value = True
        mock_wait_status.return_value = True

        provider = OpenCodeProvider("test1234", "test-session", "window-0", None)
        result = provider.initialize()

        assert result is True
        assert provider._initialized is True
        mock_wait_shell.assert_called_once()
        # The command should include inline config env vars + opencode
        sent_cmd = mock_tmux.send_keys.call_args.args[2]
        assert "OPENCODE_CONFIG_CONTENT=" in sent_cmd
        assert '"permission": "allow"' in sent_cmd
        assert "OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS=" in sent_cmd
        assert sent_cmd.endswith("opencode")
        mock_wait_status.assert_called_once()

    @patch("cli_agent_orchestrator.providers.opencode.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_initialize_shell_timeout(self, mock_tmux, mock_wait_shell):
        mock_wait_shell.return_value = False

        provider = OpenCodeProvider("test1234", "test-session", "window-0", None)

        with pytest.raises(TimeoutError, match="Shell initialization timed out"):
            provider.initialize()

    @patch("cli_agent_orchestrator.providers.opencode.wait_until_status")
    @patch("cli_agent_orchestrator.providers.opencode.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_initialize_opencode_timeout(self, mock_tmux, mock_wait_shell, mock_wait_status):
        mock_wait_shell.return_value = True
        mock_wait_status.return_value = False

        provider = OpenCodeProvider("test1234", "test-session", "window-0", None)

        with pytest.raises(TimeoutError, match="OpenCode initialization timed out"):
            provider.initialize()

    @patch("cli_agent_orchestrator.providers.opencode.wait_until_status")
    @patch("cli_agent_orchestrator.providers.opencode.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    @patch("cli_agent_orchestrator.providers.base.tmux_client")
    def test_initialize_with_env_vars(self, mock_base_tmux, mock_tmux, mock_wait_shell, mock_wait_status):
        """Env vars are exported before launching opencode."""
        mock_wait_shell.return_value = True
        mock_wait_status.return_value = True

        provider = OpenCodeProvider(
            "test1234", "test-session", "window-0", None,
            env_vars={"OPENAI_API_KEY": "sk-test123", "MY_VAR": "hello world"},
        )
        result = provider.initialize()

        assert result is True
        # base tmux_client gets the export calls
        assert mock_base_tmux.send_keys.call_count == 2
        export_texts = [c.args[2] for c in mock_base_tmux.send_keys.call_args_list]
        assert any("OPENAI_API_KEY" in t and "sk-test123" in t for t in export_texts)
        assert any("MY_VAR" in t for t in export_texts)
        # opencode tmux_client gets the opencode command (with inline config env)
        sent_cmd = mock_tmux.send_keys.call_args.args[2]
        assert "opencode" in sent_cmd
        assert "OPENCODE_CONFIG_CONTENT=" in sent_cmd

    @patch("cli_agent_orchestrator.providers.opencode.wait_until_status")
    @patch("cli_agent_orchestrator.providers.opencode.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_initialize_without_env_vars(self, mock_tmux, mock_wait_shell, mock_wait_status):
        """No export commands when env_vars is empty."""
        mock_wait_shell.return_value = True
        mock_wait_status.return_value = True

        provider = OpenCodeProvider("test1234", "test-session", "window-0", None)
        provider.initialize()

        # Only the opencode command
        assert mock_tmux.send_keys.call_count == 1


# ---------------------------------------------------------------------------
# Build command
# ---------------------------------------------------------------------------
class TestOpenCodeBuildCommand:
    def test_build_command_no_profile(self):
        provider = OpenCodeProvider("test1234", "test-session", "window-0", None)
        command = provider._build_opencode_command()
        # Should contain inline config env + opencode, no --yolo
        assert "OPENCODE_CONFIG_CONTENT=" in command
        assert '"permission": "allow"' in command
        assert "OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS=43200000" in command
        assert command.endswith("opencode")
        assert "--yolo" not in command

    @patch("cli_agent_orchestrator.providers.opencode.load_agent_profile")
    def test_build_command_with_model(self, mock_load_profile):
        mock_profile = MagicMock()
        mock_profile.model = "closeai/glm-5"
        mock_profile.system_prompt = None
        mock_load_profile.return_value = mock_profile

        provider = OpenCodeProvider("test1234", "test-session", "window-0", "my_agent")
        command = provider._build_opencode_command()

        mock_load_profile.assert_called_once_with("my_agent")
        assert "-m closeai/glm-5" in command

    @patch("cli_agent_orchestrator.providers.opencode.load_agent_profile")
    def test_build_command_system_prompt_ignored_with_warning(self, mock_load_profile):
        """OpenCode TUI doesn't support --prompt; system_prompt should be ignored."""
        mock_profile = MagicMock()
        mock_profile.model = None
        mock_profile.system_prompt = "You are a security expert."
        mock_load_profile.return_value = mock_profile

        provider = OpenCodeProvider("test1234", "test-session", "window-0", "sec_agent")
        with patch("cli_agent_orchestrator.providers.opencode.logger") as mock_logger:
            command = provider._build_opencode_command()

        # --prompt should NOT be in the command
        assert "--prompt" not in command
        assert "security expert" not in command
        # Should end with bare 'opencode' (no prompt arg)
        assert command.endswith("opencode")
        # Should have logged a warning
        mock_logger.warning.assert_called_once()

    @patch("cli_agent_orchestrator.providers.opencode.load_agent_profile")
    def test_build_command_no_model(self, mock_load_profile):
        mock_profile = MagicMock()
        mock_profile.model = None
        mock_profile.system_prompt = None
        mock_load_profile.return_value = mock_profile

        provider = OpenCodeProvider("test1234", "test-session", "window-0", "my_agent")
        command = provider._build_opencode_command()

        assert command.endswith("opencode")
        assert "-m" not in command

    def test_build_command_no_default_config_when_overridden(self):
        """If caller sets OPENCODE_CONFIG_CONTENT in env_vars, don't double-set."""
        provider = OpenCodeProvider("test1234", "test-session", "window-0", None)
        provider.set_env_vars({"OPENCODE_CONFIG_CONTENT": '{"custom":"config"}'})
        command = provider._build_opencode_command()
        # Should NOT contain inline OPENCODE_CONFIG_CONTENT (caller will export it)
        assert "OPENCODE_CONFIG_CONTENT=" not in command
        # But should still have the bash timeout
        assert "OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS=" in command
    @patch("cli_agent_orchestrator.providers.opencode.load_agent_profile")
    def test_build_command_profile_load_failure(self, mock_load_profile):
        mock_load_profile.side_effect = RuntimeError("Profile not found")

        provider = OpenCodeProvider("test1234", "test-session", "window-0", "bad_agent")

        with pytest.raises(ProviderError, match="Failed to load agent profile"):
            provider._build_opencode_command()


# ---------------------------------------------------------------------------
# Status detection
# ---------------------------------------------------------------------------
class TestOpenCodeProviderStatusDetection:
    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_get_status_idle(self, mock_tmux):
        mock_tmux.get_history.return_value = load_fixture("opencode_idle_output.txt")

        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.IDLE

    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_get_status_completed(self, mock_tmux):
        mock_tmux.get_history.return_value = load_fixture("opencode_completed_output.txt")

        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        provider._input_received = True
        status = provider.get_status()

        assert status == TerminalStatus.COMPLETED

    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_get_status_processing(self, mock_tmux):
        mock_tmux.get_history.return_value = load_fixture("opencode_processing_output.txt")

        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_get_status_error_empty_output(self, mock_tmux):
        mock_tmux.get_history.return_value = ""

        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.ERROR

    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_get_status_with_tail_lines(self, mock_tmux):
        mock_tmux.get_history.return_value = load_fixture("opencode_idle_output.txt")

        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        status = provider.get_status(tail_lines=50)

        assert status == TerminalStatus.IDLE
        mock_tmux.get_history.assert_called_once_with(
            "test-session", "window-0", tail_lines=50
        )

    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_get_status_processing_spinner(self, mock_tmux):
        """PROCESSING when spinner with 'esc interrupt' at bottom."""
        mock_tmux.get_history.return_value = (
            "  ┃  explain this code\n"
            "  ┃\n"
            "\n"
            "  ┃  Build  model anthropic      /project\n"
            "  ╹▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀\n"
            "  ⬝ ⬝ ⬝ ■ ⬝ ⬝                 esc interrupt\n"
        )

        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_get_status_thinking_is_processing(self, mock_tmux):
        """PROCESSING when Thinking block is present without footer."""
        mock_tmux.get_history.return_value = (
            "  ┃  what is recursion?\n"
            "  ┃\n"
            "\n"
            "  ┃  Thinking: I need to explain recursion clearly...\n"
        )

        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_get_status_completed_with_input_received(self, mock_tmux):
        """COMPLETED when build marker + footer and input_received is True."""
        mock_tmux.get_history.return_value = (
            "  ┃  explain fibonacci\n"
            "  ┃\n"
            "\n"
            "  The sequence starts with 0 and 1.\n"
            "\n"
            "  ▣  Build · claude-sonnet-4 · 3.1s\n"
            "\n"
            "  ┃\n"
            "  ┃  Build  claude-sonnet-4 anthropic      /project\n"
            "  ╹▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀\n"
            "  tab agents  ctrl+p commands                  OpenCode 1.3.3\n"
        )

        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        provider._input_received = True
        status = provider.get_status()

        assert status == TerminalStatus.COMPLETED

    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_get_status_idle_when_completed_but_no_input(self, mock_tmux):
        """IDLE when build marker + footer but _input_received is False (initial state)."""
        mock_tmux.get_history.return_value = (
            "  ┃  explain fibonacci\n"
            "  ┃\n"
            "\n"
            "  The sequence starts with 0 and 1.\n"
            "\n"
            "  ▣  Build · claude-sonnet-4 · 3.1s\n"
            "\n"
            "  ┃\n"
            "  ┃  Build  claude-sonnet-4 anthropic      /project\n"
            "  ╹▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀\n"
            "  tab agents  ctrl+p commands                  OpenCode 1.3.3\n"
        )

        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        provider._input_received = False
        status = provider.get_status()

        assert status == TerminalStatus.IDLE

    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_get_status_idle_footer_no_build(self, mock_tmux):
        """IDLE when footer visible but no build marker (fresh start after welcome)."""
        mock_tmux.get_history.return_value = (
            "  ┃\n"
            "  ┃\n"
            "  ┃  Build  model anthropic      /project\n"
            "  ╹▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀\n"
            "  tab agents  ctrl+p commands                  OpenCode 1.3.3\n"
        )

        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.IDLE

    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_get_status_processing_build_without_timing(self, mock_tmux):
        """PROCESSING when build marker exists without timing (still running)."""
        mock_tmux.get_history.return_value = (
            "  ┃  do something\n"
            "  ┃\n"
            "\n"
            "  ▣  Build · claude-sonnet-4\n"
            "\n"
            "  ┃\n"
            "  ┃  Build  claude-sonnet-4 anthropic      /project\n"
            "  ╹▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀\n"
            "  tab agents  ctrl+p commands                  OpenCode 1.3.3\n"
        )

        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        status = provider.get_status()

        assert status == TerminalStatus.PROCESSING


# ---------------------------------------------------------------------------
# Message extraction
# ---------------------------------------------------------------------------
class TestOpenCodeMessageExtraction:
    def test_extract_simple_response(self):
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        output = load_fixture("opencode_completed_output.txt")

        provider._input_received = True
        result = provider.extract_last_message_from_script(output)

        assert "Fibonacci sequence" in result
        assert "F(n) = F(n-1) + F(n-2)" in result
        assert "F(0) = 0" in result

    def test_extract_complex_response(self):
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        output = load_fixture("opencode_complex_response.txt")

        result = provider.extract_last_message_from_script(output)

        assert "lru_cache" in result
        assert "def fibonacci" in result
        assert "O(n)" in result or "O(2^n)" in result

    def test_extract_no_user_message_raises(self):
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        output = "Just some random text\nwith no markers\n"

        with pytest.raises(ValueError, match="No user message found"):
            provider.extract_last_message_from_script(output)

    def test_extract_empty_response_raises(self):
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        # User message immediately followed by completed marker, no content
        output = (
            "  ┃  hello\n"
            "  ┃\n"
            "  ▣  Build · model · 0.1s\n"
        )

        with pytest.raises(ValueError, match="Empty OpenCode response"):
            provider.extract_last_message_from_script(output)

    def test_extract_response_with_thinking_block(self):
        """Thinking blocks should be included in extraction (they precede the response)."""
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        output = (
            "  ┃  what is 2+2\n"
            "  ┃\n"
            "\n"
            "  ┃  Thinking: simple arithmetic...\n"
            "\n"
            "  The answer is 4.\n"
            "\n"
            "  ▣  Build · model · 1.0s\n"
        )

        result = provider.extract_last_message_from_script(output)
        assert "4" in result

    def test_extract_skips_user_message(self):
        """Extracted text should not include the user's message."""
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        output = (
            "  ┃  user question here\n"
            "  ┃\n"
            "\n"
            "  Agent response here.\n"
            "\n"
            "  ▣  Build · model · 2.0s\n"
        )

        result = provider.extract_last_message_from_script(output)
        assert "user question" not in result
        assert "Agent response" in result

    def test_extract_multi_turn_uses_last_message(self):
        """When multiple user messages exist, extract response for the last one."""
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        output = (
            "  ┃  first question\n"
            "  ┃\n"
            "\n"
            "  First answer.\n"
            "\n"
            "  ▣  Build · model · 1.0s\n"
            "\n"
            "  ┃  second question\n"
            "  ┃\n"
            "\n"
            "  Second answer.\n"
            "\n"
            "  ▣  Build · model · 2.0s\n"
        )

        result = provider.extract_last_message_from_script(output)
        assert "Second answer" in result

    def test_extract_response_without_completed_marker(self):
        """Falls back to footer boundary when no completed marker."""
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        output = (
            "  ┃  explain something\n"
            "  ┃\n"
            "\n"
            "  Here is my explanation.\n"
            "  It covers the topic well.\n"
            "\n"
            "  tab agents  ctrl+p commands\n"
        )

        result = provider.extract_last_message_from_script(output)
        assert "explanation" in result
        assert "tab agents" not in result


# ---------------------------------------------------------------------------
# Properties and utility methods
# ---------------------------------------------------------------------------
class TestOpenCodeProviderProperties:
    def test_paste_enter_count(self):
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        assert provider.paste_enter_count == 1

    def test_exit_cli(self):
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        assert provider.exit_cli() == "C-c"

    def test_get_idle_pattern_for_log(self):
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        pattern = provider.get_idle_pattern_for_log()
        assert pattern == IDLE_PATTERN_LOG

    def test_mark_input_received(self):
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        assert provider._input_received is False
        provider.mark_input_received()
        assert provider._input_received is True

    def test_cleanup(self):
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        provider._initialized = True
        provider._input_received = True
        provider.cleanup()
        assert provider._initialized is False
        assert provider._input_received is False


# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------
class TestOpenCodeEnvVars:
    def test_default_env_vars_empty(self):
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        assert provider.env_vars == {}

    def test_set_env_vars_via_constructor(self):
        provider = OpenCodeProvider(
            "test1234", "test-session", "window-0",
            env_vars={"KEY": "value"},
        )
        assert provider.env_vars == {"KEY": "value"}

    def test_set_env_vars_via_method(self):
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        provider.set_env_vars({"FOO": "bar", "BAZ": "qux"})
        assert provider.env_vars == {"FOO": "bar", "BAZ": "qux"}

    def test_set_env_vars_replaces(self):
        provider = OpenCodeProvider(
            "test1234", "test-session", "window-0",
            env_vars={"OLD": "value"},
        )
        provider.set_env_vars({"NEW": "value2"})
        assert "OLD" not in provider.env_vars
        assert provider.env_vars == {"NEW": "value2"}

    @patch("cli_agent_orchestrator.providers.base.tmux_client")
    def test_apply_env_vars_sends_exports(self, mock_tmux):
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        provider.set_env_vars({"API_KEY": "secret", "MODE": "test"})
        provider._apply_env_vars()

        assert mock_tmux.send_keys.call_count == 2
        export_texts = [c.args[2] for c in mock_tmux.send_keys.call_args_list]
        assert any("API_KEY" in t and "secret" in t for t in export_texts)
        assert any("MODE" in t and "test" in t for t in export_texts)

    @patch("cli_agent_orchestrator.providers.base.tmux_client")
    def test_apply_env_vars_quotes_values(self, mock_tmux):
        """Values with spaces/special chars are shell-quoted."""
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        provider.set_env_vars({"MSG": "hello world"})
        provider._apply_env_vars()

        export_cmd = mock_tmux.send_keys.call_args_list[0].args[2]
        # shlex.quote wraps in single quotes
        assert "MSG=" in export_cmd
        assert "'hello world'" in export_cmd

    @patch("cli_agent_orchestrator.providers.base.tmux_client")
    def test_apply_env_vars_empty_does_nothing(self, mock_tmux):
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        provider._apply_env_vars()
        mock_tmux.send_keys.assert_not_called()

    def test_apply_env_vars_rejects_invalid_keys(self):
        """Keys with shell metacharacters must be rejected to prevent injection."""
        provider = OpenCodeProvider("test1234", "test-session", "window-0")

        bad_keys = [
            "FOO;rm -rf /",     # semicolon injection
            "VAR&&echo pwned",  # && injection
            "VAR|cat /etc/p",   # pipe injection
            "123VAR",           # starts with digit
            "VAR-NAME",         # hyphen
            "VAR NAME",         # space
            "",                 # empty
        ]
        for bad_key in bad_keys:
            provider.set_env_vars({bad_key: "safe_value"})
            with pytest.raises(ValueError, match="Invalid environment variable name"):
                provider._apply_env_vars()

    @patch("cli_agent_orchestrator.providers.base.tmux_client")
    def test_apply_env_vars_accepts_valid_keys(self, mock_tmux):
        """Underscores, uppercase, digits (non-leading) are all valid."""
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        provider.set_env_vars({
            "OPENCODE_YOLO": "true",
            "_private": "val",
            "A1B2C3": "ok",
        })
        provider._apply_env_vars()  # should not raise
        assert mock_tmux.send_keys.call_count == 3


# ---------------------------------------------------------------------------
# Session ID extraction (graceful_exit)
# ---------------------------------------------------------------------------
class TestOpenCodeSessionId:
    def test_extract_session_id_from_output(self):
        output = (
            "ubuntu@host:/project$ opencode\n"
            "\n"
            "  Session   Greeting\n"
            "  Continue  opencode -s ses_2c57b2436ffepiOds7uuqq2hHd\n"
            "\n"
            "ubuntu@host:/project$\n"
        )

        session_id = OpenCodeProvider.extract_session_id(output)
        assert session_id == "ses_2c57b2436ffepiOds7uuqq2hHd"

    def test_extract_session_id_with_ansi(self):
        output = (
            "\x1b[32mSession\x1b[0m   Greeting\n"
            "\x1b[34mContinue\x1b[0m  opencode -s ses_abc123def456\n"
        )

        session_id = OpenCodeProvider.extract_session_id(output)
        assert session_id == "ses_abc123def456"

    def test_extract_session_id_not_found(self):
        output = "ubuntu@host:/project$ echo hello\nhello\n"
        session_id = OpenCodeProvider.extract_session_id(output)
        assert session_id is None

    def test_extract_session_id_empty_output(self):
        assert OpenCodeProvider.extract_session_id("") is None
        assert OpenCodeProvider.extract_session_id(None) is None

    @patch("cli_agent_orchestrator.providers.opencode.wait_for_shell", return_value=True)
    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_graceful_exit_success(self, mock_tmux, mock_wait_shell):
        mock_tmux.get_history.return_value = (
            "  Session   Greeting\n"
            "  Continue  opencode -s ses_test_session_id_here\n"
            "ubuntu@host:~$\n"
        )

        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        provider._initialized = True

        session_id = provider.graceful_exit()

        assert session_id == "ses_test_session_id_here"
        assert provider._initialized is False
        mock_tmux.send_special_key.assert_called_once_with(
            "test-session", "window-0", "C-c"
        )
        mock_wait_shell.assert_called_once_with(
            mock_tmux, "test-session", "window-0", timeout=10.0
        )
        mock_tmux.get_history.assert_called_once_with(
            "test-session", "window-0", tail_lines=30
        )

    @patch("cli_agent_orchestrator.providers.opencode.wait_for_shell", return_value=True)
    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_graceful_exit_no_session_id(self, mock_tmux, mock_wait_shell):
        """Returns None when no session ID pattern found after exit."""
        mock_tmux.get_history.return_value = "ubuntu@host:~$\n"

        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        provider._initialized = True

        session_id = provider.graceful_exit()

        assert session_id is None
        assert provider._initialized is False

    @patch("cli_agent_orchestrator.providers.opencode.wait_for_shell", return_value=False)
    @patch("cli_agent_orchestrator.providers.opencode.tmux_client")
    def test_graceful_exit_timeout(self, mock_tmux, mock_wait_shell):
        """Returns None if shell prompt doesn't appear within timeout."""
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        provider._initialized = True

        session_id = provider.graceful_exit()

        assert session_id is None
        assert provider._initialized is False
        mock_tmux.send_special_key.assert_called_once()
        # get_history should NOT be called if wait_for_shell times out
        mock_tmux.get_history.assert_not_called()

    def test_base_provider_graceful_exit_returns_none(self):
        """BaseProvider.graceful_exit() returns None by default."""
        from cli_agent_orchestrator.providers.base import BaseProvider

        # Can't instantiate ABC directly, test via OpenCode's super
        provider = OpenCodeProvider("test1234", "test-session", "window-0")
        # Call the base class method explicitly
        result = BaseProvider.graceful_exit(provider)
        assert result is None


# ---------------------------------------------------------------------------
# Pattern matching validation
# ---------------------------------------------------------------------------
class TestOpenCodePatterns:
    """Validate regex patterns against representative strings."""

    def test_welcome_pattern(self):
        import re
        assert re.search(WELCOME_PATTERN, "                    Ask anything...                    ")
        assert not re.search(WELCOME_PATTERN, "some other text")

    def test_spinner_pattern(self):
        import re
        assert re.search(SPINNER_PATTERN, "⬝ ⬝ ⬝ ■ ⬝           esc interrupt")
        assert re.search(SPINNER_PATTERN, "  esc  interrupt  ")
        assert not re.search(SPINNER_PATTERN, "tab agents ctrl+p commands")

    def test_completed_marker_pattern(self):
        import re
        assert re.search(COMPLETED_MARKER_PATTERN, "▣  Build · claude-sonnet-4 · 5.2s")
        assert re.search(COMPLETED_MARKER_PATTERN, "  ▣  Build · gpt-4o · 12.8s  ")
        assert not re.search(COMPLETED_MARKER_PATTERN, "▣  Build · gpt-4o")  # no timing

    def test_footer_pattern(self):
        import re
        assert re.search(FOOTER_PATTERN, "tab agents  ctrl+p commands")
        assert re.search(FOOTER_PATTERN, "  tab  agents  ctrl+p  commands  OpenCode 1.3.3")
        assert not re.search(FOOTER_PATTERN, "some random footer")

    def test_session_id_pattern(self):
        import re
        match = re.search(SESSION_ID_PATTERN, "Continue  opencode -s ses_2c57b2436ffepiOds7uuqq2hHd")
        assert match
        assert match.group(1) == "ses_2c57b2436ffepiOds7uuqq2hHd"


# ---------------------------------------------------------------------------
# Provider Manager integration
# ---------------------------------------------------------------------------
class TestOpenCodeProviderManagerIntegration:
    def test_create_opencode_provider(self):
        from cli_agent_orchestrator.providers.manager import ProviderManager

        manager = ProviderManager()
        provider = manager.create_provider(
            "opencode", "test1234", "test-session", "window-0"
        )

        assert isinstance(provider, OpenCodeProvider)
        assert manager.get_provider("test1234") is provider

    def test_create_opencode_with_env_vars(self):
        from cli_agent_orchestrator.providers.manager import ProviderManager

        manager = ProviderManager()
        provider = manager.create_provider(
            "opencode", "test1234", "test-session", "window-0",
            env_vars={"MY_KEY": "my_value"},
        )

        assert isinstance(provider, OpenCodeProvider)
        assert provider.env_vars == {"MY_KEY": "my_value"}

    def test_opencode_in_provider_type_enum(self):
        from cli_agent_orchestrator.models.provider import ProviderType

        assert ProviderType.OPENCODE.value == "opencode"
