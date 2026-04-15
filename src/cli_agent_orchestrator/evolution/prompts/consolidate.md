## Heartbeat: Knowledge Synthesis

Pause and synthesize shared knowledge across agents.

### Context
```json
{evolution_signals_json}
```

### Action

Load and execute the **cao-consolidate** skill from your evolution skills directory.
The skill is at: `evo-skills/cao-consolidate/SKILL.md`
(or pulled into your local skills dir via `cao_pull_skills`)

Pass this context to the skill:
- Task ID: {task_id}
- The evolution signals above (include cross-agent data)
- Leaderboard for context on other agents' progress

After the skill completes (a synthesis Note is written), apply any insights to your work and resume.
