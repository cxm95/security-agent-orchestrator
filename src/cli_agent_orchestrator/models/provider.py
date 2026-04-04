from enum import Enum


class ProviderType(str, Enum):
    """Provider type enumeration."""

    Q_CLI = "q_cli"
    KIRO_CLI = "kiro_cli"
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    KIMI_CLI = "kimi_cli"
    GEMINI_CLI = "gemini_cli"
    COPILOT_CLI = "copilot_cli"
    OPENCODE = "opencode"
    CLOTHER_MINIMAX_CN = "clother_minimax_cn"
    SCRIPT = "script"
    HUNTDEX = "huntdex"
