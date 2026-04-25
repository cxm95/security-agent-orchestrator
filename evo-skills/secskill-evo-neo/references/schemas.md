# JSON Schemas

All JSON schemas used by secskill-evo-neo. Two files, unified terminology.

---

## judge_results.json

Output from the LLM-as-Judge agent (Step 2). Located at
`<workspace>/judge_results.json`.

### Single evaluation

```json
{
  "eval_id": 1,
  "binary": {
    "is_correct": false,
    "confidence": 0.85,
    "rationale": "Agent missed the authentication bypass because the skill has no auth testing guidance."
  },
  "soft_score": {
    "score": 42,
    "rationale": "Found 3 of 7 vulnerabilities but missed the critical auth bypass.",
    "strengths": [
      "Thorough parameter fuzzing on public endpoints",
      "Good use of error message analysis"
    ],
    "weaknesses": [
      "Skipped auth testing entirely",
      "Did not check for privilege escalation paths"
    ]
  },
  "root_cause": {
    "category": "instruction_gap",
    "detail": "The skill's recon phase covers endpoint discovery but has no guidance on testing authentication mechanisms.",
    "skill_section": "## Phase 2: Endpoint Analysis",
    "is_skill_fault": true
  },
  "improvement_hints": [
    {
      "hint": "Add auth testing checklist to Phase 2: missing auth header, expired tokens, alternative auth methods, privilege escalation.",
      "target_section": "## Phase 2: Endpoint Analysis",
      "generalizability": 88,
      "reasoning": "Auth testing applies to any web API target."
    }
  ]
}
```

### Fields

- `eval_id` — Integer identifier matching the failure case
- `binary` — Pass/fail judgment
  - `is_correct` — Boolean: does the output substantially accomplish the task?
  - `confidence` — Float 0.0–1.0
  - `rationale` — Brief explanation
- `soft_score` — Nuanced 0–100 quality score (aligned with CAO grader conventions)
  - `score` — Integer 0–100
  - `rationale` — Why this score
  - `strengths` — List of positive aspects
  - `weaknesses` — List of issues
- `root_cause` — Failure diagnosis
  - `category` — One of: `instruction_gap`, `instruction_ambiguity`, `logic_error`, `scope_mismatch`, `environment_issue`, `agent_error`
  - `detail` — What specifically went wrong
  - `skill_section` — Which section of the skill is relevant (if applicable)
  - `is_skill_fault` — Boolean: true only for `instruction_gap`, `instruction_ambiguity`, `logic_error`
- `improvement_hints` — List of suggested changes (empty if `is_skill_fault` is false)
  - `hint` — Specific, actionable change description
  - `target_section` — Which skill section to modify
  - `generalizability` — 0–100 score; below 50 is flagged as risky
  - `reasoning` — Why this change generalizes

### Multiple evaluations

Wrap in a JSON array:

```json
[
  {"eval_id": 1, "binary": {}, "soft_score": {}, "root_cause": {}, "improvement_hints": []},
  {"eval_id": 2, "binary": {}, "soft_score": {}, "root_cause": {}, "improvement_hints": []}
]
```

### Aggregation summary

Appended when evaluating multiple cases:

```json
{
  "summary": {
    "total": 5,
    "correct": 2,
    "incorrect": 3,
    "accuracy": 0.4,
    "avg_score": 48,
    "root_cause_distribution": {
      "instruction_gap": 2,
      "instruction_ambiguity": 1,
      "agent_error": 1,
      "environment_issue": 1
    },
    "skill_attributable_failures": 3,
    "recommended_change_level": "L2",
    "common_patterns": [
      "Auth testing consistently missed across all failure cases"
    ]
  }
}
```

- `skill_attributable_failures` — Count where `is_skill_fault` is true
- `recommended_change_level` — Advisory: `L0`, `L1`, `L2`, or `L3`
- `common_patterns` — Recurring themes across failures

---

## utility.json

Tracks evolution history for a skill. Located at `<skill-dir>/utility.json`.
**Mandatory** — updated every evolution cycle regardless of outcome.

```json
{
  "evolutions": [
    {
      "timestamp": "2026-04-25T10:30:00Z",
      "from_version": "v1",
      "to_version": "v2",
      "trigger": "heartbeat plateau: score stuck at 35 for 3 attempts",
      "change_level": "L1",
      "changes_summary": "Clarified step 3 wording on auth token extraction",
      "score_before": 35,
      "score_after": null,
      "generalizability_argument": "Applies to any target with token-based auth",
      "status": "applied"
    },
    {
      "timestamp": "2026-04-25T14:00:00Z",
      "from_version": "v2",
      "to_version": "v2",
      "trigger": "feedback-fetch: human annotated report #42",
      "change_level": "L0",
      "changes_summary": "No change — failure was environment_issue (target server timeout)",
      "score_before": 35,
      "score_after": null,
      "generalizability_argument": null,
      "status": "skipped"
    }
  ]
}
```

### Fields

- `evolutions[]` — Array of evolution events (append-only)
  - `timestamp` — ISO 8601 timestamp
  - `from_version` — Git tag before evolution
  - `to_version` — Git tag after evolution (same as `from_version` for L0/skipped)
  - `trigger` — What prompted this cycle (heartbeat, feedback-fetch, user request)
  - `change_level` — `L0`, `L1`, `L2`, or `L3`
  - `changes_summary` — One-line description. For L0, explain WHY no change was made
  - `score_before` — Score at evolution time (from grader or judge)
  - `score_after` — Score after next grading cycle. `null` until filled in by subsequent evaluation
  - `generalizability_argument` — Why the change applies beyond this task. `null` for L0
  - `status` — One of:
    - `applied` — Change was made and committed
    - `skipped` — L0 outcome, no change made
    - `reverted` — Change was made but reverted due to regression
