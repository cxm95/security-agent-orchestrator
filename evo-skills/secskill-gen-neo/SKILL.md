---
name: secskill-gen-neo
description: >
  Distill a proven method into a reusable skill after an agent successfully
  completes a task. Use when an agent has explored, failed, and ultimately
  succeeded — and the method deserves to be captured for other agents.
  Conservative: only generates a skill when the method genuinely generalizes.
  Triggers on "capture this as a skill", "distill skill", "沉淀技能",
  "提炼技能", or via heartbeat after sustained high scores.
---

# Secskill-Gen-Neo

Distill proven methods from successful executions into reusable skills.

Skills are not designed top-down — they are **precipitated** from practice.
An agent explores, fails, adjusts, and eventually succeeds. This skill
captures the "how I succeeded" into a form that helps other agents on
other tasks. If the method doesn't generalize, it stays as a note, not
a skill.

## Core Principle: Earn the Right to Become a Skill

Not every success deserves a skill. A skill is shared infrastructure —
it occupies context window space for every agent that loads it. The bar
for generating a new skill is intentionally high:

1. **The method must be proven** — it actually worked, not just
   theoretically sound
2. **The method must generalize** — it would help an agent working on
   a completely different target
3. **The method must be incremental** — existing skills and notes don't
   already cover it
4. **The method must be multi-step** — a single trick or observation
   belongs in a secnote, not a skill

If any of these fail, the correct output is a secnote (via cao-secnote),
not a skill. This is not a failure — it's the right granularity choice.

Read `references/generation-gate.md` at Step 2 for the full framework.

---

## Trigger Detection

This skill activates when:

- **CAO heartbeat** sends a `generate_skill` prompt (sustained high
  scores suggest the agent has a method worth capturing)
- **User explicitly asks**: "capture this as a skill", "distill skill",
  "沉淀技能", "提炼技能", "turn this into a skill"
- **cao-reflect** output identifies a reusable multi-step pattern

If the trigger source is ambiguous, ask: "What method do you want to
capture, and what execution demonstrated it?"

---

## Generation Flow

### Step 1: Reconstruct the Execution Story

Review the session history to build a narrative of what happened:

1. **What was the goal?** What task was the agent trying to accomplish?
2. **What failed?** Which approaches were tried and didn't work? Why?
3. **What was the turning point?** Which decision or discovery changed
   the outcome from failure to success?
4. **What was the final method?** The sequence of steps that actually
   worked, in order.
5. **What was task-specific vs general?** Separate the method (general)
   from the application (specific to this target).

Write this as a structured summary — you'll need it for Steps 2–3.

**CAO heartbeat integration:** When invoked via heartbeat, the
`evolution_signals` contain recent scores and task context. Use the
leaderboard to identify which task(s) the agent excelled at.

### Step 2: Generation Gate

**This step is mandatory. Do not skip it.**

Read `references/generation-gate.md` in full. Then evaluate:

**Gate 1 — Generalizability:**
- Strip all target-specific details from the method. Does a coherent,
  useful method remain?
- Would this method help an agent working on a completely different
  application/target/framework?
- If NO → write a secnote instead (via cao-secnote). Stop here.

**Gate 2 — Incremental value:**
- Search existing knowledge: `cao_recall` with keywords from the method.
- Does an existing skill already cover this method (80%+ overlap)?
  → Don't generate. Consider filing an evolution request for the
  existing skill instead.
- Does an existing note already capture the key insight?
  → Don't generate. A note is sufficient.
- If no incremental value → stop here.

**Gate 3 — Granularity:**
- Is this a single trick, observation, or finding?
  → secnote, not a skill.
- Is this a complete multi-step methodology where removing any step
  would break the method?
  → This is skill-worthy. Proceed.
- Rule of thumb: if it takes fewer than 3 steps to describe, it's
  a note.

**If any gate fails:** recommend writing a secnote instead and explain
why. This is a valid and valuable outcome.

### Step 3: Distill the Skill

Read `templates/skill-skeleton.md` for the output structure. Then:

#### 3a. Extract the method

From the execution story (Step 1), extract:
- The **steps** in order — what to do, not what was done
- The **decision points** — where judgment is needed, with guidance
- The **pitfalls** — what the agent tried that didn't work, and why
  (these become warnings in the skill)
- The **success criteria** — how to know each step worked

#### 3b. Abstract away specifics

For each element, remove task-specific details:
- Replace specific endpoints with "[target endpoint]"
- Replace specific vulnerabilities found with the CLASS of vulnerability
- Replace specific tools used with the CATEGORY of tool
- Keep the reasoning and decision logic — that's the valuable part

#### 3c. Write the SKILL.md

Follow the skeleton from `templates/skill-skeleton.md`. Key constraints:
- **≤200 lines** for SKILL.md body. If longer, you're including too
  much detail — move reference material to `references/`.
- **No session leakage**: grep your output for any IPs, ports, paths,
  domain names, API keys, or specific findings from the current session.
  Remove all of them.
- **Imperative voice**: "Check the authentication mechanism" not
  "The agent checked the authentication mechanism"
- **Explain why, not just what**: "Check auth tokens for expiration
  handling (common misconfiguration that leads to session fixation)"

#### 3d. Write the description

The YAML frontmatter `description` field determines when the skill
triggers. Follow these guidelines:
- Focus on user intent, not implementation details
- Use imperative phrasing: "Use this skill when..."
- Include trigger phrases in both English and Chinese if relevant
- Stay under 1024 characters
- Be specific enough to avoid false triggers, broad enough to catch
  relevant cases

### Step 4: Self-Review

Before writing the skill to disk, verify:

- [ ] **No session leakage**: No IPs, ports, paths, domain names,
      credentials, or specific findings from the current session
- [ ] **Standalone comprehension**: An agent that has never seen the
      current task can understand and follow this skill
- [ ] **Generalizability**: Replace the current target mentally with
      3 different applications — does the skill still make sense?
- [ ] **Incremental value**: This skill teaches something that no
      existing skill or note already covers
- [ ] **Appropriate granularity**: This is genuinely a multi-step
      method, not a single trick dressed up as a skill
- [ ] **Conciseness**: SKILL.md body is ≤200 lines
- [ ] **Description quality**: Triggers correctly, doesn't false-trigger

If any check fails:
- Can it be fixed by editing? → Fix and re-check.
- Is the core problem that it's not skill-worthy? → Downgrade to
  secnote. Write it via cao-secnote instead.

### Step 5: Write and Sync

#### 5a. Choose a name

- kebab-case, lowercase, descriptive
- Pattern: `<domain>-<method>` (e.g., `api-auth-bypass-testing`,
  `jwt-token-analysis`, `rate-limit-enumeration`)
- Check for name collisions: `cao_recall` with the proposed name

#### 5b. Write to disk

```bash
SKILL_NAME="<chosen-name>"
SKILL_DIR="$HOME/.cao-evolution-client/skills/$SKILL_NAME"
mkdir -p "$SKILL_DIR"
# Write SKILL.md (generated in Step 3)
# Write references/ if needed
```

If the skill references helper scripts or detailed documentation,
create `references/` or `scripts/` subdirectories as needed. Keep
the total footprint minimal.

#### 5c. Sync

```bash
cd ~/.cao-evolution-client && git add -A && \
  git commit -m "gen: $SKILL_NAME — <one-line description>" && git push
```
Or call `cao_push` via MCP.

#### 5d. Report

Tell the user (or log for heartbeat):
- Skill name and path
- One-line summary of what it captures
- Which execution it was distilled from

---

## What This Skill Does NOT Do

- **Create skills from specifications** — that's top-down design, not
  bottom-up distillation. Use secskill-evo's Create Mode (legacy) or
  write manually.
- **Evolve existing skills** — that's secskill-evo-neo's job.
- **Share individual findings** — that's cao-secnote's job.
- **Derive skill variants** — that's openspace-evo's job.

The boundary is clear: gen-neo turns a successful execution into a NEW
skill. Everything else has its own tool.

---

## Reference Files

- `references/generation-gate.md` — Generation gate framework
  (generalizability, incremental value, granularity checks).
  **Must be read at Step 2.**
- `templates/skill-skeleton.md` — SKILL.md template for generated
  skills. Read at Step 3.
