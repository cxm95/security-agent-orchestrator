## Heartbeat: Knowledge Synthesis

Pause and synthesize shared knowledge. Call `cao_search_knowledge` and `cao_get_shared_notes` to review what the team knows.

### Process

1. **Read**: Search notes with `cao_search_knowledge(query="", tags="{task_id}")` to find all notes for this task.

2. **Synthesize**: Identify patterns across multiple notes. Create a synthesis note that distills key findings.

3. **Identify gaps**: What questions remain unanswered? What contradictions exist?

### Output

Call `cao_share_note` with:
- `title="Synthesis: <topic>"`
- `tags="synthesis,{task_id}"`
- Content that distills multiple notes into actionable insights.
