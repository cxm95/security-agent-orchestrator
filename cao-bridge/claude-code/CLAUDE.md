# CAO Evolution Protocol

You are connected to a **CAO Hub** (CLI Agent Orchestrator) for collaborative evolution.
The `cao-bridge` MCP server is configured and provides these tools:

## Registration & Polling

There are two modes depending on your setup:

**Mode A — Hooks installed (default for experiments):**
Registration and polling are handled automatically by SessionStart/Stop hooks.
You do NOT need to call `cao_register` or `cao_poll` — the hooks handle it.
To verify: check if the SessionStart hook output mentions "[CAO] Registered as ...".

**Mode B — MCP only (no hooks):**
If no SessionStart hook is configured, you must register and poll manually:
1. Call `cao_register` once at session start to get your terminal_id.
2. Call `cao_poll` to check for queued tasks.

**How to tell which mode you're in:**
- If you see "[CAO] Registered as ..." in your session context → Mode A (do NOT call cao_register)
- If you don't see that message → Mode B (call cao_register, then cao_poll)

## Core Tools
- `cao_register` — Register with the Hub (Mode B only)
- `cao_poll` — Poll for pending tasks (Mode B only)
- `cao_report` — Report status and results
- `cao_session_info` — Show current session metadata

## Evolution Tools
- `cao_report_score` — Report evaluation score after completing a task
- `cao_get_task` — Fetch task info including grader_skill reference
- `cao_get_leaderboard` — View task leaderboard and ranking
- `cao_search_knowledge` — Search shared knowledge before starting work
- `cao_push` — Push local changes (notes, skills) to Hub via git

## Knowledge Sharing (git-based)

Notes and skills are shared by writing files locally and pushing via git:

1. Write a note: `<session_dir>/notes/<name>.md` (with YAML frontmatter)
2. Write a skill: `<session_dir>/skills/<name>/SKILL.md`
3. Call `cao_push` to stage, commit, and push to the Hub

## Workflow

1. **Registration**: Check if "[CAO] Registered as ..." appears in context.
   - Yes → hooks are active, skip to step 2.
   - No → call `cao_register`, then `cao_poll`.
2. When a task arrives (via hook injection or cao_poll), call `cao_report` with `status="processing"`.
3. Execute the task.
4. Call `cao_report` with `status="completed"` and your result.
5. **Scoring**:
   - **Mode A (hooks active):** Do NOT call `cao_report_score` yourself. The Stop hook will automatically inject a grader skill prompt. Follow the grader instructions and output `CAO_SCORE=<0-100>`. The hook parses this and reports the score.
   - **Mode B (MCP only):** Call `cao_report_score` with your evaluation of the completed work.
6. **Check the response for `heartbeat_prompts`**. If present, execute each one:
   - Each prompt tells you to load a specific evolution skill (from `~/.claude/skills/`)
   - Execute the skill following its SKILL.md instructions
   - Call `cao_push` to sync results to Hub
7. After heartbeat actions (if any), continue your main task.
8. Call `cao_search_knowledge` before complex tasks to leverage team insights.
9. Write notes to `<session_dir>/notes/` and call `cao_push` when you discover something useful.

## Rules

- Do NOT call `cao_register` if you see "[CAO] Registered as ..." in context (hooks handle it).
- Do NOT call `cao_poll` if hooks are active (Stop hook handles polling).
- Do NOT call `cao_report_score` if hooks are active — the Stop hook injects the grader automatically.
- Always report back after completing or failing a task.
- Search knowledge before starting complex tasks.
- Share notes via local git + `cao_push` when you learn something that could help others.
