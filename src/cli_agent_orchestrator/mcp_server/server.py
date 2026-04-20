"""CLI Agent Orchestrator MCP Server implementation."""

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

import requests
from fastmcp import FastMCP
from pydantic import Field

from cli_agent_orchestrator.constants import API_BASE_URL, DEFAULT_PROVIDER
from cli_agent_orchestrator.mcp_server.models import HandoffResult
from cli_agent_orchestrator.utils.agent_profiles import load_agent_profile

# Create a requests session that ignores proxy env vars so that
# localhost API calls (to the CAO server) never go through an external proxy.
_http = requests.Session()
_http.trust_env = False
from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.utils.terminal import generate_session_name, wait_until_terminal_status

logger = logging.getLogger(__name__)

# Environment variable to enable/disable working_directory parameter
ENABLE_WORKING_DIRECTORY = os.getenv("CAO_ENABLE_WORKING_DIRECTORY", "false").lower() == "true"

# Environment variable to enable/disable automatic sender terminal ID injection
ENABLE_SENDER_ID_INJECTION = os.getenv("CAO_ENABLE_SENDER_ID_INJECTION", "false").lower() == "true"

# When true, session_root / global_folder / output_folder become REQUIRED
# in assign/handoff tool schemas (no default → model must provide them).
REQUIRE_CONTEXT_FOLDERS = os.getenv("CAO_REQUIRE_CONTEXT_FOLDERS", "false").lower() == "true"

# Shared Field definitions — required vs optional based on env flag
if REQUIRE_CONTEXT_FOLDERS:
    _CTX_SESSION_ROOT = Field(description="Session root directory path (REQUIRED). Forwarded to worker via [CAO Context] header.")
    _CTX_GLOBAL_FOLDER = Field(description="Shared folder path accessible by all agents (REQUIRED). Typically returned by prepare_phase_context.")
    _CTX_OUTPUT_FOLDER = Field(description="Folder where the agent should write output (REQUIRED). Typically returned by prepare_phase_context.")
else:
    _CTX_SESSION_ROOT = Field(default=None, description="Session root directory path, forwarded to worker via [CAO Context] header")
    _CTX_GLOBAL_FOLDER = Field(default=None, description="Shared folder path accessible by all agents")
    _CTX_OUTPUT_FOLDER = Field(default=None, description="Folder where the agent should write output")


def _build_context_header(
    global_folder: Optional[str] = None,
    output_folder: Optional[str] = None,
    input_folder: Optional[str] = None,
    input_folders: Optional[Dict[str, str]] = None,
    metadata_folder: Optional[str] = None,
    session_root: Optional[str] = None,
) -> str:
    """Build a [CAO Context] header from optional folder params.

    Returns empty string when all params are None/empty.
    """
    ctx: Dict[str, Any] = {}
    if session_root:
        ctx["session_root"] = session_root
    if global_folder:
        ctx["global_folder"] = global_folder
    if output_folder:
        ctx["output_folder"] = output_folder
    if input_folder:
        ctx["input_folder"] = input_folder
    if input_folders:
        ctx["input_folders"] = input_folders
    if metadata_folder:
        ctx["metadata_folder"] = metadata_folder
    if not ctx:
        return ""
    return f"[CAO Context]\n{json.dumps(ctx, indent=2)}\n[/CAO Context]\n\n"


def _load_system_prompt(agent_profile: str) -> str:
    """Load the system_prompt from an agent profile and wrap it in a header.

    Returns empty string if the profile has no system_prompt.
    """
    try:
        profile = load_agent_profile(agent_profile)
        if profile.system_prompt:
            return f"[System Prompt]\n{profile.system_prompt}\n[/System Prompt]\n\n"
    except Exception as e:
        logger.warning(f"Failed to load system prompt for '{agent_profile}': {e}")
    return ""


# Create MCP server
mcp = FastMCP(
    "cao-mcp-server",
    instructions="""
    # CLI Agent Orchestrator MCP Server

    This server provides tools to facilitate terminal delegation within CLI Agent Orchestrator sessions.

    ## Best Practices

    - Use specific agent profiles and providers
    - Provide clear and concise messages
    - Ensure you're running within a CAO terminal (CAO_TERMINAL_ID must be set)
    """,
)

# Register evolution tools (score reporting, knowledge sharing, etc.)
from cli_agent_orchestrator.mcp_server.evolution_tools import register_evolution_tools
register_evolution_tools(mcp)


def _create_terminal(
    agent_profile: str,
    working_directory: Optional[str] = None,
    display_name: Optional[str] = None,
    provider_override: Optional[str] = None,
) -> Tuple[str, str]:
    """Create a new terminal with the specified agent profile.

    Args:
        agent_profile: Agent profile for the terminal
        working_directory: Optional working directory for the terminal
        display_name: Optional display name for the tmux window
        provider_override: Optional provider type to use instead of inheriting
            from the parent terminal (e.g., "script", "opencode")

    Returns:
        Tuple of (terminal_id, provider)

    Raises:
        Exception: If terminal creation fails
    """
    provider = DEFAULT_PROVIDER

    # Get current terminal ID from environment
    current_terminal_id = os.environ.get("CAO_TERMINAL_ID")
    if current_terminal_id:
        # Get terminal metadata via API
        response = _http.get(f"{API_BASE_URL}/terminals/{current_terminal_id}")
        response.raise_for_status()
        terminal_metadata = response.json()

        provider = terminal_metadata["provider"]
        session_name = terminal_metadata["session_name"]

        # Allow caller to override the provider type (e.g., script → opencode)
        if provider_override:
            provider = provider_override

        # If no working_directory specified, get conductor's current directory
        if working_directory is None:
            try:
                response = _http.get(
                    f"{API_BASE_URL}/terminals/{current_terminal_id}/working-directory"
                )
                if response.status_code == 200:
                    working_directory = response.json().get("working_directory")
                    logger.info(f"Inherited working directory from conductor: {working_directory}")
                else:
                    logger.warning(
                        f"Failed to get conductor's working directory (status {response.status_code}), "
                        "will use server default"
                    )
            except Exception as e:
                logger.warning(
                    f"Error fetching conductor's working directory: {e}, will use server default"
                )

        # Create new terminal in existing session - always pass working_directory
        # send_system_prompt=false: handoff/assign prepend the prompt themselves
        params = {
            "provider": provider,
            "agent_profile": agent_profile,
            "send_system_prompt": "false",
        }
        if working_directory:
            params["working_directory"] = working_directory
        if display_name:
            params["display_name"] = display_name

        response = _http.post(f"{API_BASE_URL}/sessions/{session_name}/terminals", params=params)
        response.raise_for_status()
        terminal = response.json()
    else:
        # Create new session with terminal
        # send_system_prompt=false: handoff/assign prepend the prompt themselves
        session_name = generate_session_name()
        params = {
            "provider": provider,
            "agent_profile": agent_profile,
            "session_name": session_name,
            "send_system_prompt": "false",
        }
        if working_directory:
            params["working_directory"] = working_directory
        if display_name:
            params["display_name"] = display_name

        response = _http.post(f"{API_BASE_URL}/sessions", params=params)
        response.raise_for_status()
        terminal = response.json()

    return terminal["id"], provider


def _send_direct_input(terminal_id: str, message: str) -> None:
    """Send input directly to a terminal (bypasses inbox).

    Args:
        terminal_id: Terminal ID
        message: Message to send

    Raises:
        Exception: If sending fails
    """
    response = _http.post(
        f"{API_BASE_URL}/terminals/{terminal_id}/input", json={"message": message}
    )
    response.raise_for_status()


def _send_direct_input_handoff(terminal_id: str, provider: str, message: str) -> None:
    """Send handoff payload to an agent, always prepending [CAO Handoff] header.

    All providers receive the header so the agent knows this is a blocking task
    and should output results directly without using send_message.
    """
    supervisor_id = os.environ.get("CAO_TERMINAL_ID", "unknown")
    handoff_message = (
        f"[CAO Handoff] Supervisor terminal ID: {supervisor_id}. "
        "This is a blocking handoff — the orchestrator will automatically "
        "capture your response when you finish. Complete the task and output "
        "your results directly. Do NOT use send_message to notify the supervisor "
        "unless explicitly needed — just do the work and present your deliverables.\n\n"
        f"{message}"
    )

    _send_direct_input(terminal_id, handoff_message)


def _send_direct_input_assign(terminal_id: str, message: str) -> None:
    """Send assign payload to a worker agent, appending callback instructions."""
    # Auto-inject sender terminal ID suffix when enabled
    if ENABLE_SENDER_ID_INJECTION:
        sender_id = os.environ.get("CAO_TERMINAL_ID", "unknown")
        message += (
            f"\n\n[CAO Assign] supervisor_terminal_id={sender_id}. "
            f"When all work is complete, call: "
            f'send_message(receiver_id="{sender_id}", message="RUNNER_DONE runner=<your_runner_id>")]'
        )

    _send_direct_input(terminal_id, message)


def _send_to_inbox(receiver_id: str, message: str) -> Dict[str, Any]:
    """Send message to another terminal's inbox (queued delivery when IDLE).

    Args:
        receiver_id: Target terminal ID
        message: Message content

    Returns:
        Dict with message details

    Raises:
        ValueError: If CAO_TERMINAL_ID not set
        Exception: If API call fails
    """
    sender_id = os.getenv("CAO_TERMINAL_ID")
    if not sender_id:
        raise ValueError("CAO_TERMINAL_ID not set - cannot determine sender")

    response = _http.post(
        f"{API_BASE_URL}/terminals/{receiver_id}/inbox/messages",
        params={"sender_id": sender_id, "message": message},
    )
    response.raise_for_status()
    return response.json()


# Implementation functions
async def _handoff_impl(
    agent_profile: str,
    message: str,
    timeout: int = 1800,
    working_directory: Optional[str] = None,
    display_name: Optional[str] = None,
    global_folder: Optional[str] = None,
    output_folder: Optional[str] = None,
    input_folder: Optional[str] = None,
    input_folders: Optional[Dict[str, str]] = None,
    metadata_folder: Optional[str] = None,
    session_root: Optional[str] = None,
    debug: bool = True,
    provider: Optional[str] = None,
) -> HandoffResult:
    """Implementation of handoff logic.

    Args:
        debug: When True (default), keep the worker tmux window after
            completion for inspection.  When False, delete the window
            after capturing output.
        provider: Optional provider type override.  When set, the child
            terminal uses this provider instead of inheriting the parent's.
    """
    # Validate required context folders BEFORE creating terminal
    if REQUIRE_CONTEXT_FOLDERS:
        missing = [k for k, v in {"session_root": session_root, "global_folder": global_folder, "output_folder": output_folder}.items() if not v]
        if missing:
            raise ValueError(f"CAO_REQUIRE_CONTEXT_FOLDERS is enabled — the following required parameters are missing or null: {', '.join(missing)}")

    start_time = time.time()

    # Build the full message: system_prompt + context header + task message
    system_prompt_header = _load_system_prompt(agent_profile)
    context_header = _build_context_header(
        global_folder=global_folder,
        output_folder=output_folder,
        input_folder=input_folder,
        input_folders=input_folders,
        metadata_folder=metadata_folder,
        session_root=session_root,
    )
    full_message = system_prompt_header + context_header + message

    try:
        # Create terminal
        terminal_id, provider_used = _create_terminal(
            agent_profile, working_directory, display_name, provider_override=provider
        )

        # Script provider: the script is already running after initialize().
        # Skip IDLE wait and message send — go straight to waiting for completion.
        if provider_used == "script":
            logger.info(f"Script provider: waiting for completion (timeout={timeout}s)")
        else:
            # Wait for terminal to be ready (IDLE) before sending the message.
            if not wait_until_terminal_status(
                terminal_id,
                {TerminalStatus.IDLE},
                timeout=120.0,
            ):
                return HandoffResult(
                    success=False,
                    message=f"Terminal {terminal_id} did not reach ready status within 120 seconds",
                    output=None,
                    terminal_id=terminal_id,
                )

            await asyncio.sleep(2)  # wait another 2s

            # Send message to terminal (prepends [CAO Handoff] header)
            _send_direct_input_handoff(terminal_id, provider_used, full_message)

        # Monitor until completion with timeout
        if not wait_until_terminal_status(
            terminal_id, TerminalStatus.COMPLETED, timeout=timeout, polling_interval=1.0
        ):
            return HandoffResult(
                success=False,
                message=f"Handoff timed out after {timeout} seconds",
                output=None,
                terminal_id=terminal_id,
            )

        # Get the response
        response = _http.get(
            f"{API_BASE_URL}/terminals/{terminal_id}/output", params={"mode": "last"}
        )
        response.raise_for_status()
        output_data = response.json()
        output = output_data["output"]

        # Send provider-specific exit command and extract session ID
        response = _http.post(f"{API_BASE_URL}/terminals/{terminal_id}/exit")
        response.raise_for_status()
        provider_session_id = response.json().get("session_id")

        # Optionally delete the worker tmux window
        if not debug:
            time.sleep(2)  # let CLI process exit cleanly
            try:
                _http.delete(f"{API_BASE_URL}/terminals/{terminal_id}")
            except Exception:
                pass  # non-fatal: window may already be gone

        execution_time = time.time() - start_time

        return HandoffResult(
            success=True,
            message=f"Successfully handed off to {agent_profile} ({provider_used}) in {execution_time:.2f}s",
            output=output,
            terminal_id=terminal_id,
            provider_session_id=provider_session_id,
        )

    except Exception as e:
        return HandoffResult(
            success=False, message=f"Handoff failed: {str(e)}", output=None, terminal_id=None
        )


# Conditional tool registration based on environment variable
if ENABLE_WORKING_DIRECTORY:

    @mcp.tool()
    async def handoff(
        agent_profile: str = Field(
            description='The agent profile to hand off to (e.g., "developer", "analyst")'
        ),
        message: str = Field(description="The message/task to send to the target agent"),
        session_root: Optional[str] = _CTX_SESSION_ROOT,
        global_folder: Optional[str] = _CTX_GLOBAL_FOLDER,
        output_folder: Optional[str] = _CTX_OUTPUT_FOLDER,
        timeout: int = Field(
            default=1800,
            description="Maximum time to wait for the agent to complete the task (in seconds). Default 1800 (30min).",
            ge=1,
            le=86400,
        ),
        working_directory: Optional[str] = Field(
            default=None,
            description='Optional working directory where the agent should execute (e.g., "/path/to/workspace/src/Package")',
        ),
        input_folder: Optional[str] = Field(
            default=None, description="Primary input folder (e.g., upstream phase output)"
        ),
        input_folders: Optional[str] = Field(
            default=None, description='JSON object mapping dependency names to input paths, e.g. {"phase1":"/path/to/phase1/out"}'
        ),
        metadata_folder: Optional[str] = Field(
            default=None, description="Folder for task-level metadata"
        ),
        display_name: Optional[str] = Field(
            default=None, description="Display name for the tmux window (e.g., 't0-phase1')"
        ),
        debug: bool = Field(
            default=True,
            description="When True (default), keep worker tmux window after completion for inspection. Set False to auto-delete.",
        ),
        provider: Optional[str] = Field(
            default=None,
            description='Override the provider type for the child terminal (e.g., "script", "opencode"). If omitted, inherits from parent.',
        ),
    ) -> HandoffResult:
        """Hand off a task to another agent and wait for completion (working_directory enabled)."""
        return await _handoff_impl(
            agent_profile, message, timeout, working_directory,
            display_name=display_name,
            global_folder=global_folder,
            output_folder=output_folder,
            input_folder=input_folder,
            input_folders=json.loads(input_folders) if input_folders else None,
            metadata_folder=metadata_folder,
            session_root=session_root,
            debug=debug,
            provider=provider,
        )

else:

    @mcp.tool()
    async def handoff(
        agent_profile: str = Field(
            description='The agent profile to hand off to (e.g., "developer", "analyst")'
        ),
        message: str = Field(description="The message/task to send to the target agent"),
        session_root: Optional[str] = _CTX_SESSION_ROOT,
        global_folder: Optional[str] = _CTX_GLOBAL_FOLDER,
        output_folder: Optional[str] = _CTX_OUTPUT_FOLDER,
        timeout: int = Field(
            default=1800,
            description="Maximum time to wait for the agent to complete the task (in seconds). Default 1800 (30min).",
            ge=1,
            le=86400,
        ),
        input_folder: Optional[str] = Field(
            default=None, description="Primary input folder (e.g., upstream phase output)"
        ),
        input_folders: Optional[str] = Field(
            default=None, description='JSON object mapping dependency names to input paths, e.g. {"phase1":"/path/to/phase1/out"}'
        ),
        metadata_folder: Optional[str] = Field(
            default=None, description="Folder for task-level metadata"
        ),
        display_name: Optional[str] = Field(
            default=None, description="Display name for the tmux window (e.g., 't0-phase1')"
        ),
        debug: bool = Field(
            default=True,
            description="When True (default), keep worker tmux window after completion for inspection. Set False to auto-delete.",
        ),
        provider: Optional[str] = Field(
            default=None,
            description='Override the provider type for the child terminal (e.g., "script", "opencode"). If omitted, inherits from parent.',
        ),
    ) -> HandoffResult:
        """Hand off a task to another agent and wait for completion."""
        return await _handoff_impl(
            agent_profile, message, timeout, None,
            display_name=display_name,
            global_folder=global_folder,
            output_folder=output_folder,
            input_folder=input_folder,
            input_folders=json.loads(input_folders) if input_folders else None,
            metadata_folder=metadata_folder,
            session_root=session_root,
            debug=debug,
            provider=provider,
        )


# Implementation function for assign
def _assign_impl(
    agent_profile: str,
    message: str,
    working_directory: Optional[str] = None,
    display_name: Optional[str] = None,
    global_folder: Optional[str] = None,
    output_folder: Optional[str] = None,
    input_folder: Optional[str] = None,
    input_folders: Optional[Dict[str, str]] = None,
    metadata_folder: Optional[str] = None,
    session_root: Optional[str] = None,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Implementation of assign logic."""
    # Validate required context folders BEFORE creating terminal
    if REQUIRE_CONTEXT_FOLDERS:
        missing = [k for k, v in {"session_root": session_root, "global_folder": global_folder, "output_folder": output_folder}.items() if not v]
        if missing:
            return {"success": False, "terminal_id": None, "message": f"CAO_REQUIRE_CONTEXT_FOLDERS is enabled — the following required parameters are missing or null: {', '.join(missing)}"}

    try:
        # Build the full message: system_prompt + context header + task message
        system_prompt_header = _load_system_prompt(agent_profile)
        context_header = _build_context_header(
            global_folder=global_folder,
            output_folder=output_folder,
            input_folder=input_folder,
            input_folders=input_folders,
            metadata_folder=metadata_folder,
            session_root=session_root,
        )
        full_message = system_prompt_header + context_header + message

        # Create terminal
        terminal_id, _ = _create_terminal(
            agent_profile, working_directory, display_name, provider_override=provider
        )

        # Send message immediately (auto-injects sender terminal ID suffix when enabled)
        _send_direct_input_assign(terminal_id, full_message)

        return {
            "success": True,
            "terminal_id": terminal_id,
            "message": f"Task assigned to {agent_profile} (terminal: {terminal_id})",
        }

    except Exception as e:
        return {"success": False, "terminal_id": None, "message": f"Assignment failed: {str(e)}"}


def _build_assign_description(enable_sender_id: bool, enable_workdir: bool) -> str:
    """Build the assign tool description based on feature flags."""
    # Build tool description overview.
    if enable_sender_id:
        desc = """\
Assigns a task to another agent without blocking.

The sender's terminal ID and callback instructions will automatically be appended to the message."""
    else:
        desc = """\
Assigns a task to another agent without blocking.

In the message to the worker agent include instruction to send results back via send_message tool.
**IMPORTANT**: The terminal id of each agent is available in environment variable CAO_TERMINAL_ID.
When assigning, first find out your own CAO_TERMINAL_ID value, then include the terminal_id value in the message to the worker agent to allow callback.
Example message: "Analyze the logs. When done, send results back to terminal ee3f93b3 using send_message tool.\""""

    if enable_workdir:
        desc += """

## Working Directory

- By default, agents start in the supervisor's current working directory
- You can specify a custom directory via working_directory parameter
- Directory must exist and be accessible"""

    desc += """

Args:
    agent_profile: Agent profile for the worker terminal
    message: Task message (include callback instructions)"""

    if enable_workdir:
        desc += """
    working_directory: Optional working directory where the agent should execute"""

    desc += """

Returns:
    Dict with success status, worker terminal_id, and message"""

    return desc


_assign_description = _build_assign_description(
    ENABLE_SENDER_ID_INJECTION, ENABLE_WORKING_DIRECTORY
)
_assign_message_field_desc = (
    "The task message to send to the worker agent."
    if ENABLE_SENDER_ID_INJECTION
    else "The task message to send. Include callback instructions for the worker to send results back."
)

if ENABLE_WORKING_DIRECTORY:

    @mcp.tool(description=_assign_description)
    async def assign(
        agent_profile: str = Field(
            description='The agent profile for the worker agent (e.g., "developer", "analyst")'
        ),
        message: str = Field(description=_assign_message_field_desc),
        session_root: Optional[str] = _CTX_SESSION_ROOT,
        global_folder: Optional[str] = _CTX_GLOBAL_FOLDER,
        output_folder: Optional[str] = _CTX_OUTPUT_FOLDER,
        working_directory: Optional[str] = Field(
            default=None, description="Optional working directory where the agent should execute"
        ),
        input_folder: Optional[str] = Field(
            default=None, description="Primary input folder (e.g., upstream phase output)"
        ),
        input_folders: Optional[str] = Field(
            default=None, description='JSON object mapping dependency names to input paths'
        ),
        metadata_folder: Optional[str] = Field(
            default=None, description="Folder for task-level metadata"
        ),
        display_name: Optional[str] = Field(
            default=None, description="Human-readable name for the terminal window"
        ),
        provider: Optional[str] = Field(
            default=None,
            description='Override the provider type for the child terminal (e.g., "script", "opencode"). If omitted, inherits from parent.',
        ),
    ) -> Dict[str, Any]:
        return _assign_impl(
            agent_profile, message, working_directory,
            display_name=display_name,
            global_folder=global_folder,
            output_folder=output_folder,
            input_folder=input_folder,
            input_folders=json.loads(input_folders) if input_folders else None,
            metadata_folder=metadata_folder,
            session_root=session_root,
            provider=provider,
        )

else:

    @mcp.tool(description=_assign_description)
    async def assign(
        agent_profile: str = Field(
            description='The agent profile for the worker agent (e.g., "developer", "analyst")'
        ),
        message: str = Field(description=_assign_message_field_desc),
        session_root: Optional[str] = _CTX_SESSION_ROOT,
        global_folder: Optional[str] = _CTX_GLOBAL_FOLDER,
        output_folder: Optional[str] = _CTX_OUTPUT_FOLDER,
        input_folder: Optional[str] = Field(
            default=None, description="Primary input folder (e.g., upstream phase output)"
        ),
        input_folders: Optional[str] = Field(
            default=None, description='JSON object mapping dependency names to input paths'
        ),
        metadata_folder: Optional[str] = Field(
            default=None, description="Folder for task-level metadata"
        ),
        display_name: Optional[str] = Field(
            default=None, description="Human-readable name for the terminal window"
        ),
        provider: Optional[str] = Field(
            default=None,
            description='Override the provider type for the child terminal (e.g., "script", "opencode"). If omitted, inherits from parent.',
        ),
    ) -> Dict[str, Any]:
        return _assign_impl(
            agent_profile, message, None,
            display_name=display_name,
            global_folder=global_folder,
            output_folder=output_folder,
            input_folder=input_folder,
            input_folders=json.loads(input_folders) if input_folders else None,
            metadata_folder=metadata_folder,
            session_root=session_root,
            provider=provider,
        )


# Implementation function for send_message
def _send_message_impl(receiver_id: str, message: str) -> Dict[str, Any]:
    """Implementation of send_message logic."""
    try:
        # Auto-inject sender terminal ID suffix when enabled
        if ENABLE_SENDER_ID_INJECTION:
            sender_id = os.environ.get("CAO_TERMINAL_ID", "unknown")
            message += (
                f"\n\n[Message from terminal {sender_id}. "
                "Use send_message MCP tool for any follow-up work.]"
            )

        return _send_to_inbox(receiver_id, message)
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
async def send_message(
    receiver_id: str = Field(description="Target terminal ID to send message to"),
    message: str = Field(description="Message content to send"),
) -> Dict[str, Any]:
    """Send a message to another terminal's inbox.

    The message will be delivered when the destination terminal is IDLE.
    Messages are delivered in order (oldest first).

    Args:
        receiver_id: Terminal ID of the receiver
        message: Message content to send

    Returns:
        Dict with success status and message details
    """
    return _send_message_impl(receiver_id, message)


def main():
    """Main entry point for the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
