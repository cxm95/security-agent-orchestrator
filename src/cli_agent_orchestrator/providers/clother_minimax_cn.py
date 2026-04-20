"""Clother MiniMax CN provider — identical to Claude Code but uses clother-minimax-cn binary."""

from cli_agent_orchestrator.providers.claude_code import ClaudeCodeProvider


class ClotherMinimaxCnProvider(ClaudeCodeProvider):
    """Provider for clother-minimax-cn, using the same protocol as Claude Code."""

    def __init__(self, *args, bare: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self._bare = bare

    def _build_claude_command(self) -> str:
        """Build command string, replacing 'claude' with 'clother-minimax-cn' and using --yolo."""
        cmd = super()._build_claude_command()
        cmd = cmd.replace("; claude ", "; clother-minimax-cn ", 1)
        cmd = cmd.replace("--dangerously-skip-permissions", "--yolo", 1)
        if self._bare:
            cmd = cmd.replace("--yolo", "--yolo --bare", 1)
        return cmd
