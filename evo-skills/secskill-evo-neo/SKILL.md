---
name: secskill-evo-neo
description: >
  Evolve existing skills based on execution feedback. Use when a skill
  underperformed and needs targeted improvement — triggered by CAO heartbeat
  plateau detection, human feedback annotations, or explicit user request.
  Enforces conservative evolution: no change without failure evidence,
  and no change without proof the fix would actually help. Also triggers on "reflect and evolve", "evolve
  this skill", "反思并进化", "基于本次执行反思并进行进化".
---

# Secskill-Evo-Neo

Evolve skills based on execution feedback. Conservative by design — every
change must pass a sequential evidence gate before it touches the skill:
first prove a failure exists, then prove the fix would help.

This skill does ONE thing: take a skill that underperformed, diagnose why,
and apply the minimum viable fix that generalizes beyond the current task.
It does not create skills from scratch, run benchmarks, or optimize
descriptions.

## Core Principle: Conservative Evolution

A skill serves many agents across many tasks. A change that helps one task
but hurts three others is a net loss. Before any modification:

1. **Failure evidence must exist** — a concrete case where the skill
   produced wrong output, missed a step, or led the agent astray.
   Without this, there is nothing to fix. Stop here.
2. **Improvement evidence must exist** — even with a real failure, a
   change is only justified if you can demonstrate the proposed fix
   would actually make things better. "It might help" is not enough.

These gates are sequential: pass Gate 1 first, then Gate 2. If either
fails, the correct action is to document the observation in TIP.md and
move on without modifying the skill.

Read `references/conservative-evolution.md` at Step 3 for the full
framework — change levels, generalizability checklist, and anti-patterns.

---

## Trigger Detection

This skill activates when:

- **CAO heartbeat** sends evolution signals (prompt contains
  `evolution_signals` and/or `leaderboard`)
- **feedback-fetch** delivers human annotations on a previous report
- **User explicitly asks**: "evolve", "reflect and evolve", "反思并进化",
  "基于本次执行反思并进行进化", "the skill failed on X", "fix the skill"

If the trigger source is ambiguous, ask: "Which skill needs evolution, and
what went wrong?"

---

## Evolution Flow

### Step 1: Gather Context

Collect three pieces of information (from conversation history, heartbeat
signals, or by asking the user):

| Input | Source | Required |
|-------|--------|----------|
| **Target skill** | Path to skill directory | Yes |
| **Failure evidence** | Error messages, wrong output, missed steps, score regression | Yes |
| **Expected vs actual** | What should have happened vs what did happen | Yes |

Then read the target skill thoroughly:
- `SKILL.md` — full content
- All files in `scripts/`, `agents/`, `references/` — understand the
  complete skill logic
- `TIP.md` — if it exists, read past evolution lessons to avoid repeating
  mistakes
- `utility.json` — if it exists, review evolution history for patterns

**CAO heartbeat integration:** When invoked via heartbeat, extract the
target skill from `evolution_signals`. The leaderboard and score history
tell you what's plateauing and by how much.

**feedback-fetch integration:** When invoked after `cao_fetch_feedbacks`,
the feedback brief contains annotated findings with human corrections.
Map each correction back to a skill instruction gap.

### Step 2: Judge Current Performance

Read `agents/judge.md` for evaluation instructions. For each failure case:

1. **Binary judgment**: Is the output correct or incorrect? Confidence?
2. **Soft score** (0–100): How good is the output on a continuous scale?
3. **Root cause classification**:

| Category | Description | Typical Fix |
|----------|-------------|-------------|
| **Instruction gap** | Skill doesn't address this scenario | Add guidance |
| **Instruction ambiguity** | Skill says something unclear | Clarify wording |
| **Logic error** | Skill's approach leads to wrong result | Fix the logic |
| **Scope mismatch** | Failure is outside the skill's domain | Don't fix — document in TIP.md |
| **Environment issue** | Tool/infra problem, not skill problem | Don't fix — document in TIP.md |

4. **Improvement hints**: Specific, actionable suggestions for the skill

Write results to `<workspace>/judge_results.json`. See
`references/schemas.md` for the exact format.

### Step 3: Conservative Evolution Gate

**This step is mandatory. Do not skip it.**

Read `references/conservative-evolution.md` in full. Then answer these
questions for each proposed change:

**Gate 1 — Failure evidence (ask this first):**
- Is there a concrete failure case (not just "could be better")?
- Is the failure caused by the skill (not by the environment, the task
  definition, or the agent's own mistakes)?
- If NO to either → stop here, go to L0.

**Gate 2 — Improvement evidence (only if Gate 1 passed):**
- Can you articulate WHY the proposed change fixes the failure?
- Can you argue that the fix generalizes to other tasks/targets?
- Does the change avoid embedding task-specific details (IPs, paths,
  API names, framework-specific logic)?
- If NO to any → stop here, go to L0.

**Gate 3 — Change level assessment (only if both gates passed):**

| Level | Condition | Allowed scope |
|-------|-----------|---------------|
| L0 No change | Gate 1 or Gate 2 failed | Write TIP.md only |
| L1 Tweak | Wording caused misunderstanding | ≤3 lines changed |
| L2 Addition | Missing guidance for a class of scenarios | ≤1 new paragraph/section |
| L3 Restructure | Structural flaw proven by 2+ independent failures | Major edit, requires extra justification |

**If the assessment is L0**: skip Steps 4–5, go directly to Step 6 to
record observations in TIP.md. This is a valid and valuable outcome —
not every evolution cycle should produce a code change.

### Step 4: Isolate, Snapshot, and Apply

#### 4a. Create isolated workspace

Never edit the skill in-place. Copy to a temporary workspace first:

```bash
SKILL_NAME=$(basename <skill-dir>)
WORKSPACE=/tmp/cao-evo-workspace/$SKILL_NAME
rm -rf "$WORKSPACE"
cp -r <skill-dir> "$WORKSPACE"

# Safety check: verify workspace is where we expect
RESOLVED=$(cd "$WORKSPACE" && pwd -P)
if [[ ! "$RESOLVED" =~ ^/tmp/cao-evo-workspace/ ]]; then
  echo "Error: workspace path outside expected directory"; exit 1
fi
```

#### 4b. Git snapshot (pre-evolution)

```bash
SCRIPTS_DIR="<path-to-secskill-evo-neo>/scripts"

python3 "$SCRIPTS_DIR/git_version.py" init "$WORKSPACE"
python3 "$SCRIPTS_DIR/git_version.py" commit "$WORKSPACE" \
  --message "pre-evolve: baseline" --tag v{N}
```

Use `python3 "$SCRIPTS_DIR/git_version.py" current "$WORKSPACE"` to
determine the current version number N.

#### 4c. Apply changes

Edit the skill files in `$WORKSPACE` following these principles:

- **Preserve working functionality**: don't break what works while fixing
  what doesn't
- **Explain "why"**: don't add "ALWAYS do X" — explain the reasoning so
  the model can generalize
- **Keep the skill lean**: target <500 lines for SKILL.md
- **Match the change level**: if you assessed L1, don't make L2 changes

#### 4d. Self-review

Before committing, review your own changes against the conservative
evolution checklist:

- [ ] Each changed line traces back to a specific failure case
- [ ] No task-specific details (IPs, ports, paths, API names) were added
- [ ] The change would help an agent working on a completely different
      target
- [ ] The change level matches the assessment from Step 3
- [ ] No "ALWAYS"/"NEVER" rules were added without explaining why
- [ ] The skill's existing structure and terminology are preserved

If any check fails, revise the change or downgrade to a lower change level.

### Step 5: Commit and Sync

#### 5a. Commit the evolution

```bash
python3 "$SCRIPTS_DIR/git_version.py" commit "$WORKSPACE" \
  --message "v{N+1}: <one-line summary of what changed and why>" \
  --tag v{N+1}
```

Show the diff:
```bash
python3 "$SCRIPTS_DIR/git_version.py" diff "$WORKSPACE" \
  --from v{N} --to v{N+1}
```

#### 5b. Copy back and sync

```bash
rsync -a --exclude='.git' "$WORKSPACE/" <original-skill-dir>/
```

If running in CAO distributed mode:
```bash
cd ~/.cao-evolution-client && git add -A && \
  git commit -m "evolve: <skill-name> v{N+1}" && git push
```
Or call `cao_sync` / `cao_push` via MCP.

#### 5c. Retry on regression (max 2 attempts)

If self-review reveals the change is worse than expected:

1. Revert to v{N}:
   ```bash
   python3 "$SCRIPTS_DIR/git_version.py" revert "$WORKSPACE" --to v{N}
   ```
2. Try a different approach (not a tweak of the same approach)
3. After 2 failed attempts, abandon this cycle — revert to v{N}, record
   what was tried in TIP.md, and do NOT leave the skill degraded

### Step 6: Record Experience

This step is **mandatory** regardless of whether the skill was modified.

#### 6a. TIP.md (always)

Write or append to `<skill-dir>/TIP.md` with a dated entry:

```markdown
## YYYY-MM-DD — <brief title>

**Trigger**: <what prompted this evolution cycle>
**Assessment**: <L0/L1/L2/L3>
**Outcome**: <changed/not-changed>

<What was observed, what was tried, what was learned.
For L0 outcomes, explain WHY no change was made — this is
valuable signal for future evolution cycles.>
```

Do not overwrite existing entries — append. The history of past decisions
is itself useful context for future evolutions.

#### 6b. utility.json (always)

Update `<skill-dir>/utility.json` with the evolution record:

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
    }
  ]
}
```

`score_after` is null at evolution time — it gets filled in by the next
grading cycle. `status` is one of: `applied`, `reverted`, `skipped` (L0).

See `references/schemas.md` for the full schema.

---

## CAO Heartbeat Integration

When invoked via a CAO heartbeat prompt (contains `evolution_signals`
and `leaderboard`):

1. **Identify the target skill** from evolution signals or recent work
2. **Use leaderboard data** as failure evidence — score plateau or
   regression across multiple attempts is strong signal
3. **After evolution**, sync results and report:
   - Copy evolved skill to your skills directory
   - Call `cao_sync` or `cao_push`
   - Continue your main task
   - Call `cao_report_score` to close the feedback loop

---

## Reference Files

- `agents/judge.md` — LLM-as-Judge evaluation instructions (binary +
  soft scoring + root cause classification)
- `references/conservative-evolution.md` — Conservative evolution
  framework (change levels, generalizability checklist, anti-patterns).
  **Must be read at Step 3.**
- `references/schemas.md` — JSON schemas for judge_results.json and
  utility.json
