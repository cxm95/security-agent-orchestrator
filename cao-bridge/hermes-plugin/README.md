# CAO Hermes Plugin

Integrates Hermes Agent into the CAO co-evolution framework. Uses the same
`CaoBridge` class as all other agents — data flows through:

```
CaoBridge → HTTP API → Hub writes files → git checkpoint → git push/pull
```

## Quick Start

### Option A: Full Plugin (recommended)

```bash
# Copy plugin to hermes plugins directory
cp -r cao-bridge/hermes-plugin ~/.hermes/plugins/cao-evolution

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

skills:
  external_dirs:
    - /path/to/cao-bridge/skill           # loads SKILL.md protocol
    - ~/.cao-evolution/skills  # shared skill pool
```

### Option C: Sync script fallback (no Plugin, no MCP)

```bash
# One-shot sync
./hermes-sync.sh

# Periodic sync (every 60s)
watch -n 60 ./hermes-sync.sh
```

## What Each Component Does

| Component | What | Automated? |
|-----------|------|-----------|
| **MCP** (`cao_bridge_mcp.py`) | 9 tools for hermes LLM to call | Agent-driven |
| **SKILL** (`SKILL.md` via `external_dirs`) | Protocol instructions | Passive |
| **Plugin** (`cao-evolution`) | Auto register/push/heartbeat | Lifecycle hooks |
| **Sync script** (`hermes-sync.sh`) | Push skills+memory | Cron/manual |

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
| `HERMES_SKILLS_DIR` | `~/.hermes/skills` | Override hermes skills directory |
| `HERMES_MEMORY_PATH` | `~/.hermes/memories/MEMORY.md` | Override memory file path |
| `CAO_HUB_URL` | `http://127.0.0.1:9889` | Used by sync script |

## Data Flow

- **Out** (session end): hermes skills → `bridge.share_skill()` → Hub files → git
- **Out** (session end): MEMORY.md § entries → `bridge.share_note()` → Hub files → git
- **In** (session start): `bridge.search_knowledge()` → inject context
- **In** (external_dirs): shared skills → hermes reads as read-only
- **Heartbeat**: `bridge.poll()` → inject into next turn
