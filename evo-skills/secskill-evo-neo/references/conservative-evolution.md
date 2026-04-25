# Conservative Evolution Framework

This document defines the rules for skill evolution. Read it in full
before proposing any change to a skill. It exists because skills are
shared infrastructure — a change that helps one agent on one task but
degrades performance for others is a net loss.

## The Sequential Evidence Gate

Every proposed change must pass two gates **in order**. Fail at any
gate and the change is rejected — record the observation in TIP.md
instead.

### Gate 1: Failure Evidence

First ask: is there a concrete problem? Without a real failure, there
is nothing to fix — stop here.

A concrete, specific case where the skill caused a bad outcome.

**Qualifies as failure evidence:**
- Agent produced wrong output and the transcript shows it followed the
  skill's instructions (the instructions were wrong/incomplete)
- Agent got stuck or looped because the skill's guidance was ambiguous
- Agent skipped a critical step because the skill didn't mention it
- Multiple independent agents hit the same problem on different tasks
  (strongest signal)

**Does NOT qualify:**
- "The score could be higher" without a specific failure case
- Agent made a mistake that the skill already warns against (agent
  error, not skill error)
- The task was infeasible or the environment was broken
- A single low score without understanding what went wrong
- "I think this section could be written better" (aesthetic preference)

### Gate 2: Improvement Evidence

Gate 1 passed — a real failure exists. Now ask: is there evidence that
the proposed change would actually make things better? A real problem
does not automatically justify a change. The fix must be demonstrably
sound, not speculative.

A clear argument that the proposed change would fix the failure AND
would not break other cases.

**Qualifies as improvement evidence:**
- "The skill says X, which caused the agent to do Y. If we change it
  to Z, the agent would do W instead, which is correct. This applies
  to any target that has [general property]."
- "The skill is silent on [class of scenarios]. Adding guidance for
  this class would help because [reasoning]. The guidance is not
  specific to any particular target."
- A pattern observed across 2+ independent failures pointing to the
  same root cause

**Does NOT qualify:**
- "Let's try changing this and see if it helps" (experiment without
  hypothesis)
- "This worked for the current task" without generalization argument
- "The agent would have done better if the skill said [exact thing
  the agent should have done in this specific case]"
- Copying a successful agent's ad-hoc strategy into the skill without
  abstracting it

## Change Levels

Assess the appropriate level BEFORE making any edits. The level
constrains what you're allowed to do.

### L0: No Change

**When:** Either evidence gate fails, OR the failure is outside the
skill's control (environment, task definition, agent capability).
Gate 1 failed (no real failure), or Gate 1 passed but Gate 2 failed
(no evidence the fix would help).

**Action:** Write TIP.md entry only. This is a valid and common
outcome. Most evolution cycles should end here — if you're changing
the skill every time, you're probably overfitting.

**Examples:**
- Agent failed because the target server was down → L0
- Agent scored low but followed the skill correctly; the task was
  just hard → L0
- You have a hunch the skill could be better but no concrete failure
  → L0
- The failure is real but you can't articulate a fix that generalizes
  → L0

### L1: Tweak (≤3 lines)

**When:** A specific phrase or sentence in the skill caused
misunderstanding, and rewording it would prevent the misunderstanding
for any agent on any task.

**Allowed:** Change, add, or remove up to 3 lines. No structural
changes. No new sections.

**Examples:**
- "Check the auth endpoint" → "Check the auth endpoint; if no
  dedicated auth endpoint exists, look for token handling in any
  endpoint that returns session data"
- Remove a misleading example that doesn't match the instruction
- Fix a factual error in a reference

### L2: Addition (≤1 paragraph or section)

**When:** The skill is missing guidance for a class of scenarios that
multiple agents would encounter. The gap is clear from the failure
evidence.

**Allowed:** Add up to one new paragraph within an existing section,
OR one new short section (≤15 lines). Do not restructure existing
content.

**Examples:**
- Add a "When authentication fails" subsection to a scanning skill
- Add a paragraph about handling rate-limited APIs
- Add a new entry to an existing checklist or table

### L3: Restructure

**When:** The skill's core approach has a structural flaw that causes
repeated failures across different tasks and agents. This is rare.

**Required:** At least 2 independent failure cases pointing to the
same structural issue. "Independent" means different tasks, different
agents, or different time periods.

**Allowed:** Major edits including reordering sections, rewriting
core logic, changing the skill's approach. Still subject to the
generalizability requirement.

**Examples:**
- The skill's step ordering causes agents to consistently do
  reconnaissance after exploitation (backwards)
- The skill's scoring rubric systematically undervalues a critical
  dimension, proven by multiple grading failures

## Generalizability Checklist

Before committing any L1+ change, verify each item:

- [ ] **No hardcoded specifics**: The change does not contain specific
      IPs, ports, paths, API names, domain names, or credentials
- [ ] **No framework lock-in**: If the change mentions a specific
      framework or tool, it's conditional ("when using X, ...") not
      absolute
- [ ] **Target-independent**: If you replaced the current target with
      a completely different application, the change would still be
      useful
- [ ] **Agent-independent**: The change helps any agent following the
      skill, not just the one that failed
- [ ] **Task-independent**: The change helps across different task
      types, not just the specific task that triggered this evolution
- [ ] **No session leakage**: The change does not reference anything
      from the current session (findings, scores, specific errors)
      as if it were general knowledge

## Anti-Patterns

These are changes that LOOK helpful but are actually harmful. Reject
them even if they pass the evidence gates.

### 1. Overfitting to the Grader

"The grader checks for X, so let's add an instruction to always do X."

The skill should teach good security practice. If the grader rewards
something, it's because that thing is generally valuable — not because
gaming the grader is the goal. If you find yourself optimizing for
grader dimensions rather than actual effectiveness, stop.

### 2. Promoting Workarounds to Permanent Instructions

"The agent worked around a problem by doing Y, so let's tell all
agents to do Y."

Workarounds are context-dependent. What worked for one agent on one
target may be unnecessary or harmful elsewhere. If the workaround
reveals a genuine gap in the skill, abstract the PRINCIPLE behind
the workaround, not the specific technique.

### 3. Accumulating "ALWAYS/NEVER" Rules

"Agents keep making mistake Z, so add ALWAYS/NEVER Z."

Each ALWAYS/NEVER rule adds cognitive load and reduces the agent's
ability to exercise judgment. Instead, explain WHY Z is usually wrong
and WHEN the exception applies. If you must add a hard rule, it
should be because violating it is ALWAYS wrong regardless of context
(e.g., "never commit credentials to git").

### 4. Expanding Scope Creep

"While we're here, let's also add guidance for [related topic]."

Each evolution cycle addresses ONE failure. If you notice other
improvements, write them in TIP.md for a future cycle. Bundling
changes makes it impossible to attribute improvement or regression
to a specific change.

### 5. Copying Another Agent's Session Strategy

"Agent A scored 85 by doing [specific sequence]. Let's encode that
sequence in the skill."

Agent A's strategy worked for its specific task and target. Encoding
it makes the skill brittle. Instead, ask: what PRINCIPLE made that
strategy effective? Encode the principle, not the procedure.

## Decision Flowchart

```
Failure observed
    │
    ├─ Is it caused by the skill? ──── No ──→ L0 (TIP.md only)
    │
    Yes
    │
    ├─ Can you articulate a fix? ──── No ──→ L0 (TIP.md only)
    │
    Yes
    │
    ├─ Does the fix generalize? ───── No ──→ L0 (TIP.md only)
    │
    Yes
    │
    ├─ Is it a wording issue? ─────── Yes ─→ L1 (≤3 lines)
    │
    No
    │
    ├─ Is it a missing scenario? ──── Yes ─→ L2 (≤1 section)
    │
    No
    │
    ├─ 2+ independent failures? ───── Yes ─→ L3 (restructure)
    │
    No ──→ L0 (wait for more evidence)
```
