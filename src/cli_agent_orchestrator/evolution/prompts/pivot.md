## Heartbeat: Plateau Detected — Change Direction

**You have not improved your score in several consecutive evals.** Incremental tweaks are unlikely to help. Try something fundamentally different.

### Evolution Signals
```json
{evolution_signals_json}
```

### Step 1: Diagnose
- Check `cao_get_leaderboard(task_id="{task_id}")` — where do you stand?
- Are your recent scores flat or oscillating? Why?

### Step 2: Study alternatives
- Search knowledge: `cao_search_knowledge(query="approach strategy")`
- What are other agents doing differently?

### Step 3: Change approach
Try a **fundamentally different** strategy — not a parameter tweak. Consider:
- Different algorithm or tool
- Different problem decomposition
- Techniques from other domains

### Step 4: Document
Call `cao_share_note(title="Pivot: <new approach>", tags="pivot,{task_id}")` explaining what you're trying and why.
