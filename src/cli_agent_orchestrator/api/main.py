"""Single FastAPI entry point for all HTTP routes."""

import asyncio
import fcntl
import json
import logging
import os
import pty
import signal
import struct
import subprocess
import termios
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Body, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, field_validator
from watchdog.observers.polling import PollingObserver

from cli_agent_orchestrator.clients.database import (
    create_inbox_message,
    get_inbox_messages,
    get_terminal_metadata,
    init_db,
)
from cli_agent_orchestrator.constants import (
    ALLOWED_HOSTS,
    CAO_HOME_DIR,
    CORS_ORIGINS,
    INBOX_POLLING_INTERVAL,
    SERVER_HOST,
    SERVER_PORT,
    SERVER_VERSION,
    TERMINAL_LOG_DIR,
)
from cli_agent_orchestrator.models.flow import Flow
from cli_agent_orchestrator.models.inbox import MessageStatus
from cli_agent_orchestrator.models.terminal import Terminal, TerminalId
from cli_agent_orchestrator.providers.manager import provider_manager
from cli_agent_orchestrator.services import (
    flow_service,
    inbox_service,
    session_service,
    terminal_service,
)
from cli_agent_orchestrator.api.evolution_routes import ensure_evolution_repo, router as evolution_router
from cli_agent_orchestrator.services.cleanup_service import cleanup_old_data
from cli_agent_orchestrator.services.inbox_service import LogFileHandler
from cli_agent_orchestrator.services.recovery_service import recover_on_startup
from cli_agent_orchestrator.services.terminal_service import OutputMode
from cli_agent_orchestrator.utils.agent_profiles import resolve_provider
from cli_agent_orchestrator.utils.logging import setup_logging
from cli_agent_orchestrator.utils.terminal import generate_session_name

logger = logging.getLogger(__name__)


async def flow_daemon():
    """Background task to check and execute flows."""
    logger.info("Flow daemon started")
    while True:
        try:
            flows = flow_service.get_flows_to_run()
            for flow in flows:
                try:
                    executed = flow_service.execute_flow(flow.name)
                    if executed:
                        logger.info(f"Flow '{flow.name}' executed successfully")
                    else:
                        logger.info(f"Flow '{flow.name}' skipped (execute=false)")
                except Exception as e:
                    logger.error(f"Flow '{flow.name}' failed: {e}")
        except Exception as e:
            logger.error(f"Flow daemon error: {e}")

        await asyncio.sleep(60)


# Response Models
class TerminalOutputResponse(BaseModel):
    output: str
    mode: str


class WorkingDirectoryResponse(BaseModel):
    """Response model for terminal working directory."""

    working_directory: Optional[str] = Field(
        description="Current working directory of the terminal, or None if unavailable"
    )


class CreateFlowRequest(BaseModel):
    """Request model for creating a flow."""

    name: str
    schedule: str
    agent_profile: str
    provider: str = "claude_code"
    prompt_template: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Prevent path traversal — flow name becomes a filename."""
        if "/" in v or "\\" in v or ".." in v:
            raise ValueError("Flow name must not contain '/', '\\', or '..'")
        return v




def _start_root_orchestrator() -> str | None:
    """Create the persistent Root Orchestrator terminal. Returns terminal_id or None.

    The Root Orchestrator is a Hub-internal agent that must NOT trigger the
    CAO bridge hooks (SessionStart/Stop/End) that are globally installed in
    ~/.claude/settings.json for remote agents.  We achieve isolation via:
    1. CAO_HOOKS_ENABLED=0 env var — disables all CAO hooks in the bash scripts
    2. --bare CLI flag — tells the provider to skip hooks, plugins, CLAUDE.md
    """
    from cli_agent_orchestrator.config import load_config

    cfg = load_config().root_orchestrator
    if not cfg.enabled:
        logger.info("Root orchestrator disabled in config")
        return None
    try:
        root_terminal = terminal_service.create_terminal(
            provider=cfg.provider,
            agent_profile=cfg.profile,
            session_name=cfg.session,
            new_session=True,
            send_system_prompt=True,
            working_directory=str(Path.home()),
            env_vars={"CAO_HOOKS_ENABLED": "0"},
            bare=True,
        )
        logger.info("Root orchestrator started: %s (provider=%s, session=%s)",
                     root_terminal.id, cfg.provider, cfg.session)
        return root_terminal.id
    except Exception as e:
        logger.warning("Root orchestrator start failed (non-fatal): %s", e)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    logger.info("Starting CLI Agent Orchestrator server...")
    setup_logging()
    init_db()
    ensure_evolution_repo()

    # Reattach to terminals that persisted from the previous run so remote
    # agents (RemoteProvider) can continue polling without re-registering
    # and local tmux sessions resume inbox monitoring via pipe-pane.
    try:
        report = await asyncio.to_thread(recover_on_startup)
        logger.info(f"Startup recovery: {report.summary()}")
    except Exception as e:
        logger.error(f"Startup recovery failed (continuing anyway): {e}")

    # Run cleanup in background
    asyncio.create_task(asyncio.to_thread(cleanup_old_data))

    # Start flow daemon as background task
    daemon_task = asyncio.create_task(flow_daemon())

    # Start inbox watcher
    inbox_observer = PollingObserver(timeout=INBOX_POLLING_INTERVAL)
    inbox_observer.schedule(LogFileHandler(), str(TERMINAL_LOG_DIR), recursive=False)
    inbox_observer.start()
    logger.info("Inbox watcher started (PollingObserver)")

    # Start Root Orchestrator (persistent background agent for Hub tasks)
    root_tid = await asyncio.to_thread(_start_root_orchestrator)
    app.state.root_terminal_id = root_tid

    yield

    # Shutdown: cleanup Root Orchestrator
    if getattr(app.state, "root_terminal_id", None):
        try:
            terminal_service.delete_terminal(app.state.root_terminal_id)
            logger.info("Root orchestrator stopped")
        except Exception:
            pass

    # Stop inbox observer
    inbox_observer.stop()
    inbox_observer.join()
    logger.info("Inbox watcher stopped")

    # Cancel daemon on shutdown
    daemon_task.cancel()
    try:
        await daemon_task
    except asyncio.CancelledError:
        pass

    logger.info("Shutting down CLI Agent Orchestrator server...")


app = FastAPI(
    title="CLI Agent Orchestrator",
    description="Simplified CLI Agent Orchestrator API",
    version=SERVER_VERSION,
    lifespan=lifespan,
)

# Security: DNS Rebinding Protection
# Validate Host header to prevent DNS rebinding attacks (CVE mitigation)
# Only allow requests with localhost Host headers
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=ALLOWED_HOSTS,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(evolution_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "cli-agent-orchestrator"}


@app.get("/agents/profiles")
async def list_agent_profiles_endpoint() -> List[Dict]:
    """List all available agent profiles from all configured directories."""
    try:
        from cli_agent_orchestrator.utils.agent_profiles import list_agent_profiles

        return list_agent_profiles()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list agent profiles: {str(e)}",
        )


@app.get("/agents/providers")
async def list_providers_endpoint() -> List[Dict]:
    """List available providers with installation status."""
    import shutil

    provider_binaries = {
        "claude_code": "claude",
        "codex": "codex",
        "copilot_cli": "copilot",
        "opencode": "opencode",
        "clother_minimax_cn": "clother-minimax-cn",
    }
    result = []
    for provider, binary in provider_binaries.items():
        installed = shutil.which(binary) is not None
        result.append({"name": provider, "binary": binary, "installed": installed})
    return result


@app.get("/settings/agent-dirs")
async def get_agent_dirs_endpoint() -> Dict:
    """Get configured agent directories per provider."""
    from cli_agent_orchestrator.services.settings_service import (
        get_agent_dirs,
        get_extra_agent_dirs,
    )

    return {"agent_dirs": get_agent_dirs(), "extra_dirs": get_extra_agent_dirs()}


class AgentDirsUpdate(BaseModel):
    agent_dirs: Optional[Dict[str, str]] = None
    extra_dirs: Optional[List[str]] = None


@app.post("/settings/agent-dirs")
async def set_agent_dirs_endpoint(body: AgentDirsUpdate) -> Dict:
    """Update agent directories per provider."""
    from cli_agent_orchestrator.services.settings_service import (
        get_extra_agent_dirs,
        set_agent_dirs,
        set_extra_agent_dirs,
    )

    result_dirs = {}
    result_extra = []
    if body.agent_dirs:
        result_dirs = set_agent_dirs(body.agent_dirs)
    if body.extra_dirs is not None:
        result_extra = set_extra_agent_dirs(body.extra_dirs)
    return {
        "agent_dirs": result_dirs or {},
        "extra_dirs": result_extra or get_extra_agent_dirs(),
    }


@app.post("/sessions", response_model=Terminal, status_code=status.HTTP_201_CREATED)
async def create_session(
    provider: str,
    agent_profile: str,
    session_name: Optional[str] = None,
    working_directory: Optional[str] = None,
    display_name: Optional[str] = None,
    initial_prompt: Optional[str] = None,
) -> Terminal:
    """Create a new session with exactly one terminal."""
    try:
        result = terminal_service.create_terminal(
            provider=provider,
            agent_profile=agent_profile,
            session_name=session_name,
            new_session=True,
            working_directory=working_directory,
            display_name=display_name,
            initial_prompt=initial_prompt,
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create session: {str(e)}",
        )


@app.get("/sessions")
async def list_sessions() -> List[Dict]:
    try:
        return session_service.list_sessions()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list sessions: {str(e)}",
        )


@app.get("/sessions/{session_name}")
async def get_session(session_name: str) -> Dict:
    try:
        return session_service.get_session(session_name)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get session: {str(e)}",
        )


@app.delete("/sessions/{session_name}")
async def delete_session(session_name: str) -> Dict:
    try:
        result = session_service.delete_session(session_name)
        return {"success": True, **result}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete session: {str(e)}",
        )


@app.post(
    "/sessions/{session_name}/terminals",
    response_model=Terminal,
    status_code=status.HTTP_201_CREATED,
)
async def create_terminal_in_session(
    session_name: str,
    provider: str,
    agent_profile: str,
    working_directory: Optional[str] = None,
    display_name: Optional[str] = None,
    send_system_prompt: bool = True,
) -> Terminal:
    """Create additional terminal in existing session."""
    try:
        resolved_provider = resolve_provider(agent_profile, fallback_provider=provider)

        result = terminal_service.create_terminal(
            provider=resolved_provider,
            agent_profile=agent_profile,
            session_name=session_name,
            new_session=False,
            working_directory=working_directory,
            display_name=display_name,
            send_system_prompt=send_system_prompt,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create terminal: {str(e)}",
        )


@app.get("/sessions/{session_name}/terminals")
async def list_terminals_in_session(session_name: str) -> List[Dict]:
    """List all terminals in a session."""
    try:
        from cli_agent_orchestrator.clients.database import list_terminals_by_session

        return list_terminals_by_session(session_name)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list terminals: {str(e)}",
        )


@app.get("/terminals")
async def list_all_terminals_endpoint(
    provider: Optional[str] = Query(
        default=None, description="Optional provider filter (e.g. 'remote', 'claude_code')"
    ),
) -> List[Dict]:
    """List all terminals across every session — tmux-backed or remote.

    Unlike ``/sessions``, this endpoint is independent of tmux so remote
    agents that registered via ``/remotes/register`` are always visible here.
    """
    try:
        from cli_agent_orchestrator.clients.database import (
            list_all_terminals as db_list_all_terminals,
        )

        terminals = db_list_all_terminals()
        if provider:
            terminals = [t for t in terminals if t["provider"] == provider]

        result = []
        for t in terminals:
            live_status = None
            try:
                prov = provider_manager.get_provider(t["id"])
                if prov is not None:
                    live_status = prov.get_status().value
            except Exception:
                live_status = None

            result.append(
                {
                    "id": t["id"],
                    "name": t["tmux_window"],
                    "provider": t["provider"],
                    "session_name": t["tmux_session"],
                    "agent_profile": t["agent_profile"],
                    "status": live_status,
                    "last_active": t["last_active"].isoformat() if t.get("last_active") else None,
                }
            )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list terminals: {str(e)}",
        )


@app.get("/terminals/{terminal_id}", response_model=Terminal)
async def get_terminal(terminal_id: TerminalId) -> Terminal:
    try:
        terminal = terminal_service.get_terminal(terminal_id)
        return Terminal(**terminal)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get terminal: {str(e)}",
        )


@app.get("/terminals/{terminal_id}/working-directory", response_model=WorkingDirectoryResponse)
async def get_terminal_working_directory(terminal_id: TerminalId) -> WorkingDirectoryResponse:
    """Get the current working directory of a terminal's pane."""
    try:
        working_directory = terminal_service.get_working_directory(terminal_id)
        return WorkingDirectoryResponse(working_directory=working_directory)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get working directory: {str(e)}",
        )


class TerminalInputRequest(BaseModel):
    message: str = Field(description="Message to send to the terminal")


@app.post("/terminals/{terminal_id}/input")
async def send_terminal_input(
    terminal_id: TerminalId,
    body: Optional[TerminalInputRequest] = Body(default=None),
    message: Optional[str] = Query(default=None, description="Message (query param, for backward compat)"),
) -> Dict:
    # JSON body takes precedence over query param
    msg = (body.message if body else None) or message
    if not msg:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide 'message' in JSON body or query parameter",
        )
    try:
        success = terminal_service.send_input(terminal_id, msg)
        return {"success": success}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send input: {str(e)}",
        )


@app.get("/terminals/{terminal_id}/output", response_model=TerminalOutputResponse)
async def get_terminal_output(
    terminal_id: TerminalId, mode: OutputMode = OutputMode.FULL
) -> TerminalOutputResponse:
    try:
        output = terminal_service.get_output(terminal_id, mode)
        return TerminalOutputResponse(output=output, mode=mode)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get output: {str(e)}",
        )


@app.post("/terminals/{terminal_id}/exit")
async def exit_terminal(terminal_id: TerminalId) -> Dict:
    """Gracefully exit CLI and return provider session ID if available.

    Tries ``provider.graceful_exit()`` first (extracts session ID for
    providers like OpenCode).  Falls back to ``provider.exit_cli()`` when
    ``graceful_exit`` returns *None* (base implementation).
    """
    try:
        provider = provider_manager.get_provider(terminal_id)
        if provider is None:
            raise ValueError(f"Provider not found for terminal {terminal_id}")

        # Prefer graceful_exit (extracts session_id); fall back to exit_cli
        session_id = provider.graceful_exit()
        if session_id is None:
            exit_command = provider.exit_cli()
            if exit_command.startswith(("C-", "M-")):
                terminal_service.send_special_key(terminal_id, exit_command)
            else:
                terminal_service.send_input(terminal_id, exit_command)

        return {"success": True, "session_id": session_id}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to exit terminal: {str(e)}",
        )


@app.delete("/terminals/{terminal_id}")
async def delete_terminal(terminal_id: TerminalId) -> Dict:
    """Delete a terminal."""
    try:
        success = terminal_service.delete_terminal(terminal_id)
        return {"success": success}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete terminal: {str(e)}",
        )


@app.post("/terminals/{receiver_id}/inbox/messages")
async def create_inbox_message_endpoint(
    receiver_id: TerminalId, sender_id: str, message: str
) -> Dict:
    """Create inbox message and attempt immediate delivery."""
    try:
        inbox_msg = create_inbox_message(sender_id, receiver_id, message)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create inbox message: {str(e)}",
        )

    # Best-effort immediate delivery. If the receiver terminal is idle, the
    # message is delivered now; otherwise the watchdog will deliver it when
    # the terminal becomes idle. Delivery failures must not cause the API
    # to report an error — the message was already persisted above.
    try:
        inbox_service.check_and_send_pending_messages(receiver_id)
    except Exception as e:
        logger.warning(f"Immediate delivery attempt failed for {receiver_id}: {e}")

    return {
        "success": True,
        "message_id": inbox_msg.id,
        "sender_id": inbox_msg.sender_id,
        "receiver_id": inbox_msg.receiver_id,
        "created_at": inbox_msg.created_at.isoformat(),
    }


@app.get("/terminals/{terminal_id}/inbox/messages")
async def get_inbox_messages_endpoint(
    terminal_id: TerminalId,
    limit: int = Query(default=10, le=100, description="Maximum number of messages to retrieve"),
    status_param: Optional[str] = Query(
        default=None, alias="status", description="Filter by message status"
    ),
) -> List[Dict]:
    """Get inbox messages for a terminal.

    Args:
        terminal_id: Terminal ID to get messages for
        limit: Maximum number of messages to return (default: 10, max: 100)
        status_param: Optional filter by message status ('pending', 'delivered', 'failed')

    Returns:
        List of inbox messages with sender_id, message, created_at, status
    """
    try:
        # Convert status filter if provided
        status_filter = None
        if status_param:
            try:
                status_filter = MessageStatus(status_param)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid status: {status_param}. Valid values: pending, delivered, failed",
                )

        # Get messages using existing database function
        messages = get_inbox_messages(terminal_id, limit=limit, status=status_filter)

        # Convert to response format
        result = []
        for msg in messages:
            result.append(
                {
                    "id": msg.id,
                    "sender_id": msg.sender_id,
                    "receiver_id": msg.receiver_id,
                    "message": msg.message,
                    "status": msg.status.value,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                }
            )

        return result

    except HTTPException:
        # Re-raise HTTPException (validation errors)
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve inbox messages: {str(e)}",
        )


# ---------------------------------------------------------------------------
# Remote agent endpoints
# ---------------------------------------------------------------------------


class RemoteRegisterRequest(BaseModel):
    agent_profile: str = Field(default="remote-agent")
    session_name: Optional[str] = None


class RemoteReportRequest(BaseModel):
    status: Optional[str] = None
    output: Optional[str] = None
    append: bool = False


@app.post("/remotes/register", status_code=status.HTTP_201_CREATED)
async def remote_register(body: RemoteRegisterRequest) -> Dict:
    """Register a remote agent — creates a virtual terminal (no tmux)."""
    try:
        terminal = terminal_service.create_terminal(
            provider="remote",
            agent_profile=body.agent_profile,
            session_name=body.session_name,
            new_session=False if body.session_name else True,
            send_system_prompt=False,
        )
        return {"terminal_id": terminal.id, "session_name": terminal.session_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/remotes/{terminal_id}/reattach")
async def remote_reattach(terminal_id: str) -> Dict:
    """Reattach an existing remote terminal after an agent cold-start.

    Called by the agent's SessionStart hook when it already has a cached
    ``terminal_id``.  Returns the persisted state so the agent can decide
    whether queued work is still waiting for it.  A 404 here tells the
    agent its cached id is gone and it should fall back to
    ``POST /remotes/register``.
    """
    try:
        metadata = get_terminal_metadata(terminal_id)
        if not metadata:
            raise HTTPException(status_code=404, detail="Terminal not found")
        if metadata["provider"] != "remote":
            raise HTTPException(status_code=400, detail="Not a remote terminal")

        from cli_agent_orchestrator.clients.database import (
            get_pending_messages,
            get_remote_state,
            touch_remote_state_last_seen,
        )

        provider = provider_manager.get_provider(terminal_id)
        # Agent is starting fresh — clear any stale PROCESSING/ERROR status so
        # the next /poll (or inbox delivery) isn't blocked by a status left
        # behind by the previous crashed session.
        if provider is not None and hasattr(provider, "reset_for_reattach"):
            provider.reset_for_reattach()
        touch_remote_state_last_seen(terminal_id)

        state = get_remote_state(terminal_id) or {}
        pending_inbox = get_pending_messages(terminal_id, limit=100)

        return {
            "ok": True,
            "terminal_id": terminal_id,
            "session_name": metadata["tmux_session"],
            "agent_profile": metadata["agent_profile"],
            "status": state.get("status") or (provider.get_status().value if provider else "idle"),
            "has_pending_input": bool(state.get("pending_input")),
            "pending_inbox_count": len(pending_inbox),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/remotes/{terminal_id}/poll")
async def remote_poll(terminal_id: str) -> Dict:
    """Remote agent polls for pending input."""
    try:
        provider = provider_manager.get_provider(terminal_id)
        if provider is None:
            raise HTTPException(status_code=404, detail="Terminal not found")

        from cli_agent_orchestrator.providers.remote import RemoteProvider
        if not isinstance(provider, RemoteProvider):
            raise HTTPException(status_code=400, detail="Not a remote terminal")

        # Bridge inbox → remote: deliver pending send_message() before consuming
        if provider._pending_input is None:
            try:
                inbox_service.check_and_send_pending_messages(terminal_id)
            except Exception as e:
                logger.warning(f"Inbox check for remote {terminal_id}: {e}")

        msg = provider.consume_pending_input()
        return {"has_input": msg is not None, "input": msg}

    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=404, detail="Terminal not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/remotes/{terminal_id}/report")
async def remote_report(terminal_id: str, body: RemoteReportRequest) -> Dict:
    """Remote agent reports status and/or output."""
    try:
        provider = provider_manager.get_provider(terminal_id)
        if provider is None:
            raise HTTPException(status_code=404, detail="Terminal not found")

        from cli_agent_orchestrator.providers.remote import RemoteProvider
        if not isinstance(provider, RemoteProvider):
            raise HTTPException(status_code=400, detail="Not a remote terminal")

        if body.status:
            provider.report_status(body.status)
        if body.output is not None:
            provider.report_output(body.output, append=body.append)

        return {"ok": True}

    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=404, detail="Terminal not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/remotes/{terminal_id}/status")
async def remote_status(terminal_id: str) -> Dict:
    """Get remote terminal status (for debugging / monitoring)."""
    try:
        provider = provider_manager.get_provider(terminal_id)
        if provider is None:
            raise HTTPException(status_code=404, detail="Terminal not found")

        from cli_agent_orchestrator.providers.remote import RemoteProvider
        if not isinstance(provider, RemoteProvider):
            raise HTTPException(status_code=400, detail="Not a remote terminal")

        return {
            "terminal_id": terminal_id,
            "status": provider.get_status().value,
            "has_pending_input": provider._pending_input is not None,
            "last_output_length": len(provider._last_output),
        }

    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=404, detail="Terminal not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.websocket("/terminals/{terminal_id}/ws")
async def terminal_ws(websocket: WebSocket, terminal_id: str):
    """WebSocket endpoint for live terminal streaming via tmux attach.

    Security: This endpoint provides full PTY access with no authentication.
    It is intended for localhost-only use. Do NOT expose the server to
    untrusted networks (e.g. --host 0.0.0.0) without adding authentication.
    """
    # Reject connections from non-loopback clients
    client_host = websocket.client.host if websocket.client else None
    if client_host not in (None, "127.0.0.1", "::1", "localhost"):
        await websocket.close(code=4003, reason="WebSocket access is restricted to localhost")
        return

    await websocket.accept()

    metadata = get_terminal_metadata(terminal_id)
    if not metadata:
        await websocket.close(code=4004, reason="Terminal not found")
        return

    session_name = metadata["tmux_session"]
    window_name = metadata["tmux_window"]

    # Create PTY pair for tmux attach
    master_fd, slave_fd = pty.openpty()

    # Set initial terminal size
    winsize = struct.pack("HHHH", 24, 80, 0, 0)
    fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

    # Start tmux attach inside the PTY
    proc = subprocess.Popen(
        ["tmux", "attach-session", "-t", f"{session_name}:{window_name}"],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        preexec_fn=os.setsid,
    )
    os.close(slave_fd)

    # Make master_fd non-blocking for event-driven reads
    flag = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flag | os.O_NONBLOCK)

    loop = asyncio.get_event_loop()
    output_queue: asyncio.Queue[bytes] = asyncio.Queue()
    done = asyncio.Event()

    def _on_pty_data():
        """Callback when PTY has data available."""
        try:
            data = os.read(master_fd, 65536)
            if data:
                output_queue.put_nowait(data)
            else:
                done.set()
        except BlockingIOError:
            pass
        except OSError:
            done.set()

    loop.add_reader(master_fd, _on_pty_data)

    async def _forward_output():
        """Read from PTY queue and send to WebSocket."""
        while not done.is_set():
            try:
                data = await asyncio.wait_for(output_queue.get(), timeout=1.0)
                # Drain any additional pending data for batching
                while not output_queue.empty():
                    try:
                        data += output_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                await websocket.send_bytes(data)
            except asyncio.TimeoutError:
                if proc.poll() is not None:
                    break
            except Exception:
                break

    async def _forward_input():
        """Receive from WebSocket and write to PTY."""
        try:
            while not done.is_set():
                msg = await websocket.receive_text()
                payload = json.loads(msg)
                if payload.get("type") == "input":
                    os.write(master_fd, payload["data"].encode())
                elif payload.get("type") == "resize":
                    rows = payload.get("rows", 24)
                    cols = payload.get("cols", 80)
                    winsize_data = struct.pack("HHHH", rows, cols, 0, 0)
                    fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize_data)
                    # Explicitly notify tmux of the size change —
                    # TIOCSWINSZ on the master doesn't always deliver
                    # SIGWINCH to the child process group.
                    try:
                        os.kill(proc.pid, signal.SIGWINCH)
                    except OSError:
                        pass
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            done.set()

    try:
        await asyncio.gather(_forward_output(), _forward_input())
    finally:
        done.set()
        try:
            loop.remove_reader(master_fd)
        except Exception:
            pass
        try:
            os.close(master_fd)
        except OSError:
            pass
        # Terminate tmux attach (just detaches, doesn't kill the session)
        proc.terminate()
        try:
            await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=3.0)
        except asyncio.TimeoutError:
            proc.kill()
            await asyncio.to_thread(proc.wait)


# ── Flow management endpoints ────────────────────────────────────────


@app.get("/flows", response_model=List[Flow])
async def list_flows() -> List[Flow]:
    """List all flows."""
    try:
        return flow_service.list_flows()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list flows: {str(e)}",
        )


@app.get("/flows/{name}", response_model=Flow)
async def get_flow(name: str) -> Flow:
    """Get a specific flow by name."""
    try:
        return flow_service.get_flow(name)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get flow: {str(e)}",
        )


@app.post("/flows", response_model=Flow, status_code=status.HTTP_201_CREATED)
async def create_flow(body: CreateFlowRequest) -> Flow:
    """Create a new flow.

    Writes a .flow.md file with YAML frontmatter and prompt body, then
    registers it via flow_service.add_flow().
    """
    try:
        flows_dir = CAO_HOME_DIR / "flows"
        flows_dir.mkdir(parents=True, exist_ok=True)

        file_path = flows_dir / f"{body.name}.flow.md"

        # Build YAML frontmatter content
        frontmatter_lines = [
            "---",
            f"name: {body.name}",
            f'schedule: "{body.schedule}"',
            f"agent_profile: {body.agent_profile}",
            f"provider: {body.provider}",
            "---",
        ]
        file_content = "\n".join(frontmatter_lines) + "\n" + body.prompt_template

        file_path.write_text(file_content)

        return flow_service.add_flow(str(file_path))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create flow: {str(e)}",
        )


@app.delete("/flows/{name}")
async def remove_flow(name: str) -> Dict:
    """Remove a flow."""
    try:
        flow_service.remove_flow(name)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove flow: {str(e)}",
        )


@app.post("/flows/{name}/enable")
async def enable_flow(name: str) -> Dict:
    """Enable a flow."""
    try:
        flow_service.enable_flow(name)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to enable flow: {str(e)}",
        )


@app.post("/flows/{name}/disable")
async def disable_flow(name: str) -> Dict:
    """Disable a flow."""
    try:
        flow_service.disable_flow(name)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disable flow: {str(e)}",
        )


@app.post("/flows/{name}/run")
async def run_flow(name: str) -> Dict:
    """Manually execute a flow."""
    try:
        executed = flow_service.execute_flow(name)
        return {"executed": executed}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute flow: {str(e)}",
        )


# Static file serving for built web UI
WEB_DIST = Path(__file__).parent.parent.parent.parent / "web" / "dist"
if WEB_DIST.exists():
    from starlette.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")


def main():
    """Entry point for cao-server command."""
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description="CLI Agent Orchestrator Server")
    parser.add_argument(
        "--agents-dir",
        type=str,
        default=None,
        help="Path to agents directory (overrides CAO_AGENTS_DIR env var)",
    )
    parser.add_argument("--host", type=str, default=None, help="Server host")
    parser.add_argument("--port", type=int, default=None, help="Server port")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Delete all persisted state (DB, evolution data, logs) and start clean",
    )
    args = parser.parse_args()

    if args.fresh:
        import shutil

        from cli_agent_orchestrator.constants import (
            CAO_HOME_DIR,
            DATABASE_FILE,
            DB_DIR,
            LOG_DIR,
            TERMINAL_LOG_DIR,
        )

        targets = [
            DATABASE_FILE,
            LOG_DIR,
            Path.home() / ".cao-evolution",
            Path("/tmp/cao-grader"),
        ]
        for t in targets:
            if t.exists():
                if t.is_dir():
                    shutil.rmtree(t)
                else:
                    t.unlink()
                logger.info(f"--fresh: removed {t}")

        DB_DIR.mkdir(parents=True, exist_ok=True)
        TERMINAL_LOG_DIR.mkdir(parents=True, exist_ok=True)
        logger.info("--fresh: state cleared, starting clean")

    if args.agents_dir:
        os.environ["CAO_AGENTS_DIR"] = args.agents_dir
        import cli_agent_orchestrator.constants as constants

        constants.KIRO_AGENTS_DIR = Path(args.agents_dir)
        logger.info(f"Using agents directory: {args.agents_dir}")

    host = args.host or SERVER_HOST
    port = args.port or SERVER_PORT
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
