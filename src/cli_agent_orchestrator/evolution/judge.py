"""LLM-as-Judge: evaluate skill output using an LLM for binary + soft scoring.

Provides a model-agnostic judge interface. The judge:
1. Binary judgment: is_correct (bool) + confidence (0-1)
2. Soft score: 0-10 scale
3. Qualitative: strengths + weaknesses lists

Usage:
    result = evaluate_with_judge(skill_output, expected, judge_fn=my_llm_call)

The judge_fn must accept a prompt string and return a response string.
For testing, use the built-in mock_judge.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Type alias for the judge function: takes prompt str, returns response str
JudgeFn = Callable[[str], str]

JUDGE_PROMPT_TEMPLATE = """You are an expert evaluator. Judge the following output against the expected result.

## Task Input
{input_data}

## Actual Output
{actual_output}

## Expected Output
{expected_output}

## Instructions
Respond with a JSON object (no markdown fences) containing:
- "is_correct": boolean — does the output substantially match the expected?
- "confidence": float 0-1 — how confident are you in the judgment?
- "score": integer 0-10 — quality of the output (10 = perfect)
- "strengths": list of strings — what the output does well
- "weaknesses": list of strings — what could be improved

Example:
{{"is_correct": true, "confidence": 0.9, "score": 8, "strengths": ["accurate"], "weaknesses": ["verbose"]}}
"""


def evaluate_with_judge(
    input_data: str,
    actual_output: str,
    expected_output: str,
    judge_fn: JudgeFn,
) -> dict[str, Any]:
    """Run LLM-as-Judge evaluation. Returns structured result dict.

    Args:
        input_data: The original task/input
        actual_output: What the skill produced
        expected_output: What was expected
        judge_fn: A callable that takes a prompt string and returns a response string

    Returns:
        Dict with is_correct, confidence, score, strengths, weaknesses.
        On parse failure, returns a degraded result with is_correct=False.
    """
    prompt = JUDGE_PROMPT_TEMPLATE.format(
        input_data=input_data,
        actual_output=actual_output,
        expected_output=expected_output,
    )
    try:
        response = judge_fn(prompt)
        result = _parse_judge_response(response)
        return result
    except Exception as e:
        logger.warning("Judge evaluation failed: %s", e)
        return {
            "is_correct": False,
            "confidence": 0.0,
            "score": 0,
            "strengths": [],
            "weaknesses": [f"Judge failed: {e}"],
        }


def _parse_judge_response(response: str) -> dict[str, Any]:
    """Parse the judge LLM response into structured dict."""
    text = response.strip()
    # Strip markdown code fences: remove only first and last fence lines
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```)
        lines = lines[1:]
        # Remove last line if it's a closing fence
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)

    data = json.loads(text)

    return {
        "is_correct": bool(data.get("is_correct", False)),
        "confidence": float(data.get("confidence", 0.0)),
        "score": int(data.get("score", 0)),
        "strengths": list(data.get("strengths", [])),
        "weaknesses": list(data.get("weaknesses", [])),
    }


def evaluate_batch(
    cases: list[dict[str, str]],
    judge_fn: JudgeFn,
) -> list[dict[str, Any]]:
    """Evaluate multiple cases. Each case needs 'input', 'actual', 'expected' keys."""
    results = []
    for case in cases:
        r = evaluate_with_judge(
            input_data=case["input"],
            actual_output=case["actual"],
            expected_output=case["expected"],
            judge_fn=judge_fn,
        )
        r["case_id"] = case.get("id", "")
        results.append(r)
    return results


def judge_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize batch judge results into evolution signals format."""
    if not results:
        return {"source": "llm-as-judge", "total": 0}
    correct = sum(1 for r in results if r["is_correct"])
    scores = [r["score"] for r in results]
    confidences = [r["confidence"] for r in results]
    return {
        "source": "llm-as-judge",
        "total": len(results),
        "correct": correct,
        "accuracy": correct / len(results),
        "avg_score": sum(scores) / len(scores),
        "avg_confidence": sum(confidences) / len(confidences),
    }
