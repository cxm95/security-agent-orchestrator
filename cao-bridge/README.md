# CAO Remote Bridge

Connect a remote agent (OpenCode, Claude Code, etc.) to the CAO Hub.

## Two Approaches

### A. Plugin (Event-driven — recommended for OpenCode)

The plugin auto-registers, auto-polls on idle, injects tasks via SDK, and
reports results — **no agent cooperation needed**.

```bash
cp plugin/cao-bridge.ts .opencode/plugins/     # project-level
# or
cp plugin/cao-bridge.ts ~/.config/opencode/plugins/  # global
```

Set environment variables `CAO_HUB_URL` and `CAO_AGENT_PROFILE` if needed.

### B. MCP + Skill (Agent-driven — works with any MCP-capable agent)

The MCP server provides tools; the Skill teaches the agent the protocol.

**1. Configure MCP server** in `opencode.json`:
```json
{
  "mcp": {
    "cao-bridge": {
      "type": "local",
      "command": ["python3", "/path/to/cao-bridge/cao_bridge_mcp.py"],
      "environment": {
        "CAO_HUB_URL": "http://<hub-ip>:9889",
        "CAO_AGENT_PROFILE": "remote-opencode"
      }
    }
  }
}
```

**2. Install Skill** (teaches agent to call the MCP tools):
```bash
cp -r skill/cao-bridge .opencode/skills/       # project-level
# or
cp -r skill/cao-bridge ~/.claude/skills/       # Claude Code compatible
```

MCP tools provided: `cao_register`, `cao_poll`, `cao_report`.

## Architecture

```
Local Agent                    CAO Hub (:9889)                Remote Agent
    │                              │                              │
    │  send_message(remote, msg)   │                              │
    │─────────────────────────────→│  inbox INSERT (PENDING)      │
    │                              │                              │
    │                              │  ←── GET /remotes/{id}/poll ─│
    │                              │  inbox check → set_pending   │
    │                              │  ──→ {"has_input": true}     │
    │                              │                              │
    │                              │  ←── POST /report(processing)│
    │                              │                    (execute)  │
    │                              │  ←── POST /report(completed) │
```

The `send_message` MCP tool (used by local agents) stores messages in the
inbox database. When the remote agent polls, the Hub auto-delivers pending
inbox messages through the same `pending_input` queue.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CAO_HUB_URL` | `http://127.0.0.1:9889` | Hub server URL |
| `CAO_AGENT_PROFILE` | `remote-opencode` | Agent profile name |
