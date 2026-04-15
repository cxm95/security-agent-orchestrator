"""Evolution API routes — appended to the CAO FastAPI app.

Endpoints for score reporting, leaderboard, task management, and knowledge CRUD.
All routes prefixed with /evolution/.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml as _yaml
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from cli_agent_orchestrator.evolution.checkpoint import (
    checkpoint,
    init_checkpoint_repo,
    shared_dir,
)
from cli_agent_orchestrator.evolution.recall_index import RecallIndex
from cli_agent_orchestrator.evolution.attempts import (
    compare_to_history,
    count_evals_since_improvement,
    format_leaderboard,
    get_best_score,
    get_leaderboard,
    read_attempts,
    write_attempt,
)
from cli_agent_orchestrator.evolution.heartbeat import check_triggers
from cli_agent_orchestrator.evolution.types import Attempt, Finding, HumanLabel, Report
from cli_agent_orchestrator.evolution.reports import (
    list_reports,
    read_report,
    report_stats,
    write_report,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/evolution", tags=["evolution"])

EVOLUTION_DIR = os.environ.get("CAO_EVOLUTION_DIR", str(Path.home() / ".cao-evolution"))

# Singleton recall index — built once at startup, updated on each checkpoint
_recall_index: RecallIndex | None = None
_recall_lock = threading.Lock()


def get_recall_index() -> RecallIndex:
    """Return the module-level RecallIndex, building if needed (thread-safe)."""
    global _recall_index
    if _recall_index is None:
        with _recall_lock:
            if _recall_index is None:  # double-check after lock
                idx = RecallIndex(EVOLUTION_DIR)
                idx.build()
                _recall_index = idx
    return _recall_index


def _on_checkpoint_commit(evolution_dir: str, changed_files: list[str]) -> None:
    """Called after each checkpoint commit to update the recall index."""
    global _recall_index
    with _recall_lock:
        if _recall_index is not None:
            knowledge_files = [
                f for f in changed_files
                if f.startswith("notes/") or f.startswith("skills/")
            ]
            if knowledge_files:
                _recall_index.update_incremental(knowledge_files)


def _checkpoint_with_recall(
    agent_id: str = "hub", message: str = "checkpoint"
) -> str | None:
    """Wrapper: checkpoint() + recall index update callback."""
    return checkpoint(
        EVOLUTION_DIR, agent_id, message,
        on_commit=_on_checkpoint_commit,
    )

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_path_id(value: str, name: str = "id") -> str:
    """Reject path traversal in URL path parameters."""
    if not _SAFE_ID_RE.match(value):
        raise HTTPException(400, f"Invalid {name}: must match [a-zA-Z0-9_-]+")
    return value


# ── Pydantic models ─────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    task_id: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = ""
    description: str = ""
    grader_skill: str = Field(default="", pattern=r"^[a-zA-Z0-9_-]*$")  # evo-skill name for grading
    tips: list[str] = []
    eval_data_path: str = ""
    created_by: str = ""
    force: bool = False  # allow overwrite on update (agent-side wins)


class ScoreReport(BaseModel):
    agent_id: str
    score: float | None = None
    score_detail: dict[str, float] | None = None  # multi-dimension scores
    evolution_signals: dict[str, Any] | None = None  # transparent multi-source signals
    title: str = ""
    feedback: str = ""


class HeartbeatPrompt(BaseModel):
    name: str
    prompt: str


class ScoreResponse(BaseModel):
    run_id: str
    status: str
    score: float | None
    score_detail: dict[str, float] | None = None
    evolution_signals: dict[str, Any] | None = None
    best_score: float | None
    leaderboard_position: int | None
    evals_since_improvement: int
    heartbeat_triggered: list[str] = []
    heartbeat_prompts: list[HeartbeatPrompt] = []


class NoteCreate(BaseModel):
    title: str
    content: str
    tags: list[str] = []
    agent_id: str = ""
    origin_task: str = ""
    origin_score: float | None = None
    confidence: str = "medium"


class SkillCreate(BaseModel):
    name: str = Field(..., pattern=r"^[a-zA-Z0-9_-]+$")
    content: str
    tags: list[str] = []
    agent_id: str = ""


class FindingItem(BaseModel):
    finding_id: str = ""
    description: str
    severity: str = "medium"
    file_path: str = ""
    line: int | None = None
    category: str = ""


class ReportSubmit(BaseModel):
    agent_id: str
    terminal_id: str = ""
    findings: list[FindingItem]
    auto_score: float | None = None


class AnnotateBody(BaseModel):
    human_score: float | None = None
    labels: list[dict[str, Any]] = []  # [{finding_id, verdict, severity_override?, comment?}]
    annotated_by: str = ""


# ── Task management ─────────────────────────────────────────────────────

@router.post("/tasks", status_code=201)
async def create_task(body: TaskCreate) -> dict[str, Any]:
    sd = shared_dir(EVOLUTION_DIR)
    task_dir = sd / "tasks" / body.task_id
    exists = task_dir.exists() and (task_dir / "task.yaml").exists()
    if exists and not body.force:
        raise HTTPException(409, f"Task '{body.task_id}' already exists (use force=true to update)")

    # On upsert, merge with existing YAML (agent-side fields override, others preserved)
    existing: dict[str, Any] = {}
    if exists and body.force:
        try:
            existing = _yaml.safe_load((task_dir / "task.yaml").read_text()) or {}
        except Exception:
            existing = {}

    task_dir.mkdir(parents=True, exist_ok=True)
    name = body.name or existing.get("name") or body.task_id
    desc = body.description or existing.get("description", "")
    grader_skill = body.grader_skill or existing.get("grader_skill", "")
    created_by = body.created_by or existing.get("created_by", "")
    eval_data = body.eval_data_path or existing.get("eval_data_path", "")

    task_data: dict[str, Any] = {"name": name, "description": desc}
    if grader_skill:
        task_data["grader_skill"] = grader_skill
    if body.tips:
        task_data["tips"] = list(body.tips)
    if eval_data:
        task_data["eval_data_path"] = eval_data
    if created_by:
        task_data["created_by"] = created_by
    task_data["last_updated"] = datetime.now(timezone.utc).isoformat()
    (task_dir / "task.yaml").write_text(
        _yaml.dump(task_data, allow_unicode=True, default_flow_style=False, sort_keys=False)
    )

    action = "update" if exists else "create"
    _checkpoint_with_recall(created_by or "hub", f"{action} task {body.task_id}")
    return {"task_id": body.task_id, "created": not exists, "updated": exists,
            "grader_skill": grader_skill}


@router.get("/tasks")
async def list_tasks() -> list[dict[str, str]]:
    sd = shared_dir(EVOLUTION_DIR)
    tasks_dir = sd / "tasks"
    if not tasks_dir.exists():
        return []
    result = []
    for d in sorted(tasks_dir.iterdir()):
        if d.is_dir() and (d / "task.yaml").exists():
            result.append({"task_id": d.name, "path": str(d)})
    return result


@router.get("/{task_id}")
async def get_task(task_id: str) -> dict[str, Any]:
    _validate_path_id(task_id, "task_id")
    sd = shared_dir(EVOLUTION_DIR)
    task_dir = sd / "tasks" / task_id
    if not (task_dir / "task.yaml").exists():
        raise HTTPException(404, f"Task '{task_id}' not found")

    info: dict[str, Any] = {"task_id": task_id}
    raw_yaml = (task_dir / "task.yaml").read_text()
    info["task_yaml"] = raw_yaml
    # Parse grader_skill from task.yaml for convenience
    try:
        parsed = _yaml.safe_load(raw_yaml) or {}
    except Exception:
        parsed = {}
    info["grader_skill"] = parsed.get("grader_skill", "")
    attempts = read_attempts(EVOLUTION_DIR, task_id)
    info["attempt_count"] = len(attempts)
    info["best_score"] = get_best_score(EVOLUTION_DIR, task_id)
    return info


# ── Score reporting (core) ───────────────────────────────────────────────

@router.post("/{task_id}/scores", response_model=ScoreResponse)
async def submit_score(task_id: str, body: ScoreReport) -> ScoreResponse:
    _validate_path_id(task_id, "task_id")
    sd = shared_dir(EVOLUTION_DIR)
    if not (sd / "tasks" / task_id).exists():
        # Auto-create task dir for convenience
        (sd / "tasks" / task_id).mkdir(parents=True, exist_ok=True)

    # Determine status by comparing to history
    determined_status = compare_to_history(EVOLUTION_DIR, task_id, body.agent_id, body.score)

    run_id = uuid.uuid4().hex[:12]
    attempt = Attempt(
        run_id=run_id,
        agent_id=body.agent_id,
        task_id=task_id,
        title=body.title,
        score=body.score,
        status=determined_status,
        timestamp=datetime.now(timezone.utc).isoformat(),
        feedback=body.feedback,
        score_detail=body.score_detail,
        evolution_signals=body.evolution_signals,
    )

    write_attempt(EVOLUTION_DIR, attempt)
    sha = _checkpoint_with_recall(body.agent_id, f"score {task_id}: {body.score}")
    if sha:
        attempt.shared_state_hash = sha
        write_attempt(EVOLUTION_DIR, attempt)  # persist the hash

    # Leaderboard position
    lb = get_leaderboard(EVOLUTION_DIR, task_id)
    position = None
    for i, a in enumerate(lb, 1):
        if a.run_id == run_id:
            position = i
            break

    evals_no_improve = count_evals_since_improvement(EVOLUTION_DIR, task_id, body.agent_id)

    # Check heartbeat triggers — count global evals across all tasks
    local_eval_count = len(read_attempts(EVOLUTION_DIR, task_id))
    tasks_dir = Path(EVOLUTION_DIR) / "tasks"
    global_eval_count = 0
    if tasks_dir.exists():
        for td in tasks_dir.iterdir():
            if td.is_dir():
                global_eval_count += len(read_attempts(EVOLUTION_DIR, td.name))
    hb_triggered = check_triggers(
        evo_dir=EVOLUTION_DIR,
        agent_id=body.agent_id,
        task_id=task_id,
        local_eval_count=local_eval_count,
        global_eval_count=global_eval_count,
        evals_since_improvement=evals_no_improve,
        leaderboard=format_leaderboard(lb),
        evolution_signals=body.evolution_signals,
    )
    hb_names = [h["name"] for h in hb_triggered]
    hb_prompts = [HeartbeatPrompt(name=h["name"], prompt=h["prompt"]) for h in hb_triggered]

    return ScoreResponse(
        run_id=run_id,
        status=determined_status,
        score=body.score,
        score_detail=body.score_detail,
        evolution_signals=body.evolution_signals,
        best_score=get_best_score(EVOLUTION_DIR, task_id, body.agent_id),
        leaderboard_position=position,
        evals_since_improvement=evals_no_improve,
        heartbeat_triggered=hb_names,
        heartbeat_prompts=hb_prompts,
    )


# ── Leaderboard & attempts ──────────────────────────────────────────────

@router.get("/{task_id}/leaderboard")
async def leaderboard(task_id: str, top_n: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    _validate_path_id(task_id, "task_id")
    lb = get_leaderboard(EVOLUTION_DIR, task_id, top_n)
    return {
        "task_id": task_id,
        "entries": [a.to_dict() for a in lb],
        "formatted": format_leaderboard(lb),
    }


@router.get("/{task_id}/attempts")
async def list_attempts(task_id: str) -> list[dict[str, Any]]:
    _validate_path_id(task_id, "task_id")
    return [a.to_dict() for a in read_attempts(EVOLUTION_DIR, task_id)]


# ── Knowledge: notes ─────────────────────────────────────────────────────

@router.post("/knowledge/notes", status_code=201)
async def create_note(body: NoteCreate) -> dict[str, Any]:
    sd = shared_dir(EVOLUTION_DIR)
    notes_dir = sd / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename from title
    slug = body.title.lower().replace(" ", "-")[:60]
    slug = "".join(c for c in slug if c.isalnum() or c == "-")
    filename = f"{slug}.md"
    path = notes_dir / filename
    # Avoid collision
    if path.exists():
        filename = f"{slug}-{uuid.uuid4().hex[:6]}.md"
        path = notes_dir / filename

    # Build YAML frontmatter
    fm_lines = [
        "---",
        f"title: \"{body.title}\"",
        f"tags: [{', '.join(body.tags)}]",
    ]
    if body.origin_task:
        fm_lines.append(f"origin_task: {body.origin_task}")
    if body.origin_score is not None:
        fm_lines.append(f"origin_score: {body.origin_score}")
    fm_lines.append(f"confidence: {body.confidence}")
    if body.agent_id:
        fm_lines.append(f"created_by: {body.agent_id}")
    fm_lines.append(f"created_at: {datetime.now(timezone.utc).isoformat()}")
    fm_lines.append("---")

    path.write_text("\n".join(fm_lines) + "\n" + body.content + "\n")
    _checkpoint_with_recall(body.agent_id or "hub", f"note: {body.title}")

    return {"filename": filename, "path": str(path)}


@router.get("/knowledge/notes")
async def list_notes(tags: str = Query("", description="Comma-separated tags to filter")) -> list[dict[str, Any]]:
    sd = shared_dir(EVOLUTION_DIR)
    notes_dir = sd / "notes"
    if not notes_dir.exists():
        return []

    tag_filter = {t.strip().lower() for t in tags.split(",") if t.strip()} if tags else set()
    results = []

    for f in sorted(notes_dir.glob("*.md")):
        text = f.read_text()
        meta = _parse_frontmatter(text)
        if tag_filter:
            note_tags = {t.strip().lower() for t in meta.get("tags", "").split(",")}
            if not tag_filter & note_tags:
                continue
        results.append({"filename": f.name, "meta": meta, "content": _body_after_frontmatter(text)})

    return results


# ── Knowledge: skills ────────────────────────────────────────────────────

@router.post("/knowledge/skills", status_code=201)
async def create_skill(body: SkillCreate) -> dict[str, Any]:
    sd = shared_dir(EVOLUTION_DIR)
    skill_dir = sd / "skills" / body.name
    skill_dir.mkdir(parents=True, exist_ok=True)

    path = skill_dir / "SKILL.md"
    fm_lines = [
        "---",
        f"name: \"{body.name}\"",
        f"tags: [{', '.join(body.tags)}]",
    ]
    if body.agent_id:
        fm_lines.append(f"created_by: {body.agent_id}")
    fm_lines.append(f"created_at: {datetime.now(timezone.utc).isoformat()}")
    fm_lines.append("---")

    path.write_text("\n".join(fm_lines) + "\n" + body.content + "\n")
    _checkpoint_with_recall(body.agent_id or "hub", f"skill: {body.name}")

    return {"name": body.name, "path": str(path)}


@router.get("/knowledge/skills")
async def list_skills() -> list[dict[str, Any]]:
    sd = shared_dir(EVOLUTION_DIR)
    skills_dir = sd / "skills"
    if not skills_dir.exists():
        return []

    results = []
    for d in sorted(skills_dir.iterdir()):
        skill_file = d / "SKILL.md"
        if d.is_dir() and skill_file.exists():
            text = skill_file.read_text()
            results.append({
                "name": d.name,
                "meta": _parse_frontmatter(text),
                "content": _body_after_frontmatter(text),
            })
    return results


# ── Knowledge: search (phase 1 — grep + tags) ───────────────────────────

@router.get("/knowledge/search")
async def search_knowledge(
    query: str = Query(..., min_length=1, max_length=500),
    tags: str = Query("", description="Comma-separated tags"),
    top_k: int = Query(10, ge=1, le=50),
) -> list[dict[str, Any]]:
    """Phase 1: simple text search + tag filter over notes and skills."""
    sd = shared_dir(EVOLUTION_DIR)
    tag_filter = {t.strip().lower() for t in tags.split(",") if t.strip()} if tags else set()
    query_lower = query.lower()
    results = []

    # Search notes
    notes_dir = sd / "notes"
    if notes_dir.exists():
        for f in notes_dir.rglob("*.md"):
            text = f.read_text()
            if query_lower not in text.lower():
                continue
            meta = _parse_frontmatter(text)
            if tag_filter:
                note_tags = {t.strip().lower() for t in meta.get("tags", "").split(",")}
                if not tag_filter & note_tags:
                    continue
            results.append({
                "type": "note",
                "filename": f.name,
                "meta": meta,
                "snippet": _snippet(text, query_lower),
            })

    # Search skills
    skills_dir = sd / "skills"
    if skills_dir.exists():
        for f in skills_dir.rglob("SKILL.md"):
            text = f.read_text()
            if query_lower not in text.lower():
                continue
            meta = _parse_frontmatter(text)
            results.append({
                "type": "skill",
                "name": f.parent.name,
                "meta": meta,
                "snippet": _snippet(text, query_lower),
            })

    return results[:top_k]


# ── Reports: human feedback ──────────────────────────────────────────────

@router.post("/{task_id}/reports", status_code=201)
async def submit_report(task_id: str, body: ReportSubmit) -> dict[str, Any]:
    """Agent submits a vulnerability report → returns report_id."""
    _validate_path_id(task_id, "task_id")
    sd = shared_dir(EVOLUTION_DIR)
    if not (sd / "tasks" / task_id).exists():
        (sd / "tasks" / task_id).mkdir(parents=True, exist_ok=True)

    report_id = uuid.uuid4().hex[:12]
    findings = [
        Finding(
            finding_id=f.finding_id or f"f-{i}",
            description=f.description,
            severity=f.severity,
            file_path=f.file_path,
            line=f.line,
            category=f.category,
        )
        for i, f in enumerate(body.findings)
    ]
    report = Report(
        report_id=report_id,
        task_id=task_id,
        agent_id=body.agent_id,
        terminal_id=body.terminal_id,
        findings=findings,
        auto_score=body.auto_score,
        submitted_at=datetime.now(timezone.utc).isoformat(),
    )
    write_report(EVOLUTION_DIR, report)
    _checkpoint_with_recall(body.agent_id, f"report {report_id} for {task_id}")
    return {"report_id": report_id, "finding_count": len(findings)}


@router.get("/{task_id}/reports")
async def get_reports(
    task_id: str,
    terminal_id: str = Query("", description="Filter by terminal ID"),
    status: str = Query("", description="Filter by status: pending|annotated"),
) -> list[dict[str, Any]]:
    """List reports for a task, optionally filtered by terminal_id / status."""
    _validate_path_id(task_id, "task_id")
    reports = list_reports(
        EVOLUTION_DIR,
        task_id=task_id,
        terminal_id=terminal_id or None,
        status=status or None,
    )
    return [r.to_dict() for r in reports]


@router.put("/{task_id}/reports/{report_id}/annotate")
async def annotate_report(task_id: str, report_id: str, body: AnnotateBody) -> dict[str, str]:
    """Human annotates a report with labels (tp/fp/uncertain per finding)."""
    _validate_path_id(task_id, "task_id")
    _validate_path_id(report_id, "report_id")
    report = read_report(EVOLUTION_DIR, task_id, report_id)
    if report is None:
        raise HTTPException(404, f"Report '{report_id}' not found")

    report.human_score = body.human_score
    report.human_labels = [
        HumanLabel(
            finding_id=lb.get("finding_id", ""),
            verdict=lb.get("verdict", "uncertain"),
            severity_override=lb.get("severity_override"),
            comment=lb.get("comment", ""),
            annotated_by=body.annotated_by,
        )
        for lb in body.labels
    ]
    report.status = "annotated"
    report.annotated_at = datetime.now(timezone.utc).isoformat()
    write_report(EVOLUTION_DIR, report)

    # Write .result file for heartbeat/grader consumption
    import json as _json
    result_data = {
        "report_id": report_id,
        "human_score": report.human_score,
        "human_labels": [l.to_dict() for l in report.human_labels],
        "annotated_at": report.annotated_at,
    }
    result_dir = shared_dir(EVOLUTION_DIR) / "reports" / task_id
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / f"{report_id}.result").write_text(_json.dumps(result_data, indent=2))

    _checkpoint_with_recall("human", f"annotate report {report_id}")
    return {"status": "annotated", "report_id": report_id}


@router.get("/{task_id}/reports/stats")
async def get_report_stats(task_id: str) -> dict[str, Any]:
    """Aggregate stats for reports of a task."""
    _validate_path_id(task_id, "task_id")
    return report_stats(EVOLUTION_DIR, task_id=task_id)


@router.get("/{task_id}/reports/{report_id}/result")
async def get_report_result(task_id: str, report_id: str) -> dict[str, Any]:
    """Get a single report's annotation result (for .result file generation)."""
    _validate_path_id(task_id, "task_id")
    _validate_path_id(report_id, "report_id")
    report = read_report(EVOLUTION_DIR, task_id, report_id)
    if report is None:
        raise HTTPException(404, f"Report '{report_id}' not found")
    if report.status != "annotated":
        raise HTTPException(404, f"Report '{report_id}' not yet annotated")
    return {
        "report_id": report_id,
        "human_score": report.human_score,
        "human_labels": [l.to_dict() for l in report.human_labels],
        "annotated_at": report.annotated_at,
    }


# ── Helpers ──────────────────────────────────────────────────────────────

def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract YAML frontmatter key-value pairs (simple line-based parsing)."""
    if not text.startswith("---"):
        return {}
    lines = text.split("\n")
    meta: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip()] = val.strip().strip('"').strip("[").strip("]")
    return meta


def _body_after_frontmatter(text: str) -> str:
    """Return content after the closing --- of frontmatter."""
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    return parts[2].strip() if len(parts) >= 3 else ""


def _snippet(text: str, query: str, context: int = 80) -> str:
    """Return a snippet around the first match of query in text."""
    idx = text.lower().find(query)
    if idx < 0:
        return text[:context]
    start = max(0, idx - context // 2)
    end = min(len(text), idx + len(query) + context // 2)
    return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")


# ── Heartbeat config endpoints ───────────────────────────────────────────

from cli_agent_orchestrator.evolution.heartbeat import (
    get_default_actions,
    read_heartbeat_config,
    write_heartbeat_config,
)


@router.get("/heartbeat/{agent_id}")
async def get_heartbeat_config(agent_id: str) -> dict[str, Any]:
    """Get heartbeat config for an agent (or '_global')."""
    actions = read_heartbeat_config(EVOLUTION_DIR, agent_id)
    if not actions:
        actions = get_default_actions()
    return {"agent_id": agent_id, "actions": actions}


@router.put("/heartbeat/{agent_id}")
async def set_heartbeat_config(agent_id: str, body: dict[str, Any]) -> dict[str, str]:
    """Set heartbeat config for an agent (or '_global')."""
    write_heartbeat_config(EVOLUTION_DIR, agent_id, body.get("actions", []))
    return {"status": "ok"}


# ── Init helper (called by main.py lifespan) ────────────────────────────

def ensure_evolution_repo() -> None:
    """Initialize the shared evolution repo if it doesn't exist yet."""
    init_checkpoint_repo(EVOLUTION_DIR)


# ── Recall (BM25-based knowledge search) ─────────────────────────────────

@router.get("/knowledge/recall")
async def recall_knowledge(
    query: str = Query(..., min_length=1, max_length=500),
    tags: str = Query("", description="Comma-separated tags to filter"),
    top_k: int = Query(10, ge=1, le=50),
    include_content: bool = Query(
        False, description="Include full document content in results"
    ),
) -> list[dict[str, Any]]:
    """BM25-ranked knowledge recall over notes and skills.

    More precise than /knowledge/search — results ranked by relevance.
    Set include_content=True to get full document body (selective sync).
    """
    index = get_recall_index()
    tag_filter = (
        {t.strip().lower() for t in tags.split(",") if t.strip()}
        if tags else None
    )
    results = index.query(query, tags=tag_filter, top_k=top_k)
    out = []
    for r in results:
        d = r.to_dict()
        if include_content:
            doc = index.get_document(r.doc_id)
            d["content"] = doc.body if doc else ""
        out.append(d)
    return out


@router.get("/knowledge/document/{doc_id:path}")
async def get_knowledge_document(doc_id: str) -> dict[str, Any]:
    """Fetch a specific document by ID (selective sync).

    doc_id format: 'note:<stem>' or 'skill:<name>'.
    """
    if not doc_id or ".." in doc_id:
        raise HTTPException(400, "Invalid doc_id")
    index = get_recall_index()
    doc = index.get_document(doc_id)
    if doc is None:
        raise HTTPException(404, f"Document not found: {doc_id}")
    return {
        "doc_id": doc.doc_id,
        "type": doc.doc_type,
        "path": doc.path,
        "title": doc.title,
        "tags": doc.tags,
        "meta": doc.meta,
        "content": doc.body,
    }


@router.post("/knowledge/recall/rebuild")
async def rebuild_recall_index() -> dict[str, Any]:
    """Force full rebuild of the recall index."""
    index = get_recall_index()
    count = index.build()
    return {"status": "ok", "documents_indexed": count}
