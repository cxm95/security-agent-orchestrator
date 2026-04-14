## Heartbeat: Human Feedback Review

New human feedback is available. Review the annotations and adjust your approach.

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
Call `cao_share_note(title="Feedback Review: ...", content="...", tags="feedback,{task_id}")` with your calibration insights so other agents can benefit.
