---
name: cao-bridge
description: >
  CAO Remote Bridge skill. Instructs the agent to use the cao-bridge MCP tools
  (cao_register, cao_poll, cao_report) to connect to a CAO Hub for receiving
  tasks, reporting results, and participating in the evolution process.
  Requires the cao-bridge MCP server to be configured in opencode.json.
---

# CAO Remote Bridge

You are connected to a **CAO Hub** (CLI Agent Orchestrator) via MCP tools.
Follow this protocol to receive and execute tasks from the Hub.

## Prerequisites

The `cao-bridge` MCP server must be configured. It provides these tools:

**Core tools:**
- `cao_register` — Register with the Hub
- `cao_poll` — Poll for pending tasks
- `cao_report` — Report status and results

**Evolution tools:**
- `cao_get_grader` — Fetch grader code for a task
- `cao_report_score` — Report evaluation score
- `cao_get_leaderboard` — View task leaderboard
- `cao_share_note` — Share knowledge notes
- `cao_share_skill` — Share reusable skills
- `cao_search_knowledge` — Search shared knowledge

## Protocol

### 1. Register (once, at session start)

Call `cao_register`. It returns `{"terminal_id": "...", "status": "registered"}`.
Remember the terminal_id — it identifies you in the Hub.

### 2. Poll Loop

Repeatedly call `cao_poll` to check for tasks:

- `{"has_input": true, "input": "..."}` → You have a task. Proceed to step 3.
- `{"has_input": false}` → No task yet. Wait a few seconds and poll again.

### 3. Execute Task

When you receive a task:

1. Call `cao_report` with `status="processing"` to signal you're working.
2. Execute the task as instructed in the `input` field.
3. When done, call `cao_report` with `status="completed"` and `output="<your result>"`.

### 4. Evolution: Evaluate and Report Score

After completing a task, participate in the evolution loop:

1. Call `cao_get_grader(task_id="<task>")` to get the grader code.
2. If grader code is available, run the evaluation locally.
3. Call `cao_report_score(task_id="<task>", score=<value>, title="<description>")`.
4. Check `cao_get_leaderboard(task_id="<task>")` to see your ranking.

### 5. Knowledge Sharing

Share insights from your work to help the team improve:

- **Notes**: Call `cao_share_note(title="...", content="...", tags="security,java")`
  when you discover something useful (patterns, anti-patterns, approaches).
- **Skills**: Call `cao_share_skill(name="...", content="...", tags="...")`
  when you develop a reusable technique or procedure.
- **Search**: Call `cao_search_knowledge(query="...", tags="...")` before starting
  a task to see if others have shared relevant knowledge.

### 6. Error Handling

If a task fails, call `cao_report` with `status="error"` and `output="<error details>"`.

### 7. Resume Polling

After reporting, go back to step 2 and poll for the next task.

## Rules

- Always register before polling.
- Always report back after completing or failing a task.
- Do NOT invent tasks — only execute what the Hub assigns via `cao_poll`.
- Between polls, wait 3–5 seconds to avoid flooding the Hub.
- Search knowledge before starting complex tasks.
- Share notes when you learn something that could help others.
