"""Local registry for submitted vulnerability reports.

Persists the IDs of reports an agent has submitted to the Hub so that
`cao_fetch_feedbacks` can later look up which reports still need to be
checked for human annotations.

Storage: ``<client_dir>/reports/registry.json``  (flock-guarded).
This directory is agent-local runtime state and should NOT be tracked
by the evolution git repo — see ``git_sync._ensure_local_excludes``.

Entry shape:
    {
      "report_id":    "a1b2c3d4e5f6",
      "task_id":      "vuln-scan-xyz",
      "source":       "cao",             # which API source produced the id
      "submitted_at": "2026-04-16T08:30:00+00:00",
      "status":       "pending|annotated|consumed",
      "result_path":  ""                 # set when .result lands on disk
    }
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

DEFAULT_CLIENT_DIR = Path.home() / ".cao-evolution-client"


def client_dir() -> Path:
    """Return the session-aware client directory.

    Delegates to git_sync.client_dir() when session isolation is active,
    falls back to CAO_CLIENT_DIR or the default.
    """
    try:
        from git_sync import client_dir as _git_client_dir
        return _git_client_dir()
    except ImportError:
        return Path(os.environ.get("CAO_CLIENT_DIR", str(DEFAULT_CLIENT_DIR)))


def reports_dir() -> Path:
    d = client_dir() / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def registry_path() -> Path:
    return reports_dir() / "registry.json"


@contextmanager
def _locked_registry() -> Iterator[dict]:
    """Open registry.json under an exclusive flock; yield the parsed dict.

    Writes back on exit. Creates the file if missing.
    """
    path = registry_path()
    # Open in r+ if exists, else create empty.
    if not path.exists():
        path.write_text(json.dumps({"entries": {}}, indent=2))

    with path.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            raw = fh.read() or '{"entries": {}}'
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("registry.json corrupt, resetting")
                data = {"entries": {}}
            if "entries" not in data or not isinstance(data["entries"], dict):
                data["entries"] = {}

            yield data

            fh.seek(0)
            fh.truncate()
            fh.write(json.dumps(data, indent=2, sort_keys=True))
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def add_report(report_id: str, task_id: str, source: str = "cao") -> None:
    """Register a newly submitted report. Idempotent."""
    with _locked_registry() as data:
        if report_id in data["entries"]:
            return
        data["entries"][report_id] = {
            "report_id": report_id,
            "task_id": task_id,
            "source": source,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "result_path": "",
        }
        logger.info("registered report %s (task=%s source=%s)", report_id, task_id, source)


def list_pending(task_id: str | None = None, source: str | None = None) -> list[dict]:
    """Return entries with status=pending, optionally filtered."""
    with _locked_registry() as data:
        out = []
        for e in data["entries"].values():
            if e.get("status") != "pending":
                continue
            if task_id and e.get("task_id") != task_id:
                continue
            if source and e.get("source") != source:
                continue
            out.append(dict(e))
        return out


def mark_annotated(report_id: str, result_path: str) -> None:
    with _locked_registry() as data:
        if report_id not in data["entries"]:
            return
        data["entries"][report_id]["status"] = "annotated"
        data["entries"][report_id]["result_path"] = str(result_path)


def mark_consumed(report_id: str) -> None:
    with _locked_registry() as data:
        if report_id in data["entries"]:
            data["entries"][report_id]["status"] = "consumed"
