---
name: cao-pivot
description: >
  Change fundamental strategy when score has plateaued. Try a completely different
  approach instead of incremental tweaks.
  Triggered by CAO heartbeat on plateau detection, or manually.
  Triggers on: "pivot", "change approach", "转向", "try something different", "plateau".
---

# CAO Pivot

Your score has plateaued — incremental tweaks are unlikely to help. Step back and
try something **fundamentally different**.

This skill is part of the CAO co-evolution framework, ported from CORAL's `pivot`
heartbeat action. It triggers when N consecutive evaluations show no improvement
(default: 5 evals without improvement).

## When This Skill Runs

- **Heartbeat trigger**: After N consecutive evals without score improvement (plateau detection)
- **Manual trigger**: User says "pivot", "change strategy", "转向", "nothing is working"

## Inputs

When invoked via heartbeat:

- **Evolution signals**: includes `evals_since_improvement` count, recent score trend
- **Leaderboard**: where you stand vs other agents
- **Task ID**: the task you're stuck on

## Process

### Step 1: Diagnose the Plateau

1. Review your recent attempts: Are scores flat or oscillating?
2. Check the leaderboard: Are other agents also stuck, or just you?
3. Identify what you've been trying: List the last 3-5 approaches
4. Why aren't they working? Common plateau causes:
   - **Local optimum**: Your approach works well up to a point but can't improve further
   - **Wrong decomposition**: You're optimizing the wrong sub-problem
   - **Missing information**: You need knowledge you don't have yet
   - **Overfitting**: Your approach is too specialized for the test cases you've seen

### Step 2: Study Alternatives

Search the shared knowledge base for different approaches:

**Via MCP:**
```
cao_search_knowledge(query="approach strategy alternative")
cao_get_leaderboard(task_id="{task_id}")
```

**Via git:**
Read notes in `~/.cao-evolution-client/notes/` — especially synthesis and pivot notes from other agents.

What are other agents doing differently? What approaches haven't been tried?

### Step 3: Choose a Fundamentally Different Strategy

This is NOT about tweaking parameters. Consider:

- **Different algorithm or tool**: If you've been doing X, try Y
- **Different problem decomposition**: Break the problem differently
- **Different data perspective**: Look at the inputs/outputs from a new angle
- **Techniques from other domains**: What would a different field do?
- **Simplification**: Sometimes a much simpler approach wins

Write down your new strategy in one paragraph. If you can describe it as
"the same thing but with minor changes", it's not different enough.

### Step 4: Document the Pivot

Share your reasoning so others can learn from it.

Write to local git and push:

Create `~/.cao-evolution-client/notes/pivot-<timestamp>.md`:

```markdown
---
creator: {agent_id}
created: {ISO 8601 timestamp}
tags: [pivot, {task_id}]
type: pivot
previous_approach: <brief description>
new_approach: <brief description>
evals_since_improvement: {N}
---
# Pivot: <new approach>

## Why the old approach plateaued
<specific diagnosis from Step 1>

## What I'm trying instead
<new strategy from Step 3>

## Expected outcome
<what I think will change and why>
```

Then sync: `cd ~/.cao-evolution-client && git add -A && git commit -m "note: pivot" && git push`

### Step 5: Execute the New Strategy

Don't just plan — immediately begin executing the new approach.
Resume your main task using the new strategy.
