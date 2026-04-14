"""Tests for human-feedback report types, storage, and API endpoints."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from cli_agent_orchestrator.evolution.types import Finding, HumanLabel, Report
from cli_agent_orchestrator.evolution.reports import (
    list_reports,
    read_report,
    report_stats,
    write_report,
)


# ── Type tests ───────────────────────────────────────────────────────────


class TestFinding:
    def test_roundtrip(self):
        f = Finding(finding_id="f-1", description="SQL injection in login", severity="high",
                    file_path="src/auth.py", line=42, category="sqli")
        d = f.to_dict()
        f2 = Finding.from_dict(d)
        assert f2.finding_id == "f-1"
        assert f2.severity == "high"
        assert f2.line == 42

    def test_defaults(self):
        f = Finding.from_dict({"finding_id": "f-0", "description": "test"})
        assert f.severity == "medium"
        assert f.file_path == ""
        assert f.line is None


class TestHumanLabel:
    def test_roundtrip(self):
        lbl = HumanLabel(finding_id="f-1", verdict="tp", comment="confirmed")
        d = lbl.to_dict()
        lbl2 = HumanLabel.from_dict(d)
        assert lbl2.verdict == "tp"
        assert lbl2.comment == "confirmed"

    def test_minimal(self):
        lbl = HumanLabel.from_dict({"finding_id": "f-1", "verdict": "fp"})
        assert lbl.severity_override is None


class TestReport:
    def test_roundtrip(self):
        r = Report(
            report_id="r-abc",
            task_id="scan-1",
            agent_id="agent-x",
            terminal_id="t-123",
            findings=[Finding(finding_id="f-1", description="XSS")],
            auto_score=0.8,
            submitted_at="2026-01-01T00:00:00Z",
        )
        d = r.to_dict()
        r2 = Report.from_dict(d)
        assert r2.report_id == "r-abc"
        assert r2.terminal_id == "t-123"
        assert len(r2.findings) == 1
        assert r2.status == "pending"

    def test_annotated(self):
        r = Report(
            report_id="r-1", task_id="t", agent_id="a", terminal_id="t-1",
            findings=[Finding(finding_id="f-1", description="test")],
            human_score=0.9,
            human_labels=[HumanLabel(finding_id="f-1", verdict="tp")],
            status="annotated",
            submitted_at="2026-01-01T00:00:00Z",
        )
        d = r.to_dict()
        assert d["status"] == "annotated"
        assert d["human_labels"][0]["verdict"] == "tp"


# ── Storage tests ────────────────────────────────────────────────────────


class TestReportsStorage:
    def _make_evo_dir(self, tmp: str) -> str:
        evo = str(Path(tmp) / "evo")
        Path(evo).mkdir()
        (Path(evo) / "shared").mkdir()
        return evo

    def test_write_and_read(self, tmp_path):
        evo = self._make_evo_dir(str(tmp_path))
        r = Report(
            report_id="r-1", task_id="scan-1", agent_id="a", terminal_id="t-1",
            findings=[Finding(finding_id="f-1", description="XSS")],
            submitted_at="2026-01-01T00:00:00Z",
        )
        write_report(evo, r)
        r2 = read_report(evo, "scan-1", "r-1")
        assert r2 is not None
        assert r2.report_id == "r-1"

    def test_read_missing(self, tmp_path):
        evo = self._make_evo_dir(str(tmp_path))
        assert read_report(evo, "nope", "nope") is None

    def test_list_with_filters(self, tmp_path):
        evo = self._make_evo_dir(str(tmp_path))
        for i in range(3):
            r = Report(
                report_id=f"r-{i}", task_id="scan-1", agent_id="a",
                terminal_id=f"t-{i % 2}",
                findings=[Finding(finding_id="f", description="test")],
                status="annotated" if i == 0 else "pending",
                submitted_at="2026-01-01T00:00:00Z",
            )
            write_report(evo, r)

        assert len(list_reports(evo, task_id="scan-1")) == 3
        assert len(list_reports(evo, task_id="scan-1", terminal_id="t-0")) == 2
        assert len(list_reports(evo, task_id="scan-1", status="annotated")) == 1
        assert len(list_reports(evo, task_id="nonexist")) == 0

    def test_stats(self, tmp_path):
        evo = self._make_evo_dir(str(tmp_path))
        r = Report(
            report_id="r-1", task_id="scan-1", agent_id="a", terminal_id="t-1",
            findings=[
                Finding(finding_id="f-1", description="XSS"),
                Finding(finding_id="f-2", description="CSRF"),
            ],
            human_labels=[
                HumanLabel(finding_id="f-1", verdict="tp"),
                HumanLabel(finding_id="f-2", verdict="fp"),
            ],
            status="annotated",
            submitted_at="2026-01-01T00:00:00Z",
        )
        write_report(evo, r)
        s = report_stats(evo, "scan-1")
        assert s["total"] == 1
        assert s["annotated"] == 1
        assert s["tp"] == 1
        assert s["fp"] == 1
        assert s["precision"] == 0.5


# ── API tests ────────────────────────────────────────────────────────────

import tempfile

_test_evo_dir = tempfile.mkdtemp()


@pytest.fixture(autouse=True, scope="module")
def _setup_evo_dir():
    import cli_agent_orchestrator.api.evolution_routes as mod
    original = mod.EVOLUTION_DIR
    mod.EVOLUTION_DIR = _test_evo_dir
    mod.ensure_evolution_repo()
    # Create task for report tests
    sd = Path(_test_evo_dir) / "shared" / "tasks" / "scan-1"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "task.yaml").write_text("name: scan\n")
    yield
    mod.EVOLUTION_DIR = original


@pytest.fixture(scope="module")
def client():
    from fastapi import FastAPI
    from cli_agent_orchestrator.api.evolution_routes import router
    app = FastAPI()
    app.include_router(router)
    from fastapi.testclient import TestClient
    return TestClient(app)


def test_submit_report(client):
    resp = client.post("/evolution/scan-1/reports", json={
        "agent_id": "agent-x",
        "terminal_id": "t-123",
        "findings": [
            {"description": "SQL injection in login.py", "severity": "high", "file_path": "src/login.py"},
            {"description": "XSS in search", "severity": "medium"},
        ],
        "auto_score": 0.7,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "report_id" in data
    assert data["finding_count"] == 2


def test_list_reports(client):
    # Submit two reports with different terminal_ids
    client.post("/evolution/scan-1/reports", json={
        "agent_id": "a", "terminal_id": "t-1",
        "findings": [{"description": "vuln1"}],
    })
    client.post("/evolution/scan-1/reports", json={
        "agent_id": "a", "terminal_id": "t-2",
        "findings": [{"description": "vuln2"}],
    })

    # List all (includes reports from test_submit_report)
    resp = client.get("/evolution/scan-1/reports")
    assert resp.status_code == 200
    assert len(resp.json()) >= 2

    # Filter by terminal_id
    resp = client.get("/evolution/scan-1/reports?terminal_id=t-1")
    assert len(resp.json()) >= 1
    assert all(r["terminal_id"] == "t-1" for r in resp.json())


def test_annotate_report(client):
    # Submit
    resp = client.post("/evolution/scan-1/reports", json={
        "agent_id": "a", "terminal_id": "t-ann",
        "findings": [
            {"finding_id": "f-1", "description": "SQL injection"},
            {"finding_id": "f-2", "description": "Path traversal"},
        ],
    })
    report_id = resp.json()["report_id"]

    # Annotate
    resp = client.put(f"/evolution/scan-1/reports/{report_id}/annotate", json={
        "human_score": 0.5,
        "labels": [
            {"finding_id": "f-1", "verdict": "tp", "comment": "confirmed"},
            {"finding_id": "f-2", "verdict": "fp"},
        ],
        "annotated_by": "reviewer-1",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "annotated"

    # Verify via list
    resp = client.get("/evolution/scan-1/reports?status=annotated")
    reports = resp.json()
    annotated = [r for r in reports if r["report_id"] == report_id]
    assert len(annotated) == 1
    assert annotated[0]["human_score"] == 0.5
    assert len(annotated[0]["human_labels"]) == 2


def test_annotate_nonexistent(client):
    resp = client.put("/evolution/scan-1/reports/nope/annotate", json={
        "labels": [], "human_score": 0.0,
    })
    assert resp.status_code == 404


def test_report_stats(client):
    # Stats should reflect the annotated report from test_annotate_report
    resp = client.get("/evolution/scan-1/reports/stats")
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["total"] >= 1
    assert stats["annotated"] >= 1


def test_report_result(client):
    # Submit
    resp = client.post("/evolution/scan-1/reports", json={
        "agent_id": "a", "terminal_id": "t-res",
        "findings": [{"finding_id": "f-1", "description": "v1"}],
    })
    rid = resp.json()["report_id"]

    # Not yet annotated → 404
    resp = client.get(f"/evolution/scan-1/reports/{rid}/result")
    assert resp.status_code == 404

    # Annotate
    client.put(f"/evolution/scan-1/reports/{rid}/annotate", json={
        "human_score": 0.9,
        "labels": [{"finding_id": "f-1", "verdict": "tp"}],
    })

    # Now result is available
    resp = client.get(f"/evolution/scan-1/reports/{rid}/result")
    assert resp.status_code == 200
    data = resp.json()
    assert data["human_score"] == 0.9
    assert data["human_labels"][0]["verdict"] == "tp"


def test_annotate_creates_result_file(client):
    """Annotation must write a .result file for heartbeat/grader consumption."""
    resp = client.post("/evolution/scan-1/reports", json={
        "agent_id": "a", "terminal_id": "t-file",
        "findings": [{"finding_id": "f-1", "description": "xss"}],
    })
    rid = resp.json()["report_id"]
    client.put(f"/evolution/scan-1/reports/{rid}/annotate", json={
        "human_score": 0.7,
        "labels": [{"finding_id": "f-1", "verdict": "tp"}],
    })
    # Locate .result file
    from cli_agent_orchestrator.evolution.checkpoint import shared_dir
    from cli_agent_orchestrator.api.evolution_routes import EVOLUTION_DIR
    result_file = Path(shared_dir(EVOLUTION_DIR)) / "reports" / "scan-1" / f"{rid}.result"
    assert result_file.exists(), ".result file should be written after annotation"
    data = json.loads(result_file.read_text())
    assert data["human_score"] == 0.7
    assert data["human_labels"][0]["verdict"] == "tp"


def test_path_traversal_rejected(client):
    """IDs with non-alphanumeric chars must be rejected."""
    # Spaces in task_id
    resp = client.get("/evolution/scan 1/reports/stats")
    assert resp.status_code == 400

    # Dots in report_id (annotation endpoint)
    resp = client.put("/evolution/scan-1/reports/foo.bar/annotate", json={
        "labels": [], "human_score": 0.0,
    })
    assert resp.status_code == 400

    # Valid IDs still work
    resp = client.post("/evolution/scan-1/reports", json={
        "agent_id": "a", "terminal_id": "t",
        "findings": [{"finding_id": "f-1", "description": "x"}],
    })
    assert resp.status_code == 201
