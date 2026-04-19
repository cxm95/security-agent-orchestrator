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
- `cao_get_task` — Fetch task info including grader_skill reference
- `cao_report_score` — Report evaluation score
- `cao_get_leaderboard` — View task leaderboard
- `cao_search_knowledge` — Search shared knowledge

**Git sync tools:**
- `cao_sync` — Clone or pull the shared evolution repo
- `cao_push` — Stage, commit and push local changes to Hub
- `cao_pull_skills` — Copy shared skills from the git clone into your local skills dir
- `cao_session_info` — Show current session metadata (session_id, directory)

## Session Isolation

Each agent instance runs in its own session directory under
`~/.cao-evolution-client/sessions/<session_id>/`. This prevents git conflicts
when multiple agents run concurrently on the same machine.

Session lifecycle is automatic:
- **Created** at session start (git clone into isolated directory)
- **Active** while the agent is running (last_update refreshed on git ops)
- **Inactive** when the agent exits (marked, not deleted)
- **Cleaned up** by `cao-session-mgr cleanup` after expiry

You can check your session with `cao_session_info`.

## Protocol

### 0. Sync Shared Knowledge (at session start)

If using the MCP bridge, session init happens automatically (git clone into
a fresh session directory). Call `cao_pull_skills` to copy shared skills
into your local skills directory for automatic loading.

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

1. Call `cao_get_task(task_id="<task>")` to get the task info including `grader_skill`.
2. If `grader_skill` is set, read `~/.config/opencode/skills/<grader_skill>/SKILL.md`
   (or `~/.claude/skills/<grader_skill>/SKILL.md` for Claude Code) and follow its
   instructions to evaluate your output. Print exactly: `CAO_SCORE=<integer 0-100>`.
3. **If hooks are active** (Claude Code with Stop hook): the hook parses `CAO_SCORE` from
   your output and reports the score automatically. Do NOT call `cao_report_score`.
   **If hooks are NOT active** (MCP-only mode): call `cao_report_score(task_id, score, title)`.
4. Check the response for `heartbeat_prompts`. If non-empty, proceed to step 4.5.
5. Otherwise, call `cao_get_leaderboard(task_id="<task>")` to see your ranking.

### 4.5 Handle Heartbeat

If `heartbeat_prompts` is non-empty in the `cao_report_score` response:

For each prompt in `heartbeat_prompts`:
1. Read the prompt — it specifies which **evolution skill** to execute.
2. Load the skill from the provider's global skills directory
   (`~/.config/opencode/skills/` or `~/.claude/skills/`).
3. Execute the skill following its SKILL.md instructions.
4. After the skill completes, call `cao_push` to sync results to Hub.

### 4.6 Post-Heartbeat Continuation

After all heartbeat actions complete:
1. Continue your main task.
2. On next task completion, run grader + `cao_report_score` again.
3. Return to step 2 (polling).

### 5. Knowledge Sharing

Share insights from your work to help the team improve:

- **Notes**: Write a markdown note to the session's `notes/` directory with YAML frontmatter
  (title, tags, creator) then call `cao_push` to sync to Hub.
- **Skills**: Write a `SKILL.md` to the session's `skills/<name>/`
  then call `cao_push` to share it with the team.
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

## Creating Tasks Locally

If the user asks you to create a task for evolution tracking:

1. Call `cao_create_task(task_id="<id>", name="<name>", description="<desc>",
   grader_skill="security-grader")` via MCP.
2. The Hub will store the `task.yaml` and make it available to all agents.
3. After completing the task, follow step 4 above to grade and report.
