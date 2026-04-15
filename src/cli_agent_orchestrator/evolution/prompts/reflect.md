## Heartbeat: Reflection

Pause your current work and reflect on recent results.

### Context
```json
{evolution_signals_json}
```

### Action

Load and execute the **cao-reflect** skill from your evolution skills directory.
The skill is at: `evo-skills/cao-reflect/SKILL.md`
(or pulled into your local skills dir via `cao_pull_skills`)

Pass this context to the skill:
- Task ID: {task_id}
- Your recent evolution signals (above)
- Leaderboard position and score trend

After the skill completes (a reflection Note is written), resume your main task.
