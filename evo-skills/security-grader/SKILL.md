---
name: security-grader
description: >
  Grade security scan output against a task's objectives. Triggered automatically
  by the CAO plugin after task completion. Use when you need to evaluate the
  quality, completeness, and accuracy of a security assessment, vulnerability
  scan, or code audit. Also triggers on "grade this", "evaluate output",
  "score this scan", "CAO_SCORE".
---

# Security Grader

Evaluate the quality of a security task's output and produce a normalized score.

## When This Skill Runs

This skill is invoked **automatically** by the CAO bridge plugin after an agent
completes a task that has `grader_skill: security-grader` in its `task.yaml`.
You may also invoke it manually to re-grade past output.

## Input

You will receive:

1. **Task ID** — identifies which task was performed
2. **Agent Output** — the full output text from the completed task
3. **Task Description** (optional) — from `task.yaml`, describes what the task expects

If the task description is not provided inline, fetch it:
```
cao_get_task(task_id) → read the "description" field from task_yaml
```

## Grading Process

### Step 1: Understand the Task Objective

Read the task description to understand:
- What was the agent supposed to find/do?
- What constitutes a complete answer?
- Are there specific deliverables expected (findings list, code fix, report)?

### Step 2: Evaluate Output Quality

Score each dimension on a 0–1 scale:

| Dimension | Weight | Criteria |
|-----------|--------|----------|
| **Completeness** | 0.30 | Did the agent address all aspects of the task? |
| **Accuracy** | 0.30 | Are the findings correct? No false positives? |
| **Actionability** | 0.20 | Are findings specific enough to act on (file, line, fix)? |
| **Depth** | 0.20 | Did the agent go beyond surface-level? Root cause analysis? |

### Step 3: Check for Disqualifiers

Reduce score significantly for:
- **False positives** presented as confirmed: −0.15 per instance (max −0.45)
- **Critical miss**: if a well-known vulnerability class was completely ignored: −0.20
- **Wrong scope**: agent scanned the wrong target or misunderstood the task: set score ≤ 0.1

### Step 4: Calculate Final Score

```
raw_score = completeness * 0.30 + accuracy * 0.30 + actionability * 0.20 + depth * 0.20
final_score = max(0.0, min(1.0, raw_score - penalties))
```

### Step 5: Output

Print the following on a **single line** (this is parsed by the plugin):

```
CAO_SCORE=<final_score as float, e.g. 0.72>
```

Then provide a brief rationale (2-5 sentences) explaining the score:

```
Rationale: Found 3 of 4 known SQL injection points (completeness=0.75).
All reported findings are valid (accuracy=1.0). Missing the stored XSS
in /admin/template.html (critical miss, -0.20). Findings include file
paths and line numbers (actionability=0.9). No root cause analysis
provided (depth=0.5). Raw=0.78, penalties=-0.20, final=0.58.
```

## Adaptation for Non-Security Tasks

If the task is not security-specific (e.g., code generation, documentation),
adjust the dimensions:

| Dimension | Weight | Criteria |
|-----------|--------|----------|
| **Correctness** | 0.35 | Does the output meet the requirements? |
| **Completeness** | 0.25 | Are all requested items addressed? |
| **Quality** | 0.25 | Code quality, doc clarity, best practices? |
| **Efficiency** | 0.15 | Reasonable approach? No unnecessary complexity? |

The output format remains the same: `CAO_SCORE=<float>`.

## Important Notes

- Scores MUST be between 0.0 and 1.0 inclusive
- Always output the `CAO_SCORE=` line even if evaluation is uncertain
- If the output is empty or clearly errored, score 0.0
- Be honest — do not inflate scores. The evolution system relies on accurate
  scoring to decide when to trigger skill improvements
- If you lack enough context to grade properly, default to 0.5 with a rationale
  explaining the uncertainty
