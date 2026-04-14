"""Reports storage — CRUD for human-feedback reports.

Reports are stored as JSON files under .cao-evolution/reports/{task_id}/{report_id}.json.
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from cli_agent_orchestrator.evolution.checkpoint import shared_dir
from cli_agent_orchestrator.evolution.types import Report

_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_id(value: str, name: str = "id") -> str:
    if not _SAFE_ID.match(value):
        raise ValueError(f"Invalid {name}: must be alphanumeric/dash/underscore, got '{value}'")
    return value


def _reports_dir(evo_dir: str, task_id: str) -> Path:
    _validate_id(task_id, "task_id")
    return shared_dir(evo_dir) / "reports" / task_id


def _atomic_write(path: Path, data: str) -> None:
    """Write data to file atomically via temp-file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        import os
        os.write(fd, data.encode())
        os.close(fd)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_report(evo_dir: str, report: Report) -> Path:
    d = _reports_dir(evo_dir, report.task_id)
    _validate_id(report.report_id, "report_id")
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{report.report_id}.json"
    _atomic_write(path, json.dumps(report.to_dict(), indent=2))
    return path


def read_report(evo_dir: str, task_id: str, report_id: str) -> Report | None:
    _validate_id(report_id, "report_id")
    path = _reports_dir(evo_dir, task_id) / f"{report_id}.json"
    if not path.exists():
        return None
    return Report.from_dict(json.loads(path.read_text()))


def list_reports(
    evo_dir: str,
    task_id: str | None = None,
    terminal_id: str | None = None,
    status: str | None = None,
) -> list[Report]:
    """List reports with optional filters."""
    base = shared_dir(evo_dir) / "reports"
    if not base.exists():
        return []

    task_dirs = [base / _validate_id(task_id, "task_id")] if task_id else sorted(base.iterdir())
    results: list[Report] = []

    for td in task_dirs:
        if not td.is_dir():
            continue
        for f in sorted(td.glob("*.json")):
            try:
                r = Report.from_dict(json.loads(f.read_text()))
            except (json.JSONDecodeError, KeyError):
                continue
            if terminal_id and r.terminal_id != terminal_id:
                continue
            if status and r.status != status:
                continue
            results.append(r)

    return results


def report_stats(evo_dir: str, task_id: str | None = None) -> dict:
    """Compute aggregate stats across reports."""
    reports = list_reports(evo_dir, task_id=task_id)
    total = len(reports)
    annotated = sum(1 for r in reports if r.status == "annotated")
    tp = fp = uncertain = 0
    for r in reports:
        for label in r.human_labels:
            if label.verdict == "tp":
                tp += 1
            elif label.verdict == "fp":
                fp += 1
            else:
                uncertain += 1
    return {
        "total": total,
        "annotated": annotated,
        "pending": total - annotated,
        "total_labels": tp + fp + uncertain,
        "tp": tp,
        "fp": fp,
        "uncertain": uncertain,
        "precision": tp / (tp + fp) if (tp + fp) > 0 else None,
    }
