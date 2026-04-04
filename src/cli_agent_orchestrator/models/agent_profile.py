"""Agent profile models."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class McpServer(BaseModel):
    """MCP server configuration.

    Supports two modes:
    - **local** (default): spawned via ``command`` + ``args``.
    - **remote**: connected via ``url`` (e.g. SSE / Streamable HTTP).
    """

    type: Optional[str] = None  # "local" (default) or "remote"
    command: Optional[str] = None  # Required for local, ignored for remote
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    url: Optional[str] = None  # Required for remote
    timeout: Optional[int] = None


class AgentProfile(BaseModel):
    """Agent profile configuration with Q CLI agent fields."""

    name: str
    description: str
    provider: Optional[str] = None  # Provider override (e.g. "claude_code", "kiro_cli")
    system_prompt: Optional[str] = None  # The markdown content

    # Q CLI agent fields (all optional, will be passed through to JSON)
    prompt: Optional[str] = None
    mcpServers: Optional[Dict[str, Any]] = None
    tools: Optional[List[str]] = Field(default=None)
    toolAliases: Optional[Dict[str, str]] = None
    allowedTools: Optional[List[str]] = None
    toolsSettings: Optional[Dict[str, Any]] = None
    resources: Optional[List[str]] = None
    hooks: Optional[Dict[str, Any]] = None
    useLegacyMcpJson: Optional[bool] = None
    model: Optional[str] = None

    # Script provider fields (used when provider == "script")
    script_path: Optional[str] = None
    script_args: Optional[List[str]] = None
    env_vars: Optional[Dict[str, str]] = None
