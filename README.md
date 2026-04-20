# CLI Agent Orchestrator (CAO)

> Fork of [awslabs/cli-agent-orchestrator](https://github.com/awslabs/cli-agent-orchestrator), extended with a CORAL-inspired **co-evolution system** and **memory loading**. CAO orchestrates multiple AI coding agents in tmux terminals (or remotely via HTTP bridges) and adds a continuous improvement loop: agents report scores, the Hub detects plateaus, and heartbeat prompts trigger reflection, consolidation, pivots, and skill evolution — all synchronized through a git-backed knowledge repository.

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│  Hub (cao-server :9889)                                              │
│  ┌──────────┐  ┌────────────────┐  ┌────────────────────────────┐   │
│  │ FastAPI   │  │ Evolution API  │  │ MCP Server                 │   │
│  │ api/      │  │ /evolution/*   │  │ cao-mcp-server             │   │
│  │ main.py   │  │ evolution_     │  │ server.py                  │   │
│  │           │  │ routes.py      │  │ + evolution_tools.py       │   │
│  └─────┬─────┘  └───────┬───────┘  └──────────┬─────────────────┘   │
│        │                │                      │                     │
│  ┌─────▼────────────────▼──────────────────────▼─────────────────┐   │
│  │  Services: terminal, session, inbox, flow, cleanup, settings  │   │
│  │  Evolution: heartbeat, attempts, checkpoint, repo_manager     │   │
│  │  Providers: claude_code, codex, copilot_cli, opencode,        │   │
│  │             remote, clother_closeai, clother_minimax_cn       │   │
│  └────────────────────────┬──────────────────────────────────────┘   │
│                           │                                          │
│  ┌────────────────────────▼──────────────────────────────────────┐   │
│  │  Root Orchestrator (--bare, CAO_HOOKS_ENABLED=0)              │   │
│  │  L1 Index Builder: notes/ → index.md (≤1500 tokens)           │   │
│  └───────────────────────────────────────────────────────────────┘   │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
    Local Agent   Local Agent   Remote Agent
    (tmux)        (tmux)        (HTTP bridge / SDK)
         │             │             │
         └──── evo-skills ───────────┘
              .cao-evolution/ (git)
```

**Three entry points:**

| Command | Description |
|---------|-------------|
| `cao-server` | FastAPI HTTP server on `:9889` — orchestration + evolution + L1 index APIs |
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

# Terminal 1 — start the server (Root Orchestrator auto-starts if configured)
# For shared-knowledge experiments, also export the git remote URL so the Hub
# pulls agent-pushed notes and auto-triggers L1 index rebuilds:
#   export CAO_EVOLUTION_REMOTE=https://github.com/<org>/cao-evolution-shared.git
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
| Clother CloseAI | `clother_closeai` | Claude Code subclass with `--yolo`; supports `--bare` flag |
| Clother MiniMax CN | `clother_minimax_cn` | Same as CloseAI with alternate binary; supports `--bare` |

### Root Orchestrator

A Hub-resident background agent that runs specialized tasks. Currently serves as the **L1 Index Builder** — processes shared notes into a concise knowledge index.

- Auto-starts with Hub (configurable via YAML)
- Hook-isolated: `--bare` flag + `CAO_HOOKS_ENABLED=0` prevents circular self-registration
- Communicates via inbox messages
- Lives in a dedicated tmux session (default: `ROOT`)

### L1 Knowledge Index (Memory Loading)

Agents automatically receive a curated knowledge digest at session startup, eliminating the need to manually search for prior knowledge.

**How it works:**

1. Agents produce **notes** during evolution (via `cao-reflect`, `cao-consolidate`)
2. On checkpoint commit with notes changes, Hub triggers the Root Orchestrator
3. Root Orchestrator reads all notes and generates `index.md` (≤1500 tokens)
4. New agent sessions receive the index via:
   - **CLI agents**: SessionStart hook / OpenCode plugin auto-injection
   - **SDK agents**: `CaoAgentLifecycle.build_context()` fetches and embeds index

**API endpoints:**

| Endpoint | Description |
|----------|-------------|
| `GET /evolution/index` | Retrieve current L1 index content |
| `POST /evolution/index/rebuild` | Manually trigger index rebuild |

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

### Recall System (BM25)

The Hub maintains a `RecallIndex` for BM25-based full-text search across notes and skills. Agents query it via `cao_search_knowledge` with text and optional tag filters. The index updates automatically on checkpoint commits.

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

**Four bridge variants** (in `cao-bridge/`):
1. **MCP bridge** (`cao_bridge_mcp.py`) — FastMCP stdio server with `cao_register`, `cao_poll`, `cao_report`
2. **Skill bridge** (`skill/SKILL.md`) — instruction file using `curl` for the bridge protocol
3. **Plugin bridge** (`plugin/cao-bridge.ts`) — TypeScript plugin for OpenCode
4. **SDK lifecycle** (`sdk/lifecycle.py`) — Python class for Claude Agent SDK / OpenCode SDK integration

Additional integrations: Claude Code hooks (`cao-bridge/claude-code/`), Hermes plugin (`cao-bridge/hermes-plugin/`), git-based sync (`cao-bridge/git_sync.py`).

### SDK Agent Support

For agents built with SDKs (e.g., [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python), [OpenCode SDK](https://github.com/anomalyco/opencode-sdk-python)), the `CaoAgentLifecycle` class provides lifecycle management:

```python
from sdk.lifecycle import CaoAgentLifecycle

lifecycle = CaoAgentLifecycle(hub_url="http://localhost:9889", profile="my-agent")
lifecycle.start()
context = lifecycle.build_context()  # Includes L1 index + registration info

# Pass context to your SDK agent as system prompt or initial message
agent.query(context + "\n\n" + task)

lifecycle.stop()
```

See `cao-bridge/sdk/example_claude_sdk.py` and `cao-bridge/sdk/example_opencode_sdk.py` for complete examples.

### Knowledge System

- **Notes** — markdown with YAML frontmatter (title, tags, agent_id, origin_task, confidence)
- **Skills** — reusable SKILL.md files shared across agents
- **Search** — BM25 + tag filtering via `cao_search_knowledge`
- **L1 Index** — auto-generated knowledge digest injected at session start
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

## Configuration

### YAML Configuration

CAO uses a YAML config file at `~/.aws/cli-agent-orchestrator/config.yaml` (override with `CAO_CONFIG` env var):

```yaml
root_orchestrator:
  enabled: true                    # Auto-start Root Orchestrator with Hub
  provider: clother_closeai        # Provider to use
  profile: root_orchestrator       # Agent profile name
  session: ROOT                    # Tmux session name
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CAO_ENABLE_WORKING_DIRECTORY` | `false` | Allow `working_directory` in handoff/assign |
| `CAO_REQUIRE_CONTEXT_FOLDERS` | `false` | Make context folder params required |
| `CAO_HUB_URL` | `http://localhost:9889` | Hub URL for remote bridges |
| `CAO_AGENT_PROFILE` | — | Agent profile name for remote registration |
| `CAO_CONFIG` | — | Override path to config.yaml |
| `CAO_HOOKS_ENABLED` | `1` | Set to `0` to disable bridge hooks (used for Root Orchestrator isolation) |

### Agent Profile Provider Override

```yaml
---
name: developer
description: Developer Agent
provider: claude_code
---
```

Valid `provider` values: `claude_code`, `codex`, `copilot_cli`, `opencode`, `remote`, `clother_closeai`, `clother_minimax_cn`.

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

## Project Structure

```
src/cli_agent_orchestrator/
├── api/              main.py (+ Root Orchestrator lifecycle), evolution_routes.py
├── mcp_server/       server.py, evolution_tools.py
├── evolution/        heartbeat, attempts, checkpoint, repo_manager,
│   │                 skill_sync, grader_base, reports, types
│   └── prompts/      evolve_skill.md, reflect.md, consolidate.md, pivot.md
├── providers/        base, manager, claude_code, codex, copilot_cli,
│                     opencode, remote, clother_closeai, clother_minimax_cn
├── services/         terminal, session, inbox, flow, cleanup, settings
├── clients/          tmux.py, database.py
├── models/           terminal, session, inbox, flow, provider, agent_profile
├── config.py         YAML configuration loader
└── cli/              main.py + commands/

evo-skills/           5 platform-agnostic evolution skills
cao-bridge/           Remote agent bridge implementations
├── sdk/              SDK lifecycle support (Claude Agent SDK, OpenCode SDK)
├── claude-code/      Claude Code hooks (SessionStart/Stop with L1 index injection)
├── plugin/           OpenCode TypeScript plugin
└── hermes-plugin/    Hermes Agent integration
cao-mcp-task-context/ Companion MCP server for directory context management
agent_store/          Agent profiles (root_orchestrator.md, etc.)
web/                  React + Vite + Tailwind frontend
examples/             Agent profiles and workflow examples
experiment/           Experiment scripts and E2E tests
test/                 ~90 test files (13 evolution-specific)
docs/                 API, provider, configuration, and implementation docs
```

## Documentation

| Document | Description |
|----------|-------------|
| [CODEBASE.md](CODEBASE.md) | Detailed architecture and code map |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Dev setup, testing, code quality |
| [docs/api.md](docs/api.md) | REST API reference |
| [docs/cao-code-map.md](docs/cao-code-map.md) | Full code map with line counts |
| [docs/implementation-progress.md](docs/implementation-progress.md) | Implementation history (21 steps) |
| [docs/agent-profile.md](docs/agent-profile.md) | Creating custom agent profiles |
| [docs/settings.md](docs/settings.md) | Agent directory and settings config |
| [docs/working-directory.md](docs/working-directory.md) | Working directory security policy |
| [docs/claude-code.md](docs/claude-code.md) | Claude Code provider details |
| [docs/codex-cli.md](docs/codex-cli.md) | Codex CLI provider details |
| [docs/copilot-cli.md](docs/copilot-cli.md) | GitHub Copilot CLI provider details |
| [cao-bridge/README.md](cao-bridge/README.md) | Remote bridge setup guide |
| [web/README.md](web/README.md) | Web UI architecture |
| [experiment/README.md](experiment/README.md) | Experiment guide with E2E test steps |

## Security

The server is designed for **localhost-only use**. Host header validation prevents DNS rebinding. Do not expose to untrusted networks without authentication. The Root Orchestrator runs with `--bare` to prevent hook-based circular registration.

## License

This project is licensed under the Apache-2.0 License — inherited from [awslabs/cli-agent-orchestrator](https://github.com/awslabs/cli-agent-orchestrator).
