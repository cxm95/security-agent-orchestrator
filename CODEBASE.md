# CLI Agent Orchestrator — Codebase Reference

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│                            Entry Points                                    │
├──────────────┬──────────────────┬──────────────────────────────────────────┤
│  CLI (Click) │  MCP Server      │  FastAPI HTTP API (:9889)               │
│  cao launch  │  Agent↔Hub bridge│  main.py + evolution_routes.py          │
│  cao info    │  7 evolution     │  /terminals, /sessions,                 │
│  cao flow    │  tools           │  /evolution/{task_id}/scores …          │
└──────┬───────┴────────┬─────────┴────────────────┬─────────────────────────┘
       │                │                          │
       └────────────────┴──────────┬───────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │        Services Layer        │
                    ├──────────────────────────────┤
                    │ terminal  session  inbox     │
                    │ flow      cleanup  settings  │
                    └──────────────┬───────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
     ┌────────▼────────┐  ┌───────▼────────┐  ┌────────▼─────────┐
     │    Clients       │  │   Providers    │  │   Evolution      │
     ├──────────────────┤  ├────────────────┤  ├──────────────────┤
     │ tmux  │ database │  │ claude_code    │  │ attempts (JSON)  │
     └───┬───┴────┬─────┘  │ codex          │  │ checkpoint (git) │
         │        │        │ copilot_cli    │  │ heartbeat engine │
    ┌────▼──┐ ┌───▼────┐   │ opencode       │  │ repo_manager     │
    │ Tmux  │ │ SQLite │   │ remote (DB-Q)  │  │ skill_sync       │
    │ Sess. │ │   DB   │   │ clother_mm_cn  │  │ reports          │
    └───────┘ └────────┘   └───────┬────────┘  └────────┬─────────┘
                                   │                     │
                           ┌───────▼────────┐   ┌────────▼─────────┐
                           │  CLI Tools /   │   │  evo-skills/     │
                           │  Remote Agents │   │  Skill repos     │
                           │  (tmux or      │   │  (.cao-evolution │
                           │   DB queue)    │   │   data store)    │
                           └────────────────┘   └──────────────────┘
```

**Key concepts:**

- **Local agents** run inside tmux sessions managed by a Provider (claude_code, codex, copilot_cli, opencode, clother_minimax_cn).
- **Remote agents** use `RemoteProvider` — a DB-queue virtual terminal that exchanges messages through the API without a local tmux session. The `cao-bridge` package connects remote agents to this queue.
- **Evolution layer** tracks scores, attempts, and heartbeat-driven prompts to continuously improve agent skills.

---

## Source Files

```
src/cli_agent_orchestrator/
├── __init__.py
├── constants.py                     [114 lines] Global config constants
│
├── api/
│   ├── __init__.py
│   ├── main.py                      FastAPI server — HTTP entry + routes
│   └── evolution_routes.py          Evolution API endpoints (~500 lines)
│
├── mcp_server/
│   ├── __init__.py
│   ├── server.py                    MCP Server — Agent↔Hub bridge
│   ├── evolution_tools.py           7 evolution MCP tools
│   ├── models.py                    HandoffResult model
│   └── utils.py                     DB query helpers
│
├── cli/
│   ├── __init__.py
│   ├── main.py                      Click CLI entry
│   └── commands/
│       ├── __init__.py
│       ├── launch.py                cao launch
│       ├── shutdown.py              cao shutdown
│       ├── info.py                  cao info
│       ├── install.py               cao install
│       ├── flow.py                  cao flow
│       ├── mcp_server.py            MCP server start command
│       └── init.py                  Initialize DB
│
├── evolution/
│   ├── __init__.py
│   ├── types.py                     Score, ScoreBundle, Attempt types
│   ├── attempts.py                  JSON CRUD + leaderboard + history comparison
│   ├── checkpoint.py                git init + flock commit
│   ├── heartbeat.py                 Heartbeat trigger engine + prompt rendering (~224 lines)
│   ├── repo_manager.py              Flat directory repo management
│   ├── skill_sync.py                Skill synchronization
│   ├── grader_base.py               GraderBase ABC
│   ├── reports.py                   Evolution report generation
│   └── prompts/                     Hub-side dispatch templates (loaded by heartbeat.py)
│       ├── evolve_skill.md          → dispatches to secskill-evo
│       ├── reflect.md               → dispatches to cao-reflect
│       ├── consolidate.md           → dispatches to cao-consolidate
│       ├── pivot.md                 → dispatches to cao-pivot
│       └── feedback_reflect.md      Human feedback reflection
│
├── providers/
│   ├── __init__.py
│   ├── base.py                      Abstract BaseProvider
│   ├── manager.py                   ProviderManager singleton
│   ├── claude_code.py               Claude Code provider
│   ├── codex.py                     Codex CLI provider
│   ├── copilot_cli.py               GitHub Copilot provider
│   ├── opencode.py                  OpenCode TUI provider
│   ├── remote.py                    RemoteProvider for remote agents (DB-queue virtual terminal)
│   └── clother_minimax_cn.py        Clother MiniMax CN (extends claude_code)
│
├── services/
│   ├── terminal_service.py          Terminal lifecycle management
│   ├── session_service.py           Session CRUD
│   ├── inbox_service.py             Message delivery + Watchdog
│   ├── flow_service.py              Scheduled flow (APScheduler)
│   ├── cleanup_service.py           Expired data cleanup
│   └── settings_service.py          Agent directory config
│
├── clients/
│   ├── tmux.py                      TmuxClient — all tmux ops
│   └── database.py                  SQLAlchemy CRUD
│
├── models/
│   ├── terminal.py                  TerminalStatus / Terminal
│   ├── session.py                   Session model
│   ├── inbox.py                     InboxMessage / MessageStatus
│   ├── flow.py                      Flow model
│   ├── provider.py                  ProviderType enum
│   ├── agent_profile.py             AgentProfile / McpServer
│   ├── kiro_agent.py                (legacy)
│   ├── q_agent.py                   (legacy)
│   └── copilot_agent.py             CopilotAgentConfig
│
└── utils/
    ├── __init__.py
    ├── terminal.py                  ID generation, wait helpers
    ├── logging.py                   File-based logging
    ├── agent_profiles.py            Load agent profiles
    └── template.py                  Template rendering
```

---

## Companion Directories

### evo-skills/ — Platform-agnostic evolution skills

```
evo-skills/
├── secskill-evo/                    Core skill evolution (FIX algorithm)
│   ├── SKILL.md                     Main instructions (~744 lines)
│   ├── agents/                      Sub-agent instructions (grader, judge, analyzer, comparator)
│   ├── scripts/                     Python utilities (git_version, run_loop, etc.)
│   ├── references/                  Schema docs
│   ├── assets/                      HTML templates
│   ├── README.md
│   └── LICENSE.txt
├── openspace-evo/SKILL.md           OpenSpace-style evolution (DERIVED + CAPTURED + lineage)
├── cao-reflect/SKILL.md             Structured reflection → note generation
├── cao-consolidate/SKILL.md         Cross-agent knowledge synthesis
└── cao-pivot/SKILL.md               Strategy pivot
```

### cao-bridge/ — Bridge implementations for remote agents

```
cao-bridge/
├── cao_bridge_mcp.py                MCP bridge server
├── cao_bridge.py                    Base bridge module
├── git_sync.py                      Git-based sync for evolution data
├── claude-code/                     Claude Code integration
│   ├── CLAUDE.md                    Agent instructions
│   ├── .mcp.json                    MCP config
│   ├── hooks/                       Session lifecycle hooks
│   └── install.sh                   Installer
├── skill/cao-bridge/SKILL.md        Skill-based bridge
├── plugin/cao-bridge.ts             OpenCode plugin bridge
├── hermes-plugin/                   Hermes agent integration
│   ├── plugin.yaml
│   ├── memory_parser.py
│   ├── hermes-sync.sh
│   └── README.md
└── README.md
```

### test/ — Test suite

```
test/
├── api/                             API endpoint tests
├── cli/                             CLI command tests
├── clients/                         Client tests
├── e2e/                             E2E tests (require running server)
├── evolution/                       Evolution tests (255 tests)
├── mcp_server/                      MCP server tests
├── models/                          Model tests
├── providers/                       Provider tests
├── services/                        Service tests
└── utils/                           Utility tests
```

---

## Data Flow Examples

### Terminal Creation Flow

```
cao launch --agents code_sup
  → terminal_service.create_terminal()
  → tmux_client.create_session(terminal_id)   # Sets CAO_TERMINAL_ID
  → database.create_terminal()
  → provider_manager.create_provider()
  → provider.initialize()                     # Waits for shell, sends command, waits for IDLE
  → inbox_service.register_terminal()          # Starts watchdog observer
  → Returns Terminal model
```

### Inbox Message Flow

```
MCP: send_message(receiver_id, message)
  → API: POST /terminals/{receiver_id}/inbox/messages
  → database.create_inbox_message()            # Status: PENDING
  → inbox_service.check_and_send_pending_messages()
  → If receiver IDLE  → send immediately
    If receiver PROCESSING → watchdog monitors log file
  → On log change → detect IDLE pattern → send message
  → Update message status: DELIVERED
```

### Handoff Flow

```
MCP: handoff(agent_profile, message)
  → API: POST /sessions/{session}/terminals
  → Wait for terminal IDLE
  → API: POST /terminals/{id}/input
  → Poll until status = COMPLETED
  → API: GET /terminals/{id}/output?mode=last
  → API: POST /terminals/{id}/exit
  → Return output to caller
```

### Score Submission → Heartbeat Flow

```
Agent: cao_report_score(task_id, agent_id, score)
  → POST /evolution/{task_id}/scores
  → evolution_routes.submit_score()
  → attempts.record_attempt()            → writes JSON to .cao-evolution/attempts/{task_id}/
  → attempts.compare_to_history()        → returns improved/baseline/regressed
  → checkpoint.commit()                  → git commit
  → heartbeat.check_triggers()           → checks plateau/periodic/score-change
  → If triggered:
      heartbeat.render_prompt()          → returns prompt with {agent_id}, {task_id},
                                           {leaderboard}, {evals_since_improvement}
  → Returns ScoreResponse with status + heartbeat_prompts[]
```

### Knowledge Sharing Flow

```
Agent: cao_share_note(title, content, tags)
  → POST /evolution/knowledge/notes
  → Writes .md with YAML frontmatter to shared/notes/
  → checkpoint.commit()
```

### Heartbeat Prompt → Agent Evolution

```
Hub sends heartbeat prompt (e.g., evolve_skill.md)
  → Agent reads prompt → loads secskill-evo from evo-skills/
  → Creates /tmp/cao-evo-workspace/ isolation
  → git_version.py tracks versions
  → Modifies skill → judges quality → commits or reverts
  → Syncs results back via cao_sync or git push
```
