## Heartbeat: Skill Generation

Your recent scores have been consistently strong ({consecutive_high_scores} consecutive scores above threshold).
This suggests you've developed an effective method worth capturing.

### Context
```json
{evolution_signals_json}
```
Leaderboard: {leaderboard}

### Action

Load and execute the **secskill-gen-neo** skill from your evolution skills directory.
The skill is at: `evo-skills/secskill-gen-neo/SKILL.md`
(or pulled into your local skills dir via `cao_pull_skills`)

Pass this context to the skill:
- **What you accomplished**: Review your recent high-scoring executions.
  Identify the method or approach that led to sustained success.
- **Execution history**: Use the evolution signals and leaderboard above
  to identify which task(s) you excelled at.
- **Signals**: The full evolution signals JSON above.

The skill will guide you through: reconstruct → gate check → distill → review → publish.
It enforces strict generation gates — if the method doesn't generalize or is already
covered by existing knowledge, it will recommend writing a secnote instead.

### After Generation

1. The new skill is written to `~/.cao-evolution-client/skills/<name>/`
2. Sync: `cd ~/.cao-evolution-client && git add -A && git commit -m "gen: <skill>" && git push`
   (or call `cao_push`)
3. Continue your main task
4. Report new score via `cao_report_score` to close the feedback loop
