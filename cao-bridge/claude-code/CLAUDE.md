# CAO Evolution Protocol

You are connected to a **CAO Hub** (CLI Agent Orchestrator) for collaborative evolution.
The `cao-bridge` MCP server is configured and provides these tools:

## Core Tools
- `cao_register` — Register with the Hub (call once at session start)
- `cao_poll` — Poll for pending tasks
- `cao_report` — Report status and results

## Evolution Tools
- `cao_report_score` — Report evaluation score after completing a task
- `cao_get_task` — Fetch task info including grader_skill reference
- `cao_get_leaderboard` — View task leaderboard and ranking
- `cao_search_knowledge` — Search shared knowledge before starting work
- `cao_push` — Push local changes (notes, skills) to Hub via git

## Knowledge Sharing (git-based)

Notes and skills are shared by writing files locally and pushing via git:

1. Write a note: `~/.cao-evolution-client/notes/<name>.md` (with YAML frontmatter)
2. Write a skill: `~/.cao-evolution-client/skills/<name>/SKILL.md`
3. Call `cao_push` to stage, commit, and push to the Hub

## Workflow

1. At session start, call `cao_register` to get your terminal_id.
2. Call `cao_poll` periodically to check for assigned tasks.
3. When you receive a task, call `cao_report` with `status="processing"`.
4. Execute the task, then call `cao_report` with `status="completed"` and your result.
5. Call `cao_report_score` with your evaluation of the completed work.
6. **Check the response for `heartbeat_prompts`**. If present, execute each one:
   - Each prompt tells you to load a specific evolution skill (from `evo-skills/`)
   - Execute the skill following its SKILL.md instructions
   - Call `cao_push` to sync results to Hub
7. After heartbeat actions (if any), continue your main task.
8. Call `cao_search_knowledge` before complex tasks to leverage team insights.
9. Write notes to `~/.cao-evolution-client/notes/` and call `cao_push` when you discover something useful.

## Rules

- Always register before polling.
- Always report back after completing or failing a task.
- Search knowledge before starting complex tasks.
- Share notes via local git + `cao_push` when you learn something that could help others.
