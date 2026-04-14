"""Grader base class for remote evaluation (ported from coral/grader/task_grader.py).

Simplified: no GraderConfig, no codebase_path, no subprocess helpers.
Remote agents subclass GraderBase and implement evaluate().

Usage on remote side:
    class MyGrader(GraderBase):
        def evaluate(self, result: dict) -> float:
            return result.get("vuln_count", 0) * 0.1
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class GraderBase(ABC):
    """Base class for task graders.

    Remote agents instantiate a grader, call grade(result),
    and get back a (score, feedback) tuple to report to Hub.
    """

    @abstractmethod
    def evaluate(self, result: dict[str, Any]) -> float | dict[str, float]:
        """Implement this. Return a float score or dict of named scores.

        Args:
            result: Task execution output (agent decides the format).

        Returns:
            Float score or dict of {name: score} for multi-metric evaluation.
        """
        ...

    def grade(self, result: dict[str, Any]) -> tuple[float | None, str]:
        """Run evaluate() with error handling. Returns (score, feedback).

        Never raises — returns (None, error_message) on failure.
        """
        try:
            raw = self.evaluate(result)
            if isinstance(raw, dict):
                # Multi-metric: aggregate as mean
                values = [v for v in raw.values() if isinstance(v, (int, float))]
                score = sum(values) / len(values) if values else 0.0
                feedback = ", ".join(f"{k}={v}" for k, v in raw.items())
                return score, feedback
            return float(raw), "ok"
        except Exception as e:
            return None, f"grader error: {e}"

    def grade_with_feedback(
        self,
        result: dict[str, Any],
        reports_dir: str | Path | None = None,
    ) -> tuple[float | None, str, dict[str, Any]]:
        """Grade with optional human feedback from .report/.result files.

        Returns (score, feedback_text, detail) where detail includes
        human feedback stats if reports_dir is provided.
        """
        score, feedback = self.grade(result)
        detail: dict[str, Any] = {}

        if reports_dir:
            fb = feedback_stats(Path(reports_dir))
            if fb["annotated"] > 0:
                detail["human_feedback"] = fb
                # Blend human precision into score if available
                if score is not None and fb["precision"] is not None:
                    detail["raw_score"] = score
                    detail["human_precision"] = fb["precision"]
                    # Weighted blend: 70% auto + 30% human
                    score = 0.7 * score + 0.3 * fb["precision"]
                    feedback += f" | human_precision={fb['precision']:.3f} (blended)"

        return score, feedback, detail


def feedback_stats(reports_dir: str | Path) -> dict[str, Any]:
    """Compute tp/fp/precision from .report + .result file pairs in reports_dir.

    Each .report file is a JSON with agent findings.
    Each .result file is a JSON with human labels: [{finding_id, verdict}].
    """
    reports_dir = Path(reports_dir)
    stats: dict[str, Any] = {"annotated": 0, "tp": 0, "fp": 0, "uncertain": 0, "precision": None}
    if not reports_dir.exists():
        return stats

    result_files = list(reports_dir.glob("*.result"))
    for rf in result_files:
        try:
            data = json.loads(rf.read_text())
            labels = data if isinstance(data, list) else data.get("human_labels", [])
            stats["annotated"] += 1
            for lb in labels:
                v = lb.get("verdict", "uncertain")
                if v in stats:
                    stats[v] += 1
        except (json.JSONDecodeError, OSError):
            continue

    tp, fp = stats["tp"], stats["fp"]
    if tp + fp > 0:
        stats["precision"] = tp / (tp + fp)

    return stats


def load_grader_from_source(source: str) -> GraderBase:
    """Load a GraderBase subclass from Python source code string.

    The source must define a class named 'Grader' inheriting GraderBase.

    WARNING: Uses exec() — grader code runs unsandboxed in the current process.
    Only load graders from trusted sources (your own Hub). A future version
    should run graders in isolated subprocesses.
    """
    import ast

    # Basic AST validation: reject import of os/subprocess/sys at module level
    _BLOCKED_MODULES = {"os", "subprocess", "sys", "shutil", "socket", "ctypes"}
    try:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in _BLOCKED_MODULES:
                        raise ValueError(f"Grader imports blocked module: {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in _BLOCKED_MODULES:
                    raise ValueError(f"Grader imports blocked module: {node.module}")
    except SyntaxError as e:
        raise ValueError(f"Grader source has syntax error: {e}") from e

    namespace: dict[str, Any] = {"GraderBase": GraderBase}
    exec(source, namespace)  # noqa: S102
    grader_cls = namespace.get("Grader")
    if grader_cls is None:
        raise ValueError("Grader source must define a class named 'Grader'")
    if not (isinstance(grader_cls, type) and issubclass(grader_cls, GraderBase)):
        raise TypeError("Grader class must inherit from GraderBase")
    return grader_cls()
