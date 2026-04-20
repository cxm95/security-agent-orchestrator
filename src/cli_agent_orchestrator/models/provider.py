from enum import Enum


class ProviderType(str, Enum):
    """Provider type enumeration."""

    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    COPILOT_CLI = "copilot_cli"
    OPENCODE = "opencode"
    CLOTHER_MINIMAX_CN = "clother_minimax_cn"
    CLOTHER_CLOSEAI = "clother_closeai"
    REMOTE = "remote"
