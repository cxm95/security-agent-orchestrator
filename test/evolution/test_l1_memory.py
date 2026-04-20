"""Tests for L1 memory / Root Orchestrator features.

Covers:
- config.py YAML loader
- clother_closeai / clother_minimax_cn --yolo flag
- GET /evolution/index & POST /evolution/index/rebuild routes
- _notify_root_rebuild_index inbox flow
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

_test_evo_dir = tempfile.mkdtemp()


@pytest.fixture(autouse=True, scope="module")
def _setup_evo_dir():
    import cli_agent_orchestrator.api.evolution_routes as evo_mod

    original = evo_mod.EVOLUTION_DIR
    evo_mod.EVOLUTION_DIR = _test_evo_dir
    evo_mod.ensure_evolution_repo()
    yield
    evo_mod.EVOLUTION_DIR = original


@pytest.fixture(scope="module")
def client():
    from fastapi import FastAPI
    from cli_agent_orchestrator.api.evolution_routes import router

    test_app = FastAPI()
    test_app.include_router(router)
    return TestClient(test_app)


# ── Config loader ────────────────────────────────────────────────────────


class TestConfigLoader:
    """Test YAML config loading for Root Orchestrator settings."""

    def test_defaults_when_no_file(self, tmp_path):
        with patch("cli_agent_orchestrator.config._CONFIG_PATH", tmp_path / "nonexistent.yaml"):
            from cli_agent_orchestrator.config import load_config

            cfg = load_config()
            assert cfg.root_orchestrator.enabled is True
            assert cfg.root_orchestrator.provider == "clother_closeai"
            assert cfg.root_orchestrator.profile == "root_orchestrator"
            assert cfg.root_orchestrator.session == "ROOT"

    def test_custom_yaml(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "root_orchestrator:\n"
            "  enabled: false\n"
            "  provider: claude_code\n"
            "  session: my-root\n"
        )
        with patch("cli_agent_orchestrator.config._CONFIG_PATH", config_file):
            from cli_agent_orchestrator.config import load_config

            cfg = load_config()
            assert cfg.root_orchestrator.enabled is False
            assert cfg.root_orchestrator.provider == "claude_code"
            assert cfg.root_orchestrator.session == "my-root"
            # profile keeps default when not specified
            assert cfg.root_orchestrator.profile == "root_orchestrator"

    def test_partial_yaml(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("root_orchestrator:\n  session: custom\n")
        with patch("cli_agent_orchestrator.config._CONFIG_PATH", config_file):
            from cli_agent_orchestrator.config import load_config

            cfg = load_config()
            assert cfg.root_orchestrator.session == "custom"
            assert cfg.root_orchestrator.enabled is True

    def test_invalid_yaml(self, tmp_path):
        config_file = tmp_path / "bad.yaml"
        config_file.write_text(": : : invalid yaml {{{}}")
        with patch("cli_agent_orchestrator.config._CONFIG_PATH", config_file):
            from cli_agent_orchestrator.config import load_config

            # Should return defaults, not crash
            cfg = load_config()
            assert cfg.root_orchestrator.enabled is True

    def test_empty_yaml(self, tmp_path):
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")
        with patch("cli_agent_orchestrator.config._CONFIG_PATH", config_file):
            from cli_agent_orchestrator.config import load_config

            cfg = load_config()
            assert cfg.root_orchestrator.enabled is True


# ── Clother providers: --yolo flag ───────────────────────────────────────


class TestClotherProviders:
    """Test that clother providers use --yolo instead of --dangerously-skip-permissions."""

    def test_clother_closeai_yolo_flag(self):
        from cli_agent_orchestrator.providers.clother_closeai import ClotherCloseaiProvider

        p = ClotherCloseaiProvider("tid", "sess", "win", None)
        cmd = p._build_claude_command()

        assert "--yolo" in cmd, f"Expected --yolo in command: {cmd}"
        assert "--dangerously-skip-permissions" not in cmd, f"Unexpected old flag: {cmd}"
        assert "clother-closeai" in cmd, f"Expected clother-closeai binary: {cmd}"
        assert "claude " not in cmd.split(";")[-1], f"Should not have 'claude' command: {cmd}"

    def test_clother_minimax_cn_yolo_flag(self):
        from cli_agent_orchestrator.providers.clother_minimax_cn import ClotherMinimaxCnProvider

        p = ClotherMinimaxCnProvider("tid", "sess", "win", None)
        cmd = p._build_claude_command()

        assert "--yolo" in cmd
        assert "--dangerously-skip-permissions" not in cmd
        assert "clother-minimax-cn" in cmd

    def test_claude_code_keeps_dangerously_skip(self):
        """Claude Code itself should still use --dangerously-skip-permissions."""
        from cli_agent_orchestrator.providers.claude_code import ClaudeCodeProvider

        p = ClaudeCodeProvider("tid", "sess", "win", None)
        cmd = p._build_claude_command()

        assert "--dangerously-skip-permissions" in cmd
        assert "--yolo" not in cmd

    def test_provider_type_enum(self):
        from cli_agent_orchestrator.models.provider import ProviderType

        assert ProviderType.CLOTHER_CLOSEAI.value == "clother_closeai"
        assert ProviderType.CLOTHER_MINIMAX_CN.value == "clother_minimax_cn"

    def test_provider_manager_creates_clother_closeai(self):
        from cli_agent_orchestrator.providers.manager import ProviderManager
        from cli_agent_orchestrator.providers.clother_closeai import ClotherCloseaiProvider

        pm = ProviderManager()
        p = pm.create_provider("clother_closeai", "t1", "s1", "w1")
        assert isinstance(p, ClotherCloseaiProvider)


# ── L1 Knowledge Index routes ────────────────────────────────────────────


class TestL1IndexRoutes:
    """Test GET /evolution/index and POST /evolution/index/rebuild."""

    def test_get_index_no_file(self, client):
        """When index.md doesn't exist, return default placeholder."""
        r = client.get("/evolution/index")
        assert r.status_code == 200
        assert "No index available yet" in r.text

    def test_get_index_with_content(self, client):
        """When index.md exists with real content, return it."""
        index_path = Path(_test_evo_dir) / "index.md"
        index_path.write_text("# Knowledge Index\n\n## Vulns (3 notes)\n- note:1 — XSS finding\n")
        try:
            r = client.get("/evolution/index")
            assert r.status_code == 200
            assert "Vulns" in r.text
            assert "XSS finding" in r.text
        finally:
            index_path.unlink(missing_ok=True)

    def test_rebuild_index_no_root(self, client):
        """POST /evolution/index/rebuild fails when root orchestrator not available."""
        with patch("cli_agent_orchestrator.api.main.app") as mock_app:
            mock_app.state = MagicMock()
            mock_app.state.root_terminal_id = None
            r = client.post("/evolution/index/rebuild")
            assert r.status_code == 503

    def test_rebuild_index_with_root(self, client):
        """POST /evolution/index/rebuild sends inbox message and attempts delivery."""
        mock_state = MagicMock()
        mock_state.root_terminal_id = "root-tid-123"

        with patch("cli_agent_orchestrator.api.main.app") as mock_app, \
             patch("cli_agent_orchestrator.api.evolution_routes.create_inbox_message") as mock_inbox, \
             patch("cli_agent_orchestrator.api.evolution_routes.inbox_service") as mock_isvc:
            mock_app.state = mock_state
            r = client.post("/evolution/index/rebuild")
            assert r.status_code == 200
            assert r.json()["status"] == "rebuild requested"
            mock_inbox.assert_called_once()
            call_args = mock_inbox.call_args
            msg = call_args.kwargs.get("message") or call_args[1].get("message", "")
            assert "rebuild-index" in msg
            # Verify immediate delivery was attempted
            mock_isvc.check_and_send_pending_messages.assert_called_once_with("root-tid-123")


# ── Checkpoint → Root Orchestrator notification ──────────────────────────


class TestCheckpointNotification:
    """Test that _on_checkpoint_commit notifies root orch when notes change."""

    def test_notify_on_note_change(self):
        from cli_agent_orchestrator.api.evolution_routes import _notify_root_rebuild_index

        with patch("cli_agent_orchestrator.api.main.app") as mock_app, \
             patch("cli_agent_orchestrator.api.evolution_routes.create_inbox_message") as mock_inbox, \
             patch("cli_agent_orchestrator.api.evolution_routes.inbox_service") as mock_isvc:
            mock_app.state = MagicMock()
            mock_app.state.root_terminal_id = "root-tid"

            _notify_root_rebuild_index(["notes/vuln-1.md", "notes/vuln-2.md"])

            mock_inbox.assert_called_once()
            args = mock_inbox.call_args
            msg = args.kwargs.get("message") or args[1].get("message", "")
            assert "rebuild-index" in msg
            assert "vuln-1.md" in msg
            # Verify immediate delivery was attempted
            mock_isvc.check_and_send_pending_messages.assert_called_once_with("root-tid")

    def test_notify_skipped_when_no_root(self):
        from cli_agent_orchestrator.api.evolution_routes import _notify_root_rebuild_index

        with patch("cli_agent_orchestrator.api.main.app") as mock_app, \
             patch("cli_agent_orchestrator.api.evolution_routes.create_inbox_message") as mock_inbox:
            mock_app.state = MagicMock()
            mock_app.state.root_terminal_id = None

            _notify_root_rebuild_index(["notes/test.md"])

            mock_inbox.assert_not_called()

    def test_on_checkpoint_commit_notifies_for_notes(self):
        """_on_checkpoint_commit triggers rebuild when notes/ files change."""
        from cli_agent_orchestrator.api.evolution_routes import _on_checkpoint_commit

        with patch("cli_agent_orchestrator.api.evolution_routes._notify_root_rebuild_index") as mock_notify:
            _on_checkpoint_commit(
                _test_evo_dir,
                ["notes/finding.md", "skills/scanner/SKILL.md", "attempts/a1.json"],
            )
            mock_notify.assert_called_once_with(["notes/finding.md"])

    def test_on_checkpoint_commit_skips_when_no_notes(self):
        """_on_checkpoint_commit does NOT trigger rebuild for non-note changes."""
        from cli_agent_orchestrator.api.evolution_routes import _on_checkpoint_commit

        with patch("cli_agent_orchestrator.api.evolution_routes._notify_root_rebuild_index") as mock_notify:
            _on_checkpoint_commit(
                _test_evo_dir,
                ["skills/scanner/SKILL.md", "attempts/a1.json"],
            )
            mock_notify.assert_not_called()


# ── Root Orchestrator agent profile ──────────────────────────────────────


class TestRootOrchestratorProfile:
    """Verify the root_orchestrator.md agent profile is loadable."""

    def test_profile_loads(self):
        from cli_agent_orchestrator.utils.agent_profiles import load_agent_profile

        profile = load_agent_profile("root_orchestrator")
        assert profile is not None
        assert profile.name == "root_orchestrator"
        assert "L1" in profile.system_prompt
        assert "index.md" in profile.system_prompt

    def test_profile_has_no_mcp(self):
        from cli_agent_orchestrator.utils.agent_profiles import load_agent_profile

        profile = load_agent_profile("root_orchestrator")
        assert not profile.mcpServers


# ── Root Orchestrator lifecycle ──────────────────────────────────────────


class TestRootOrchestratorLifecycle:
    """Test _start_root_orchestrator with config integration."""

    def test_disabled_in_config(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("root_orchestrator:\n  enabled: false\n")

        with patch("cli_agent_orchestrator.config._CONFIG_PATH", config_file):
            from cli_agent_orchestrator.api.main import _start_root_orchestrator

            result = _start_root_orchestrator()
            assert result is None

    def test_start_uses_config_values(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "root_orchestrator:\n"
            "  provider: claude_code\n"
            "  session: my-session\n"
        )

        with patch("cli_agent_orchestrator.config._CONFIG_PATH", config_file), \
             patch("cli_agent_orchestrator.api.main.terminal_service") as mock_ts:
            mock_terminal = MagicMock()
            mock_terminal.id = "root-123"
            mock_ts.create_terminal.return_value = mock_terminal

            from cli_agent_orchestrator.api.main import _start_root_orchestrator

            result = _start_root_orchestrator()
            assert result == "root-123"
            mock_ts.create_terminal.assert_called_once_with(
                provider="claude_code",
                agent_profile="root_orchestrator",
                session_name="my-session",
                new_session=True,
                send_system_prompt=True,
                working_directory=str(Path.home()),
                env_vars={"CAO_HOOKS_ENABLED": "0"},
                bare=True,
            )

    def test_start_failure_returns_none(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("root_orchestrator:\n  enabled: true\n")

        with patch("cli_agent_orchestrator.config._CONFIG_PATH", config_file), \
             patch("cli_agent_orchestrator.api.main.terminal_service") as mock_ts:
            mock_ts.create_terminal.side_effect = RuntimeError("tmux not found")

            from cli_agent_orchestrator.api.main import _start_root_orchestrator

            result = _start_root_orchestrator()
            assert result is None
