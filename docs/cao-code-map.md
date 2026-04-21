# CAO (cli-agent-orchestrator) 代码地图

> 最后更新: Step 20 — Git-Centric 重构

## 总览

```
src/cli_agent_orchestrator/          (~10000行)
├── __init__.py
├── constants.py                     [114行] 全局配置常量
├── config.py                        [~65行] YAML 配置加载（config.yaml）
├── api/
│   ├── __init__.py
│   ├── main.py                      [~980行] FastAPI 服务 — HTTP 入口 + 基础路由 + Root Orchestrator 生命周期
│   └── evolution_routes.py          [~890行] 进化 API 端点（任务/分数/排行/知识/心跳/recall/L1 index）
├── mcp_server/
│   ├── server.py                    [~746行] MCP Server — Agent ↔ Hub 桥梁
│   ├── evolution_tools.py           [~293行] 12 个进化 MCP 工具
│   ├── models.py                    HandoffResult 等
│   └── utils.py                     DB 查询辅助
├── cli/
│   ├── main.py                      Click CLI 入口
│   └── commands/
│       ├── launch.py                cao launch — 启动 agent 会话
│       ├── shutdown.py              cao shutdown — 关闭所有会话
│       ├── info.py                  cao info — 查看状态
│       ├── install.py               cao install — 安装 provider + agent profile
│       ├── flow.py                  cao flow — 管理定时 flow
│       ├── mcp_server.py            MCP server 启动命令
│       └── init.py                  初始化
├── evolution/                       CORAL 风格进化系统
│   ├── types.py                     [~246行] Score, ScoreBundle, Attempt 类型
│   ├── attempts.py                  JSON CRUD + 排行榜 + 历史比较
│   ├── checkpoint.py                [~305行] git init + flock commit + on_commit + _sync_remote
│   ├── recall_index.py              [~435行] BM25 Okapi 知识召回索引
│   ├── heartbeat.py                 [~226行] 心跳触发引擎 + prompt 渲染
│   ├── repo_manager.py              扁平目录 repo 管理
│   ├── skill_sync.py                [~229行] Skill 同步
│   ├── grader_base.py               [~148行] GraderBase 抽象基类（保留向后兼容）
│   ├── reports.py                   进化报告生成
│   └── prompts/                     Hub 侧调度模板（heartbeat.py 加载）
│       ├── evolve_skill.md          → 调度 secskill-evo
│       ├── reflect.md               → 调度 cao-reflect
│       ├── consolidate.md           → 调度 cao-consolidate
│       ├── pivot.md                 → 调度 cao-pivot
│       └── feedback_reflect.md      人类反馈反思（独立）
├── providers/
│   ├── base.py                      [~218行] BaseProvider 抽象基类
│   ├── manager.py                   ProviderManager 单例
│   ├── claude_code.py               [~328行] Claude Code 适配
│   ├── codex.py                     [~475行] Codex CLI 适配
│   ├── copilot_cli.py               [~464行] GitHub Copilot 适配
│   ├── opencode.py                  [~522行] OpenCode TUI 适配
│   ├── remote.py                    RemoteProvider — 远程 Agent DB 队列虚拟终端
│   ├── clother_closeai.py           Clother CloseAI（继承 claude_code, --yolo）
│   └── clother_minimax_cn.py        Clother MiniMax CN（继承 claude_code, --yolo）
├── clients/
│   ├── tmux.py                      [~511行] TmuxClient 单例 — 所有 tmux 操作
│   └── database.py                  [~385行] SQLAlchemy CRUD
├── services/
│   ├── terminal_service.py          [~418行] 终端生命周期管理
│   ├── session_service.py           会话 CRUD（tmux session 层）
│   ├── inbox_service.py             [~151行] 消息投递 + Watchdog 文件监控
│   ├── flow_service.py              [~235行] 定时 flow 调度（APScheduler cron）
│   ├── cleanup_service.py           过期数据清理
│   └── settings_service.py          Agent 目录配置
├── models/
│   ├── terminal.py                  TerminalStatus / Terminal / TerminalId
│   ├── provider.py                  ProviderType 枚举
│   ├── session.py                   Session 模型
│   ├── inbox.py                     InboxMessage / MessageStatus
│   ├── flow.py                      Flow 模型
│   ├── agent_profile.py             AgentProfile / McpServer 模型
│   ├── copilot_agent.py             Copilot 专用配置
│   ├── kiro_agent.py                (上游遗留)
│   └── q_agent.py                   (上游遗留)
└── utils/
    ├── agent_profiles.py            [~238行] Profile 发现 + 加载
    ├── terminal.py                  ID 生成 + wait_until_status
    ├── template.py                  Flow 模板渲染
    └── logging.py                   日志设置

agent_store/                         内置 Agent Profile（随包分发）
└── root_orchestrator.md             Root Orchestrator — L1 Index Builder

evo-skills/                          平台无关的进化 Skill
├── secskill-evo/                    核心 Skill 进化（FIX 算法）
│   ├── SKILL.md                     主指令
│   ├── agents/                      子 Agent 指令（grader, judge, analyzer, comparator）
│   ├── scripts/                     Python 工具（git_version, run_loop 等）
│   ├── references/schemas.md        JSON Schema 参考
│   └── assets/eval_review.html      基准测试可视化
├── security-grader/SKILL.md         通用安全评分 Skill（grader_skill 引用目标）
├── openspace-evo/SKILL.md           OpenSpace 风格进化（DERIVED + CAPTURED + 谱系）
├── cao-reflect/SKILL.md             结构化反思 -> note 生成
├── cao-consolidate/SKILL.md         跨 Agent 知识综合
└── cao-pivot/SKILL.md               策略转向

cao-bridge/                          远程 Agent 桥接实现
├── cao_bridge_mcp.py                [~377行] MCP 桥接服务器（16 工具，含 cao_session_info）
├── cao_bridge.py                    [~483行] 基础桥接模块（含 session 生命周期 + fetch_index）
├── git_sync.py                      [~247行] Git 同步（session-aware）
├── session_manager.py               [~262行] Session 隔离管理（create/touch/deactivate/cleanup）
├── report_registry.py               [~132行] 本地报告登记簿（flock 保护）
├── cao-session-mgr.sh               Session 管理 CLI（create/list/cleanup/info）
├── claude-code/                     Claude Code 集成（CLAUDE.md + hooks + .mcp.json）
├── skill/cao-bridge/SKILL.md        Skill 桥接协议文档
├── opencode/                        OpenCode 集成
│   ├── install.sh                   安装脚本
│   └── plugin/cao-bridge.ts         [~443行] 事件驱动插件（含 session 隔离）
├── sdk/                             SDK Agent 生命周期支持
│   ├── __init__.py                  导出 CaoAgentLifecycle
│   ├── lifecycle.py                 [~190行] SDK Agent 生命周期（start/stop/build_context/fetch_index）
│   ├── example_claude_sdk.py        Claude Agent SDK 集成示例
│   ├── example_opencode_sdk.py      OpenCode SDK 集成示例
│   └── test_sdk_lifecycle.py        E2E 测试（3 tests）
├── hermes/                   Hermes Agent 集成
│   ├── __init__.py                  [~236行] Plugin 主逻辑（session-aware）
│   ├── hermes-sync.sh               独立同步脚本（session-aware）
│   └── memory_parser.py             [~46行] MEMORY.md 解析器
└── README.md

cao-mcp-task-context/                独立 MCP 工具包 — 多任务 phase 工作流
├── src/cao_mcp_task_context/server.py
└── pyproject.toml

test/                                测试套件（~350 测试）
├── api/                             API 端点测试
├── cli/                             CLI 命令测试
├── clients/                         Client 测试
├── e2e/                             E2E 测试（需要运行中的服务器）
├── evolution/                       进化测试
├── mcp_server/                      MCP 服务器测试
├── models/                          模型测试
├── providers/                       Provider 测试
├── services/                        服务层测试
└── utils/                           工具测试
```

---

## 4 个入口点（pyproject.toml scripts）

| 命令 | 入口 | 用途 |
|------|------|------|
| `cao` | `cli/main.py:cli` | Click CLI（launch/shutdown/info/flow/install） |
| `cao-server` | `api/main.py:main` | FastAPI HTTP 服务（端口 9889） |
| `cao-mcp-server` | `mcp_server/server.py:main` | FastMCP stdio — Agent 加载的主 MCP |
| `cao-task-context` | `cao_mcp_task_context/server.py:main` | FastMCP SSE — 多任务 phase workflow MCP |

---

## 层级架构

```
┌──────────────────────────────────────────────────────────┐
│  入口层 (Entrypoints)                                     │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────┐       │
│  │ CLI (cao) │  │ HTTP (FastAPI)│  │ MCP (FastMCP) │       │
│  └────┬─────┘  └──────┬───────┘  └──────┬────────┘       │
├───────┼────────────────┼─────────────────┼────────────────┤
│  编排层 (Services)     │                 │                │
│  ┌─────────────────────┴─────────────────┘                │
│  │  terminal_service  ◄──── 核心编排器                     │
│  │  session_service / inbox_service / flow_service        │
│  └──────┬──────────────┬──────────────────────────────────┤
│  进化层 (Evolution)    │                                  │
│  ┌─────────────────────┘                                  │
│  │  evolution_routes.py  ◄── 分数/任务/知识/L1 index API  │
│  │  heartbeat.py         ◄── 心跳触发 + prompt 渲染       │
│  │  attempts.py          ◄── 历史比较 + 排行榜             │
│  │  checkpoint.py        ◄── git 版本管理 + 远程同步       │
│  │  recall_index.py      ◄── BM25 知识召回                │
│  │  evolution_tools.py   ◄── 12 个 MCP 进化工具           │
│  └──────┬──────────────┬──────────────────────────────────┤
│  基础设施层 (Infra)    │                                  │
│  ┌──────┴─────┐  ┌─────┴──────┐  ┌───────────────┐       │
│  │ TmuxClient │  │ Database   │  │ ProviderManager│       │
│  │ (tmux.py)  │  │ (SQLite)   │  │ + Providers   │       │
│  └────────────┘  └────────────┘  └───────────────┘       │
└──────────────────────────────────────────────────────────┘

外部:
  evo-skills/*     <- Agent 侧加载的进化指令（不在 Hub 进程中运行）
  cao-bridge/*     <- 远程 Agent 桥接实现
```

---

## 3 种 Agent 编排模式 (MCP Tools)

### 1. Handoff（同步阻塞）
```
Supervisor Agent --MCP:handoff--> MCP Server
                                    │
                                    ├─ 1. POST /sessions/.../terminals (创建 tmux 窗口)
                                    ├─ 2. wait_until_status(IDLE) (等 provider 初始化)
                                    ├─ 3. POST /terminals/{id}/input (发送任务)
                                    ├─ 4. wait_until_status(COMPLETED) (轮询直到完成)
                                    ├─ 5. GET /terminals/{id}/output?mode=last (提取结果)
                                    └─ 6. 返回 HandoffResult --> Supervisor
```

### 2. Assign（异步非阻塞）
```
Supervisor Agent --MCP:assign--> MCP Server
                                    │
                                    ├─ 1. POST /sessions/.../terminals
                                    ├─ 2. POST /terminals/{id}/input (发任务, 附回调指令)
                                    └─ 3. 立即返回 {terminal_id} --> Supervisor
                                                     ↑
Worker 完成后 --MCP:send_message--> Supervisor (异步回调)
```

### 3. Send Message（消息队列）
```
Agent A --MCP:send_message--> MCP Server
                                │
                                ├─ POST /terminals/{receiver}/inbox/messages
                                │     -> 写入 SQLite inbox 表 (status=PENDING)
                                │
                                └─ Watchdog 检测 receiver 日志变化
                                       -> 若 receiver IDLE -> deliver (tmux send_keys)
                                       -> 更新 status=DELIVERED
```

---

## 核心数据流（含代码路径）

### Terminal 生命周期

```
create_terminal()                      <- services/terminal_service.py:58
  │
  ├─ generate_terminal_id()            <- utils/terminal.py (8位hex)
  ├─ tmux_client.create_session()      <- clients/tmux.py:112
  │   └─ libtmux.Server.new_session() -> 创建 tmux 窗口
  ├─ db_create_terminal()              <- clients/database.py:72 -> SQLite
  ├─ provider_manager.create_provider()<- providers/manager.py:30
  ├─ provider.initialize()             <- providers/claude_code.py -> 在 tmux 中启动 CLI
  ├─ tmux_client.send_keys(sys_prompt) <- clients/tmux.py:193 (bracketed paste)
  └─ tmux_client.pipe_pane(log_path)   <- clients/tmux.py -> 输出重定向
```

### Handoff 完整流程

```
Agent 调 MCP:handoff(agent_profile, message)
  │
  ├─ mcp_server/server.py:403 -> handoff() MCP tool
  │    └─ _handoff_impl()     <- server.py:279
  │
  ├─ 1. _create_terminal()    <- server.py:109
  │      └─ HTTP POST -> api/main.py create_terminal_in_session()
  │           └─ terminal_service.create_terminal()
  │
  ├─ 2. wait_until_terminal_status(IDLE)
  │      └─ 轮询 GET /terminals/{id} -> provider.get_status()
  │           └─ tmux_client.get_history() -> 正则匹配终端输出
  │
  ├─ 3. _send_direct_input_handoff()  <- server.py:219
  │      └─ HTTP POST /terminals/{id}/input
  │           └─ tmux_client.send_keys() (load-buffer -> paste-buffer)
  │
  ├─ 4. wait_until_terminal_status(COMPLETED, timeout=1800s)
  │
  ├─ 5. GET /terminals/{id}/output?mode=last
  │      └─ provider.extract_last_message_from_script()
  │
  └─ 6. 返回 HandoffResult(success, output, terminal_id)
```

### Provider 状态检测

```
provider.get_status()  <- providers/{claude_code,codex,...}.py
  │
  ├─ tmux_client.get_history(tail_lines=200)  <- clients/tmux.py:333
  │    └─ tmux capture-pane -e -p -S -200
  ├─ 用 provider 特定的正则匹配:
  │    IDLE / PROCESSING / COMPLETED / ERROR
  └─ 返回 TerminalStatus 枚举 <- models/terminal.py
```

---

## Provider 接口 (BaseProvider)

```python
class BaseProvider(ABC):
    # 必须实现:
    initialize()                    # 在 tmux 中启动 CLI
    get_status(tail_lines)          # 解析终端输出判断状态
    get_idle_pattern_for_log()      # 日志中快速检测 idle 的模式
    extract_last_message_from_script(output)  # 从终端输出提取最后回复
    exit_cli()                      # 退出命令
    cleanup()                       # 清理资源

    # 可选覆盖:
    paste_enter_count               # 粘贴后按几次Enter (默认2)
    extraction_retries              # 提取失败重试次数 (默认0)
    graceful_exit()                 # 优雅退出+返回session_id
    env_vars / set_env_vars()       # CLI启动前的环境变量
    _apply_env_vars()               # 在 tmux 中 export 环境变量（ClaudeCode/Clother 在 initialize() 调用）

    # Clother 系列特有:
    bare: bool                      # --bare 跳过 hooks/plugins/CLAUDE.md（用于 Root Orchestrator 隔离）
```

---

## 数据库表 (SQLite via SQLAlchemy)

```
terminals                        inbox                         flows
┌──────────────────────┐        ┌─────────────────────┐      ┌────────────────────┐
│ id (PK, 8-hex)       │        │ id (PK, auto-incr)  │      │ name (PK)          │
│ tmux_session         │        │ sender_id            │      │ file_path          │
│ tmux_window          │        │ receiver_id          │      │ schedule (cron)    │
│ provider             │        │ message              │      │ agent_profile      │
│ agent_profile        │        │ status (enum)        │      │ provider           │
│ last_active          │        │ created_at           │      │ script             │
└──────────────────────┘        └─────────────────────┘      │ last_run / next_run│
                                                               │ enabled            │
remote_state (断点续传用)                                      └────────────────────┘
┌──────────────────────┐
│ terminal_id (PK)     │    RemoteProvider 内存状态在每次变更
│ status               │    时镜像到本表；Hub 重启后由
│ pending_input        │    RecoveryService 于 lifespan startup
│ last_output          │    阶段 rehydrate 成 Provider 实例，
│ full_output (clipped)│    full_output 尾部被裁剪到 128KB。
│ last_seen_at         │
│ updated_at           │
└──────────────────────┘
```

### 崩溃恢复 / Reattach 流程

1. Hub 启动: `lifespan` → `RecoveryService.recover_all()` 遍历 `terminals`：
   - local（tmux）终端: `tmux has-session` 存活则保留，否则标记 stale 并清理
   - remote 终端: 为每行在 `ProviderManager` 重建 `RemoteProvider`，
     构造函数内 `_hydrate_from_db()` 从 `remote_state` 加载状态
2. Agent 冷启动 (cao-bridge / plugin / hook):
   - 若本地缓存有 `terminal_id` → `POST /remotes/{id}/reattach`
     - 404: 缓存失效 → fallback 到 `POST /remotes/register`
     - 200: 返回 `status` / `has_pending_input` / `pending_inbox_count`，
       同时调用 `provider.reset_for_reattach()` 把遗留的
       `processing`/`error` 重置为 `idle`，避免 inbox 投递被阻塞
3. 之后正常 `poll` / `report` 循环，`pending_input` 和 `full_output` 从
   崩溃前保留。

---

## HTTP API 路由汇总

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/agents/profiles` | 列出所有 agent profile |
| GET | `/agents/providers` | 列出 provider + 安装状态 |
| GET/POST | `/settings/agent-dirs` | Agent 目录配置 |
| POST | `/sessions` | 创建新会话 (含首个终端) |
| GET | `/sessions` | 列出所有会话 |
| GET | `/sessions/{name}` | 获取会话详情 |
| DELETE | `/sessions/{name}` | 删除会话 |
| POST | `/sessions/{name}/terminals` | 添加终端 |
| GET | `/sessions/{name}/terminals` | 列出终端 |
| GET | `/terminals/{id}` | 获取终端状态 |
| POST | `/terminals/{id}/input` | 发送输入 |
| GET | `/terminals/{id}/output` | 获取输出 |
| POST | `/terminals/{id}/exit` | 优雅退出 |
| DELETE | `/terminals/{id}` | 删除终端 |
| POST | `/terminals/{id}/inbox/messages` | 发送 inbox 消息 |
| GET | `/terminals/{id}/inbox/messages` | 查询 inbox |
| WS | `/terminals/{id}/ws` | WebSocket 实时终端 |
| CRUD | `/flows/*` | Flow 定时任务管理 |
| POST | `/remotes/register` | 远程 Agent 注册 |
| POST | `/remotes/{id}/reattach` | 冷启动复用已注册的 terminal_id（断点续传） |
| GET | `/remotes/{id}/poll` | 轮询待执行命令 |
| POST | `/remotes/{id}/report` | 上报执行结果 |
| GET | `/remotes/{id}/status` | 远程 Agent 当前状态 + 是否有待派发输入 |
| | **进化端点 (evolution_routes.py)** | |
| POST | `/evolution/tasks` | 创建任务（含 grader_skill） |
| GET | `/evolution/tasks` | 列出所有任务 |
| GET | `/evolution/{task_id}` | 获取任务详情 |
| POST | `/evolution/{task_id}/scores` | **核心**: 上报分数 -> 触发心跳 |
| GET | `/evolution/{task_id}/leaderboard` | 排行榜 |
| GET | `/evolution/{task_id}/attempts` | 尝试历史 |
| POST | `/evolution/knowledge/notes` | 创建笔记（Hub 内部用，Agent 走 git push） |
| GET | `/evolution/knowledge/notes` | 查询笔记 |
| POST | `/evolution/knowledge/skills` | 创建 skill（Hub 内部用，Agent 走 git push） |
| GET | `/evolution/knowledge/skills` | 查询 skill |
| GET | `/evolution/knowledge/search` | 知识搜索（grep + tags） |
| GET | `/evolution/knowledge/recall` | BM25 排序知识召回 |
| GET | `/evolution/knowledge/document/{doc_id}` | 按 ID 获取完整文档 |
| POST | `/evolution/knowledge/recall/rebuild` | 手动触发 BM25 索引重建 |
| POST | `/evolution/{task_id}/reports` | 提交报告 |
| GET | `/evolution/{task_id}/reports` | 报告列表 |
| GET | `/evolution/{task_id}/reports/stats` | 报告统计 |
| PUT | `/evolution/{task_id}/reports/{id}/annotate` | 人工标注 |
| GET | `/evolution/{task_id}/reports/{id}/result` | 标注结果 |
| GET | `/evolution/heartbeat/{agent_id}` | 获取心跳配置 |
| PUT | `/evolution/heartbeat/{agent_id}` | 更新心跳配置 |

---

## 关键常量 (constants.py)

```python
SESSION_PREFIX      = "cao-"                     # tmux 会话名前缀
TMUX_HISTORY_LINES  = 200                        # 终端回滚捕获行数
CAO_HOME_DIR        = ~/.aws/cli-agent-orchestrator/  # 数据根目录
SERVER_HOST         = "127.0.0.1"                # 仅本地
SERVER_PORT         = 9889                       # API 端口
INBOX_POLLING_INTERVAL = 5                       # 秒
RETENTION_DAYS      = 14                         # 数据保留天数
```

---

## 模块依赖图 (核心)

```
constants.py <---- (配置枢纽)
     │
     v
models/* <---- terminal.py 被多数文件引用
     │
     v
clients/database.py <-- (持久层)
clients/tmux.py     <-- (终端控制)
     │
     ├──> providers/base.py --> providers/{claude,codex,opencode,remote,...}.py
     │    providers/manager.py
     │
     ├──> evolution/types.py --> evolution/attempts.py --> evolution/heartbeat.py
     │    evolution/checkpoint.py    evolution/recall_index.py
     │    evolution/repo_manager.py  evolution/skill_sync.py
     │
     v
services/terminal_service.py <-- (核心编排: DB + tmux + provider)
services/session_service.py / inbox_service.py / flow_service.py
     │
     v
api/main.py ---- (HTTP路由, 调用所有 service)
api/evolution_routes.py ---- (进化路由, 调用 evolution/*)
mcp_server/server.py ---- (MCP工具, 调用 HTTP API)
mcp_server/evolution_tools.py ---- (进化 MCP 工具, 调用 HTTP API)
cli/main.py ---- (CLI命令, 调用 service)
```

**特点**: 无循环依赖。MCP Server 通过 HTTP 调用 API（不直接调 service），实现进程解耦。
evolution 层独立于 services 层，通过 evolution_routes.py 暴露给 HTTP/MCP。

---

## Hub 进化 MCP 工具 (evolution_tools.py, 12 个)

| 工具名 | 功能 |
|--------|------|
| `cao_report_score` | 上报分数 -> 触发心跳检查 |
| `cao_get_leaderboard` | 查询任务排行榜 |
| `cao_search_knowledge` | 搜索共享知识（full=grep, selective=BM25） |
| `cao_get_shared_notes` | 获取共享笔记列表 |
| `cao_get_shared_skills` | 获取共享 skill 列表 |
| `cao_submit_report` | 提交安全报告 |
| `cao_fetch_feedback` | 获取人工反馈 |
| `cao_list_reports` | 列出报告 |
| `cao_create_task` | 创建进化任务（含 grader_skill） |
| `cao_list_tasks` | 列出所有任务 |
| `cao_recall` | BM25 排序知识召回 |
| `cao_fetch_document` | 按 doc_id 获取完整文档 |

> **已移除** (Step 20): `cao_share_note`, `cao_share_skill` — Agent 走 git push

---

## Bridge MCP 工具 (cao_bridge_mcp.py, 16 个)

| 工具名 | 功能 |
|--------|------|
| `cao_register` | 远程 Agent 注册 |
| `cao_poll` | 轮询待执行命令 |
| `cao_report` | 上报执行结果 |
| `cao_create_task` | 创建进化任务 |
| `cao_get_task` | 获取任务详情（含 grader_skill） |
| `cao_report_score` | 上报分数 |
| `cao_get_leaderboard` | 查询排行榜 |
| `cao_search_knowledge` | 搜索共享知识 |
| `cao_recall` | BM25 排序知识召回 |
| `cao_fetch_document` | 按 doc_id 获取完整文档 |
| `cao_submit_report` | 提交漏洞报告 + 本地登记 |
| `cao_fetch_feedbacks` | 拉取人工标注 + 渲染反馈 md |
| `cao_sync` | 双向 Git 同步（push + pull） |
| `cao_push` | Git add + commit + push |
| `cao_pull_skills` | 拉取共享 skills |
| `cao_session_info` | 查看当前 session 元数据 |

> **已移除** (Step 20): `cao_share_note`, `cao_share_skill` — 改为本地写入 + `cao_push`
