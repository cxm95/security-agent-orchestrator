---
name: cao-reflect
description: >
  Reflect on recent execution results and produce a structured Note with insights.
  Triggered by CAO heartbeat after each evaluation, or manually.
  Triggers on: "reflect", "反思", "review recent results", "write a reflection note".
---

# CAO Reflect

Pause your current task and reflect on recent results. Produce a structured Note
with concrete insights that help future work.

This skill is part of the CAO co-evolution framework, ported from CORAL's
`reflect` heartbeat action. It runs after each evaluation cycle to build
self-awareness and prevent repeating mistakes.

## When This Skill Runs

- **Heartbeat trigger**: Automatically after every N evaluations (default: every 1)
- **Manual trigger**: User says "reflect", "反思", "review what happened"

## Inputs

When invoked via heartbeat, you receive:

- **Evolution signals** (JSON): scores, trends, comparison data
- **Leaderboard**: current standings vs other agents
- **Task ID**: which task you're working on

## Process

### Step 1: Anchor in Concrete Results

Review your recent work. Specifically:

1. What was your most recent score? How does it compare to your best?
2. What specific actions led to improvements?
3. What specific actions led to regressions or no change?

Do NOT write vague reflections like "I need to try harder". Every observation must
reference a specific action and its measurable outcome.

### Step 2: Examine Surprises

What didn't go as expected? Surprises reveal gaps in your mental model.

- Did a change you expected to improve the score actually hurt it?
- Did something you thought was minor turn out to be important?
- Were there error modes you didn't anticipate?

### Step 3: Analyze Root Causes

For your most significant result (good or bad):

1. **Why** did it happen? (first-level cause)
2. **Why** that cause? (second-level — dig deeper)
3. What does this tell you about the problem structure?

### Step 4: Plan Next Step

Based on this reflection:

1. What's one specific thing to try next?
2. What's one thing to explicitly avoid?
3. What hypothesis are you testing with your next attempt?

### Step 5: Write and Share the Note

Produce a reflection note and share it via local git:

Create a file at `~/.cao-evolution-client/notes/reflect-<timestamp>.md` with YAML frontmatter:

```markdown
---
creator: {agent_id}
created: {ISO 8601 timestamp}
tags: [reflection, {task_id}]
type: reflect
---
# Reflection: <one-line summary>

## Recent Results
<Step 1 output>

## Surprises
<Step 2 output>

## Root Cause Analysis
<Step 3 output>

## Next Steps
<Step 4 output>
```

Then push: `cao_push` (MCP) or `cd ~/.cao-evolution-client && git add -A && git commit -m "note: reflection" && git push`

### Step 6: Return to Main Task

After writing the note, resume your main task. Do not get stuck in meta-reflection loops.
