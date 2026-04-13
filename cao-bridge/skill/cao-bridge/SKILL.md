---
name: cao-bridge
description: >
  CAO Remote Bridge skill. Instructs the agent to use the cao-bridge MCP tools
  (cao_register, cao_poll, cao_report) to connect to a CAO Hub for receiving
  tasks and reporting results. Requires the cao-bridge MCP server to be
  configured in opencode.json.
---

# CAO Remote Bridge

You are connected to a **CAO Hub** (CLI Agent Orchestrator) via MCP tools.
Follow this protocol to receive and execute tasks from the Hub.

## Prerequisites

The `cao-bridge` MCP server must be configured. It provides three tools:
- `cao_register` — Register with the Hub
- `cao_poll` — Poll for pending tasks
- `cao_report` — Report status and results

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

### 4. Error Handling

If a task fails, call `cao_report` with `status="error"` and `output="<error details>"`.

### 5. Resume Polling

After reporting, go back to step 2 and poll for the next task.

## Rules

- Always register before polling.
- Always report back after completing or failing a task.
- Do NOT invent tasks — only execute what the Hub assigns via `cao_poll`.
- Between polls, wait 3–5 seconds to avoid flooding the Hub.
