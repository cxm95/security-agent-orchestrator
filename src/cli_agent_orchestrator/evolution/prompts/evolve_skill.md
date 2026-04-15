## Heartbeat: Skill Evolution

Your score has plateaued ({evals_since_improvement} evals without improvement).
Instead of tweaking your approach, **evolve your skills**.

### Context
```json
{evolution_signals_json}
```
Leaderboard: {leaderboard}

### Action

Load and execute the **secskill-evo** skill (Evolution Mode) from your evolution skills directory.
The skill is at: `evo-skills/secskill-evo/SKILL.md`
(or pulled into your local skills dir via `cao_pull_skills`)

Pass this context to the skill:
- **Which skill to evolve**: The skill most related to your current task plateau.
  Identify it from the evolution signals or by reviewing your recent work.
- **What went wrong**: Your recent attempts show no improvement.
  Use the evolution signals and leaderboard above for details.
- **Signals**: The full evolution signals JSON above.

The skill will guide you through: judge → analyze → snapshot → improve → validate → commit.
It uses `/tmp/cao-evo-workspace/` for safe isolation (won't pollute your git repo).

### After Evolution

1. The evolved skill is copied back to your skills directory automatically
2. Sync: `cd ~/.cao-evolution-client && git add -A && git commit -m "evolve: <skill>" && git push`
   (or call `cao_sync`)
3. Continue your main task
4. Report new score via `cao_report_score` to close the feedback loop
