#!/usr/bin/env python3
"""MCP tool server: structured directory contexts for CAO multi-agent phase workflows.

Directory layout managed by this server:

    {session_root}/
    ├── global/                     # shared across all tasks/runners
    ├── tasks/                      # task list files (e.g. task.json)
    ├── workflow.json               # phase definitions + dependency graph
    └── {task_index}/               # 0, 1, 2 … N-1
        ├── meta/                   # task-level metadata JSONs
        └── {phase}/                # phase private working directory
            └── out/                # phase output directory

Context parameters (global_folder, working_directory, output_folder,
input_folder, input_folders, metadata_folder) are returned by
prepare_phase_context and meant to be forwarded to CAO handoff/assign.
"""

import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastmcp import FastMCP
from pydantic import Field

logger = logging.getLogger(__name__)

DEFAULT_SESSION_ROOT = Path.home() / ".cao" / "sessions"
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_CODEX_RESUME_RE = re.compile(r"codex\s+resume\s+([0-9a-fA-F-]{16,})")

# ---------------------------------------------------------------------------
# Skill detection
# ---------------------------------------------------------------------------

CLAUDE_SKILLS_ROOT = Path.home() / ".claude" / "skills"
CODEX_SKILLS_ROOT = Path.home() / ".codex" / "skills"

PROVIDER_SKILL_PATHS = {
    "claude": CLAUDE_SKILLS_ROOT,
    "opencode": CLAUDE_SKILLS_ROOT,  # OpenCode shares ~/.claude/skills
    "codex": CODEX_SKILLS_ROOT,
}


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _terminal_log_path(terminal_id: str) -> Path:
    return (
        Path.home()
        / ".aws"
        / "cli-agent-orchestrator"
        / "logs"
        / "terminal"
        / f"{terminal_id}.log"
    )


def _extract_codex_session_id(text: str) -> Optional[str]:
    m = _CODEX_RESUME_RE.search(text)
    return m.group(1) if m else None


mcp = FastMCP(
    "cao-task-context",
    instructions=(
        "Manage structured directory contexts for CAO multi-agent phase workflows. "
        "Provides session initialization, workflow management, phase context preparation, "
        "metadata writing, cleanup, and provider session archival."
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_session_root(session_root: Optional[str] = None) -> Path:
    """Resolve session root. Priority: explicit param > env > default."""
    if session_root:
        return Path(session_root).expanduser().resolve()
    raw = os.environ.get("CAO_SESSION_ROOT")
    return Path(raw).expanduser().resolve() if raw else DEFAULT_SESSION_ROOT.resolve()


def _validate_name(value: str, label: str) -> str:
    if not value or not SAFE_NAME_RE.fullmatch(value):
        raise ValueError(
            f"Invalid {label}: '{value}'. Only letters, digits, '.', '_', '-' allowed."
        )
    return value


def _validate_task_index(value: str) -> str:
    """Validate task index is a non-negative integer string."""
    if not value.isdigit():
        raise ValueError(
            f"Invalid task_index: '{value}'. Must be a non-negative integer string."
        )
    return value


def _global_dir(session_root: Optional[str] = None) -> Path:
    return _resolve_session_root(session_root) / "global"


def _task_dir(task_index: str, session_root: Optional[str] = None) -> Path:
    return _resolve_session_root(session_root) / _validate_task_index(task_index)


def _phase_dir(task_index: str, phase: str, session_root: Optional[str] = None) -> Path:
    return _task_dir(task_index, session_root) / _validate_name(phase, "phase")


def _output_dir(task_index: str, phase: str, session_root: Optional[str] = None) -> Path:
    return _phase_dir(task_index, phase, session_root) / "out"


def _meta_dir(task_index: str, session_root: Optional[str] = None) -> Path:
    return _task_dir(task_index, session_root) / "meta"


def _workflow_path(session_root: Optional[str] = None) -> Path:
    return _resolve_session_root(session_root) / "workflow.json"


def _resolve_workflow_root(
    workflow_root: Optional[str],
    session_name: Optional[str] = None,
    session_root: Optional[str] = None,
) -> Path:
    """Resolve workflow root directory. Priority: param > WORKFLOW_ROOT_DIR env."""
    if workflow_root:
        return Path(workflow_root).expanduser().resolve()
    env_root = os.environ.get("WORKFLOW_ROOT_DIR")
    if env_root:
        return Path(env_root).expanduser().resolve()
    raise ValueError(
        "workflow_root not provided and WORKFLOW_ROOT_DIR env var not set."
    )




def _load_workflow(session_root: Optional[str] = None) -> Dict[str, Any]:
    wf_path = _workflow_path(session_root)
    if not wf_path.exists():
        raise ValueError(f"workflow.json not found: {wf_path}. Call init_session first.")
    return json.loads(wf_path.read_text())


def _get_phase_def(workflow: Dict[str, Any], phase: str) -> Dict[str, Any]:
    for p in workflow["phases"]:
        if p["name"] == phase:
            return p
    raise ValueError(
        f"Phase '{phase}' not defined in workflow.json. "
        f"Defined phases: {[p['name'] for p in workflow['phases']]}"
    )


# ---------------------------------------------------------------------------
# Core logic (pure functions, easy to test)
# ---------------------------------------------------------------------------

def _init_session(
    session_name: str,
    phases: List[Dict[str, Any]],
    session_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Initialize a session: create root, global/, workflow.json."""
    _validate_name(session_name, "session_name")

    # Validate phase definitions
    defined_names: List[str] = []
    for p in phases:
        name = _validate_name(p["name"], "phase.name")
        _validate_name(p["agent"], "phase.agent")
        for dep in p.get("depends_on", []):
            if dep not in defined_names:
                raise ValueError(
                    f"Phase '{name}' depends on '{dep}', but '{dep}' is not defined before it."
                )
        defined_names.append(name)

    root = _resolve_session_root(session_root)
    root.mkdir(parents=True, exist_ok=True)

    global_folder = _global_dir(session_root)
    global_folder.mkdir(parents=True, exist_ok=True)

    tasks_folder = root / "tasks"
    tasks_folder.mkdir(parents=True, exist_ok=True)

    # Write workflow.json
    workflow = {
        "session_name": session_name,
        "phases": phases,
        "_created_at": datetime.now(timezone.utc).isoformat(),
    }
    _workflow_path(session_root).write_text(json.dumps(workflow, ensure_ascii=False, indent=2))

    return {
        "session_root": str(root),
        "global_folder": str(global_folder),
        "tasks_folder": str(tasks_folder),
        "workflow_path": str(_workflow_path(session_root)),
        "phases": [p["name"] for p in phases],
    }


def _prepare_task(task_index: str, session_root: Optional[str] = None) -> Dict[str, Any]:
    """Create task directory and meta/ subdirectory."""
    task_index = _validate_task_index(task_index)
    task_path = _task_dir(task_index, session_root)
    meta_path = _meta_dir(task_index, session_root)
    task_path.mkdir(parents=True, exist_ok=True)
    meta_path.mkdir(parents=True, exist_ok=True)
    return {
        "task_index": task_index,
        "task_dir": str(task_path),
        "metadata_folder": str(meta_path),
    }


def _prepare_phase_context(
    task_index: str,
    phase: str,
    target_id: str = "",
    session_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Create phase working directory structure and resolve dependencies.

    Returns all paths needed for CAO handoff/assign context parameters.
    """
    task_index = _validate_task_index(task_index)
    phase = _validate_name(phase, "phase")

    workflow = _load_workflow(session_root)
    phase_def = _get_phase_def(workflow, phase)
    depends_on: List[str] = phase_def.get("depends_on", [])

    global_folder = _global_dir(session_root)
    meta_folder = _meta_dir(task_index, session_root)
    meta_folder.mkdir(parents=True, exist_ok=True)

    working_directory = _phase_dir(task_index, phase, session_root)
    output_folder = _output_dir(task_index, phase, session_root)
    working_directory.mkdir(parents=True, exist_ok=True)
    output_folder.mkdir(parents=True, exist_ok=True)

    # Resolve upstream input folders
    input_folders: Dict[str, str] = {}
    for upstream in depends_on:
        upstream_out = _output_dir(task_index, upstream, session_root)
        if not upstream_out.exists():
            # Fallback: check global/{phase}/out then global/{phase}
            global_phase_out = _global_dir(session_root) / upstream / "out"
            global_phase_dir = _global_dir(session_root) / upstream
            if global_phase_out.exists():
                upstream_out = global_phase_out
            elif global_phase_dir.exists():
                upstream_out = global_phase_dir
            else:
                # Upstream phase was skipped — record as missing but do not fail
                logger.warning(
                    "Upstream phase '%s' output dir does not exist: "
                    "checked %s and %s. Phase may have been skipped.",
                    upstream, _output_dir(task_index, upstream, session_root), global_phase_out,
                )
                continue
        input_folders[upstream] = str(upstream_out)

    primary_input = input_folders.get(depends_on[-1]) if depends_on else None

    return {
        "task_index": task_index,
        "target_id": target_id,
        "phase": phase,
        "agent": phase_def["agent"],
        "global_folder": str(global_folder),
        "working_directory": str(working_directory),
        "output_folder": str(output_folder),
        "metadata_folder": str(meta_folder),
        "input_folder": primary_input,
        "input_folders": input_folders,
    }


def _write_meta(task_index: str, key: str, data: Dict[str, Any], session_root: Optional[str] = None) -> Dict[str, Any]:
    task_index = _validate_task_index(task_index)
    key = _validate_name(key, "key")
    meta_folder = _meta_dir(task_index, session_root)
    meta_folder.mkdir(parents=True, exist_ok=True)
    filepath = meta_folder / f"{key}.json"
    # Merge with existing file if present (update semantics)
    existing: Dict[str, Any] = {}
    if filepath.exists():
        try:
            existing = json.loads(filepath.read_text())
        except (json.JSONDecodeError, OSError):
            existing = {}
    now = datetime.now(timezone.utc).isoformat()
    if "_assigned_at" not in existing:
        data.setdefault("_assigned_at", now)
    payload = {**existing, **data, "_updated_at": now}
    filepath.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return {"path": str(filepath), "written": True}


def _cleanup_phase(task_index: str, phase: str, session_root: Optional[str] = None) -> Dict[str, Any]:
    task_index = _validate_task_index(task_index)
    phase = _validate_name(phase, "phase")
    phase_path = _phase_dir(task_index, phase, session_root)
    existed = phase_path.exists()
    if existed:
        shutil.rmtree(phase_path)
    return {"task_index": task_index, "phase": phase, "path": str(phase_path), "deleted": existed}


def _cleanup_task(task_index: str, session_root: Optional[str] = None) -> Dict[str, Any]:
    task_index = _validate_task_index(task_index)
    root = _task_dir(task_index, session_root)
    existed = root.exists()
    if existed:
        shutil.rmtree(root)
    return {"task_index": task_index, "path": str(root), "deleted": existed}


def _list_tasks(session_root: Optional[str] = None) -> Dict[str, Any]:
    """List all task directories under session root with their phase status."""
    root = _resolve_session_root(session_root)
    if not root.exists():
        return {"session_root": str(root), "tasks": []}

    tasks = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and entry.name.isdigit():
            task_index = entry.name
            phases = []
            for phase_entry in sorted(entry.iterdir()):
                if phase_entry.is_dir() and phase_entry.name != "meta":
                    out_dir = phase_entry / "out"
                    has_output = out_dir.exists() and any(out_dir.iterdir()) if out_dir.exists() else False
                    phases.append({
                        "phase": phase_entry.name,
                        "has_output": has_output,
                        "working_directory": str(phase_entry),
                    })
            meta_dir = entry / "meta"
            meta_files = []
            if meta_dir.exists():
                meta_files = [f.name for f in sorted(meta_dir.iterdir()) if f.is_file()]
            tasks.append({
                "task_index": task_index,
                "path": str(entry),
                "phases": phases,
                "meta_files": meta_files,
            })

    return {"session_root": str(root), "tasks": tasks}


def _archive_provider_session(
    task_index: str,
    phase: str,
    provider: str,
    terminal_id: str,
    display_name: Optional[str] = None,
    session_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Archive provider resumable session info to task meta."""
    task_index = _validate_task_index(task_index)
    phase = _validate_name(phase, "phase")

    log_path = _terminal_log_path(terminal_id)
    found = False
    session_id: Optional[str] = None
    resume_command: Optional[str] = None
    reason: Optional[str] = None

    if log_path.exists():
        raw = log_path.read_text(errors="ignore")
        cleaned = _strip_ansi(raw)
        if provider == "codex":
            session_id = _extract_codex_session_id(cleaned)
            if session_id:
                found = True
                resume_command = f"codex resume {session_id}"
            else:
                reason = "resume marker not found"
        elif provider == "open_code":
            found = True
            resume_command = "opencode --continue"
            reason = "opencode session archived (log-based)"
        else:
            reason = "provider not supported"
    else:
        reason = "terminal log not found"

    payload: Dict[str, Any] = {
        "provider": provider,
        "terminal_id": terminal_id,
        "display_name": display_name,
        "log_path": str(log_path),
        "found": found,
    }
    if session_id:
        payload["session_id"] = session_id
        payload["resume_command"] = resume_command
    if reason:
        payload["reason"] = reason

    key = f"{phase}_provider_session"
    return _write_meta(task_index, key, payload, session_root=session_root)


def _get_required_skills_impl(
    session_name: str,
    workflow_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Scan workflow_root/skills/ for required skills and installation status."""
    try:
        skills_root = _resolve_workflow_root(workflow_root, session_name)
        skills_dir = skills_root / "skills"
        skills_file = skills_dir / "skills.json"

        if not skills_file.is_file():
            return {
                "success": False,
                "skills": [],
                "message": f"skills.json not found at {skills_root}.",
            }

        skills_data = json.loads(skills_file.read_text())
        skill_entries = skills_data.get("skills", [])

        missing: List[str] = []
        missing_names: List[str] = []
        installed: List[str] = []

        for entry in skill_entries:
            name = entry.get("name")
            skill_type = entry.get("type", "name_only")
            source = entry.get("source", "")

            # Check installed status for each provider
            provider_missing: List[str] = []
            for provider, skill_root in PROVIDER_SKILL_PATHS.items():
                if not (skill_root / name / "SKILL.md").is_file():
                    provider_missing.append(provider)

            # Only report missing if ALL providers are missing the skill
            if len(provider_missing) == len(PROVIDER_SKILL_PATHS):
                hint_parts = []
                if skill_type == "local_folder":
                    hint_parts.append(f"本地路径: {skills_dir / name}")
                if source:
                    hint_parts.append(f"安装命令: {source}")
                hint = " | ".join(hint_parts) if hint_parts else ""
                detail = f"{name} (type={skill_type})"
                if hint:
                    detail += f" | {hint}"
                missing.append(detail)
                missing_names.append(name)
            else:
                installed.append(name)

        # Build message
        lines = ["[CAO Skills] 当前 workflow 技能状态：", ""]
        if installed:
            lines.append(f"✅ 已安装 ({len(installed)}): {', '.join(installed)}")
        if missing:
            lines.append(f"❌ 未安装 ({len(missing)}):")
            for m in missing:
                lines.append(f"- {m}")
        lines.append("")
        lines.append("请安装缺失的技能后继续。")

        return {
            "success": True,
            "workflow_root": str(skills_root),
            "installed": installed,
            "missing": missing_names,
            "message": "\n".join(lines),
        }

    except Exception as e:
        return {"success": False, "skills": [], "message": f"Error: {str(e)}"}


# ---------------------------------------------------------------------------
# MCP tool registrations
# ---------------------------------------------------------------------------

_SESSION_ROOT_FIELD = Field(
    description=(
        "Session root directory path (REQUIRED). "
        "Use the session_root value returned by init_session."
    ),
)


@mcp.tool()
async def init_session(
    session_name: str = Field(
        description="Session identifier, e.g. 'cao-task-20260330'"
    ),
    session_root: str = Field(
        description=(
            "Session root directory path (REQUIRED). "
            "Pass the value from [Session Config] CAO_SESSION_ROOT."
        )
    ),
    workflow_root: str = Field(
        description=(
            "Workflow project root directory (REQUIRED). "
            "Contains workflow.json, skills/, assets/. "
            "Pass the value from [Session Config] WORKFLOW_ROOT_DIR."
        )
    ),
    phases: str = Field(
        default="",
        description=(
            'Workflow phases as JSON array. Each element: '
            '{"name":"phase1","agent":"phase1_agent","depends_on":[]}. '
            'Must be in topological order. '
            'If empty/omitted, auto-loads from workflow_root/workflow.json.'
        )
    ),
) -> Dict[str, Any]:
    """Initialize a workflow session: creates root dir, global/, tasks/, workflow.json.

    Returns session_root which should be passed to all subsequent tool calls.
    """
    if phases and phases.strip():
        phase_list = json.loads(phases)
    else:
        wf_root = _resolve_workflow_root(workflow_root, session_name, session_root=session_root)
        wf_file = wf_root / "workflow.json"
        if not wf_file.exists():
            raise ValueError(
                f"phases not provided and workflow.json not found at {wf_file}. "
                f"Either pass phases parameter or set workflow_root."
            )
        wf_data = json.loads(wf_file.read_text())
        phase_list = wf_data.get("phases", [])
    return _init_session(session_name, phase_list, session_root=session_root)


@mcp.tool()
async def get_workflow(
    session_root: str = _SESSION_ROOT_FIELD,
) -> Dict[str, Any]:
    """Read and return the current workflow.json."""
    return _load_workflow(session_root)


@mcp.tool()
async def prepare_task(
    task_index: str = Field(description="Task index (non-negative integer), e.g. '0', '1'"),
    session_root: str = _SESSION_ROOT_FIELD,
) -> Dict[str, Any]:
    """Create task directory and meta/ subdirectory for a given task index."""
    return _prepare_task(task_index, session_root=session_root)


@mcp.tool()
async def prepare_phase_context(
    task_index: str = Field(description="Task index, e.g. '0'"),
    phase: str = Field(description="Phase name, e.g. 'phase1'"),
    session_root: str = _SESSION_ROOT_FIELD,
    target_id: str = Field(default="", description="Target identifier for reference"),
) -> Dict[str, Any]:
    """Prepare phase working directory and resolve upstream dependencies.

    Creates: {task_index}/{phase}/, {task_index}/{phase}/out/
    Returns all context paths needed for CAO handoff/assign.
    """
    return _prepare_phase_context(task_index, phase, target_id, session_root=session_root)


@mcp.tool()
async def write_task_meta(
    task_index: str = Field(description="Task index, e.g. '0'"),
    key: str = Field(description="Metadata filename (without .json)"),
    data: str = Field(description="JSON string of metadata to write"),
    session_root: str = _SESSION_ROOT_FIELD,
) -> Dict[str, Any]:
    """Write a metadata JSON file to {task_index}/meta/{key}.json."""
    return _write_meta(task_index, key, json.loads(data), session_root=session_root)


@mcp.tool()
async def cleanup_phase(
    task_index: str = Field(description="Task index"),
    phase: str = Field(description="Phase name to clean up"),
    session_root: str = _SESSION_ROOT_FIELD,
) -> Dict[str, Any]:
    """Remove a phase directory and all its contents."""
    return _cleanup_phase(task_index, phase, session_root=session_root)


@mcp.tool()
async def cleanup_task(
    task_index: str = Field(description="Task index to clean up"),
    session_root: str = _SESSION_ROOT_FIELD,
) -> Dict[str, Any]:
    """Remove an entire task directory and all its contents."""
    return _cleanup_task(task_index, session_root=session_root)


@mcp.tool()
async def list_tasks(
    session_root: str = _SESSION_ROOT_FIELD,
) -> Dict[str, Any]:
    """List all task directories under the session root with phase status."""
    return _list_tasks(session_root=session_root)


@mcp.tool()
async def archive_provider_session(
    task_index: str = Field(description="Task index, e.g. '0'"),
    phase: str = Field(description="Phase name, e.g. 'phase1'"),
    provider: str = Field(description="Provider name, e.g. 'codex', 'open_code'"),
    terminal_id: str = Field(description="CAO terminal_id (8-hex)"),
    session_root: str = _SESSION_ROOT_FIELD,
    display_name: Optional[str] = Field(
        default=None, description="Optional display name, e.g. 'runner-1/task-0/phase1'"
    ),
) -> Dict[str, Any]:
    """Archive provider resumable session info to task meta/{phase}_provider_session.json."""
    return _archive_provider_session(
        task_index, phase, provider, terminal_id, display_name, session_root=session_root
    )


@mcp.tool()
async def get_required_skills(
    session_name: str = Field(
        description="Session name，用于标识当前 workflow"
    ),
    workflow_root: str = Field(
        description=(
            "Workflow project root directory (REQUIRED). "
            "Contains skills/skills.json and skills/{name}/SKILL.md. "
            "Pass the value from [Session Config] WORKFLOW_ROOT_DIR."
        )
    ),
    session_root: str = _SESSION_ROOT_FIELD,
) -> Dict[str, Any]:
    """扫描当前 workflow 所需的技能列表，返回技能定义并提示 agent 检查安装状态。

    在任务执行开始之前，请先调用此工具检查 skill 是否完成准备。

    读取 {workflow_root}/skills/skills.json，按其中的技能名称扫描
    {workflow_root}/skills/{skill_name}/SKILL.md，与各 provider 的
    技能安装路径比对是否已安装，返回绝对路径列表及安装状态。

    Provider 技能安装路径：
    - Claude / OpenCode: ~/.claude/skills/{name}/SKILL.md
    - Codex: ~/.codex/skills/{name}/SKILL.md

    所有路径均为绝对路径。
    """
    return _get_required_skills_impl(session_name, workflow_root)


def main() -> None:
    """Run cao-task-context as an SSE MCP server.

    Port is configurable via:
      --port CLI arg  >  CAO_TASK_CONTEXT_PORT env  >  default 9890
    Host is configurable via:
      --host CLI arg  >  default 127.0.0.1
    """
    import argparse

    parser = argparse.ArgumentParser(description="cao-task-context MCP server (SSE)")
    parser.add_argument(
        "--port", type=int,
        default=int(os.environ.get("CAO_TASK_CONTEXT_PORT", "9890")),
        help="SSE server port (default: 9890, env: CAO_TASK_CONTEXT_PORT)",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="SSE server bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--transport", choices=["sse", "stdio"], default="sse",
        help="MCP transport mode (default: sse)",
    )
    args = parser.parse_args()

    if args.transport == "sse":
        logger.info(f"Starting cao-task-context SSE server on {args.host}:{args.port}")
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
