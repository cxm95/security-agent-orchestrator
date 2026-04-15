## Heartbeat: Plateau Detected — Change Direction

**You have not improved your score in several consecutive evals.** Incremental tweaks are unlikely to help.

### Context
```json
{evolution_signals_json}
```

### Action

Load and execute the **cao-pivot** skill from your evolution skills directory.
The skill is at: `evo-skills/cao-pivot/SKILL.md`
(or pulled into your local skills dir via `cao_pull_skills`)

Pass this context to the skill:
- Task ID: {task_id}
- Evals since improvement: shown in the signals above
- Leaderboard: {leaderboard}

After the skill completes (a pivot Note is written and new strategy chosen), immediately begin executing the new strategy.
