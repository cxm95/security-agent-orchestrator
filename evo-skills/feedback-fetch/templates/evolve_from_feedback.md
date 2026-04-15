# Evolve From Human Feedback

**{fetched_count}** newly-annotated report(s) are available for tasks:
`{task_ids}`.

Report ids: `{report_ids}`

## Annotated reports

{entries_markdown}

## Raw annotation payloads

Each entry below contains the server's annotation payload (`human_score`,
per-finding `human_labels` with `verdict ∈ {tp, fp, uncertain}`, and any
comments). The `.result` files listed above are the persisted copy — read
them from disk if you need to stream them into a sub-agent.

```json
{payloads_json}
```

## Your task

1. Load **`secskill-evo`** (Evolution Mode) from your evolution skills
   directory (`evo-skills/secskill-evo/SKILL.md`, or pulled locally via
   `cao_pull_skills`).

2. Pass the annotations above to the skill as structured input:

   - **`verdict == "fp"` findings** → negative fixtures. The evolved
     skill must stop flagging these patterns.
   - **`verdict == "tp"` findings** → regression fixtures. The evolved
     skill must continue to flag these.
   - **`verdict == "uncertain"`** → calibration notes; do not promote to
     hard fixtures.
   - Any **`comment`** fields are human rationale — preserve them as
     `Why:` annotations on the fixtures you extract.

3. Choose the target skill to evolve based on the finding categories and
   your current task's skill surface. If unclear, consult
   `cao_recall("detector for <category>")` before editing.

4. Run the full secskill-evo cycle: judge → analyze → snapshot → improve
   → validate → commit. Use `/tmp/cao-evo-workspace/` for isolation.

5. After a successful evolution:
   - `cao_sync` to push the evolved skill back to the shared repo.
   - `cao_report_score` with the new evaluation to close the loop.

## Notes

- This brief was rendered by the **feedback-fetch** skill. The underlying
  `.result` files are in `~/.cao-evolution-client/reports/` and are
  **not** tracked in the shared evolution git repo — they are agent-local
  runtime state.
- If annotations contradict an earlier fixture in `secskill-evo`, treat
  the latest human judgment as authoritative and update the fixture.
