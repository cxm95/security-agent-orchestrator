# CAO Local-Only Mode — Design Document

# CAO 本地模式设计方案

---

## 1. 背景 / Context

当前 cao-bridge 系统要求所有 remote agent 连接 CAO Hub 才能工作——即使只是同一台机器上的多个 agent 实例之间共享 notes 和 skills。用户需要一个轻量的本地模式：

Currently, the cao-bridge system requires all remote agents to connect to a CAO Hub server — even when the only goal is sharing notes and skills between agent instances on the same machine. A lightweight local-only mode is needed:

- 无 Hub、不上传 / No Hub server, no upload
- 无心跳、无自动进化 / No heartbeat, no auto-evolution
- Skill 靠 prompt 手动触发 / Skills triggered manually via prompts
- Notes 和 skills 在本地保存，跨实例共享 / Notes and skills saved locally, shared across instances
- L1 索引在生成 3+ 条 note 后手动触发 skill 构建 / L1 index built manually via skill after 3+ notes

**当前范围 / Current scope:** 仅支持 OpenCode。Claude Code 和 Hermes 留 TODO。

**Current scope:** OpenCode only. Claude Code and Hermes deferred with TODOs.

---

## 2. 架构对比 / Architecture Comparison

### 2.1 AS-IS：Hub 模式（当前）

```
┌─────────────────────────────────────────────────────────────────────┐
│                        同一台机器 / Same Machine                      │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐            │
│  │ Claude Code   │   │  OpenCode    │   │   Hermes     │            │
│  │  (hooks)      │   │  (plugin)    │   │  (plugin)    │            │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘            │
│         │                  │                   │                    │
│    bash curl          TS fetch()        Python CaoBridge            │
│         │                  │                   │                    │
│         ▼                  ▼                   ▼                    │
│  ┌─────────────────────────────────────────────────────┐           │
│  │              CAO Hub (:9889)  ← HTTP 服务器           │           │
│  │  /remotes/register  /remotes/{id}/poll               │           │
│  │  /remotes/{id}/report  /evolution/{task}/scores       │           │
│  │  /evolution/knowledge/search  /evolution/index        │           │
│  └──────────────────────┬──────────────────────────────┘           │
│                         │ git push/pull                             │
│                         ▼                                          │
│  ┌─────────────────────────────────────────────────────┐           │
│  │         Evolution Repo (远程 git / remote git)        │           │
│  └─────────────────────────────────────────────────────┘           │
│                         │                                          │
│              git clone (per-session)                                │
│         ┌───────────────┼───────────────┐                          │
│         ▼               ▼               ▼                          │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐                   │
│  │ session-A   │  │ session-B   │  │ session-C   │                  │
│  │ ~/.cao-evo  │  │ ~/.cao-evo  │  │ ~/.cao-evo  │                  │
│  │ -client/    │  │ -client/    │  │ -client/    │                  │
│  │ sessions/   │  │ sessions/   │  │ sessions/   │                  │
│  │  <id-A>/    │  │  <id-B>/    │  │  <id-C>/    │                  │
│  │ ├─notes/    │  │ ├─notes/    │  │ ├─notes/    │                  │
│  │ ├─skills/   │  │ ├─skills/   │  │ ├─skills/   │                  │
│  │ └─tasks/    │  │ └─tasks/    │  │ └─tasks/    │                  │
│  └────────────┘  └────────────┘  └────────────┘                   │
│                                                                     │
│  数据流 / Data flow:                                                 │
│  ① Agent → HTTP → Hub (register/poll/report/score)                 │
│  ② Hub → git push → Evolution Repo (remote)                        │
│  ③ Agent → git clone → per-session dir (本地)                       │
│  ④ Agent → git push → Evolution Repo → Hub git pull (共享)          │
│  ⑤ Hub → /evolution/index → Agent (L1 索引注入)                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 TO-BE：Local-Only 模式（OpenCode）

```
┌─────────────────────────────────────────────────────────────────────┐
│                        同一台机器 / Same Machine                      │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐            │
│  │ Claude Code   │   │  OpenCode    │   │   Hermes     │            │
│  │  (TODO)       │   │  ✅ 已支持    │   │  (TODO)      │            │
│  └──────────────┘   └──────┬───────┘   └──────────────┘            │
│                            │                                        │
│                       [无 HTTP]                                     │
│                       git only                                      │
│                            │                                        │
│                            ▼                                        │
│                     ┌────────────┐                                  │
│                     │ session-A   │  ← per-session git clone        │
│                     │ ├─notes/    │                                  │
│                     │ ├─skills/   │                                  │
│                     │ └─index.md  │                                  │
│                     └──────┬─────┘                                  │
│                            │                                        │
│         ┌──────────────────┼──────────────────┐                    │
│         │    git push      │                  │    git pull         │
│         ▼                  ▼                  ▼                     │
│  ┌─────────────────────────────────────────────────────┐           │
│  │       ~/.cao-evolution-local/shared.git              │           │
│  │         (本地 bare repo / auto-created)               │           │
│  └─────────────────────────────────────────────────────┘           │
│         ▲                  ▲                  ▲                     │
│         │    git pull      │                  │    git push         │
│         │                  │                  │                     │
│  ┌──────┴─────┐     ┌─────┴──────┐    ┌─────┴──────┐              │
│  │ session-B   │     │ session-C   │    │ session-D   │             │
│  │ (OpenCode)  │     │ (OpenCode)  │    │ (OpenCode)  │             │
│  └────────────┘     └────────────┘    └────────────┘              │
│                                                                     │
│  数据流 / Data flow:                                                 │
│  ① Agent 启动 → git clone from local bare repo → per-session dir   │
│  ② Agent 写 note/skill → cao_push → git push → local bare repo    │
│  ③ 其他 Agent → git pull → 获取最新 notes/skills                     │
│  ④ 手动触发 cao-build-l1-index skill → 读 notes → 写 index.md       │
│  ⑤ git push index.md → 其他 Agent pull 获取 L1 索引                  │
│                                                                     │
│  特点 / Features:                                                    │
│  • 无 Hub 服务器，无 HTTP 调用                                        │
│  • 无心跳，无自动进化（skill 手动触发）                                  │
│  • 跨实例共享通过本地 git bare repo                                    │
│  • L1 索引由 agent 手动触发 skill 构建                                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Git 仓库架构 / Git Repo Architecture

每个 agent 实例启动时，`session_manager.create_session()` 在
`~/.cao-evolution-client/sessions/<session_id>/` 下创建**独立的 git clone**（per-session）。
多个实例各自有自己的 clone，通过 push/pull 到同一个 git remote 来共享。

Each agent instance gets its own git clone (per-session) under
`~/.cao-evolution-client/sessions/<session_id>/`.
Multiple instances share by pushing/pulling to the same git remote.

**本地模式的改变 / Change in local mode:**
- AS-IS: git remote → 远程 URL（Hub 管理的 evolution repo）
- TO-BE: git remote → `file://~/.cao-evolution-local/shared.git`（本地 bare repo，自动创建）

---

## 4. 修改策略 / Modification Strategy

### 4.1 OpenCode 的两条 Hub 调用路径

OpenCode plugin 有两条独立的 Hub 调用路径，都需要处理：

```
OpenCode Agent
    │
    ├──→ cao-bridge.ts (TypeScript plugin)
    │      fetch() via hub() helper ──→ Hub HTTP API
    │      ❌ 不经过 CaoBridge Python 类
    │      → 需要在 .ts 里加 LOCAL_ONLY 守卫
    │
    └──→ MCP tools (cao_push, cao_search_knowledge, ...)
           cao_bridge_mcp.py ──→ CaoBridge Python 类 ──→ Hub HTTP API
           ✅ 修改 CaoBridge 即可覆盖
```

### 4.2 修改范围

| 文件 / File | 操作 | 说明 |
|---|---|---|
| `cao-bridge/git_sync.py` | 修改 | 共享基础设施：local bare repo 自动创建 |
| `cao-bridge/cao_bridge.py` | 修改 | CaoBridge 早返回 → 覆盖 MCP tools |
| `cao-bridge/opencode/plugin/cao-bridge.ts` | 修改 | LOCAL_ONLY 守卫 → 覆盖 plugin 直接调用 |
| `evo-skills/cao-build-l1-index/SKILL.md` | **新建** | L1 索引构建 skill（install.sh 自动安装） |
| `cao-bridge/README.md` | 修改 | 文档 |
| `test/evolution/test_local_only.py` | **新建** | 测试 |
| `cao-bridge/claude-code/hooks/*.sh` | TODO 注释 | 未来支持 |
| `cao-bridge/hermes/__init__.py` | TODO 注释 | 未来支持 |

### 4.3 install.sh

**不需要修改。** `CAO_LOCAL_ONLY` 是运行时环境变量。新 skill 放在 `evo-skills/` 下，
现有 install.sh 会自动安装。

---

## 5. 核心设计 / Core Design

### 5.1 开关 / Switch

`CAO_LOCAL_ONLY=1` 环境变量。

### 5.2 本地共享仓库 / Local Shared Repository

`~/.cao-evolution-local/shared.git` — bare repo，首次使用时自动创建。
`git_sync._git_remote()` 在 `CAO_LOCAL_ONLY=1` 且 `CAO_GIT_REMOTE` 未设置时返回此路径。

### 5.3 CaoBridge Hub 调用旁路

| 方法 | 本地模式返回值 |
|---|---|
| `register()` | `"local-<profile>"` |
| `poll()` | `None` |
| `report()` | 空操作 |
| `search_knowledge()` / `recall_knowledge()` | `_local_search()` |
| `fetch_index()` | 读本地 `<clone>/index.md` |
| 其余 Hub 方法 | 空操作 / no-op |

### 5.4 OpenCode plugin 守卫

`cao-bridge.ts` 中加 `LOCAL_ONLY` 常量，守卫所有 `hub()` / `fetch(HUB+...)` 调用。
Git 操作（`gitPush`, `pullSkillsFromClone`, `pushSkillsToClone`）保持不变。
L1 索引从本地 `CLIENT_DIR + "/index.md"` 读取。

### 5.5 L1 索引 Skill

`evo-skills/cao-build-l1-index/SKILL.md` — 手动触发，读 notes → 综合 → 写 index.md → cao_push。

---

## 6. 环境变量 / Environment Variables

| 变量 | 默认值 | 说明 |
|---|---|---|
| `CAO_LOCAL_ONLY` | `0` | 启用本地模式 |
| `CAO_GIT_REMOTE` | *(空)* | 本地模式下可不设置，自动使用 local bare repo |

---

## 7. 验证 / Verification

```bash
# 1. bare repo 自动创建
CAO_LOCAL_ONLY=1 python3 -c "from git_sync import ensure_local_shared_repo; print(ensure_local_shared_repo())"

# 2. CaoBridge 本地注册（无 Hub 不报错）
CAO_LOCAL_ONLY=1 python3 -c "from cao_bridge import CaoBridge; b = CaoBridge(); print(b.register())"

# 3. 跨实例共享: Terminal 1 写 note + cao_push → Terminal 2 pull 验证

# 4. L1 索引: 写 3+ notes → 触发 cao-build-l1-index → 验证 index.md

# 5. pytest test/ -x
```
