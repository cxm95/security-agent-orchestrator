"""Core types for the evolution subsystem (ported from coral/types.py).

Simplified: no Task dataclass (use task.yaml), no commit_hash/parent_hash
(no code snapshots). Added task_id as partition key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Score:
    """Single evaluation score."""

    value: float | None
    name: str
    explanation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "name": self.name, "explanation": self.explanation}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Score:
        return cls(value=data["value"], name=data["name"], explanation=data.get("explanation"))


@dataclass
class ScoreBundle:
    """Collection of named scores with optional aggregate."""

    scores: dict[str, Score]
    aggregated: float | None = None
    feedback: str | None = None

    def compute_aggregated(self, weights: dict[str, float] | None = None) -> float:
        weights = weights or {}
        total = 0.0
        weight_sum = 0.0
        for name, score in self.scores.items():
            v = score.value
            if v is None:
                continue
            w = weights.get(name, 1.0)
            total += float(v) * w
            weight_sum += w
        return total / weight_sum if weight_sum > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scores": {n: s.to_dict() for n, s in self.scores.items()},
            "aggregated": self.aggregated,
            "feedback": self.feedback,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScoreBundle:
        scores = {n: Score.from_dict(s) for n, s in data.get("scores", {}).items()}
        return cls(
            scores=scores,
            aggregated=data.get("aggregated"),
            feedback=data.get("feedback"),
        )


@dataclass
class Attempt:
    """Record of one task execution + evaluation by an agent."""

    run_id: str
    agent_id: str
    task_id: str
    title: str
    score: float | None
    status: str  # improved | baseline | regressed | crashed | timeout
    timestamp: str  # ISO 8601
    feedback: str = ""
    agent_profile: str = ""
    batch: str = ""
    shared_state_hash: str | None = None
    score_detail: dict[str, float] | None = None  # multi-dimension scores from grader
    evolution_signals: dict[str, Any] | None = None  # transparent multi-source signal pack

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "title": self.title,
            "score": self.score,
            "status": self.status,
            "timestamp": self.timestamp,
            "feedback": self.feedback,
        }
        if self.shared_state_hash is not None:
            d["shared_state_hash"] = self.shared_state_hash
        if self.agent_profile:
            d["agent_profile"] = self.agent_profile
        if self.batch:
            d["batch"] = self.batch
        if self.score_detail is not None:
            d["score_detail"] = self.score_detail
        if self.evolution_signals is not None:
            d["evolution_signals"] = self.evolution_signals
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Attempt:
        return cls(
            run_id=data["run_id"],
            agent_id=data["agent_id"],
            task_id=data["task_id"],
            title=data.get("title", ""),
            score=data.get("score"),
            status=data.get("status", "crashed"),
            timestamp=data["timestamp"],
            feedback=data.get("feedback", ""),
            agent_profile=data.get("agent_profile", ""),
            batch=data.get("batch", ""),
            shared_state_hash=data.get("shared_state_hash"),
            score_detail=data.get("score_detail"),
            evolution_signals=data.get("evolution_signals"),
        )

    @classmethod
    def from_json(cls, text: str) -> Attempt:
        return cls.from_dict(json.loads(text))


# ── Human Feedback types ─────────────────────────────────────────────────


@dataclass
class Finding:
    """Single finding (e.g. a vulnerability) within a report."""

    finding_id: str
    description: str
    severity: str = "medium"  # critical | high | medium | low | info
    file_path: str = ""
    line: int | None = None
    category: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "finding_id": self.finding_id,
            "description": self.description,
            "severity": self.severity,
        }
        if self.file_path:
            d["file_path"] = self.file_path
        if self.line is not None:
            d["line"] = self.line
        if self.category:
            d["category"] = self.category
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Finding:
        return cls(
            finding_id=data["finding_id"],
            description=data["description"],
            severity=data.get("severity", "medium"),
            file_path=data.get("file_path", ""),
            line=data.get("line"),
            category=data.get("category", ""),
        )


@dataclass
class HumanLabel:
    """Human annotation for a single finding."""

    finding_id: str
    verdict: str  # tp | fp | uncertain
    severity_override: str | None = None
    comment: str = ""
    annotated_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "finding_id": self.finding_id,
            "verdict": self.verdict,
        }
        if self.severity_override:
            d["severity_override"] = self.severity_override
        if self.comment:
            d["comment"] = self.comment
        if self.annotated_by:
            d["annotated_by"] = self.annotated_by
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HumanLabel:
        return cls(
            finding_id=data["finding_id"],
            verdict=data["verdict"],
            severity_override=data.get("severity_override"),
            comment=data.get("comment", ""),
            annotated_by=data.get("annotated_by", ""),
        )


@dataclass
class Report:
    """A vulnerability report submitted by an agent, with optional human labels."""

    report_id: str
    task_id: str
    agent_id: str
    terminal_id: str
    findings: list[Finding]
    auto_score: float | None = None
    human_score: float | None = None
    human_labels: list[HumanLabel] = field(default_factory=list)
    status: str = "pending"  # pending | annotated
    submitted_at: str = ""
    annotated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "terminal_id": self.terminal_id,
            "findings": [f.to_dict() for f in self.findings],
            "auto_score": self.auto_score,
            "human_score": self.human_score,
            "human_labels": [l.to_dict() for l in self.human_labels],
            "status": self.status,
            "submitted_at": self.submitted_at,
            "annotated_at": self.annotated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Report:
        return cls(
            report_id=data["report_id"],
            task_id=data["task_id"],
            agent_id=data["agent_id"],
            terminal_id=data.get("terminal_id", ""),
            findings=[Finding.from_dict(f) for f in data.get("findings", [])],
            auto_score=data.get("auto_score"),
            human_score=data.get("human_score"),
            human_labels=[HumanLabel.from_dict(l) for l in data.get("human_labels", [])],
            status=data.get("status", "pending"),
            submitted_at=data.get("submitted_at", ""),
            annotated_at=data.get("annotated_at"),
        )
