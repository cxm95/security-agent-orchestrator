"""Clother MiniMax CN provider — identical to Claude Code but uses clother-minimax-cn binary."""

from cli_agent_orchestrator.providers.claude_code import ClaudeCodeProvider


class ClotherMinimaxCnProvider(ClaudeCodeProvider):
    """Provider for clother-minimax-cn, using the same protocol as Claude Code."""

    def _build_claude_command(self) -> str:
        """Build command string, replacing 'claude' with 'clother-minimax-cn'."""
        cmd = super()._build_claude_command()
        # The super() command starts with "unset ...; claude ..."
        # Replace only the first occurrence of the bare 'claude' word after '; '
        return cmd.replace("; claude ", "; clother-minimax-cn ", 1)
