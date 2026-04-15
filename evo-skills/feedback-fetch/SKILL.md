---
name: feedback-fetch
description: Poll the Hub for human annotations on previously submitted vulnerability reports, and when annotations are available, produce an actionable brief the agent hands off to secskill-evo for skill evolution.
when_to_use: |
  - After the agent has submitted one or more reports via `cao_submit_report`
    and some time has passed.
  - Before or during an evolution/heartbeat cycle — invoke this skill first
    so that any fresh human feedback can drive the evolution.
  - Whenever you suspect annotations might be ready (e.g. end of a run).
triggers:
  - "check for human feedback"
  - "pull annotations"
  - "feedback review"
  - "evolve from feedback"
---

# feedback-fetch

## Purpose

Bridge asynchronous human annotation back into the agent's evolution loop:
consult the local registry of pending report ids, ask the Hub (or another
configured API source) which of them have now been annotated, land those
results on disk, and emit an **`evolve_from_feedback.md`** brief that the
agent uses as input to **`secskill-evo`**.

Human annotation arrives on an unpredictable schedule. Most calls will find
nothing, which is fine — this skill is safe to invoke repeatedly.

## Procedure

1. **Fetch annotations**

   Call the MCP tool:

   ```
   cao_fetch_feedbacks(
       task_id="",               # "" = all tasks the agent has reported on
       template_path="",         # optional override; defaults search path:
                                 #   $CAO_FEEDBACK_TEMPLATE  →
                                 #   ~/.config/opencode/skills/feedback-fetch/templates/
                                 #   evo-skills/feedback-fetch/templates/
       output_dir=""             # "" = current working directory
   )
   ```

   The tool returns JSON:

   ```jsonc
   {
     "feedback_md_path": "<cwd>/evolve_from_feedback.md",  // "" if nothing fetched
     "fetched":      ["a1b2c3d4e5f6", ...],                // newly-annotated ids
     "pending":      ["f0e1d2c3b4a5", ...],                // still awaiting
     "result_files": ["/.../a1b2c3d4e5f6.result", ...]
   }
   ```

   The tool:
   - Reads the local registry at `~/.cao-evolution-client/reports/registry.json`.
   - For each `pending` entry, queries the configured Hub endpoint
     `GET /evolution/{task_id}/reports/{report_id}/result`.
   - Writes each annotation payload to
     `~/.cao-evolution-client/reports/<report_id>.result`.
   - Updates the registry entry to `status=annotated`.
   - Renders `evolve_from_feedback.md` from this skill's template.

2. **Branch on `feedback_md_path`**

   - **Empty string** → no new feedback this cycle. Continue your main task.
   - **Non-empty** → read that file; it tells you which reports were
     confirmed TP vs FP and where the `.result` files live. Treat it as the
     single source of truth for this round's human signal.

3. **Hand off to `secskill-evo`**

   Load `evo-skills/secskill-evo/SKILL.md` in *Evolution Mode* and pass the
   rendered brief as the `what_went_wrong` / `signals` input:

   - False positives (`verdict=fp`) become **negative fixtures** — examples
     the evolved skill must no longer flag.
   - True positives (`verdict=tp`) become **regression fixtures** — examples
     the evolved skill must continue to catch.
   - `uncertain` entries stay as calibration notes, not hard fixtures.

4. **(Optional) Mark consumed**

   After the evolved skill is committed and the registry entry is no longer
   useful to re-fetch, the registry can be left as-is — `status=annotated`
   prevents re-download. A future `cao_ack_feedback` tool may switch the
   status to `consumed`; not required for correctness today.

## Configuration (multi-source)

The default fetcher targets the CAO Hub. Future adapters (custom HTTP
annotation platforms, etc.) will be configurable via a `sources` section in
the bridge environment. For now, `source="cao"` is set automatically when
`cao_submit_report` registers an id.

## Non-goals

- This skill does **not** aggregate tp/fp rates or compute calibration
  metrics. Those are deferred — the brief just surfaces the raw
  annotations and lets `secskill-evo` decide what to do.
- This skill does **not** write into the shared evolution git repo. The
  `reports/` directory under `~/.cao-evolution-client/` is agent-local
  runtime state and is excluded from sync.
