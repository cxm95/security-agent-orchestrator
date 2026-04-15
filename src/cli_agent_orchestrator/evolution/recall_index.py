"""RecallIndex — BM25-based knowledge recall for evolution knowledge base.

Indexes notes/*.md and skills/*/SKILL.md from the evolution directory.
Built on Hub startup; incrementally updated after each checkpoint().

No external dependencies — pure-Python BM25 Okapi implementation.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Document:
    """A single indexed document (note or skill)."""
    doc_id: str
    doc_type: str          # "note" or "skill"
    path: str              # relative path from evolution_dir
    title: str
    tags: list[str]
    body: str              # full content (after frontmatter)
    meta: dict[str, str] = field(default_factory=dict)


@dataclass
class RecallResult:
    """A single recall result with BM25 score."""
    doc_id: str
    doc_type: str
    title: str
    tags: list[str]
    score: float
    snippet: str
    meta: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "type": self.doc_type,
            "title": self.title,
            "tags": self.tags,
            "score": round(self.score, 4),
            "snippet": self.snippet,
            "meta": self.meta,
        }


# ---------------------------------------------------------------------------
# Tokenizer — lightweight, handles mixed CJK + Latin text
# ---------------------------------------------------------------------------

_SPLIT_RE = re.compile(r"[\w]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens. Handles CJK by treating each
    character as a token; Latin words are split on word boundaries."""
    tokens: list[str] = []
    for match in _SPLIT_RE.finditer(text.lower()):
        word = match.group()
        # Split CJK characters individually for better matching
        latin_buf: list[str] = []
        for ch in word:
            if unicodedata.category(ch).startswith("Lo"):
                # Flush any buffered Latin chars as a single token
                if latin_buf:
                    tokens.append("".join(latin_buf))
                    latin_buf = []
                tokens.append(ch)
            else:
                latin_buf.append(ch)
        if latin_buf:
            tokens.append("".join(latin_buf))
    return tokens


# ---------------------------------------------------------------------------
# BM25 Okapi implementation
# ---------------------------------------------------------------------------

class BM25:
    """Pure-Python BM25 Okapi ranking.

    Parameters follow the classic defaults: k1=1.5, b=0.75.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._corpus_size = 0
        self._avgdl = 0.0
        self._doc_len: list[int] = []          # per-doc token count
        self._doc_freqs: list[dict[str, int]] = []  # per-doc term freq
        self._idf: dict[str, float] = {}       # term → IDF
        self._df: dict[str, int] = {}          # term → document frequency

    def fit(self, tokenized_corpus: list[list[str]]) -> None:
        """Build the index from a tokenized corpus."""
        self._corpus_size = len(tokenized_corpus)
        self._doc_len = []
        self._doc_freqs = []
        self._df = {}

        for tokens in tokenized_corpus:
            self._doc_len.append(len(tokens))
            freq: dict[str, int] = {}
            for t in tokens:
                freq[t] = freq.get(t, 0) + 1
            self._doc_freqs.append(freq)
            for t in freq:
                self._df[t] = self._df.get(t, 0) + 1

        self._avgdl = (
            sum(self._doc_len) / self._corpus_size
            if self._corpus_size > 0 else 1.0
        )
        self._compute_idf()

    def _compute_idf(self) -> None:
        """Compute IDF for each term using the BM25 formula."""
        self._idf = {}
        n = self._corpus_size
        for term, df in self._df.items():
            # Standard BM25 IDF: log((N - df + 0.5) / (df + 0.5) + 1)
            self._idf[term] = math.log((n - df + 0.5) / (df + 0.5) + 1.0)

    def query(self, tokens: list[str]) -> list[float]:
        """Score all documents against a query. Returns list of scores."""
        scores = [0.0] * self._corpus_size
        for t in tokens:
            if t not in self._idf:
                continue
            idf = self._idf[t]
            for i in range(self._corpus_size):
                tf = self._doc_freqs[i].get(t, 0)
                if tf == 0:
                    continue
                dl = self._doc_len[i]
                denom = tf + self.k1 * (1.0 - self.b + self.b * dl / self._avgdl)
                scores[i] += idf * (tf * (self.k1 + 1.0)) / denom
        return scores


# ---------------------------------------------------------------------------
# RecallIndex — main interface
# ---------------------------------------------------------------------------

class RecallIndex:
    """BM25-based knowledge recall index.

    Covers notes/*.md and skills/*/SKILL.md under evolution_dir.
    """

    def __init__(self, evolution_dir: str | Path) -> None:
        self.evolution_dir = Path(evolution_dir)
        self._documents: list[Document] = []
        self._doc_map: dict[str, int] = {}     # doc_id → index
        self._bm25 = BM25()
        self._built = False

    @property
    def document_count(self) -> int:
        return len(self._documents)

    # ── Build / Update ────────────────────────────────────────────────

    def build(self) -> int:
        """Full rebuild of the index. Returns number of documents indexed."""
        self._documents = []
        self._doc_map = {}

        self._index_notes()
        self._index_skills()

        corpus = [tokenize(f"{d.title} {' '.join(d.tags)} {d.body}")
                  for d in self._documents]
        self._bm25.fit(corpus)
        self._built = True

        logger.info("RecallIndex built: %d documents", len(self._documents))
        return len(self._documents)

    def update_incremental(self, changed_files: list[str]) -> int:
        """Incrementally update index for changed files, then rebuild BM25.

        Args:
            changed_files: List of paths relative to evolution_dir
                           (e.g. ["notes/finding-1.md", "skills/scanner/SKILL.md"]).

        Returns:
            Number of documents updated.
        """
        updated = 0
        for rel_path in changed_files:
            abs_path = self.evolution_dir / rel_path
            if rel_path.startswith("notes/") and rel_path.endswith(".md"):
                doc = self._parse_note(abs_path)
                if doc:
                    self._upsert_document(doc)
                    updated += 1
                else:
                    self._remove_document(f"note:{abs_path.stem}")
                    updated += 1
            elif rel_path.startswith("skills/") and rel_path.endswith("SKILL.md"):
                doc = self._parse_skill(abs_path)
                if doc:
                    self._upsert_document(doc)
                    updated += 1
                else:
                    parts = Path(rel_path).parts
                    if len(parts) >= 2:
                        self._remove_document(f"skill:{parts[1]}")
                        updated += 1

        if updated > 0:
            # Compact: remove empty stubs left by _remove_document
            live_docs = [d for d in self._documents if d.doc_type]
            self._documents = live_docs
            self._doc_map = {d.doc_id: i for i, d in enumerate(live_docs)}
            corpus = [tokenize(f"{d.title} {' '.join(d.tags)} {d.body}")
                      for d in self._documents]
            self._bm25.fit(corpus)

        logger.info("RecallIndex incremental update: %d docs changed", updated)
        return updated

    # ── Query ─────────────────────────────────────────────────────────

    def query(
        self,
        query_text: str,
        tags: set[str] | None = None,
        top_k: int = 10,
    ) -> list[RecallResult]:
        """BM25 recall with optional tag filtering.

        Returns results sorted by descending BM25 score.
        """
        if not self._built or not self._documents:
            return []

        tokens = tokenize(query_text)
        if not tokens:
            return []

        scores = self._bm25.query(tokens)

        # Build scored candidates
        candidates: list[tuple[float, int]] = []
        for i, score in enumerate(scores):
            if score <= 0:
                continue
            doc = self._documents[i]
            if tags:
                doc_tags = {t.lower() for t in doc.tags}
                if not tags & doc_tags:
                    continue
            candidates.append((score, i))

        candidates.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, i in candidates[:top_k]:
            doc = self._documents[i]
            results.append(RecallResult(
                doc_id=doc.doc_id,
                doc_type=doc.doc_type,
                title=doc.title,
                tags=doc.tags,
                score=score,
                snippet=_make_snippet(doc.body, query_text),
                meta=doc.meta,
            ))
        return results

    def get_document(self, doc_id: str) -> Document | None:
        """Retrieve a full document by ID."""
        idx = self._doc_map.get(doc_id)
        if idx is not None and idx < len(self._documents):
            return self._documents[idx]
        return None

    # ── Internal: parsing ─────────────────────────────────────────────

    def _index_notes(self) -> None:
        notes_dir = self.evolution_dir / "notes"
        if not notes_dir.exists():
            return
        for f in sorted(notes_dir.rglob("*.md")):
            doc = self._parse_note(f)
            if doc:
                self._add_document(doc)

    def _index_skills(self) -> None:
        skills_dir = self.evolution_dir / "skills"
        if not skills_dir.exists():
            return
        for f in sorted(skills_dir.rglob("SKILL.md")):
            doc = self._parse_skill(f)
            if doc:
                self._add_document(doc)

    def _parse_note(self, path: Path) -> Document | None:
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        meta = _parse_frontmatter(text)
        body = _body_after_frontmatter(text)
        tags = [t.strip() for t in meta.get("tags", "").split(",") if t.strip()]
        rel = path.relative_to(self.evolution_dir)
        return Document(
            doc_id=f"note:{path.stem}",
            doc_type="note",
            path=str(rel),
            title=meta.get("title", path.stem),
            tags=tags,
            body=body,
            meta=meta,
        )

    def _parse_skill(self, path: Path) -> Document | None:
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        meta = _parse_frontmatter(text)
        body = _body_after_frontmatter(text)
        tags = [t.strip() for t in meta.get("tags", "").split(",") if t.strip()]
        skill_name = path.parent.name
        rel = path.relative_to(self.evolution_dir)
        return Document(
            doc_id=f"skill:{skill_name}",
            doc_type="skill",
            path=str(rel),
            title=meta.get("title", meta.get("name", skill_name)),
            tags=tags,
            body=body,
            meta=meta,
        )

    def _add_document(self, doc: Document) -> None:
        idx = len(self._documents)
        self._documents.append(doc)
        self._doc_map[doc.doc_id] = idx

    def _upsert_document(self, doc: Document) -> None:
        existing = self._doc_map.get(doc.doc_id)
        if existing is not None:
            self._documents[existing] = doc
        else:
            self._add_document(doc)

    def _remove_document(self, doc_id: str) -> None:
        idx = self._doc_map.get(doc_id)
        if idx is None:
            return
        # Replace with empty doc to keep indices stable until next fit()
        self._documents[idx] = Document(
            doc_id=doc_id, doc_type="", path="", title="",
            tags=[], body="",
        )
        del self._doc_map[doc_id]


# ---------------------------------------------------------------------------
# Helpers (shared with evolution_routes.py via import)
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract YAML frontmatter as simple key-value pairs."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    meta: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, val = line.partition(":")
            val = val.strip().strip('"').strip("'")
            if val.startswith("[") and val.endswith("]"):
                val = val[1:-1]
            meta[key.strip()] = val
    return meta


def _body_after_frontmatter(text: str) -> str:
    """Return content after closing --- of frontmatter."""
    parts = text.split("---", 2)
    if len(parts) >= 3:
        return parts[2].strip()
    return text


def _make_snippet(body: str, query: str, context: int = 120) -> str:
    """Extract a snippet around the first match of query in body."""
    lower = body.lower()
    query_lower = query.lower()
    idx = lower.find(query_lower)
    if idx == -1:
        # Fallback: try first query token
        tokens = query_lower.split()
        for t in tokens:
            idx = lower.find(t)
            if idx != -1:
                break
    if idx == -1:
        return body[:context] + ("…" if len(body) > context else "")

    half = context // 2
    start = max(0, idx - half)
    end = min(len(body), idx + len(query) + half)
    snippet = body[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(body):
        snippet = snippet + "…"
    return snippet
