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

## Shared Skill Namespace

Only skills whose directory name starts with `cao-` participate in sync.
Non-prefixed skills in `~/.claude/skills/`, `~/.config/opencode/skills/`,
or `~/.hermes/skills/` stay **private** — they are never pushed to the Hub
and never overwritten by pulls. To share a skill, rename it to `cao-<name>`
so it enters the shared namespace; collisions within `cao-*` are resolved
by git push order.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CAO_HUB_URL` | `http://127.0.0.1:9889` | Hub server URL |
| `CAO_AGENT_PROFILE` | `remote-opencode` | Agent profile name |
| `CAO_PUSH_ONLY` | `1` | Push-only mode — skip L1 knowledge index pull. Set `0` to enable pull. |
| `CAO_LOCAL_SKILLS_DIR` | *(heuristic)* | Colon-separated list of local skill dirs to scan for `cao-*` skills on push. Defaults to the known claude-code / opencode / hermes paths. |

## Local-Only Mode

For same-machine setups without a Hub server, set `CAO_LOCAL_ONLY=1`.
Agents share notes and skills via a local bare git repo at
`~/.cao-evolution-local/shared.git` (auto-created on first use).

```bash
export CAO_LOCAL_ONLY=1
# Start any agent — it will auto-create the local shared repo
```

| Feature | Behavior |
|---------|----------|
| Hub registration | Skipped — local terminal ID assigned |
| Task polling | Disabled |
| Heartbeat / auto-evolution | Disabled — trigger skills manually via prompt |
| Notes / skills sharing | Local git (`file://` bare repo, cross-instance) |
| Knowledge search | Local file search over `notes/` directory |
| L1 knowledge index | Manual — trigger `cao-build-l1-index` skill after 3+ notes |

**Current scope:** OpenCode plugin fully supported. Claude Code hooks and
Hermes plugin have TODO markers for future support.

| Variable | Default | Description |
|----------|---------|-------------|
| `CAO_LOCAL_ONLY` | `0` | Enable local-only mode — no Hub, no upload |
| `CAO_GIT_REMOTE` | *(auto)* | Optional in local mode; auto-uses `file://~/.cao-evolution-local/shared.git` |
