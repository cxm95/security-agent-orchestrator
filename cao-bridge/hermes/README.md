# CAO Hermes Plugin

Integrates Hermes Agent into the CAO co-evolution framework. Uses the same
`CaoBridge` class + `git_sync` module as all other agents — data flows through:

```
上行: CaoBridge → HTTP API → Hub writes files → git commit → git push
下行: git_sync → git clone/pull ~/.cao-evolution-client/ → pull skills to ~/.hermes/skills/
```

## Quick Start

### Option A: Full Plugin (recommended)

```bash
# Copy plugin to hermes plugins directory
cp -r cao-bridge/hermes ~/.hermes/plugins/cao-evolution

# Set git remote (required for sync)
export CAO_GIT_REMOTE="git@github.com:org/evolution.git"  # or file:///path/to/.cao-evolution

# Add to ~/.hermes/config.yaml:
plugins:
  cao-evolution:
    hub_url: "http://127.0.0.1:9889"
    push_skills: true
    push_memory: true
    heartbeat_enabled: true
```

### Option B: MCP + SKILL only (no Plugin)

```yaml
# ~/.hermes/config.yaml
mcp:
  cao-bridge:
    command: ["python3", "/path/to/cao-bridge/cao_bridge_mcp.py"]
    environment:
      CAO_HUB_URL: "http://127.0.0.1:9889"
      CAO_AGENT_PROFILE: "remote-hermes"
      CAO_GIT_REMOTE: "git@github.com:org/evolution.git"

skills:
  external_dirs:
    - /path/to/cao-bridge/skill                 # loads SKILL.md protocol
    - ~/.cao-evolution-client/skills             # shared skill pool (git clone)
```

### Option C: Sync script fallback (no Plugin, no MCP)

```bash
# Set git remote
export CAO_GIT_REMOTE="git@github.com:org/evolution.git"

# One-shot sync
./hermes-sync.sh

# Periodic sync (every 60s)
watch -n 60 ./hermes-sync.sh
```

## What Each Component Does

| Component | What | Automated? |
|-----------|------|-----------|
| **MCP** (`cao_bridge_mcp.py`) | 11 tools for hermes LLM (incl. cao_sync, cao_pull_skills) | Agent-driven |
| **SKILL** (`SKILL.md` via `external_dirs`) | Protocol instructions | Passive |
| **Plugin** (`cao-evolution`) | Auto git sync/register/push/heartbeat | Lifecycle hooks |
| **Sync script** (`hermes-sync.sh`) | Git sync + push skills+memory | Cron/manual |

## Plugin Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `hub_url` | string | `http://127.0.0.1:9889` | CAO Hub URL |
| `agent_id` | string | `""` | Agent ID (auto if empty) |
| `push_skills` | bool | `true` | Push skills on session end |
| `push_memory` | bool | `true` | Push MEMORY.md on session end |
| `heartbeat_enabled` | bool | `true` | Accept heartbeat prompts |
| `our_evolution_enabled` | bool | `false` | Use CAO judge/evals (hermes has its own) |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CAO_GIT_REMOTE` | _(required)_ | Git remote URL of Hub's evolution repo |
| `CAO_CLIENT_DIR` | `~/.cao-evolution-client` | Agent-side clone path |
| `HERMES_SKILLS_DIR` | `~/.hermes/skills` | Override hermes skills directory |
| `HERMES_MEMORY_PATH` | `~/.hermes/memories/MEMORY.md` | Override memory file path |
| `CAO_HUB_URL` | `http://127.0.0.1:9889` | Used by sync script |

## Data Flow

- **Out** (session end): hermes skills → write to `~/.cao-evolution-client/skills/` → `git_push()`
- **Out** (session end): MEMORY.md § entries → write to `~/.cao-evolution-client/notes/` → `git_push()`
- **In** (session start): `git_sync.init_client_repo()` → clone/pull `~/.cao-evolution-client/`
- **In** (session start): `_pull_skills_from_clone()` → copy skills to `~/.hermes/skills/`
- **In** (session start): `bridge.search_knowledge()` → inject context as session prompt
- **In** (session end): `git_sync.pull()` → refresh clone with our writes + others' changes
- **Heartbeat**: `report_score()` response → pending_heartbeats → inject into next turn
