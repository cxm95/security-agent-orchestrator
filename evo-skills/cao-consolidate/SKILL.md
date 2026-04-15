---
name: cao-consolidate
description: >
  Synthesize shared knowledge from all agents' notes into actionable insights.
  Triggered by CAO heartbeat periodically, or manually.
  Triggers on: "consolidate", "synthesize knowledge", "综合", "knowledge synthesis".
---

# CAO Consolidate

Pause and synthesize the shared knowledge base. Read notes from all agents,
identify patterns and contradictions, and produce a synthesis note that distills
key findings into actionable insights.

This skill is part of the CAO co-evolution framework, ported from CORAL's
`consolidate` heartbeat action. It runs periodically (default: every 5 global evals)
to enable cross-agent knowledge transfer.

## When This Skill Runs

- **Heartbeat trigger**: Every N global evaluations (default: every 5, global scope)
- **Manual trigger**: User says "consolidate", "synthesize notes", "综合知识"

## Inputs

When invoked via heartbeat, you receive:

- **Evolution signals** (JSON): aggregated signals from all agents
- **Leaderboard**: standings of all agents
- **Task ID**: which task to consolidate knowledge for

## Process

### Step 1: Gather All Shared Notes

Read the shared knowledge base:

**Via MCP:**
```
cao_search_knowledge(query="", tags="{task_id}")
cao_get_shared_notes(task_id="{task_id}")
```

**Via git:**
Read all `.md` files in `~/.cao-evolution-client/notes/`

Collect all notes related to the current task. Pay attention to:
- Who wrote each note (different agents have different perspectives)
- When it was written (recent notes may supersede older ones)
- Tags (reflection, pivot, synthesis, evolution)

### Step 2: Identify Patterns

Across all notes, look for:

1. **Convergent findings**: Multiple agents independently reached the same conclusion
   → These are likely robust insights
2. **Divergent approaches**: Agents trying fundamentally different strategies
   → Compare their scores to see which approach works better
3. **Contradictions**: Agent A says X works, Agent B says X doesn't
   → Investigate: different contexts? different implementations?
4. **Gaps**: Important questions no one has addressed yet

### Step 3: Synthesize

Create a synthesis that:

1. **Distills** the most important findings (not just a summary of each note)
2. **Resolves** contradictions where possible (explain why both can be true)
3. **Ranks** approaches by effectiveness (backed by score data)
4. **Identifies** the most promising next directions

### Step 4: Write and Share Synthesis

Write synthesis to local git and push:

Create `~/.cao-evolution-client/notes/synthesis-<timestamp>.md`:

```markdown
---
creator: {agent_id}
created: {ISO 8601 timestamp}
tags: [synthesis, {task_id}]
type: consolidate
sources: [<list of note filenames/titles referenced>]
---
# Synthesis: <topic>

## Key Findings
<Convergent findings ranked by confidence>

## Effective Approaches
<Approaches ranked by score, with evidence>

## Open Questions
<Gaps and unresolved contradictions>

## Recommended Next Steps
<Specific actions based on the synthesis>
```

Then sync: `cd ~/.cao-evolution-client && git add -A && git commit -m "note: synthesis" && git push`

### Step 5: Return to Main Task

Apply any insights from the synthesis to your own work, then resume.
