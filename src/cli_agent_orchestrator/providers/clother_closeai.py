"""Clother CloseAI provider — identical to Claude Code but uses clother-closeai binary."""

from cli_agent_orchestrator.providers.claude_code import ClaudeCodeProvider


class ClotherCloseaiProvider(ClaudeCodeProvider):
    """Provider for clother-closeai, using the same protocol as Claude Code."""

    def __init__(self, *args, bare: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self._bare = bare

    def _build_claude_command(self) -> str:
        """Build command string, replacing 'claude' with 'clother-closeai' and using --yolo."""
        cmd = super()._build_claude_command()
        cmd = cmd.replace("; claude ", "; clother-closeai ", 1)
        cmd = cmd.replace("--dangerously-skip-permissions", "--yolo", 1)
        if self._bare:
            # --bare skips hooks, plugins, CLAUDE.md, LSP — essential for
            # Hub-side agents (e.g. Root Orchestrator) that must NOT trigger
            # the CAO bridge hooks installed globally in ~/.claude/settings.json.
            cmd = cmd.replace("--yolo", "--yolo --bare", 1)
        return cmd
