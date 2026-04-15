"""Tests for evolution/recall_index.py – BM25-based knowledge recall."""

import json
import tempfile
from pathlib import Path

import pytest

from cli_agent_orchestrator.evolution.recall_index import (
    BM25,
    Document,
    RecallIndex,
    RecallResult,
    tokenize,
)


# ── tokenize() ───────────────────────────────────────────────────────────


class TestTokenize:
    def test_basic_english(self):
        tokens = tokenize("hello world")
        assert tokens == ["hello", "world"]

    def test_lowercases(self):
        tokens = tokenize("Hello WORLD")
        assert tokens == ["hello", "world"]

    def test_strips_punctuation(self):
        tokens = tokenize("foo, bar. baz!")
        assert tokens == ["foo", "bar", "baz"]

    def test_cjk_characters(self):
        tokens = tokenize("检测漏洞")
        assert "检" in tokens
        assert "测" in tokens
        assert "洞" in tokens

    def test_mixed_cjk_latin(self):
        tokens = tokenize("SQL注入 detection")
        assert "sql" in tokens
        assert "detection" in tokens
        # CJK chars split individually
        assert "注" in tokens
        assert "入" in tokens

    def test_empty_string(self):
        assert tokenize("") == []

    def test_whitespace_only(self):
        assert tokenize("   \n\t  ") == []

    def test_numbers_preserved(self):
        tokens = tokenize("version 3.14 release")
        assert "version" in tokens
        assert "release" in tokens


# ── BM25 ─────────────────────────────────────────────────────────────────


class TestBM25:
    def setup_method(self):
        corpus = [
            ["the", "cat", "sat", "on", "the", "mat"],
            ["the", "dog", "chased", "the", "cat"],
            ["a", "fish", "swam", "in", "the", "pond"],
        ]
        self.bm25 = BM25()
        self.bm25.fit(corpus)

    def test_score_relevant(self):
        scores = self.bm25.query(["cat"])
        # doc 0 and doc 1 mention "cat", doc 2 does not
        assert scores[0] > 0
        assert scores[1] > 0
        assert scores[2] == pytest.approx(0.0)

    def test_score_empty_query(self):
        scores = self.bm25.query([])
        assert all(s == pytest.approx(0.0) for s in scores)

    def test_score_unknown_term(self):
        scores = self.bm25.query(["elephant"])
        assert all(s == pytest.approx(0.0) for s in scores)

    def test_top_results(self):
        scores = self.bm25.query(["cat"])
        # Find top 2 by score
        indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:2]
        assert len(indexed) == 2
        assert indexed[0][0] in (0, 1)
        assert indexed[0][1] > 0

    def test_multiple_query_terms(self):
        scores = self.bm25.query(["cat", "mat"])
        # doc 0 has both "cat" and "mat"
        assert scores[0] > scores[1]


# ── RecallIndex ──────────────────────────────────────────────────────────


@pytest.fixture
def evo_dir(tmp_path):
    """Create a minimal evolution dir with notes and skills (flat layout)."""
    notes = tmp_path / "notes"
    skills = tmp_path / "skills" / "scanner"
    notes.mkdir(parents=True)
    skills.mkdir(parents=True)

    (notes / "finding-1.md").write_text(
        "---\ntitle: SQL Injection Found\ntags: [sql, injection, security]\n---\n"
        "We found a SQL injection vulnerability in the login endpoint.\n"
        "The input is not sanitized before passing to the query.\n"
    )
    (notes / "finding-2.md").write_text(
        "---\ntitle: XSS in Dashboard\ntags: [xss, frontend]\n---\n"
        "Cross-site scripting in the admin dashboard.\n"
        "User input reflected without encoding.\n"
    )
    (notes / "approach.md").write_text(
        "---\ntitle: Testing Approach\ntags: [strategy]\n---\n"
        "Use fuzz testing to find edge cases.\n"
    )
    (skills / "SKILL.md").write_text(
        "---\ntitle: Vulnerability Scanner\ntags: [scanner, security]\n---\n"
        "# Scanner Skill\n\nScan code for common vulnerability patterns.\n"
        "Supports SQL injection, XSS, and CSRF detection.\n"
    )

    return tmp_path


class TestRecallIndex:
    def test_build(self, evo_dir):
        idx = RecallIndex(evo_dir)
        idx.build()
        assert len(idx._documents) == 4  # 3 notes + 1 skill

    def test_query_basic(self, evo_dir):
        idx = RecallIndex(evo_dir)
        idx.build()
        results = idx.query("SQL injection")
        assert len(results) > 0
        assert results[0].doc_id == "note:finding-1"
        assert results[0].score > 0

    def test_query_xss(self, evo_dir):
        idx = RecallIndex(evo_dir)
        idx.build()
        results = idx.query("XSS cross-site scripting")
        assert len(results) > 0
        top_ids = [r.doc_id for r in results[:2]]
        assert "note:finding-2" in top_ids

    def test_query_with_tag_filter(self, evo_dir):
        idx = RecallIndex(evo_dir)
        idx.build()
        results = idx.query("security", tags={"sql"})
        ids = {r.doc_id for r in results}
        # Only finding-1 has "sql" tag
        assert "note:finding-2" not in ids

    def test_query_empty(self, evo_dir):
        idx = RecallIndex(evo_dir)
        idx.build()
        results = idx.query("")
        assert results == []

    def test_query_top_k(self, evo_dir):
        idx = RecallIndex(evo_dir)
        idx.build()
        results = idx.query("security", top_k=2)
        assert len(results) <= 2

    def test_query_skill(self, evo_dir):
        idx = RecallIndex(evo_dir)
        idx.build()
        results = idx.query("vulnerability scanner")
        skill_results = [r for r in results if r.doc_type == "skill"]
        assert len(skill_results) > 0

    def test_get_document_exists(self, evo_dir):
        idx = RecallIndex(evo_dir)
        idx.build()
        doc = idx.get_document("note:finding-1")
        assert doc is not None
        assert doc.title == "SQL Injection Found"
        assert "sql" in doc.tags
        assert "injection" in doc.body.lower()

    def test_get_document_not_found(self, evo_dir):
        idx = RecallIndex(evo_dir)
        idx.build()
        assert idx.get_document("note:nonexistent") is None

    def test_get_document_skill(self, evo_dir):
        idx = RecallIndex(evo_dir)
        idx.build()
        doc = idx.get_document("skill:scanner")
        assert doc is not None
        assert "Scanner" in doc.title or "scanner" in doc.title.lower()

    def test_incremental_update_add(self, evo_dir):
        idx = RecallIndex(evo_dir)
        idx.build()
        initial_count = len(idx._documents)

        # Add a new note
        new_note = evo_dir / "notes" / "new-vuln.md"
        new_note.write_text(
            "---\ntitle: Buffer Overflow\ntags: [memory, overflow]\n---\n"
            "Stack buffer overflow in parser function.\n"
        )

        idx.update_incremental(["notes/new-vuln.md"])
        assert len(idx._documents) == initial_count + 1

        results = idx.query("buffer overflow")
        assert any(r.doc_id == "note:new-vuln" for r in results)

    def test_incremental_update_modify(self, evo_dir):
        idx = RecallIndex(evo_dir)
        idx.build()

        # Modify existing note
        note = evo_dir / "notes" / "finding-1.md"
        note.write_text(
            "---\ntitle: SQL Injection Found (Updated)\ntags: [sql, injection, critical]\n---\n"
            "Critical SQL injection in login and registration endpoints.\n"
        )

        idx.update_incremental(["notes/finding-1.md"])
        doc = idx.get_document("note:finding-1")
        assert doc is not None
        assert "Updated" in doc.title

    def test_incremental_update_delete(self, evo_dir):
        idx = RecallIndex(evo_dir)
        idx.build()

        # Delete a note
        (evo_dir / "notes" / "finding-2.md").unlink()

        idx.update_incremental(["notes/finding-2.md"])
        assert idx.get_document("note:finding-2") is None

    def test_incremental_ignores_non_knowledge(self, evo_dir):
        idx = RecallIndex(evo_dir)
        idx.build()
        initial_count = len(idx._documents)

        # update_incremental should ignore non-notes/skills paths
        idx.update_incremental(["attempts/abc.json"])
        assert len(idx._documents) == initial_count

    def test_build_empty_dir(self, tmp_path):
        idx = RecallIndex(tmp_path)
        idx.build()
        assert len(idx._documents) == 0
        assert idx.query("anything") == []

    def test_results_sorted_by_score(self, evo_dir):
        idx = RecallIndex(evo_dir)
        idx.build()
        results = idx.query("security")
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_snippet_generated(self, evo_dir):
        idx = RecallIndex(evo_dir)
        idx.build()
        results = idx.query("SQL injection login")
        assert len(results) > 0
        assert len(results[0].snippet) > 0
