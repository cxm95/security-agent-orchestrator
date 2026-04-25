---
name: grader-gaiasec
description: >
  Grade web vulnerability hunting sessions against API audit tasks.
  Five-dimensional scoring: target coverage, step thoroughness, finding
  confidence, token efficiency, and novel discoveries.
  Output format: CAO_SCORE=<integer 0-100>
---

# Web Vulnerability Hunting Grader

Evaluate the quality of a web security audit session. Produce a score (0-100).

## When This Skill Runs

Invoked automatically by the CAO bridge plugin after an agent completes a
task with `grader_skill: grader-gaiasec` in its `task.yaml`.
You may also invoke it manually to re-grade past output.

## Input

1. **Task ID** — identifies which audit task was performed
2. **Session Log** — the full agent output from the audit session
3. **Task Description** (optional) — from `task.yaml`

If the task description is not provided inline, fetch it:
```
cao_get_task(task_id) → read the "description" field from task_yaml
```

## Grading Process

### Step 1: Understand the Audit Scope

Read the task description to extract:
- Target API endpoints / routes / controllers to audit
- Technology stack (framework, ORM, auth mechanism, etc.)
- Specific vulnerability classes to look for (if any)

If the task specifies N target endpoints/files, record that as `total_targets`.
If not explicitly listed, infer from the codebase scope described.

### Step 2: Evaluate Five Dimensions

Score each dimension on a 0–1 scale, then apply weights.

#### D1 — Target Coverage (weight 0.25)

Did the agent examine all relevant code paths for the audit target?

| Score | Criteria |
|-------|----------|
| 1.0 | All target endpoints/files reviewed; related middleware, auth guards, validators, and data-flow sinks also examined |
| 0.7 | Most targets reviewed (≥80%); minor peripheral code skipped |
| 0.5 | Roughly half the targets reviewed; some important routes ignored |
| 0.3 | Only a few targets touched; large blind spots remain |
| 0.0 | Agent did not read any target code, or audited the wrong scope entirely |

How to measure:
- List every target endpoint/file from the task description
- For each, check if the session log shows the agent read, analyzed, or tested it
- `coverage_ratio = reviewed_targets / total_targets`
- Bonus +0.1 (capped at 1.0) if the agent also traced cross-cutting concerns
  (middleware, shared validators, ORM query builders, auth decorators)

#### D2 — Step Thoroughness (weight 0.25)

For each action the agent took, did it execute properly or cut corners?

| Score | Criteria |
|-------|----------|
| 1.0 | Every analysis step is complete: reads source → understands logic → identifies risk → verifies/tests → concludes |
| 0.7 | Most steps are thorough; occasional shallow passes on low-risk areas |
| 0.5 | Mixed — some steps are deep, others are clearly rushed or skipped |
| 0.3 | Predominantly shallow: agent skimmed code, made assumptions without verification |
| 0.0 | Agent did almost nothing meaningful, or copy-pasted generic checklists without applying them |

Red flags (each −0.1, max −0.3):
- **Skipped verification**: agent claimed a vuln exists without reading the actual code path
- **Lazy grep**: agent only grepped for keywords (e.g. `eval`, `exec`) without understanding context
- **Abandoned mid-step**: agent started analyzing a route then moved on without conclusion

#### D3 — Finding Confidence (weight 0.25)

For each reported finding, is there sufficient evidence?

| Score | Criteria |
|-------|----------|
| 1.0 | Every finding has: exact file + line, vulnerable code snippet, data-flow trace from source to sink, and a concrete exploit scenario or PoC |
| 0.7 | Findings have file/line and code reference; data-flow is described but not fully traced |
| 0.5 | Findings identify the right area but lack precise evidence; some hand-waving |
| 0.3 | Findings are vague ("this endpoint might be vulnerable to SQLi") with no code reference |
| 0.0 | No findings reported, or all findings are clearly false positives |

Penalties:
- **False positive presented as confirmed**: −0.15 per instance (max −0.45)
- **Severity inflation**: claiming Critical/High without justification: −0.05 per instance

Bonus:
- +0.1 if agent explicitly marks uncertain findings as "needs verification" rather than asserting them (intellectual honesty)

#### D4 — Token Efficiency (weight 0.15)

Did the agent plan well and execute without unnecessary waste?

| Score | Criteria |
|-------|----------|
| 1.0 | Clean execution: good plan upfront, minimal backtracking, no repeated mistakes |
| 0.7 | Minor inefficiencies: one or two wrong turns quickly corrected |
| 0.5 | Noticeable waste: agent went down a wrong path, re-read the same files, or repeated failed approaches |
| 0.3 | Significant waste: multiple wrong plans, circular reasoning, or large blocks of irrelevant analysis |
| 0.0 | Chaotic: agent spent most of the session on wrong targets, repeated the same errors, or produced walls of irrelevant output |

What counts as waste:
- Reading the same file/function multiple times without new purpose
- Pursuing a vulnerability theory that was already disproven
- Generating long generic security checklists instead of targeted analysis
- Planning steps that are never executed
- Executing steps that contradict the plan without acknowledging the change

What does NOT count as waste:
- Re-reading code to verify a finding (intentional)
- Changing approach after discovering new information (adaptive)
- Thorough analysis that turns out negative (diligence)

#### D5 — Discovery & Knowledge Leverage (weight 0.10)

Did the agent find anything beyond the obvious, or effectively leverage shared
knowledge to achieve better results?

This dimension rewards two things: original discovery AND smart reuse of
cross-agent knowledge (secnotes, L1 briefing, recall results).

| Score | Criteria |
|-------|----------|
| 1.0 | Agent discovered a non-trivial vulnerability or architectural weakness not hinted at in the task description, well-supported with evidence; OR agent leveraged shared knowledge (secnotes/recall) that directly led to a confirmed finding or significantly improved coverage/efficiency |
| 0.7 | Agent identified an interesting secondary issue beyond primary targets; OR agent referenced shared knowledge and applied it effectively to a different component (e.g. applied a known technique from a secnote to a new endpoint, used a recon note to prioritize high-risk targets) |
| 0.5 | Agent noted potential issues beyond scope but did not fully investigate; OR agent searched shared knowledge but only used it superficially |
| 0.3 | Agent mentioned generic "other things to look at" without substance; OR agent searched knowledge but did not act on it |
| 0.0 | No discoveries beyond what was explicitly asked for, and no use of shared knowledge (this is the baseline — not a penalty) |

How to evaluate knowledge leverage:
- Check if the session log shows `cao_search_knowledge`, `cao_recall`, or `cao_fetch_document` calls
- Check if the agent referenced content from the L1 Security Briefing or specific secnotes
- The key question: did the reused knowledge lead to a CONCRETE outcome (finding, coverage gain, time saved by skipping a dead-end)?
- Merely searching without acting on results = 0.3 at best
- Applying a shared technique to a new target and getting a result = 0.7+
- Using a recon note to discover an attack surface that led to a confirmed vuln = 1.0

Note: This dimension rewards both initiative and collaboration. A score of 0.0 is neutral, not negative.

### Step 3: Calculate Final Score

```
raw = D1 * 0.25 + D2 * 0.25 + D3 * 0.25 + D4 * 0.15 + D5 * 0.10
penalties = sum of all red-flag deductions from D2 and D3
adjusted = max(0.0, min(1.0, raw - penalties))
final_score = round(adjusted * 100)
```

### Step 4: Check for Disqualifiers

Before outputting, check these overrides:

| Condition | Override |
|-----------|----------|
| Agent audited the wrong target entirely | Cap at 10 |
| Agent refused or declined the task | Score 0 |
| Agent produced no output or errored out | Score 0 |
| Session log is truncated/incomplete | Grade on available evidence, note in rationale |

### Step 5: Output

Print exactly one line (parsed by the plugin):

```
CAO_SCORE=<integer 0-100>
```

Then provide a structured rationale:

```
D1-Coverage: 0.80 — reviewed 8/10 endpoints, missed /admin/export and /api/webhook
D2-Thoroughness: 0.70 — solid analysis on auth routes, but skipped input validation on /api/upload
D3-Confidence: 0.85 — 3 findings with code-level evidence; 1 marked as needs-verification
D4-Efficiency: 0.60 — wasted ~20% of session re-reading auth middleware after initial pass
D5-Discovery&Leverage: 0.50 — used cao_recall to find a dead-end note on SSRF, skipped that path; noted a potential IDOR in /api/users/{id}/settings but did not pursue
Penalties: -0.10 (one skipped verification in D2)
Raw: 0.73, Adjusted: 0.63, Final: 63
```

## Edge Cases

- **No vulnerabilities found but analysis is thorough**: Score by D1+D2+D4+D5; D3 = 0.5 (neutral — absence of findings is not a failure if the code is genuinely secure, but agent should explicitly state "no issues found" with reasoning)
- **Agent found vulns not in scope**: Credit under D5 if well-supported; do not penalize D1
- **Multiple audit passes on same target**: Grade the cumulative result, not individual passes
- **Agent self-corrected a false positive**: This is positive — do not penalize the initial mistake if it was retracted

## Important Notes

- Scores MUST be integers between 0 and 100 inclusive
- Always output the `CAO_SCORE=` line even if evaluation is uncertain
- Be strict — do not inflate scores. The evolution system depends on honest grading
- If you lack enough context to grade properly, default to 50 with a rationale explaining the uncertainty
- This grader is designed for web API security audits; for other task types, fall back to `security-grader`
