# CAO 自进化流程与数据流

> **本文档是 CAO Evolution 系统的核心数据流、自进化流程参考。**
> 涵盖：task/attempt 生命周期、分数提交调用链、心跳触发、知识系统、Git 同步架构。
> 架构总览与代码地图见 `cao-code-map.md`。

---

## 1. 架构总览

Evolution 系统受 CORAL 启发，核心原则：

- **所有进化操作在远端 Agent 侧执行**，Hub 不执行任何进化逻辑
- Hub（CAO Server，端口 `:9889`）是**同步中心** — 存储分数/报告、比较历史、触发心跳提示
- Agent 收到心跳提示或拿到人工标注后，自行加载 evo-skill 并执行进化
- **评分也在 Agent 侧执行**：Agent 加载 `grader_skill` 指定的 evo-skill 进行自评

### 1.1 统一数据流总览

下图把五条原本散落在各节的子流程整合到一张图里：
**a) 自评打分 → 心跳**、**b) 漏洞上报 → 人工标注**、**c) 异步拉取反馈**、
**d) 反馈驱动的技能进化**、**e) Git 知识同步**。标注 ⓐ-ⓔ 对应下方小节。

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                               Remote Agent                                    │
│                                                                              │
│  ~/.cao-evolution-client/sessions/<session_id>/   (per-instance git 克隆)     │
│  ├── skills/  notes/  tasks/                  ← cao_sync / cao_push          │
│  └── reports/                                 ← 本地运行时状态 ❌ 不入 git    │
│      ├── registry.json                          (flock 保护, pending→annotated)
│      └── <report_id>.result                     (拉到的人工标注)             │
│                                                                              │
│  <cwd>/evolve_from_feedback.md                ← feedback-fetch 的产物        │
└──────────────────────────────────────────────────────────────────────────────┘
          │                                                     ▲
   ⓐ 自评得分 + ⓑ 上报疑点           ⓒ 异步拉取           ⓔ 拉 skill/notes
          │                                                     │
          ▼                                                     │
┌──────────────────────────────────────────────────────────────────────────────┐
│                             Hub  (CAO :9889)                                  │
│                                                                              │
│  ⓐ POST /evolution/{task}/scores   ──▶ attempts.json + checkpoint           │
│                                         heartbeat.check_triggers()           │
│                                         └──▶ ScoreResponse.heartbeat_prompts │
│                                                                              │
│  ⓑ POST /evolution/{task}/reports  ──▶ Report(status=pending)               │
│                                                                              │
│             ┌──── ② 人工标注 (Web UI / API) ───┐                              │
│             ▼                                 │                              │
│       PUT /reports/{id}/annotate ──▶ Report(status=annotated)                │
│                                         + shared_dir/reports/{id}.result    │
│                                                                              │
│  ⓒ GET /reports/{id}/result        ──▶ 标注 JSON (404 = 未标注)              │
│                                                                              │
│  ⓔ Git remote (notes/ skills/ tasks/) ──▶ 其他 Agent                         │
└──────────────────────────────────────────────────────────────────────────────┘


                      ── Agent 侧触发/消费路径（按时间展开）──

 ⓐ cao_report_score ─┐
                     ├──▶ Hub 写 attempt → 回传 heartbeat_prompts
                     │         ├─ reflect / consolidate / pivot
                     │         └─ evolve_skill (plateau 触发)
                     │
 ⓑ cao_submit_report ─▶ registry 追加 {report_id, status=pending}
                          (人工标注何时到达未知, 大概率需多次轮询)
                     │
 ⓒ cao_fetch_feedbacks ─▶ 扫描 pending → GET /result
                          ├─ 404: 仍 pending
                          └─ 200: 落盘 .result + registry→annotated
                                   + 渲染 <cwd>/evolve_from_feedback.md
                                   + 返回 {feedback_md_path, fetched, pending}
                     │
 ⓓ 如果 feedback_md_path 非空:
       Agent 读 evolve_from_feedback.md
         → 调 secskill-evo (Evolution Mode)
           · fp 实例 → negative fixtures
           · tp 实例 → regression fixtures
         → 新 skill 版本就位
         → cao_sync / cao_report_score 闭环
```

> **设计要点 — 为什么分两条触发链：**
> ⓐ 是 *快速同步* 通道（submit_score 立即回 heartbeat_prompts），
> ⓑ-ⓒ 是 *异步就绪* 通道（人工标注不是 submit_report 的返回值，可能延迟数小时/天）。
> 这就是为什么需要 `registry.json` 登记簿 + 轮询的 `cao_fetch_feedbacks`：
> Agent 不能阻塞等待标注，只能在后续心跳或显式时机再来查一次。

### 1.2 精简时序（仅分数 + 心跳）

如果只看 ⓐ 这一条链：

```
┌────────────────────────────────────┐     ┌──────────────────────────────┐
│         Remote Agent               │     │     Hub (CAO :9889)          │
│                                    │     │                              │
│  0. 获取 task（cao_get_task）       │◀────│  task.yaml（含 grader_skill） │
│  1. 执行任务                        │     │                              │
│  2. 加载 grader skill，自评得分     │     │                              │
│  3. cao_report_score(score)        │────▶│  4. 写 attempt.json          │
│                                    │     │  5. Git checkpoint            │
│                                    │◀────│  6. 返回 heartbeat_prompts   │
│  7. 根据 prompt 加载 evo-skill     │     │                              │
│  8. 执行进化，提交新分数            │────▶│  9. 循环...                  │
└────────────────────────────────────┘     └──────────────────────────────┘
```

---

## 2. 双层 Prompt 架构

Evolution 使用两层 prompt 设计，分离调度与执行：

### 2.1 Hub 侧分发模板

**路径：** `src/cli_agent_orchestrator/evolution/prompts/*.md`

- 轻量级 15-25 行模板
- 由 `heartbeat.py:_load_prompt()` (行 21) 在模块初始化时加载到 `DEFAULT_PROMPTS` 字典 (行 26)
- 作用：告诉 Agent **加载哪个 evo-skill**

**模板占位符：**

| 占位符 | 含义 |
|--------|------|
| `{agent_id}` | Agent 终端标识 |
| `{task_id}` | 任务 ID |
| `{leaderboard}` | Markdown 格式排行榜 |
| `{evolution_signals_json}` | 进化上下文信号（JSON） |
| `{evals_since_improvement}` | 距上次提升的评估次数 |

### 2.2 Agent 侧执行指令

**路径：** `evo-skills/*/SKILL.md`

- 详细的 85-744 行操作指南，Agent 逐步执行
- 平台无关（不绑定特定 Agent 框架）

**现有 evo-skills：**

```
evo-skills/
├── secskill-evo/          # 安全技能进化（主要）
│   ├── SKILL.md
│   ├── agents/            # analyzer, comparator, judge, grader.md
│   └── references/        # schemas.md
├── security-grader/       # 通用安全评分 Skill（grader_skill 引用）
│   └── SKILL.md
├── cao-reflect/           # 反思总结
│   └── SKILL.md
├── cao-consolidate/       # 跨 Agent 知识整合
│   └── SKILL.md
├── cao-pivot/             # 策略转向
│   └── SKILL.md
└── openspace-evo/         # OpenSpace 进化
    └── SKILL.md
```

---

## 3. task.yaml 与 attempt.json 生命周期

这两个文件是 evolution 系统的核心数据载体。理解它们的完整流转，才能理解整个系统。

### 3.1 task.yaml — 任务定义（Hub → Agent 单向流动）

**创建方**：Hub 端（管理员/实验设计者 或 Agent 通过 API 上报）

**存储位置**：Hub 侧 `.cao-evolution/tasks/{task_id}/task.yaml`

**Agent 获取方式**：
- A. `GET /evolution/{task_id}` API 接口 — 返回 JSON 含完整 yaml 及 grader_skill
- B. Agent 侧 `cao_get_task(task_id)` MCP 工具 → 调用上述 API
- C. Git clone/pull `.cao-evolution-client/` 后读取本地副本

**task.yaml 结构：**

```yaml
task_id: sec-audit-2025
name: Security Audit
description: Scan repos for SQL injection vulnerabilities
grader_skill: security-grader    # 指向 evo-skills/security-grader/
tips:
  - Check parameterized queries
  - Look for string concatenation in SQL
created_by: admin
last_updated: "2026-04-15T10:00:00Z"
```

**关键字段 grader_skill：**

- 值为 evo-skill 名称（如 `security-grader`）
- Agent 加载 `evo-skills/{grader_skill}/SKILL.md` 进行评分
- 为空字符串表示无指定 grader，Agent 报 score=0 或跳过评分
- 正则约束：`^[a-zA-Z0-9_-]*$`，防止路径穿越

**创建路径（两种场景）：**

```
场景 A：Hub 管理员创建
管理员 → POST /evolution/tasks (含 grader_skill)
  → evolution_routes.py:create_task() 行 181
  → 写入 .cao-evolution/tasks/{task_id}/task.yaml
  → git checkpoint → Agent 通过 git pull 或 API 获取

场景 B：Remote Agent 本地创建
用户指示 Agent 创建任务
  → Agent 调用 cao_create_task() MCP 工具
  → cao_bridge_mcp.py 行 85 → cao_bridge.py:create_task()
  → HTTP POST /evolution/tasks
  → Hub 写入 task.yaml → git checkpoint
```

### 3.2 attempt.json — 每次评估记录（Hub 侧写入）

**写入方**：Hub 端 `submit_score()` 流程

**存储位置**：Hub 侧 `.cao-evolution/attempts/{task_id}/{run_id}.json`

**Agent 获取方式**：
- `GET /evolution/{task_id}/attempts` API 接口
- Git clone 后读取 `.cao-evolution-client/attempts/`

**attempt.json 结构：**

```json
{
  "run_id": "20260415-103000-abc123",
  "agent_id": "remote-a1b2c3d4",
  "task_id": "sec-audit-2025",
  "score": 0.72,
  "status": "improved",
  "title": "initial scan",
  "feedback": "found 3 SQL injection points",
  "timestamp": "2026-04-15T10:30:00Z",
  "evolution_signals": {
    "grader_skill": {"skill": "security-grader", "score": 0.72},
    "judge": {"source": "llm-as-judge", "confidence": 0.85}
  }
}
```

### 3.3 端到端数据流（Remote Agent 完整生命周期）

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Phase 1: 任务创建与分发                            │
│                                                                      │
│  Hub 端:                                                             │
│    POST /evolution/tasks                                             │
│    → create_task() 行 181                                            │
│    → 写入 tasks/{task_id}/task.yaml                                  │
│    → git checkpoint                                                  │
│                                                                      │
│  Agent 端:                                                           │
│    cao_get_task(task_id) 或 cao_poll()                               │
│    → 获取 task 信息 + grader_skill 名称                              │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                    Phase 2: 任务执行                                  │
│                                                                      │
│  Agent 端:                                                           │
│    → 执行 task.yaml 中描述的任务（用户提示词 / cao_poll 分发）        │
│    → 产出结果文本                                                    │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                    Phase 3: Grader Skill 评分                        │
│                                                                      │
│  Agent 端:                                                           │
│    → 读取 task.yaml 的 grader_skill 字段（如 "security-grader"）     │
│    → 加载 evo-skills/security-grader/SKILL.md                        │
│    → SKILL.md 指导 Agent 按评分维度打分                               │
│    → 输出: CAO_SCORE=0.72                                            │
│                                                                      │
│  Plugin 自动化（OpenCode 示例）:                                      │
│    session.idle 触发 → getTaskInfo() → grader_skill 存在?            │
│    → 是: 注入 grader prompt → 等 Agent 评分 → 提取 CAO_SCORE         │
│    → 否: 报 score=0                                                  │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                    Phase 4: 分数上报（触发核心调用链）                 │
│                                                                      │
│  Agent 端:                                                           │
│    cao_report_score(task_id, score=0.72, title="scan round 1")       │
│    → POST /evolution/{task_id}/scores                                │
│                                                                      │
│  Hub 端 (submit_score() 行 261):                                     │
│    → compare_to_history() → status: improved/baseline/regressed      │
│    → write_attempt() → 写入 attempt.json                             │
│    → checkpoint() → git add && commit → on_commit → recall 索引更新  │
│    → check_triggers() → 心跳判定                                     │
│    → 返回 ScoreResponse(heartbeat_prompts=[...])                     │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                    Phase 5: 自进化（由心跳 prompt 驱动）               │
│                                                                      │
│  Agent 端:                                                           │
│    → 从 ScoreResponse 取出 heartbeat_prompts                        │
│    → prompt 指向特定 evo-skill（如 secskill-evo, cao-reflect）       │
│    → 加载 SKILL.md → 在隔离工作区执行进化                             │
│    → 完成后 git push / cao_sync 回 Hub                               │
│    → 再次 cao_report_score → 回到 Phase 4 形成闭环                   │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.4 task.yaml 流动方向总结

```
task.yaml:    Hub ──(write)──▶ .cao-evolution/tasks/
                              ──(git sync)──▶ .cao-evolution-client/tasks/
                              ──(API/MCP)──▶ Agent 内存
              Agent ──(cao_create_task)──▶ Hub（本地创建场景）
              ⚠ Agent 不直接修改 tasks/ 目录

attempt.json: Hub ──(write_attempt)──▶ .cao-evolution/attempts/
                                     ──(git sync)──▶ .cao-evolution-client/attempts/
              Agent ──(cao_report_score)──▶ Hub（间接写入）
              ⚠ Agent 不直接写 attempts/ 目录
```

---

## 4. 分数提交调用链（核心触发路径）

这是整个 evolution 系统的**主驱动链**。每次 Agent 提交分数时触发。

**前置阶段**（Agent 侧，在调用本链之前）：

```
Agent 完成任务
  │
  ▼
读取 task.yaml 的 grader_skill 字段
  │  cao_get_task(task_id) → {"grader_skill": "security-grader", ...}
  │
  ▼
加载 evo-skills/{grader_skill}/SKILL.md
  │  SKILL.md 指导 Agent 按维度评分
  │  Agent 输出: CAO_SCORE=0.72
  │
  ▼
Plugin 自动提取 / Agent 手动调用 cao_report_score
```

**核心调用链**（Hub 侧，submit_score() 入口）：

```
Agent 调用: cao_report_score(task_id, agent_id, score, ...)
  │
  ▼
MCP Tool: mcp_server/evolution_tools.py → cao_report_score()
  │  构建 HTTP 请求
  ▼
HTTP: POST /evolution/{task_id}/scores
  │
  ▼
API 入口: api/evolution_routes.py:submit_score()  (行 261)
  │
  ├─ Step 1: 比较历史
  │    → evolution/attempts.py:compare_to_history()  (行 51)
  │    → 返回: "improved" | "baseline" | "regressed" | "crashed"
  │    → 逻辑:
  │        new_score is None        → "crashed"
  │        best is None (首次)      → "improved"
  │        new_score > best         → "improved"
  │        new_score == best        → "baseline"
  │        否则                     → "regressed"
  │
  ├─ Step 2: 写入 Attempt 记录
  │    → evolution/attempts.py:write_attempt()  (行 22)
  │    → 写入: .cao-evolution/attempts/{task_id}/{run_id}.json
  │    → 字段: run_id, agent_id, task_id, score, status, timestamp,
  │            feedback, evolution_signals
  │
  ├─ Step 3: Git checkpoint（带文件锁）
  │    → evolution/checkpoint.py:checkpoint()  (行 96)
  │    → git add -A && git commit（.cao-evolution/ 内）
  │    → 并发安全: fcntl.flock() 文件锁  (行 120)
  │    → 锁释放后触发 on_commit 回调 → BM25 recall 索引增量更新
  │
  ├─ Step 4: 计算排行榜位置
  │    → evolution/attempts.py:get_leaderboard()  (行 67)
  │
  ├─ Step 5: 计算距上次提升的评估次数
  │    → evolution/attempts.py:count_evals_since_improvement()  (行 77)
  │
  ├─ Step 6: 检查心跳触发条件
  │    → evolution/heartbeat.py:check_triggers()  (行 152)
  │    → 传入: task_id, agent_id, status, score,
  │            local_eval_count, evals_since_improvement
  │    → 返回: 触发的 action 列表 + 渲染后的 prompt 列表
  │
  └─ Step 7: 返回响应
       → ScoreResponse {
           status,
           best_score,
           leaderboard_position,
           evals_since_improvement,
           heartbeat_triggered: [...],   # 触发的 action 名称
           heartbeat_prompts: [...]      # 渲染后的完整 prompt
         }
       → Agent 从响应中读取 heartbeat_prompts
```

---

## 5. 心跳触发机制详解

### 5.1 触发类型

`HeartbeatRunner.check()` (行 53) 支持两种触发模式：

| 模式 | 判断逻辑 | 适用场景 |
|------|----------|----------|
| **interval** | `eval_count % action.every == 0` | 定期触发（如每 N 次评估） |
| **plateau** | `evals_since_improvement > action.every` | 停滞检测（连续 N 次无提升） |

防重复机制：`_plateau_fired_at` 字典记录上次触发点，避免在同一区间内重复触发。
详见 `_check_plateau()` (行 71)。

### 5.2 默认心跳动作（heartbeat.py 行 105-112）

| 动作 | every | 模式 | 范围 | 说明 |
|------|-------|------|------|------|
| `reflect` | 1 | interval | local | 每次评估后反思 |
| `consolidate` | 5 | interval | global | 每 5 次全局评估整合知识 |
| `pivot` | 5 | plateau | local | 连续 5 次无提升则转向 |
| `evolve_skill` | 3 | plateau | local | 连续 3 次无提升则进化技能 |

### 5.3 Prompt 渲染

触发后，`render_prompt()` (行 136) 执行：

1. 从 `DEFAULT_PROMPTS[prompt_key]` 获取模板
2. 替换所有 `{placeholder}` 占位符
3. 返回完整的 prompt 文本

### 5.4 心跳 Prompt 类型总览

| Prompt Key | 模板文件 | 触发条件 | 分发到 |
|---|---|---|---|
| `evolve_skill` | `prompts/evolve_skill.md` | Plateau（N 次无提升） | `evo-skills/secskill-evo/` |
| `reflect` | `prompts/reflect.md` | 每次评估后 / 提升后 | `evo-skills/cao-reflect/` |
| `consolidate` | `prompts/consolidate.md` | 多 Agent 同任务，定期 | `evo-skills/cao-consolidate/` |
| `pivot` | `prompts/pivot.md` | 扩展 Plateau（2× 阈值） | `evo-skills/cao-pivot/` |
| `feedback_reflect` | `prompts/feedback_reflect.md` | *(legacy)* 基于 hub-side `.result`；`check_triggers` 调用处未传 `reports_dir`，实际休眠。新流程见 §6.4。 | — |

> **人工反馈的正式入口是 §6.4 的 `feedback-fetch` skill + `cao_fetch_feedbacks` MCP 工具。**
> 老的 `feedback_reflect` 模板与 `has_new_feedback` 旁路保留但不再主动触发，以免破坏既有测试；不建议在新代码中依赖。

---

## 6. Agent 侧执行流程

### 6.1 Grader Skill 评分流程

Agent 完成任务后，通过加载 grader_skill 指定的 evo-skill 进行自评：

```
Agent 完成任务，产出结果文本
  │
  ├─ 方式 A: Plugin 自动触发（OpenCode）
  │    → session.idle → getTaskInfo(taskId)
  │    → grader_skill 非空? → 注入 grader prompt
  │    → Agent LLM 读取 evo-skills/{grader_skill}/SKILL.md
  │    → Agent 输出 "CAO_SCORE=0.72"
  │    → Plugin 正则提取: /CAO_SCORE\s*=\s*(\d+\.?\d*)/
  │    → 调用 reportScore(taskId, 0.72)
  │
  ├─ 方式 B: Plugin 自动触发（Hermes）
  │    → on_session_end → bridge.get_task(task_id)
  │    → grader_skill 非空? → 排入 pending_heartbeats 队列
  │    → 下次 pre_llm_call → 注入 grader prompt
  │    → Agent 评分并上报
  │
  └─ 方式 C: Agent 手动/SKILL.md 引导
       → cao_get_task(task_id) → 获得 grader_skill
       → 加载 evo-skills/{grader_skill}/SKILL.md
       → 按照 SKILL.md 评分维度打分
       → 调用 cao_report_score(task_id, score)
```

### 6.2 心跳驱动的进化执行流（以 evolve_skill 为例）

Agent 在 `ScoreResponse` 中收到 `heartbeat_prompts` 后：

```
Agent 收到 ScoreResponse.heartbeat_prompts
  │
  ▼
读取 prompt: "加载 evo-skills/secskill-evo/SKILL.md"
  │
  ▼
SKILL.md 执行步骤:
  ├─ Step 1-3: 收集上下文
  │    → 读取当前 skill 代码
  │    → 读取 heartbeat 数据（分数历史、信号）
  │    → 分析失败模式
  │
  ├─ Step 4: 创建隔离工作区
  │    → /tmp/cao-evo-workspace/（防止污染主代码）
  │
  ├─ Step 5: 应用改进
  │    → 修改 skill / 策略 / 参数
  │
  ├─ Step 6: 验证
  │    → LLM-as-judge（通过 agents/judge.md 评估）
  │
  ├─ Step 7: 提交结果
  │    → 如果有提升: git commit + 同步回 Hub
  │    → 通过 cao_sync MCP 工具或 git push 到 .cao-evolution-client/
  │
  └─ Step 8: 重试或回滚
       → 最多重试 2 次
       → 如果回退: git revert
```

### 6.3 三种连接路径

Agent 可通过不同方式处理心跳：

| 路径 | 处理方式 |
|------|----------|
| **MCP 路径** | Agent 的 MCP 客户端自动处理 prompt |
| **Plugin 路径** | Plugin 轮询心跳，注入 prompt 到 Agent 上下文 |
| **Skill 路径** | Agent 在 SKILL.md 指引下主动检查心跳响应 |

### 6.4 人工反馈驱动的进化流（feedback-fetch → secskill-evo）

人工标注是**异步就绪**的 —— Agent 上报疑点后，标注可能数分钟到数天才到达。
不能阻塞 Agent 等待，也不能把"有没有标注"塞进 `cao_report_score` 的同步返回。
因此使用一条独立的登记簿 + 轮询链，由新的 **`feedback-fetch`** skill 驱动：

**参与组件**

| 组件 | 位置 | 职责 |
|---|---|---|
| `cao_submit_report` (MCP) | `cao-bridge/cao_bridge_mcp.py` | POST `/evolution/{task}/reports`，返回后把 `report_id` 追加到本地登记簿 |
| `cao_fetch_feedbacks` (MCP) | 同上 | 扫登记簿里的 pending，GET `/reports/{id}/result`，落盘 + 渲染 md |
| `report_registry.py` | `cao-bridge/` | `registry.json` 的 flock 读写 (add / list_pending / mark_annotated / mark_consumed) |
| `feedback-fetch` skill | `evo-skills/feedback-fetch/SKILL.md` | 指导 agent 何时调 MCP、如何把产物交给 `secskill-evo` |
| `evolve_from_feedback.md` 模板 | `evo-skills/feedback-fetch/templates/` | 渲染结果文件的骨架，跟 skill 走（不嵌在 MCP 代码里） |
| `.git/info/exclude` (agent 侧) | `<session_dir>/.git/info/exclude` | 自动追加 `reports/` + `.session.json`，本地运行时状态不入共享 repo |

**完整时序**

```
        Agent                              Hub                     Human
          │                                 │                         │
  ⓑ cao_submit_report(findings)             │                         │
  ────────────────────────────────────────▶ │                         │
          │  ◀── {report_id}                │                         │
          │    registry: add(pending)       │                         │
          │                                 │                         │
          │                                 │  ◀── 人工标注 (UI/API) ──
          │                                 │      PUT /annotate      │
          │                                 │  status: annotated      │
          │                                 │                         │
  ⓒ cao_fetch_feedbacks()                   │                         │
  ────────────────────────────────────────▶ │                         │
          │    list_pending() →             │                         │
          │    loop {                       │                         │
          │      GET /reports/{id}/result ─▶│                         │
          │      ◀── 404 (仍 pending)       │                         │
          │           或                    │                         │
          │      ◀── 200 { labels, score }  │                         │
          │      write .result              │                         │
          │      registry.mark_annotated    │                         │
          │    }                            │                         │
          │    render <cwd>/evolve_from_feedback.md                   │
          │  ◀── { feedback_md_path,        │                         │
          │        fetched, pending }       │                         │
          │                                 │                         │
  ⓓ 若 feedback_md_path 非空:                │                         │
     → 读 md                                 │                         │
     → 加载 secskill-evo (Evolution Mode)    │                         │
       · verdict=fp 实例 → 负例                                        │
       · verdict=tp 实例 → 回归例                                      │
       · verdict=uncertain → 不做硬约束                                │
     → snapshot → improve → validate → commit                         │
     → cao_sync (push evolved skill) ──────▶│                         │
     → cao_report_score (新版本闭环)  ──────▶│                         │
```

**登记簿结构** (`<session_dir>/reports/registry.json`)

```jsonc
{
  "entries": {
    "a1b2c3d4e5f6": {
      "report_id":    "a1b2c3d4e5f6",
      "task_id":      "vuln-scan-xyz",
      "source":       "cao",                     // 预留多 API 源路由
      "submitted_at": "2026-04-16T08:30:00+00:00",
      "status":       "pending | annotated | consumed",
      "result_path":  ".../reports/a1b2c3d4e5f6.result"
    }
  }
}
```

**关键不变量**

- `cao_submit_report` 成功后**必定**写入 registry；如果 Hub 返回无 `report_id`，跳过（安全降级）。
- `cao_fetch_feedbacks` 对未标注的 report **不**修改 registry（保持 pending 以便下次重试）。
- 404 视为"尚未标注"，不视为失败；网络异常亦保留为 pending，下次再取。
- 同一 `report_id` 二次调用是幂等的：`status=annotated` 后不会重复 GET。
- 若本轮没有任何新标注，**不**渲染 `evolve_from_feedback.md`，返回 `feedback_md_path=""`，由 agent 自行选择是否跳过。

**模板占位符**（`evolve_from_feedback.md`）

| 占位符 | 含义 |
|---|---|
| `{fetched_count}` | 本轮新拉到的标注数 |
| `{task_ids}` | 涉及的 task 列表（逗号分隔） |
| `{report_ids}` | 涉及的 report_id（逗号分隔） |
| `{entries_markdown}` | 每个 report 的一行 markdown 列表 |
| `{payloads_json}` | 所有标注原始 JSON（供 secskill-evo 直接消费） |

---

## 7. Bridge 变体

远端 Agent 通过 Bridge 连接 Hub，不同 Bridge 处理心跳和 Grader 方式不同：

```
cao-bridge/
├── cao_bridge.py          # 主 Bridge 逻辑（get_task, report_score, submit_report,
│                          #   fetch_feedbacks, init_session, close_session 等）
├── cao_bridge_mcp.py      # MCP 集成（16 个工具，含 cao_submit_report /
│                          #   cao_fetch_feedbacks / cao_session_info）
├── session_manager.py     # Session 隔离管理（create/touch/deactivate/cleanup）
├── report_registry.py     # 本地 registry.json 的 flock 读写（§6.4）
├── git_sync.py            # Git 同步工具（session-aware, _ensure_local_excludes）
├── cao-session-mgr.sh     # Session 管理 CLI（create/list/cleanup/info）
├── skill/                 # Skill Bridge（SKILL.md 指导式）
├── plugin/                # Plugin Bridge（OpenCode, Copilot）
├── claude-code/           # Claude Code 适配
└── hermes/         # Hermes 适配
```

| Bridge | 入口文件 | Grader 触发方式 | 心跳处理方式 |
|--------|----------|----------------|-------------|
| **MCP Bridge** | `cao_bridge_mcp.py` (16 工具) | Agent 手动 `cao_get_task` -> 加载 grader skill | ScoreResponse 中的心跳 -> Agent 直接处理 |
| **Skill Bridge** | `skill/cao-bridge/SKILL.md` | Step 4: "cao_get_task → 加载 grader skill" | Step 4.5: "检查 heartbeat prompts" |
| **Plugin Bridge** | `opencode/plugin/cao-bridge.ts` | 自动: session.idle → getTaskInfo → 注入 grader prompt → 提取 CAO_SCORE | Plugin 自动注入 heartbeat prompts |
| **Claude Code** | `claude-code/CLAUDE.md` | 同 MCP Bridge（CLAUDE.md 列出 cao_get_task） | Hooks + MCP 配置 |
| **Hermes** | `hermes/__init__.py` | on_end() → get_task → 排队 grader prompt → pre_llm 注入 | on_session_end push → score report → pre_llm 注入 |

---

## 8. 知识系统 — Note 与 Skill 的完整生命周期

### 8.1 Note 生命周期

**核心设计：Note 是只追加（append-only）的知识沉淀。Agent 产生，Hub 存储，其它 Agent 消费。**

#### 8.1.1 Note 的产生

Note **由 Remote Agent 端侧产生**，通过 git push 写入 Hub：

```
Agent 本地写入 + git push（唯一写入路径）

  Agent 完成反思/整合/转向
    │
    ▼
  在 <session_dir>/notes/ 下创建 .md 文件
    │  → 格式: YAML frontmatter + Markdown 正文
    │  → 调用 cao_push (MCP) 或手动 git add && git commit && git push
    ▼
  Hub 侧 checkpoint() → _sync_remote() → git pull
    │  → 检测 pulled 文件列表
    │  → 触发 on_commit → BM25 索引增量更新
    ▼
  其它 Agent 可通过 API/MCP/git sync 读取
```

> **注意**：Hub 内部（heartbeat 生成笔记、WebUI）仍通过 HTTP POST 写入 notes，
> 但所有 Remote Agent 都通过 git push。`cao_share_note` MCP 工具已移除。

#### 8.1.2 Note 的消费（读取路径）

| 消费方式 | 入口 | 适用场景 |
|----------|------|----------|
| `cao_search_knowledge(q, tags)` | 文本 + tag 过滤 | 快速查找相关知识 |
| `cao_recall(query, top_k)` | BM25 排序召回 | 精确排序的知识检索 |
| `cao_get_shared_notes(tags)` | 按 tag 列出 | 获取特定类型全部笔记 |
| `cao_fetch_document(doc_id)` | 按 ID 获取 | 获取完整文档内容 |
| Git sync 后本地读取 | `<session_dir>/notes/` | 离线/批量读取 |

#### 8.1.3 Note 的类型与产生时机

不同 evo-skill 在不同进化阶段产生不同类型的 Note：

| evo-skill | 触发时机 | 产生的 Note 类型 | tags 示例 |
|-----------|----------|-----------------|-----------|
| `cao-reflect` | 每次评估后 | **反思笔记** — 分析得失，计划下一步 | `reflection,{task_id}` |
| `cao-consolidate` | 每 5 次全局评估 | **综合笔记** — 跨 Agent 知识整合、矛盾消解 | `synthesis,{task_id}` |
| `cao-pivot` | plateau 触发 | **转向笔记** — 记录旧策略失败原因、新策略方向 | `pivot,{task_id}` |

#### 8.1.4 Note 的数据流方向

```
产生方向:   Remote Agent ──(local write + git push)──▶ Hub (.cao-evolution/notes/)
消费方向:   Hub ──(API/MCP/git sync)──▶ Remote Agent
修改规则:   ⚠ Note 创建后不修改，只追加新 Note
合并机制:   cao-consolidate 读取多条 Note → 产生新的综合 Note（不删除原始 Note）
```

#### 8.1.5 Note 文件结构

```markdown
---
title: "Reflection: SQL injection scan patterns"
tags: [reflection, sec-audit-2025]
origin_task: sec-audit-2025
origin_score: 0.72
confidence: 0.8
created_by: remote-a1b2c3d4
created_at: "2026-04-15T10:30:00Z"
---

## 发现
1. String concatenation in Java DAO layer is the primary pattern
2. Parameterized queries already used in 70% of endpoints

## 失败模式
- False positive on ORM-generated queries (deducted -0.15)

## 下一步
- Focus on legacy DAO classes in src/legacy/
```

### 8.2 Skill 生命周期

Skill 有两种存在形式，生命周期不同：

#### 8.2.1 共享 Skill（Hub 知识库中的 Skill）

**产生路径：**

```
Agent 发现可复用技巧/工具
  │
  ▼
本地写入 <session_dir>/skills/{name}/SKILL.md
  │  → YAML frontmatter + 技能正文
  │  → 调用 cao_push (MCP) 或手动 git add && git commit && git push
  ▼
Hub 侧 checkpoint() → _sync_remote() → git pull
  │  → 检测 pulled 文件列表
  │  → 触发 on_commit → BM25 索引更新
  ▼
其它 Agent 通过以下方式获取:
  ├─ cao_get_shared_skills()      → 列出所有共享技能
  ├─ cao_search_knowledge(q)      → 搜索匹配的技能
  ├─ cao_recall(query)            → BM25 排序召回
  ├─ cao_sync() + cao_pull_skills() → git pull 后拷贝到本地技能目录
  └─ 本地读取 <session_dir>/skills/{name}/SKILL.md
```

> **注意**：`cao_share_skill` MCP 工具已移除。Hub 内部仍可通过 HTTP POST 创建 skill。

#### 8.2.2 Skill 自动收编（Auto-Adopt）

非 `cao-` 前缀的本地 skill 默认不参与共享同步。`push_repo()` 在每次 push 前
自动调用 `_auto_adopt_skills()`，将符合条件的本地 skill 复制一份并加上 `cao-` 前缀，
使其进入共享管线：

```
cao_push / push_repo()
  │
  ├─ _auto_adopt_skills(local_dir)
  │    遍历 local_dir 下的非 cao- 目录
  │    ├─ 跳过: 无 SKILL.md、已有 cao- 前缀、本地已存在 cao-X、clone 已存在 cao-X
  │    └─ 复制: my-scanner/ → cao-my-scanner/（原始保留不动）
  │
  ├─ import_local_skills(local_dir)  ← cao-* 镜像到 git clone
  │
  └─ git push
```

也可通过 `cao_adopt_skill` MCP 工具显式收编，支持自定义名称。

#### 8.2.3 Evo-Skill（进化技能，`evo-skills/` 目录）

Evo-skill 是预定义的进化指令集，由 `secskill-evo` 负责在 Agent 端侧进化：

```
secskill-evo 触发（plateau 检测）
  │
  ▼
Step 1: 创建隔离工作区
  │  → /tmp/cao-evo-workspace/{skill-name}/
  │  → 快照当前 skill: cp -r <skill-path> <workspace>/skill-snapshot/
  │
  ▼
Step 2-5: 在工作区中迭代改进
  │  → 基准测试 → 修改 → 评估 → 比较
  │  → 使用 LLM-as-Judge（agents/judge.md）或人工评审
  │
  ▼
Step 6: 提交进化结果（如果有提升）
  │  → 拷贝进化后的 skill 回技能目录
  │  → 通过 cao_sync MCP 工具或 git push 到 session 目录
  │  → 或调用 cao_sync() MCP 工具
  │
  ▼
Step 7: 继续主任务，cao_report_score → 闭环
```

**Evo-Skill 与共享 Skill 的区别：**

| 维度 | Evo-Skill (`evo-skills/`) | 共享 Skill (`skills/`) |
|------|--------------------------|----------------------|
| **存储位置** | 项目仓库 `evo-skills/` 目录 | Hub `.cao-evolution/skills/` |
| **创建方式** | 开发者预定义 | Agent 通过 API 创建 |
| **进化方式** | `secskill-evo` 在隔离工作区迭代 | 创建新版本覆盖旧版本 |
| **分发方式** | 项目仓库 clone / 心跳 prompt 引用 | Hub API / git sync |
| **用途** | 指导 Agent 执行进化操作 | 可复用的知识片段/工具 |

### 8.3 知识消费在进化循环中的位置

```
                     ┌──────── 产生 Note ────────┐
                     │                           │
  ┌─────┐     ┌──────────┐     ┌──────────┐     │
  │ 评估 │────▶│  reflect  │────▶│ 写 Note  │─────┘
  └──┬──┘     └──────────┘     └──────────┘
     │
     │ 5 次全局
     ▼
  ┌──────────────┐     ┌────────────────┐     ┌──────────┐
  │ consolidate  │────▶│ 读取所有 Notes │────▶│ 写综合    │
  └──────────────┘     └────────────────┘     │ Note     │
                                               └──────────┘
     │ plateau
     ▼
  ┌──────────┐     ┌────────────────┐     ┌──────────┐
  │  pivot   │────▶│ 读取历史 Notes │────▶│ 写 Pivot │
  └──────────┘     │ + 分数数据     │     │ Note     │
                   └────────────────┘     └──────────┘
     │ plateau
     ▼
  ┌──────────────┐     ┌────────────────────┐
  │ evolve_skill │────▶│ 在工作区中修改 Skill│
  └──────────────┘     │ → git push 回 Hub  │
                       └────────────────────┘
```

### 8.4 API / MCP 工具映射

| 操作 | REST API | Hub MCP | Bridge MCP |
|------|----------|---------|------------|
| 写 Note | `POST /evolution/knowledge/notes` (Hub内部) | — | — (本地 git write + `cao_push`) |
| 列 Notes | `GET /evolution/knowledge/notes` | `cao_get_shared_notes` | — (通过 Hub MCP) |
| 写 Skill | `POST /evolution/knowledge/skills` (Hub内部) | — | — (本地 git write + `cao_push`) |
| 列 Skills | `GET /evolution/knowledge/skills` | `cao_get_shared_skills` | — (通过 Hub MCP) |
| 搜索知识 | `GET /evolution/knowledge/search` | `cao_search_knowledge` | `cao_search_knowledge` |
| BM25 召回 | `GET /evolution/knowledge/recall` | `cao_recall` | `cao_recall` |
| 获取文档 | `GET /evolution/knowledge/recall/{doc_id}` | `cao_fetch_document` | `cao_fetch_document` |
| Git 推送 | — (git 操作) | — | `cao_push` |
| 拉取 Skills | — (git 操作) | — | `cao_pull_skills` |

---

## 9. Git 同步架构

### 9.1 Session 隔离

多个 Remote Agent 实例可在同一台机器上并发运行。每个实例拥有独立的 session 目录，
避免 git 操作竞态和文件覆盖：

```
~/.cao-evolution-client/
├── sessions/
│   ├── 20260416T103000-a3f2b1c8/     ← session A（active）
│   │   ├── .git/                      ← 独立 git clone
│   │   ├── .session.json              ← 元数据（status, last_update, pid）
│   │   ├── skills/ notes/ tasks/ attempts/ graders/
│   │   └── reports/                   ← 本地运行时状态（不入 git）
│   │       └── registry.json
│   ├── 20260416T110500-d4e5f6a7/     ← session B（active）
│   └── 20260415T090000-b2c3d4e5/     ← session C（inactive，待清理）
└── .base.json                         ← 全局配置（预留）
```

**Session 生命周期：**

```
创建 ──→ active ──→ inactive ──→ 清理删除
 │                    │              │
 │  bridge/plugin     │  bridge/     │  cao-session-mgr
 │  init_session()    │  close_      │  cleanup
 │  (git clone)       │  session()   │  (max_age + pid 检测)
```

**管理命令：**

```bash
cao-session-mgr create --git-remote <url>    # 创建新 session
cao-session-mgr list [--status active]       # 列出 session
cao-session-mgr cleanup [--max-age 24]       # 清理过期 inactive session
cao-session-mgr info <session_id>            # 查看 session 详情
```

### 9.2 Hub ↔ Agent 同步

```
Hub 侧                                    Agent 侧（每个 session 独立）
┌───────────────────────────┐              ┌──────────────────────────────────┐
│ .cao-evolution/           │   git sync   │ ~/.cao-evolution-client/sessions │
│ (主仓库，扁平目录)         │◀────────────▶│ /<session_id>/                   │
│                           │              │                                  │
│ ├── tasks/{task_id}/      │  git_sync.py │ ├── tasks/                       │
│ │   └── task.yaml         │  push / pull │ ├── skills/                      │
│ ├── attempts/{task_id}/   │              │ ├── notes/                       │
│ │   └── {run_id}.json     │              │ │   └── _synthesis/              │
│ ├── skills/               │              │ ├── attempts/                    │
│ ├── notes/                │              │ ├── graders/                     │
│ │   └── _synthesis/       │              │ └── reports/  (gitignored)       │
│ ├── graders/              │              │                                  │
│ ├── reports/              │              └──────────────────────────────────┘
│ └── heartbeat/            │
│     (gitignored)          │
└───────────────────────────┘
```

**实际目录结构**（由 `checkpoint.py` 行 23 `_SUBDIRS` 定义）：

```python
_SUBDIRS = ["tasks", "skills", "notes", "notes/_synthesis",
            "attempts", "graders", "reports"]
```

**关键机制：**

- **Session 隔离**: 每个 Agent 实例在 `sessions/<session_id>/` 下拥有独立 git clone
- **扁平布局**: 无 `shared/` 中间层，所有子目录直接位于 session 目录下
- **Checkpoint**: 每次 `submit_score` 调用时自动执行 `git add -A && git commit`
- **并发安全**: Hub 侧 `checkpoint.py` 使用 `fcntl.flock()` 文件锁；Agent 侧通过 session 隔离避免竞态
- **目录初始化**: `session_manager.create_session()` 创建 session 目录 + git clone + 子目录结构
- **远端同步**: `_setup_remote()` (行 185) + `_sync_remote()` (行 200) — pull(rebase) then push
- **历史查询**: `checkpoint_history()` (行 177) 获取最近提交记录
- **Agent 侧**: `git_sync.py` 通过 `client_dir()` 自动定位当前 session 目录
- **Session 清理**: `cao-session-mgr cleanup` 移除过期 inactive session，标记 stale active session

---

## 10. MCP 工具完整列表

### 10.1 Hub 侧工具（`mcp_server/evolution_tools.py`，12 个工具）

| 类别 | 工具名 | 说明 |
|------|--------|------|
| **分数** | `cao_report_score` | 提交评估分数（触发完整调用链） |
| **排行榜** | `cao_get_leaderboard` | 获取 Top N |
| **知识** | `cao_search_knowledge` | 搜索 notes + skills |
| | `cao_get_shared_notes` | 获取笔记 |
| | `cao_get_shared_skills` | 获取技能 |
| **报告** | `cao_submit_report` | 提交漏洞报告 |
| | `cao_fetch_feedback` | 获取人类标注 |
| | `cao_list_reports` | 列出报告 |
| **任务** | `cao_create_task` | 创建/更新任务（含 grader_skill） |
| | `cao_list_tasks` | 列出所有任务 |
| **召回** | `cao_recall` | BM25 排序知识召回 |
| | `cao_fetch_document` | 按 ID 获取完整文档内容 |

> **已移除**：`cao_share_note`、`cao_share_skill`（Agent 通过 git push 写入知识）

### 10.2 Bridge 侧工具（`cao_bridge_mcp.py`，17 个工具）

Agent 端通过 Bridge MCP 访问 Hub，以下为 Agent 可调用的工具：

| 类别 | 工具名 | 说明 |
|------|--------|------|
| **注册** | `cao_register` | 向 Hub 注册为远程 Agent |
| **轮询** | `cao_poll` | 轮询待处理任务 |
| **状态** | `cao_report` | 上报执行状态/输出 |
| **任务** | `cao_create_task` | 创建任务（支持 grader_skill） |
| | `cao_get_task` | 获取任务详情（含 grader_skill 引用） |
| | `cao_list_tasks` | 列出所有任务 |
| **分数** | `cao_report_score` | 提交分数 → 触发心跳 |
| **排行榜** | `cao_get_leaderboard` | 查看排名 |
| **知识** | `cao_search_knowledge` | 搜索知识 |
| **召回** | `cao_recall` | BM25 排序知识召回 |
| | `cao_fetch_document` | 按 ID 获取完整文档 |
| **报告** | `cao_submit_report` | 上报疑点 → 返回 report_id 并登记到本地 registry（§6.4） |
| | `cao_fetch_feedbacks` | 轮询 registry 里的 pending，拉标注并渲染 `evolve_from_feedback.md`（§6.4） |
| **同步** | `cao_sync` | 双向同步（先 push 再 pull） |
| | `cao_push` | 本地变更提交并 push 到 Hub |
| | `cao_pull_skills` | 拷贝共享 skills 到本地 |
| | `cao_adopt_skill` | 收编本地 skill 到共享管线（加 cao- 前缀） |
| **Session** | `cao_session_info` | 查看当前 session 元数据（session_id, 目录, 状态） |

> **已移除**：`cao_share_note`、`cao_share_skill`（改用 local write + `cao_push`）

---

## 11. 添加新的进化策略

### 分步指南

**Step 1 — 创建 evo-skill：**

```bash
mkdir -p evo-skills/my-new-evo/
# 编写 SKILL.md，参考 evo-skills/secskill-evo/SKILL.md 的结构
```

**Step 2 — 创建 Hub 侧分发模板：**

```bash
# 在 src/cli_agent_orchestrator/evolution/prompts/ 下创建
cat > evolution/prompts/my_new_evo.md << 'EOF'
# My New Evo — {task_id}

Agent: {agent_id}
Evals since improvement: {evals_since_improvement}

## 指令
加载并执行 evo-skills/my-new-evo/SKILL.md

## 上下文
{evolution_signals_json}

## 排行榜
{leaderboard}
EOF
```

**Step 3 — 注册到 DEFAULT_PROMPTS：**

```python
# heartbeat.py 行 26 附近
DEFAULT_PROMPTS = {
    "reflect": _load_prompt("reflect"),
    "consolidate": _load_prompt("consolidate"),
    "pivot": _load_prompt("pivot"),
    "evolve_skill": _load_prompt("evolve_skill"),
    "feedback_reflect": _load_prompt("feedback_reflect"),
    "my_new_evo": _load_prompt("my_new_evo"),  # ← 新增
}
```

**Step 4 — 添加触发条件：**

```python
# 在 HeartbeatRunner 的默认 actions 中添加（行 105-112 附近）
# 或在 check_triggers() 中添加自定义逻辑
HeartbeatAction(
    name="my_new_evo",
    every=4,          # 触发阈值
    mode="plateau",   # interval 或 plateau
    scope="local",    # local 或 global
)
```

**Step 5 — 编写测试：**

```bash
# 在 test/evolution/ 下添加测试
# 验证: 触发条件、prompt 渲染、占位符替换
```

---

## 12. 关键配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `EVO_PLATEAU_THRESHOLD` | `3` | evolve_skill 触发前需要的连续无提升次数 |
| Pivot plateau threshold | `5` | pivot 触发的 plateau 阈值 |
| Consolidate interval | `5` | consolidate 的全局评估间隔 |
| `.cao-evolution/` | — | Hub 数据目录 |
| `.cao-evolution-client/sessions/` | — | Agent 侧 session 目录（每实例独立 git clone） |
| `CAO_CLIENT_BASE_DIR` | `~/.cao-evolution-client` | Session 根目录覆盖 |
| `CAO_CLIENT_DIR` | — | 完整覆盖 session 目录（跳过 session_manager，向后兼容） |
| `heartbeat/*.json` | gitignored | Agent 心跳状态（不跨 Agent 共享） |

---

## 13. 调试技巧

### 查看触发历史

```bash
# 查看某 task 的所有 attempt
ls .cao-evolution/attempts/{task_id}/
cat .cao-evolution/attempts/{task_id}/{run_id}.json | python -m json.tool

# 查看 git checkpoint 历史
cd .cao-evolution && git log --oneline -20
```

### 手动测试触发

```bash
# 连续提交相同分数 3 次，应触发 evolve_skill
curl -X POST http://localhost:9889/evolution/{task_id}/scores \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "test-agent", "score": 0.5}'
# 第 3 次响应中 heartbeat_prompts 应非空
```

### 检查 prompt 渲染结果

```python
from cli_agent_orchestrator.evolution.heartbeat import render_prompt
prompt = render_prompt("evolve_skill", "agent-1", "task-1",
                       leaderboard="...", evolution_signals_json="{}",
                       evals_since_improvement=3)
print(prompt)
```

---

## 快速参考：核心文件索引

| 文件 | 关键函数 / 行号 |
|------|-----------------|
| `api/evolution_routes.py` | `create_task()` 行 181, `get_task()` 行 236, `submit_score()` 行 261 — 主入口 |
| `api/evolution_routes.py` | `recall_knowledge()` 行 701, `get_knowledge_document()` 行 731, `rebuild_recall_index()` 行 754 |
| `evolution/attempts.py` | `write_attempt()` 行 22, `compare_to_history()` 行 51, `count_evals_since_improvement()` 行 77, `get_leaderboard()` 行 67, `get_best_score()` 行 42 |
| `evolution/recall_index.py` | `RecallIndex.build()` 行 179, `query()` 行 241, `update_incremental()` 行 195, `tokenize()` 行 67 |
| `evolution/heartbeat.py` | `_load_prompt()` 行 21, `DEFAULT_PROMPTS` 行 26, `HeartbeatRunner.check()` 行 53, `_check_plateau()` 行 71, `render_prompt()` 行 136, `check_triggers()` 行 152 |
| `evolution/checkpoint.py` | `init_checkpoint_repo()` 行 31, `checkpoint()` 行 96 (含 on_commit 回调), `checkpoint_history()` 行 177, `fcntl.flock()` 行 120 |
| `mcp_server/evolution_tools.py` | Hub 侧 12 工具: `cao_report_score()`, `cao_recall()`, `cao_fetch_document()`, `cao_create_task()` 等 |
| `cao-bridge/cao_bridge.py` | `get_task()` ~行 227, `create_task()` ~行 209, `report_score()`, `init_session()`, `close_session()` |
| `cao-bridge/cao_bridge_mcp.py` | Bridge 侧 16 工具: `cao_get_task`, `cao_create_task`, `cao_push`, `cao_recall`, `cao_session_info` 等 |
| `cao-bridge/session_manager.py` | `create_session()`, `deactivate_session()`, `cleanup_sessions()`, `touch_session()` |
| `cao-bridge/opencode/plugin/cao-bridge.ts` | OpenCode Plugin: session.idle → 二阶段 grader 流程 |
