"""Tests for hermes-plugin — memory_parser and plugin lifecycle hooks.

Verifies that the Hermes integration reuses CaoBridge for all Hub communication,
matching the data flow of other agents (opencode, claude code).
"""

from __future__ import annotations

import hashlib
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ── memory_parser tests ───────────────────────────────────────────


class TestMemoryParser:
    """Test MEMORY.md parsing logic."""

    @pytest.fixture
    def parser_module(self):
        """Import memory_parser from the hermes-plugin directory."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "memory_parser",
            str(Path(__file__).parent.parent.parent / "cao-bridge" / "hermes-plugin" / "memory_parser.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_basic_section_split(self, parser_module):
        text = "First entry\n§\nSecond entry\n§\nThird entry"
        results = list(parser_module.parse_memory_text(text))
        assert len(results) == 3
        assert results[0][1] == "First entry"
        assert results[1][1] == "Second entry"
        assert results[2][1] == "Third entry"

    def test_header_lines_skipped(self, parser_module):
        text = textwrap.dedent("""\
            ══════════════════════════════════════════════
            MEMORY (your personal notes) [67% — 1,474/2,200 chars]
            ══════════════════════════════════════════════
            Real content here
            §
            Another entry""")
        results = list(parser_module.parse_memory_text(text))
        assert len(results) == 2
        assert results[0][1] == "Real content here"

    def test_empty_entries_skipped(self, parser_module):
        text = "§\n§\nActual content\n§\n§"
        results = list(parser_module.parse_memory_text(text))
        assert len(results) == 1
        assert results[0][1] == "Actual content"

    def test_dedup_same_content(self, parser_module):
        text = "Same thing\n§\nSame thing\n§\nDifferent thing"
        results = list(parser_module.parse_memory_text(text))
        assert len(results) == 2
        contents = [r[1] for r in results]
        assert "Same thing" in contents
        assert "Different thing" in contents

    def test_title_is_hash_based(self, parser_module):
        text = "Some memory entry"
        results = list(parser_module.parse_memory_text(text))
        assert len(results) == 1
        title = results[0][0]
        assert title.startswith("hermes-memory-")
        # Verify hash matches
        expected_hash = hashlib.sha256(b"Some memory entry").hexdigest()[:12]
        assert title == f"hermes-memory-{expected_hash}"

    def test_file_not_found(self, parser_module):
        results = list(parser_module.parse_memory(Path("/nonexistent/MEMORY.md")))
        assert results == []

    def test_parse_from_file(self, parser_module, tmp_path):
        mem_file = tmp_path / "MEMORY.md"
        mem_file.write_text("Entry A\n§\nEntry B")
        results = list(parser_module.parse_memory(mem_file))
        assert len(results) == 2


# ── Plugin lifecycle tests ────────────────────────────────────────


class TestHermesPlugin:
    """Test __init__.py register() hooks using mocked CaoBridge."""

    @pytest.fixture
    def plugin_module(self):
        """Import the hermes plugin __init__ module."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "hermes_plugin",
            str(Path(__file__).parent.parent.parent / "cao-bridge" / "hermes-plugin" / "__init__.py"),
            submodule_search_locations=[
                str(Path(__file__).parent.parent.parent / "cao-bridge" / "hermes-plugin"),
            ],
        )
        mod = importlib.util.module_from_spec(spec)
        # Pre-load memory_parser so relative import works
        import importlib
        mp_spec = importlib.util.spec_from_file_location(
            "hermes_plugin.memory_parser",
            str(Path(__file__).parent.parent.parent / "cao-bridge" / "hermes-plugin" / "memory_parser.py"),
        )
        mp_mod = importlib.util.module_from_spec(mp_spec)
        mp_spec.loader.exec_module(mp_mod)
        import sys
        sys.modules["hermes_plugin.memory_parser"] = mp_mod
        # Hack: the __init__ does `from .memory_parser import parse_memory`
        # which needs the parent package in sys.modules
        sys.modules["hermes_plugin"] = mod
        spec.loader.exec_module(mod)
        return mod

    @pytest.fixture
    def mock_bridge_class(self):
        with patch("cao_bridge.CaoBridge") as mock_cls:
            instance = MagicMock()
            instance.terminal_id = "hermes-001"
            instance.register.return_value = "hermes-001"
            instance.search_knowledge.return_value = [
                {"title": "Test Note", "content": "Some shared content..."}
            ]
            instance.poll.return_value = None
            mock_cls.return_value = instance
            yield mock_cls, instance

    def test_register_creates_bridge(self, plugin_module, mock_bridge_class):
        _, instance = mock_bridge_class
        ctx = MagicMock()
        ctx.settings = {"hub_url": "http://test:9889", "agent_id": "test-01"}

        # Patch CaoBridge on the already-imported plugin module
        with patch.object(plugin_module, "CaoBridge") as patched_cls:
            patched_cls.return_value = instance
            plugin_module.register(ctx)
            patched_cls.assert_called_once_with(
                hub_url="http://test:9889",
                agent_profile="remote-hermes-test-01",
            )

    def test_register_hooks_are_registered(self, plugin_module, mock_bridge_class):
        ctx = MagicMock()
        ctx.settings = {"hub_url": "http://test:9889"}

        plugin_module.register(ctx)

        hook_names = [c.args[0] for c in ctx.register_hook.call_args_list]
        assert "on_session_start" in hook_names
        assert "on_session_end" in hook_names
        assert "pre_llm_call" in hook_names

    def test_push_skills_scans_directory(self, plugin_module, tmp_path):
        """Test _push_skills writes hermes skills to local git clone."""
        # Create mock skills
        skill1 = tmp_path / "src" / "detect-sqli"
        skill1.mkdir(parents=True)
        (skill1 / "SKILL.md").write_text("---\nname: detect-sqli\n---\nSQLi detection skill")

        skill2 = tmp_path / "src" / "xss-scanner"
        skill2.mkdir(parents=True)
        (skill2 / "SKILL.md").write_text("XSS scanning skill")

        dest = tmp_path / "clone" / "skills"
        bridge = MagicMock()

        with patch.dict("os.environ", {"HERMES_SKILLS_DIR": str(tmp_path / "src")}), \
             patch.object(plugin_module, "client_skills_dir", return_value=dest):
            count = plugin_module._push_skills(bridge)

        assert count == 2
        assert (dest / "detect-sqli" / "SKILL.md").exists()
        assert (dest / "xss-scanner" / "SKILL.md").exists()

    def test_push_memory_parses_and_writes(self, plugin_module, tmp_path):
        """Test _push_memory writes entries as note files in local clone."""
        mem_file = tmp_path / "MEMORY.md"
        mem_file.write_text("Entry one\n§\nEntry two\n§\nEntry three")

        dest = tmp_path / "clone" / "notes"
        bridge = MagicMock()

        with patch.dict("os.environ", {"HERMES_MEMORY_PATH": str(mem_file)}), \
             patch.object(plugin_module, "client_notes_dir", return_value=dest):
            count = plugin_module._push_memory(bridge)

        assert count == 3
        notes = list(dest.glob("hermes-*.md"))
        assert len(notes) == 3
        for n in notes:
            content = n.read_text()
            assert "hermes" in content
            assert "memory" in content

    def test_push_skills_empty_dir(self, plugin_module, tmp_path):
        bridge = MagicMock()
        with patch.dict("os.environ", {"HERMES_SKILLS_DIR": str(tmp_path)}):
            count = plugin_module._push_skills(bridge)
        assert count == 0

    def test_push_memory_no_file(self, plugin_module, tmp_path):
        bridge = MagicMock()
        with patch.dict("os.environ", {"HERMES_MEMORY_PATH": str(tmp_path / "nonexistent.md")}):
            count = plugin_module._push_memory(bridge)
        assert count == 0

    def test_format_knowledge(self, plugin_module):
        results = [
            {"title": "Note A", "content": "Content of note A"},
            {"title": "Note B", "content": "Content of note B"},
        ]
        formatted = plugin_module._format_knowledge(results)
        assert "CAO Shared Knowledge" in formatted
        assert "Note A" in formatted
        assert "Note B" in formatted

    def test_format_knowledge_empty(self, plugin_module):
        assert plugin_module._format_knowledge([]) == ""
