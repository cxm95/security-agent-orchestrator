## Heartbeat: Skill Evolution

Your score has plateaued. Instead of tweaking your approach, focus on **improving an existing skill** or **creating a refined version**.

### Evolution Signals
```json
{evolution_signals_json}
```

### Step 1: Identify the weakest skill
Review your current skills and the signals above. Which skill is most responsible for the plateau? Look for:
- Skills with low eval pass rates
- Skills that the signals highlight as underperforming
- Skills that haven't been updated despite changing requirements

### Step 2: Diagnose root cause
Read the skill's content and its `evals.json` (if present). What specific test cases does it fail? What patterns does it miss?

### Step 3: Evolve the skill
Create an improved version. Key principles:
- **Keep what works** — don't rewrite from scratch unless fundamentally flawed
- **Add missing cases** — address specific failures from evals
- **Update TIP.md** — record what you learned and what you changed

### Step 4: Validate
After modifying the skill, run its evals to confirm:
- All previously passing cases still pass (no regression)
- At least one previously failing case now passes (improvement)

If validation fails, revert and try a different approach.

---

**Actions**:
1. Read current skills via `cao_get_shared_skills`
2. Modify the skill file locally
3. Run evals: check `evals.json` for the skill
4. If improved, share via `cao_share_skill`
5. Record learnings in `cao_share_note(tags="evolution,skill,{task_id}")`
