"""Tests for Claude Code bridge — config validation, hook syntax, install script."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

# All claude-code bridge files live here
CLAUDE_DIR = Path(__file__).resolve().parent.parent.parent / "cao-bridge" / "claude-code"


class TestConfigFiles:
    """Validate JSON config files are well-formed."""

    def test_mcp_json_valid(self):
        data = json.loads((CLAUDE_DIR / ".mcp.json").read_text())
        assert "mcpServers" in data
        assert "cao-bridge" in data["mcpServers"]
        srv = data["mcpServers"]["cao-bridge"]
        assert srv["command"] == "python3"
        assert "cao_bridge_mcp.py" in srv["args"][0]
        assert "CAO_HUB_URL" in srv["env"]
        assert "CAO_AGENT_PROFILE" in srv["env"]
        assert srv["env"]["CAO_AGENT_PROFILE"] == "remote-claude-code"
        assert "no_proxy" in srv["env"] or "NO_PROXY" in srv["env"]


class TestCLAUDEmd:
    """Validate CLAUDE.md references all expected MCP tools."""

    EXPECTED_TOOLS = [
        "cao_register", "cao_poll", "cao_report",
        "cao_report_score", "cao_get_task", "cao_get_leaderboard",
        "cao_search_knowledge", "cao_push",
    ]

    def test_file_exists(self):
        assert (CLAUDE_DIR / "CLAUDE.md").is_file()

    def test_references_all_tools(self):
        text = (CLAUDE_DIR / "CLAUDE.md").read_text()
        for tool in self.EXPECTED_TOOLS:
            assert tool in text, f"CLAUDE.md missing reference to {tool}"

    def test_has_workflow_section(self):
        text = (CLAUDE_DIR / "CLAUDE.md").read_text()
        assert "## Workflow" in text


class TestHookScripts:
    """Validate hook shell scripts are syntactically correct."""

    @pytest.mark.parametrize("name", ["cao-session-start.sh", "cao-session-stop.sh"])
    def test_bash_syntax(self, name):
        script = CLAUDE_DIR / "hooks" / name
        assert script.is_file()
        result = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Syntax error in {name}: {result.stderr}"

    def test_start_hook_has_register_call(self):
        text = (CLAUDE_DIR / "hooks" / "cao-session-start.sh").read_text()
        assert "/remotes/register" in text
        assert "terminal_id" in text
        assert "CAO_HUB_URL" in text

    def test_stop_hook_has_report_call(self):
        text = (CLAUDE_DIR / "hooks" / "cao-session-stop.sh").read_text()
        assert "/report" in text
        assert "CAO_STATE_FILE" in text

    def test_start_hook_outputs_json(self):
        text = (CLAUDE_DIR / "hooks" / "cao-session-start.sh").read_text()
        # Should output {"context": ...} for Claude Code
        assert '"context"' in text

    def test_start_hook_handles_unreachable_hub(self):
        text = (CLAUDE_DIR / "hooks" / "cao-session-start.sh").read_text()
        assert "standalone mode" in text.lower() or "unreachable" in text.lower()


class TestEvolveCommand:
    """Validate /evolve slash command."""

    def test_file_exists(self):
        assert (CLAUDE_DIR / "commands" / "evolve.md").is_file()

    def test_has_frontmatter(self):
        text = (CLAUDE_DIR / "commands" / "evolve.md").read_text()
        assert text.startswith("---")
        assert "description:" in text

    def test_references_evolution_tools(self):
        text = (CLAUDE_DIR / "commands" / "evolve.md").read_text()
        for tool in ["cao_report_score", "cao_push", "cao_get_leaderboard"]:
            assert tool in text, f"evolve.md missing {tool}"


class TestInstallScript:
    """Test install.sh creates correct structure."""

    def test_syntax_valid(self):
        script = CLAUDE_DIR / "install.sh"
        result = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"Syntax error: {result.stderr}"

    def test_install_creates_structure(self):
        """Run install.sh in a temp dir and verify the output structure."""
        script = CLAUDE_DIR / "install.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ["bash", str(script), tmpdir],
                capture_output=True, text=True,
                env={**os.environ, "CAO_HUB_URL": "http://test:9999"},
            )
            assert result.returncode == 0, f"Install failed: {result.stderr}"

            target = Path(tmpdir)
            # CLAUDE.md
            assert (target / "CLAUDE.md").is_file()
            # .mcp.json with correct Hub URL
            mcp = json.loads((target / ".mcp.json").read_text())
            assert mcp["mcpServers"]["cao-bridge"]["env"]["CAO_HUB_URL"] == "http://test:9999"
            # .mcp.json args should have absolute path to cao_bridge_mcp.py
            args = mcp["mcpServers"]["cao-bridge"]["args"]
            assert os.path.isabs(args[0])
            assert args[0].endswith("cao_bridge_mcp.py")
            # Commands
            assert (target / ".claude" / "commands" / "evolve.md").is_file()
            # Settings with hooks
            settings = json.loads((target / ".claude" / "settings.local.json").read_text())
            assert "hooks" in settings
            assert "SessionStart" in settings["hooks"]
            assert "Stop" in settings["hooks"]

    def test_install_preserves_existing_claude_md(self):
        """If CLAUDE.md already exists, install should not overwrite it."""
        script = CLAUDE_DIR / "install.sh"
        with tempfile.TemporaryDirectory() as tmpdir:
            existing = Path(tmpdir) / "CLAUDE.md"
            existing.write_text("# My existing instructions\n")
            subprocess.run(
                ["bash", str(script), tmpdir],
                capture_output=True, text=True,
            )
            assert "My existing instructions" in existing.read_text()
