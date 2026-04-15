"""Tests for recall API endpoints (/evolution/knowledge/recall, document, rebuild)."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

_test_evo_dir = tempfile.mkdtemp()


def _patched_evo_dir():
    return _test_evo_dir


@pytest.fixture(autouse=True, scope="module")
def _setup_evo_dir():
    """Set up a temp evolution dir with sample knowledge files."""
    import cli_agent_orchestrator.api.evolution_routes as evo_mod
    original = evo_mod.EVOLUTION_DIR
    evo_mod.EVOLUTION_DIR = _test_evo_dir
    evo_mod.ensure_evolution_repo()

    # Create notes (flat layout — no shared/ prefix)
    notes_dir = Path(_test_evo_dir) / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    (notes_dir / "vuln-report.md").write_text(
        "---\ntitle: Vulnerability Report\ntags: [security, vulnerability]\n---\n"
        "Found SQL injection in login endpoint.\n"
        "Authentication bypass possible via crafted input.\n"
    )
    (notes_dir / "approach.md").write_text(
        "---\ntitle: Scanning Approach\ntags: [strategy, scanning]\n---\n"
        "Use automated scanning plus manual review.\n"
        "Focus on OWASP Top 10 vulnerabilities.\n"
    )
    (notes_dir / "xss-finding.md").write_text(
        "---\ntitle: XSS Finding\ntags: [xss, frontend]\n---\n"
        "Cross-site scripting in search results page.\n"
    )

    # Create a skill
    skill_dir = Path(_test_evo_dir) / "skills" / "scanner"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        "---\ntitle: Scanner Skill\ntags: [scanner, tool]\n---\n"
        "# Vulnerability Scanner\n\nDetect common security issues.\n"
    )

    # Reset recall index singleton
    evo_mod._recall_index = None

    yield
    evo_mod.EVOLUTION_DIR = original
    evo_mod._recall_index = None


@pytest.fixture(scope="module")
def client():
    from fastapi import FastAPI
    from cli_agent_orchestrator.api.evolution_routes import router
    test_app = FastAPI()
    test_app.include_router(router)
    return TestClient(test_app)


# ── /evolution/knowledge/recall ──────────────────────────────────────────


class TestRecallEndpoint:
    def test_basic_recall(self, client):
        resp = client.get(
            "/evolution/knowledge/recall",
            params={"query": "SQL injection"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        # Top result should be the vuln report with SQL injection
        assert data[0]["doc_id"] == "note:vuln-report"
        assert data[0]["score"] > 0

    def test_recall_with_tags(self, client):
        resp = client.get(
            "/evolution/knowledge/recall",
            params={"query": "security", "tags": "xss"},
        )
        assert resp.status_code == 200
        data = resp.json()
        ids = {d["doc_id"] for d in data}
        # Only xss-finding has the "xss" tag
        assert "note:vuln-report" not in ids

    def test_recall_with_include_content(self, client):
        resp = client.get(
            "/evolution/knowledge/recall",
            params={"query": "scanning", "include_content": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        # At least one result should have content field
        has_content = any(d.get("content") for d in data)
        assert has_content

    def test_recall_top_k(self, client):
        resp = client.get(
            "/evolution/knowledge/recall",
            params={"query": "security", "top_k": 1},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) <= 1

    def test_recall_empty_query(self, client):
        resp = client.get(
            "/evolution/knowledge/recall",
            params={"query": ""},
        )
        # min_length=1 validation → 422
        assert resp.status_code == 422

    def test_recall_no_match(self, client):
        resp = client.get(
            "/evolution/knowledge/recall",
            params={"query": "quantum computing blockchain"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # May return empty or low-score results
        assert isinstance(data, list)

    def test_recall_result_fields(self, client):
        resp = client.get(
            "/evolution/knowledge/recall",
            params={"query": "vulnerability"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        r = data[0]
        assert "doc_id" in r
        assert "type" in r
        assert "title" in r
        assert "tags" in r
        assert "score" in r
        assert "snippet" in r


# ── /evolution/knowledge/document/{doc_id} ──────────────────────────────


class TestDocumentEndpoint:
    def test_get_note(self, client):
        resp = client.get("/evolution/knowledge/document/note:vuln-report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == "note:vuln-report"
        assert "SQL injection" in data.get("body", data.get("content", ""))

    def test_get_skill(self, client):
        resp = client.get("/evolution/knowledge/document/skill:scanner")
        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == "skill:scanner"

    def test_not_found(self, client):
        resp = client.get("/evolution/knowledge/document/note:nonexistent")
        assert resp.status_code == 404

    def test_get_note_has_title_and_tags(self, client):
        resp = client.get("/evolution/knowledge/document/note:approach")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Scanning Approach"
        assert "strategy" in data["tags"]


# ── /evolution/knowledge/recall/rebuild ─────────────────────────────────


class TestRebuildEndpoint:
    def test_rebuild(self, client):
        resp = client.post("/evolution/knowledge/recall/rebuild")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["documents_indexed"] >= 4  # 3 notes + 1 skill
