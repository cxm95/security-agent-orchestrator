"""Structured retry: evolve a skill with snapshot/modify/validate/revert loop.

Flow:
1. Snapshot current skill content
2. Apply modification (via evolve_fn callback)
3. Validate against evals.json (via validate_fn callback)
4. If regression → revert to snapshot, try again with different strategy
5. Max 2 retries. On all failures, keep original.

This module is model-agnostic — the evolve_fn and validate_fn are injected.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

# evolve_fn: (skill_content, attempt_number, prev_feedback, evolution_signals) → new_content
EvolveFn = Callable[[str, int, str, dict], str]

# validate_fn: (skill_content) → {"passed": int, "failed": int, "details": str}
ValidateFn = Callable[[str], dict[str, Any]]

MAX_RETRIES = 2


@dataclass
class EvolutionResult:
    """Result of a structured evolution attempt."""
    success: bool
    original_content: str
    final_content: str
    attempts: int
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "attempts": self.attempts,
            "history": self.history,
        }


def evolve_with_retry(
    skill_content: str,
    evolve_fn: EvolveFn,
    validate_fn: ValidateFn,
    max_retries: int = MAX_RETRIES,
    evolution_signals: dict[str, Any] | None = None,
) -> EvolutionResult:
    """Attempt to evolve a skill with structured retry.

    Args:
        skill_content: Current skill text
        evolve_fn: Callable(content, attempt_num, feedback, signals) → new_content
        validate_fn: Callable(content) → {"passed": int, "failed": int, "details": str}
        max_retries: Maximum retry attempts (default 2)
        evolution_signals: Multi-signal dict (judge, grader, etc.) forwarded to evolve_fn

    Returns:
        EvolutionResult with success flag, final content, and attempt history.
    """
    snapshot = skill_content
    signals = evolution_signals or {}
    baseline = validate_fn(snapshot)
    baseline_passed = baseline.get("passed", 0)

    history = [{"attempt": 0, "type": "baseline", "validation": baseline}]
    feedback = ""

    for attempt in range(1, max_retries + 1):
        try:
            new_content = evolve_fn(snapshot, attempt, feedback, signals)
        except Exception as e:
            logger.warning("evolve_fn failed on attempt %d: %s", attempt, e)
            history.append({
                "attempt": attempt,
                "type": "evolve_failed",
                "error": str(e),
            })
            feedback = f"Evolution failed: {e}. Try a different approach."
            continue

        validation = validate_fn(new_content)
        new_passed = validation.get("passed", 0)
        new_failed = validation.get("failed", 0)

        history.append({
            "attempt": attempt,
            "type": "evolved",
            "validation": validation,
        })

        # Check for regression
        if new_passed < baseline_passed:
            logger.info("Attempt %d regressed (%d→%d passed). Reverting.", attempt, baseline_passed, new_passed)
            feedback = (
                f"Attempt {attempt} regressed: {baseline_passed}→{new_passed} passing. "
                f"Details: {validation.get('details', '')}. Try a fundamentally different approach."
            )
            continue

        # Check for improvement
        if new_failed == 0 or new_passed > baseline_passed:
            logger.info("Attempt %d improved (%d→%d passed).", attempt, baseline_passed, new_passed)
            return EvolutionResult(
                success=True,
                original_content=snapshot,
                final_content=new_content,
                attempts=attempt,
                history=history,
            )

        # No regression but no improvement either — try again with feedback
        feedback = (
            f"Attempt {attempt} didn't improve: still {new_passed} passing, {new_failed} failing. "
            f"Details: {validation.get('details', '')}. Try a different strategy."
        )

    # All retries exhausted — keep original
    logger.info("All %d retries exhausted. Keeping original skill.", max_retries)
    return EvolutionResult(
        success=False,
        original_content=snapshot,
        final_content=snapshot,
        attempts=max_retries,
        history=history,
    )
