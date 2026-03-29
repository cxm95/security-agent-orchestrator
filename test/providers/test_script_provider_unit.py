"""Unit tests for Script provider."""

from unittest.mock import patch

import pytest

from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.script import ScriptProvider


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
class TestScriptProviderInitialization:
    @patch("cli_agent_orchestrator.providers.script.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.script.tmux_client")
    def test_initialize_success(self, mock_tmux, mock_wait_shell):
        mock_wait_shell.return_value = True

        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/usr/local/bin/my_scan.sh",
            script_args=["--target", "192.168.1.0/24"],
        )
        result = provider.initialize()

        assert result is True
        assert provider._initialized is True
        mock_wait_shell.assert_called_once()
        mock_tmux.send_keys.assert_called_once_with(
            "test-session", "window-0",
            "/usr/local/bin/my_scan.sh --target 192.168.1.0/24",
        )

    @patch("cli_agent_orchestrator.providers.script.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.script.tmux_client")
    def test_initialize_shell_timeout(self, mock_tmux, mock_wait_shell):
        mock_wait_shell.return_value = False

        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/bin/echo",
        )

        with pytest.raises(TimeoutError, match="Shell initialization timed out"):
            provider.initialize()

    @patch("cli_agent_orchestrator.providers.base.tmux_client")
    @patch("cli_agent_orchestrator.providers.script.wait_for_shell")
    @patch("cli_agent_orchestrator.providers.script.tmux_client")
    def test_initialize_with_env_vars(self, mock_tmux, mock_wait_shell, mock_base_tmux):
        mock_wait_shell.return_value = True

        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/bin/echo",
            script_args=["hello"],
            env_vars={"API_KEY": "secret", "MODE": "scan"},
        )
        result = provider.initialize()

        assert result is True
        # 2 export calls via base tmux_client
        assert mock_base_tmux.send_keys.call_count == 2
        exports = [c.args[2] for c in mock_base_tmux.send_keys.call_args_list]
        assert any("API_KEY" in t for t in exports)
        assert any("MODE" in t for t in exports)
        # 1 script command via script tmux_client
        mock_tmux.send_keys.assert_called_once_with(
            "test-session", "window-0", "/bin/echo hello"
        )

    def test_initialize_no_script_path_raises(self):
        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="",
        )
        with pytest.raises(ValueError, match="script_path must be provided"):
            provider._build_script_command()


# ---------------------------------------------------------------------------
# Command building
# ---------------------------------------------------------------------------
class TestScriptBuildCommand:
    def test_simple_command(self):
        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/usr/bin/nmap",
            script_args=["-sV", "192.168.1.1"],
        )
        cmd = provider._build_script_command()
        assert cmd == "/usr/bin/nmap -sV 192.168.1.1"

    def test_command_no_args(self):
        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/usr/bin/whoami",
        )
        cmd = provider._build_script_command()
        assert cmd == "/usr/bin/whoami"

    def test_command_with_spaces_in_args(self):
        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/bin/echo",
            script_args=["hello world", "foo bar"],
        )
        cmd = provider._build_script_command()
        assert "'hello world'" in cmd
        assert "'foo bar'" in cmd

    def test_empty_script_path_raises(self):
        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="",
        )
        with pytest.raises(ValueError, match="script_path must be provided"):
            provider._build_script_command()


# ---------------------------------------------------------------------------
# Status detection
# ---------------------------------------------------------------------------
class TestScriptProviderStatusDetection:
    @patch("cli_agent_orchestrator.providers.script.tmux_client")
    def test_completed_when_shell_prompt(self, mock_tmux):
        """COMPLETED when script finished and shell prompt visible."""
        mock_tmux.get_history.return_value = (
            "ubuntu@host:~/dir$ /usr/bin/nmap -sV 192.168.1.1\n"
            "Starting Nmap 7.92 ...\n"
            "Nmap scan report for 192.168.1.1\n"
            "PORT   STATE SERVICE\n"
            "22/tcp open  ssh\n"
            "Nmap done: 1 IP address (1 host up) scanned in 2.3s\n"
            "ubuntu@host:~/dir$\n"
        )

        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/usr/bin/nmap",
        )
        assert provider.get_status() == TerminalStatus.COMPLETED

    @patch("cli_agent_orchestrator.providers.script.tmux_client")
    def test_processing_when_no_prompt(self, mock_tmux):
        """PROCESSING when script is still running (no shell prompt)."""
        mock_tmux.get_history.return_value = (
            "ubuntu@host:~/dir$ /usr/bin/nmap -sV 192.168.1.1\n"
            "Starting Nmap 7.92 ...\n"
            "Scanning 192.168.1.1 [1000 ports]\n"
        )

        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/usr/bin/nmap",
        )
        assert provider.get_status() == TerminalStatus.PROCESSING

    @patch("cli_agent_orchestrator.providers.script.tmux_client")
    def test_error_on_empty_output(self, mock_tmux):
        mock_tmux.get_history.return_value = ""

        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/bin/echo",
        )
        assert provider.get_status() == TerminalStatus.ERROR

    @patch("cli_agent_orchestrator.providers.script.tmux_client")
    def test_completed_with_root_prompt(self, mock_tmux):
        """COMPLETED when root prompt (#) visible."""
        mock_tmux.get_history.return_value = (
            "root@host:/# ./scan.sh\n"
            "scan complete\n"
            "root@host:/#\n"
        )

        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="./scan.sh",
        )
        assert provider.get_status() == TerminalStatus.COMPLETED

    @patch("cli_agent_orchestrator.providers.script.tmux_client")
    def test_status_with_tail_lines(self, mock_tmux):
        mock_tmux.get_history.return_value = "some output\nuser@host:~$\n"

        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/bin/echo",
        )
        provider.get_status(tail_lines=50)

        mock_tmux.get_history.assert_called_once_with(
            "test-session", "window-0", tail_lines=50
        )


# ---------------------------------------------------------------------------
# Message extraction
# ---------------------------------------------------------------------------
class TestScriptMessageExtraction:
    def test_extract_full_output(self):
        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/usr/bin/nmap",
        )
        output = (
            "ubuntu@host:~/dir$ /usr/bin/nmap -sV 192.168.1.1\n"
            "Starting Nmap 7.92\n"
            "PORT   STATE SERVICE\n"
            "22/tcp open  ssh\n"
            "Nmap done: 1 host up\n"
            "ubuntu@host:~/dir$\n"
        )

        result = provider.extract_last_message_from_script(output)
        assert "Starting Nmap" in result
        assert "22/tcp open  ssh" in result
        assert "Nmap done" in result
        assert "ubuntu@host" not in result

    def test_extract_empty_raises(self):
        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/bin/echo",
        )
        with pytest.raises(ValueError, match="Empty script output"):
            provider.extract_last_message_from_script("")

    def test_extract_multiline_output(self):
        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/bin/echo",
        )
        output = (
            "user@host:~$ /bin/echo hello\n"
            "hello\n"
            "user@host:~$\n"
        )

        result = provider.extract_last_message_from_script(output)
        assert result == "hello"


# ---------------------------------------------------------------------------
# Properties & cleanup
# ---------------------------------------------------------------------------
class TestScriptProviderProperties:
    def test_paste_enter_count(self):
        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/bin/echo",
        )
        assert provider.paste_enter_count == 1

    def test_exit_cli(self):
        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/bin/echo",
        )
        assert provider.exit_cli() == "C-c"

    def test_idle_pattern_for_log(self):
        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/bin/echo",
        )
        assert provider.get_idle_pattern_for_log() == r"[$#]\s*$"

    def test_cleanup(self):
        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/bin/echo",
        )
        provider._initialized = True
        provider.cleanup()
        assert provider._initialized is False

    def test_graceful_exit_returns_none(self):
        """Script provider does not support session persistence."""
        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/bin/echo",
        )
        assert provider.graceful_exit() is None


# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------
class TestScriptEnvVars:
    def test_env_vars_from_constructor(self):
        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/bin/echo",
            env_vars={"KEY": "val"},
        )
        assert provider.env_vars == {"KEY": "val"}

    def test_env_vars_via_setter(self):
        provider = ScriptProvider(
            "test1234", "test-session", "window-0",
            script_path="/bin/echo",
        )
        provider.set_env_vars({"A": "1", "B": "2"})
        assert provider.env_vars == {"A": "1", "B": "2"}


# ---------------------------------------------------------------------------
# Provider Manager integration
# ---------------------------------------------------------------------------
class TestScriptProviderManagerIntegration:
    def test_create_script_provider_generic_raises(self):
        """create_provider('script') must direct users to create_script_provider()."""
        from cli_agent_orchestrator.providers.manager import ProviderManager

        manager = ProviderManager()
        with pytest.raises(ValueError, match="create_script_provider"):
            manager.create_provider(
                "script", "test1234", "test-session", "window-0"
            )

    def test_create_script_provider_convenience(self):
        from cli_agent_orchestrator.providers.manager import ProviderManager

        manager = ProviderManager()
        provider = manager.create_script_provider(
            "test1234", "test-session", "window-0",
            script_path="/usr/bin/nmap",
            script_args=["-sV", "10.0.0.1"],
            env_vars={"SCAN_MODE": "fast"},
        )
        assert isinstance(provider, ScriptProvider)
        assert provider._script_path == "/usr/bin/nmap"
        assert provider._script_args == ["-sV", "10.0.0.1"]
        assert provider.env_vars == {"SCAN_MODE": "fast"}
        assert manager.get_provider("test1234") is provider

    def test_script_in_provider_type_enum(self):
        from cli_agent_orchestrator.models.provider import ProviderType

        assert ProviderType.SCRIPT.value == "script"
