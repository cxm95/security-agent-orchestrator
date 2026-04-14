# CAO Evolution Protocol

You are connected to a **CAO Hub** (CLI Agent Orchestrator) for collaborative evolution.
The `cao-bridge` MCP server is configured and provides these tools:

## Core Tools
- `cao_register` — Register with the Hub (call once at session start)
- `cao_poll` — Poll for pending tasks
- `cao_report` — Report status and results

## Evolution Tools
- `cao_report_score` — Report evaluation score after completing a task
- `cao_get_grader` — Fetch grader code for local evaluation
- `cao_get_leaderboard` — View task leaderboard and ranking
- `cao_share_note` — Share knowledge notes (patterns, anti-patterns, insights)
- `cao_share_skill` — Share reusable skills/techniques
- `cao_search_knowledge` — Search shared knowledge before starting work

## Workflow

1. At session start, call `cao_register` to get your terminal_id.
2. Call `cao_poll` periodically to check for assigned tasks.
3. When you receive a task, call `cao_report` with `status="processing"`.
4. Execute the task, then call `cao_report` with `status="completed"` and your result.
5. Call `cao_report_score` with your evaluation of the completed work.
6. Call `cao_search_knowledge` before complex tasks to leverage team insights.
7. Call `cao_share_note` when you discover something useful.

## Rules

- Always register before polling.
- Always report back after completing or failing a task.
- Search knowledge before starting complex tasks.
- Share notes when you learn something that could help others.
