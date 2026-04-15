## Heartbeat: Human Feedback Review

New human feedback is available. Review the annotations and adjust your approach.

### Evolution Signals
```json
{evolution_signals_json}
```

### Review Feedback
Check your `.cao-reports/` directory for `.result` files. Each contains human annotations
(tp/fp/uncertain) for findings you previously submitted.

Use `cao_fetch_feedback(task_id="{task_id}")` to pull the latest annotated reports.

### Analyze Accuracy
- Which findings were confirmed as True Positives (tp)?
- Which were marked False Positives (fp)? Why did you report them?
- What patterns distinguish real vulnerabilities from false alarms?

### Calibrate
Based on this feedback:
1. Adjust your detection thresholds and heuristics
2. Note categories where you're over- or under-reporting
3. Update your scanning strategy to reduce fp rate

### Share Learnings
Write your calibration insights to `~/.cao-evolution-client/notes/feedback-review-<timestamp>.md` with appropriate frontmatter (title, tags: feedback,{task_id}), then call `cao_push` so other agents can benefit.
