# CLI Agent Orchestrator API Documentation

Base URL: `http://localhost:9889` (default)

## Health Check

### GET /health
Check if the server is running.

**Response:**
```json
{
  "status": "ok",
  "service": "cli-agent-orchestrator"
}
```

---

## Sessions

### POST /sessions
Create a new session with one terminal.

**Parameters:**
- `provider` (string, required): Provider type ("kiro_cli", "claude_code", "codex", "gemini_cli", "kimi_cli", "copilot_cli", or "q_cli")
- `agent_profile` (string, required): Agent profile name
- `session_name` (string, optional): Custom session name
- `working_directory` (string, optional): Working directory for the agent session

**Response:** Terminal object (201 Created)

### GET /sessions
List all sessions — includes tmux-backed sessions and remote-only (DB-backed) sessions.

Each entry carries a `kind` field:
- `"local"` — a real tmux session exists for this name
- `"remote"` — no tmux session; all terminals under this name are remote agents registered via `/remotes/register`

**Response:** Array of session objects
```json
[
  {"id": "cao-foo", "name": "cao-foo", "status": "detached", "kind": "local"},
  {"id": "remote-2025-04-17", "name": "remote-2025-04-17", "status": "detached", "kind": "remote"}
]
```

### GET /sessions/{session_name}
Get details of a specific session. Works for both tmux-backed and remote-only sessions.

**Response:** Session object with terminals list

### DELETE /sessions/{session_name}
Delete a session and all its terminals.

**Response:**
```json
{
  "success": true
}
```

---

## Terminals

**Note:** All `terminal_id` path parameters must be 8-character hexadecimal strings (e.g., "a1b2c3d4").

### POST /sessions/{session_name}/terminals
Create an additional terminal in an existing session.

**Parameters:**
- `provider` (string, required): Provider type
- `agent_profile` (string, required): Agent profile name
- `working_directory` (string, optional): Working directory for the terminal

**Response:** Terminal object (201 Created)

### GET /sessions/{session_name}/terminals
List all terminals in a session.

**Response:** Array of terminal objects

### GET /terminals
List all terminals across every session, independent of tmux. Remote agents
registered via `/remotes/register` are always visible here even when no tmux
session exists.

**Parameters:**
- `provider` (string, optional): Filter by provider name (e.g. `remote`, `claude_code`, `opencode`).

**Response:** Array of terminal objects
```json
[
  {
    "id": "f39efd4c",
    "name": "remote-claude-code-xxxxxxxx",
    "provider": "remote",
    "session_name": "remote-2025-04-17",
    "agent_profile": "remote-claude-code",
    "status": "idle",
    "last_active": "2026-04-17T10:12:34"
  }
]
```

### GET /terminals/{terminal_id}
Get terminal details.

**Response:** Terminal object
```json
{
  "id": "string",
  "name": "string",
  "provider": "kiro_cli|claude_code|codex|gemini_cli|kimi_cli|copilot_cli|q_cli",
  "session_name": "string",
  "agent_profile": "string",
  "status": "idle|processing|completed|waiting_user_answer|error",
  "last_active": "timestamp"
}
```

### POST /terminals/{terminal_id}/input
Send input to a terminal.

**Parameters:**
- `message` (string, required): Message to send

**Response:**
```json
{
  "success": true
}
```

### GET /terminals/{terminal_id}/output
Get terminal output.

**Parameters:**
- `mode` (string, optional): Output mode - "full" (default), "last", or "tail"

**Response:**
```json
{
  "output": "string",
  "mode": "string"
}
```

### GET /terminals/{terminal_id}/working-directory
Get the current working directory of a terminal's pane.

**Response:**
```json
{
  "working_directory": "/home/user/project"
}
```

**Note:** Returns `null` if working directory is unavailable.

### POST /terminals/{terminal_id}/exit
Send provider-specific exit command to terminal.

**Behavior:**
- Calls the provider's `exit_cli()` method to get the exit command
- Text commands (e.g., `/exit`, `quit`) are sent as literal text via `send_input()`
- Key sequences prefixed with `C-` or `M-` (e.g., `C-d` for Ctrl+D) are sent as tmux key sequences via `send_special_key()`, which tmux interprets as actual key presses

| Provider | Exit Command | Type |
|----------|-------------|------|
| kiro_cli | `/exit` | Text |
| claude_code | `/exit` | Text |
| codex | `/exit` | Text |
| gemini_cli | `/exit` | Text |
| kimi_cli | `/exit` | Text |
| copilot_cli | `/exit` | Text |
| q_cli | `/exit` | Text |

**Response:**
```json
{
  "success": true
}
```

### DELETE /terminals/{terminal_id}
Delete a terminal.

**Response:**
```json
{
  "success": true
}
```

---

## Remote Agents (DB-backed virtual terminals)

Remote agents run outside of tmux (e.g. in a Claude Code / OpenCode plugin)
and exchange state with the Hub over HTTP. State is persisted to the
`remote_state` table so the pair survives a Hub restart.

### POST /remotes/register
Register a new remote agent. Idempotent per call (always returns a fresh
`terminal_id`).

**Body (JSON):**
- `agent_profile` (string, required)
- `session_name` (string, optional): Reuse an existing remote session;
  a new one is generated if omitted.

**Response (201 Created):**
```json
{ "terminal_id": "a1b2c3d4", "session_name": "cao-xxxxxxxx" }
```

### POST /remotes/{terminal_id}/reattach
Called by an agent at cold-start when it already has a cached
`terminal_id`. Lets the agent resume with the Hub after either side
restarts, without losing queued work or accumulated output.

**Behavior:**
- Returns **404** if the id is unknown (caller should fall back to `/register`).
- Returns **400** if the terminal is not a remote terminal.
- On success: touches `last_seen_at` and, if a stale `processing`/`error`
  status is left over from a crashed session (with no `pending_input`
  queued), flips it back to `idle` so inbox delivery isn't blocked.

**Response (200 OK):**
```json
{
  "ok": true,
  "terminal_id": "a1b2c3d4",
  "session_name": "cao-xxxxxxxx",
  "agent_profile": "remote-claude-code",
  "status": "idle",
  "has_pending_input": false,
  "pending_inbox_count": 0
}
```

### GET /remotes/{terminal_id}/poll
Agent polls for the next pending input. Consumes the queue on read.

**Response:**
```json
{ "has_input": true, "input": "the task prompt" }
```
When the queue is empty: `{ "has_input": false, "input": null }`.
An empty poll still counts as a heartbeat and updates `last_seen_at`.

Before consuming, the Hub also flushes any pending inbox messages into
the remote's virtual queue, so a single `/poll` can deliver either a
direct input or a queued inbox message (direct input wins).

### POST /remotes/{terminal_id}/report
Agent reports status and/or output after completing (or while running)
a task.

**Body (JSON):**
- `status` (string, optional): `idle` / `processing` / `completed` / `error` /
  `waiting_user_answer`. Unknown values are stored as `error`.
- `output` (string, optional): Output to record.
- `append` (bool, optional, default `false`): When `true`, appends to
  `full_output`; when `false`, replaces it.

**Response:** `{ "success": true }`

**Note:** `full_output` is unbounded in memory but the persisted copy is
trimmed to the trailing 128 KB so the DB can't grow unboundedly during a
long-running session.

### GET /remotes/{terminal_id}/status
Lightweight status check (no side effects).

**Response:**
```json
{
  "terminal_id": "a1b2c3d4",
  "status": "processing",
  "has_pending_input": false
}
```

---

## Inbox (Terminal-to-Terminal Messaging)

### POST /terminals/{receiver_id}/inbox/messages
Send a message to another terminal's inbox.

**Parameters:**
- `sender_id` (string, required): Sender terminal ID
- `message` (string, required): Message content

**Response:**
```json
{
  "success": true,
  "message_id": "string",
  "sender_id": "string",
  "receiver_id": "string",
  "created_at": "timestamp"
}
```

**Behavior:**
- Messages are queued and delivered when the receiver terminal is IDLE
- Messages are delivered in order (oldest first)
- Delivery is automatic via watchdog file monitoring

---

## Error Responses

All endpoints return standard HTTP status codes:

- `200 OK`: Success
- `201 Created`: Resource created
- `400 Bad Request`: Invalid parameters
- `404 Not Found`: Resource not found
- `500 Internal Server Error`: Server error

Error response format:
```json
{
  "detail": "Error message"
}
```

---
