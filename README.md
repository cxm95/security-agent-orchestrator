# CLI Agent Orchestrator (CAO)

> Fork of [awslabs/cli-agent-orchestrator](https://github.com/awslabs/cli-agent-orchestrator), extended with a CORAL-inspired **co-evolution system**. CAO orchestrates multiple AI coding agents in tmux terminals (or remotely via HTTP bridges) and adds a continuous improvement loop: agents report scores, the Hub detects plateaus, and heartbeat prompts trigger reflection, consolidation, pivots, and skill evolution — all synchronized through a git-backed knowledge repository.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Hub (cao-server :9889)                                         │
│  ┌──────────┐  ┌────────────────┐  ┌────────────────────────┐  │
│  │ FastAPI   │  │ Evolution API  │  │ MCP Server             │  │
│  │ api/      │  │ /evolution/*   │  │ cao-mcp-server         │  │
│  │ main.py   │  │ evolution_     │  │ server.py              │  │
│  │           │  │ routes.py      │  │ + evolution_tools.py   │  │
│  └─────┬─────┘  └───────┬───────┘  └──────────┬─────────────┘  │
│        │                │                      │                │
│  ┌─────▼─────────────────▼──────────────────────▼────────────┐  │
│  │  Services: terminal, session, inbox, flow, cleanup        │  │
│  │  Evolution: heartbeat, attempts, checkpoint, repo_manager │  │
│  │  Providers: claude_code, codex, copilot_cli, opencode,    │  │
│  │             remote, clother_minimax_cn                     │  │
│  └────────────────────────┬──────────────────────────────────┘  │
└───────────────────────────┼─────────────────────────────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
         Local Agent   Local Agent   Remote Agent
         (tmux)        (tmux)        (HTTP bridge)
              │             │             │
              └──── evo-skills ───────────┘
                   .cao-evolution/ (git)
```

**Three entry points:**

| Command | Description |
|---------|-------------|
| `cao-server` | FastAPI HTTP server on `:9889` — orchestration API + evolution endpoints |
| `cao` | CLI (Click) — `launch`, `shutdown`, `info`, `install`, `flow`, `mcp-server` |
| `cao-mcp-server` | MCP stdio server — agents call orchestration + evolution tools through this |

## Quick Start

### Requirements

- Python 3.10+
- tmux 3.2+ (for local agents; not needed for remote-only setups)
- [uv](https://docs.astral.sh/uv/) (package manager)
- At least one supported AI coding agent CLI installed

### Install & Run

```bash
# Clone and install
git clone <this-repo>
cd security-agent-orchestrator/
uv sync

# Install an agent profile
uv run cao install code_supervisor

# Terminal 1 — start the server
uv run cao-server

# Terminal 2 — launch a supervisor
uv run cao launch --agents code_supervisor --provider claude_code

# Shutdown when done
uv run cao shutdown --all
```

### Working with tmux

```bash
tmux list-sessions              # List all sessions
tmux attach -t <session-name>   # Attach to a session
# Ctrl+b, d   → detach
# Ctrl+b, w   → window selector
```

## Features

### Orchestration Modes

CAO provides three patterns for multi-agent coordination via MCP tools:

- **Handoff** — synchronous: spawn agent → send task → wait → return output
- **Assign** — asynchronous: spawn agent → send task → return immediately (agent reports back via `send_message`)
- **Send Message** — direct message to an existing agent's inbox

All modes support `working_directory`, context folder parameters, `display_name`, and cross-provider delegation.

### Providers

| Provider | Key | Notes |
|----------|-----|-------|
| Claude Code | `claude_code` | `--dangerously-skip-permissions` for auto-approve |
| Codex CLI | `codex` | `--full-auto` mode |
| GitHub Copilot CLI | `copilot_cli` | GitHub auth |
| OpenCode | `opencode` | Session persistence (`ses_xxx` resumption) |
| Remote | `remote` | HTTP bridge — no tmux on Hub side |
| Clother MiniMax CN | `clother_minimax_cn` | Claude Code subclass with alternate binary |

### Evolution System (CORAL-Inspired)

The main differentiator from upstream. Agents submit evaluation scores; the Hub tracks history, detects plateaus, and dispatches heartbeat prompts to drive improvement.

**Score → Compare → Heartbeat → Evolve cycle:**

1. Agent calls `cao_report_score(task_id, agent_id, score, feedback)`
2. Hub compares to history → returns `improved` / `baseline` / `regressed` / `crashed`
3. Hub checks heartbeat triggers:
   - **Plateau** — N evals without improvement → `evolve_skill` or `pivot`
   - **Periodic** — every N evals → `reflect` or `consolidate`
   - **Score-change** — significant delta → `feedback_reflect`
4. Triggered prompt is delivered to the agent's inbox

**Two-layer prompt architecture:**
- **Hub-side templates** (`evolution/prompts/*.md`) — `evolve_skill`, `reflect`, `consolidate`, `pivot`, `feedback_reflect`
- **Agent-side evo-skills** (`evo-skills/*/SKILL.md`) — platform-agnostic skill files agents execute locally

**Evolution MCP tools** (registered on `cao-mcp-server`):

| Tool | Description |
|------|-------------|
| `cao_report_score` | Submit evaluation score to Hub |
| `cao_get_leaderboard` | Top attempts sorted by score |
| `cao_search_knowledge` | Search notes + skills by text and tags |
| `cao_share_note` | Publish a knowledge note (markdown + YAML frontmatter) |
| `cao_share_skill` | Publish a reusable skill file |
| `cao_get_shared_notes` | List shared notes, optionally filtered by tags |
| `cao_get_shared_skills` | List all shared skills |
| `cao_submit_report` | Submit a structured findings report with human-label support |

**Git-based sync:** All evolution data (scores, prompts, knowledge) is stored in a `.cao-evolution/` repository with flat directory layout. Every score submission triggers a checkpoint commit.

### Evo-Skills

Five platform-agnostic evolution skills in `evo-skills/`:

| Skill | Purpose |
|-------|---------|
| `secskill-evo` | Create, test, and evolve Claude Code skills — benchmark, mutate, crossover |
| `openspace-evo` | Evolve skills via OpenSpace strategies (DERIVED, CAPTURED, COMPOSED) |
| `cao-reflect` | Produce a structured Note with insights from recent execution |
| `cao-consolidate` | Synthesize all agents' notes into actionable insights |
| `cao-pivot` | Abandon incremental tweaks — try a fundamentally different strategy |

Agents load these via `evo-skills/<name>/SKILL.md` or pull them from the Hub with `cao_pull_skills`.

### Remote Agents

Remote agents connect via HTTP bridge — no tmux required on the Hub side.

```
Hub (cao-server)                Remote Machine
┌──────────────┐   HTTP/REST   ┌──────────────────┐
│ RemoteProvider│◄────────────►│ Bridge            │
│ (in-memory)  │               │ (MCP/Plugin/Skill)│
└──────────────┘               │   ↕               │
                               │ Agent (any CLI)   │
                               └──────────────────┘
```

**Hub routes:** `/remotes/register`, `/remotes/{id}/poll`, `/remotes/{id}/report`, `/remotes/{id}/status`

**Three bridge variants** (in `cao-bridge/`):
1. **MCP bridge** (`cao_bridge_mcp.py`) — FastMCP stdio server with `cao_register`, `cao_poll`, `cao_report`
2. **Skill bridge** (`skill/SKILL.md`) — instruction file using `curl` for the bridge protocol
3. **Plugin bridge** (`plugin/cao-bridge.ts`) — TypeScript plugin for OpenCode

Additional integrations: Claude Code hooks (`cao-bridge/claude-code/`), Hermes plugin (`cao-bridge/hermes-plugin/`), git-based sync (`cao-bridge/git_sync.py`).

### Knowledge System

- **Notes** — markdown with YAML frontmatter (title, tags, agent_id, origin_task, confidence)
- **Skills** — reusable SKILL.md files shared across agents
- **Search** — grep + tag filtering via `cao_search_knowledge`
- **Storage** — `.cao-evolution/` git repo, checkpoint on every write

### Flows (Scheduled Sessions)

Cron-scheduled agent sessions via `cao flow add <flow.md>`:

```yaml
---
name: daily-review
schedule: "0 9 * * 1-5"
agent_profile: developer
provider: claude_code
---
Review yesterday's commits and create a summary.
```

Commands: `cao flow add|list|run|enable|disable|remove`

### Web UI

React + Vite + Tailwind dashboard in `web/`. Manages sessions, terminals, flows, and live agent output. Start with:

```bash
cd web/ && npm install && npm run dev   # Dev mode on :5173
# Or build for production: npm run build, then cao-server serves it on :9889
```

## Project Structure

```
src/cli_agent_orchestrator/
├── api/              main.py, evolution_routes.py
├── mcp_server/       server.py, evolution_tools.py
├── evolution/        heartbeat, attempts, checkpoint, repo_manager,
│   │                 skill_sync, grader_base, reports, types
│   └── prompts/      evolve_skill.md, reflect.md, consolidate.md, pivot.md
├── providers/        base, manager, claude_code, codex, copilot_cli,
│                     opencode, remote, clother_minimax_cn
├── services/         terminal, session, inbox, flow, cleanup, settings
├── clients/          tmux.py, database.py
├── models/           terminal, session, inbox, flow, provider, agent_profile
└── cli/              main.py + commands/

evo-skills/           5 platform-agnostic evolution skills
cao-bridge/           Remote agent bridge implementations
cao-mcp-task-context/ Companion MCP server for directory context management
web/                  React + Vite + Tailwind frontend
examples/             Agent profiles and workflow examples
test/                 ~90 test files (13 evolution-specific)
docs/                 API, provider, and configuration docs
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CAO_ENABLE_WORKING_DIRECTORY` | `false` | Allow `working_directory` in handoff/assign |
| `CAO_REQUIRE_CONTEXT_FOLDERS` | `false` | Make context folder params required |
| `CAO_HUB_URL` | `http://localhost:9889` | Hub URL for remote bridges |
| `CAO_AGENT_PROFILE` | — | Agent profile name for remote registration |

### Agent Profile Provider Override

```yaml
---
name: developer
description: Developer Agent
provider: claude_code
---
```

Valid `provider` values: `claude_code`, `codex`, `copilot_cli`, `opencode`, `remote`, `clother_minimax_cn`.

### MCP Server Configuration

```yaml
mcpServers:
  cao-mcp-server:
    command: cao-mcp-server
    env:
      CAO_ENABLE_WORKING_DIRECTORY: "true"
  # Remote SSE server (optional)
  taskgen:
    type: remote
    url: "http://127.0.0.1:9877/sse"
```

## Documentation

| Document | Description |
|----------|-------------|
| [CODEBASE.md](CODEBASE.md) | Detailed architecture and code map |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Dev setup, testing, code quality |
| [docs/api.md](docs/api.md) | REST API reference |
| [docs/agent-profile.md](docs/agent-profile.md) | Creating custom agent profiles |
| [docs/settings.md](docs/settings.md) | Agent directory and settings config |
| [docs/working-directory.md](docs/working-directory.md) | Working directory security policy |
| [docs/claude-code.md](docs/claude-code.md) | Claude Code provider details |
| [docs/codex-cli.md](docs/codex-cli.md) | Codex CLI provider details |
| [docs/copilot-cli.md](docs/copilot-cli.md) | GitHub Copilot CLI provider details |
| [cao-bridge/README.md](cao-bridge/README.md) | Remote bridge setup guide |
| [web/README.md](web/README.md) | Web UI architecture |

## Security

The server is designed for **localhost-only use**. Host header validation prevents DNS rebinding. Do not expose to untrusted networks without authentication.

## License

This project is licensed under the Apache-2.0 License — inherited from [awslabs/cli-agent-orchestrator](https://github.com/awslabs/cli-agent-orchestrator).
