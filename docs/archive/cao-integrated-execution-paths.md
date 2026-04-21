# CAO + CORAL 集成系统：远程进化与同步 执行路径

> **核心视角**：进化完全在远程 Agent 侧发生，Hub 仅做同步中心。
> 不涉及 CAO 本地 Agent 的进化，不需要 handoff/assign 进化场景，Agent 不写代码不需要 worktree。
> 远程 Agent 有三个控制点：Plugin、MCP、Skill。
> **双层数据模型**：任务维度（分数跟 task_id 走）+ 知识维度（notes/skills 独立于任务，带标签，支持跨任务召回）。
> **知识召回两阶段**：MVP 用 git+grep；知识膨胀后切换 memsearch 语义搜索（接口不变）。
> **hermes 融合**：通过 external_dirs + 同步脚本零代码接入。

---

## 一、架构总览

### 1.1 角色分工

```
┌──────────────────────────────────────────────────────────────────────┐
│  Remote Agent (opencode / claude code / codex / copilot)             │
│  ─────────────────────────────────────────────────────────────       │
│  ★ 进化主体 — 所有进化活动在此发生                                    │
│  ★ 三个控制点: Plugin(自动) / MCP(工具调用) / Skill(提示词引导)        │
│                                                                      │
│  负责:                                                               │
│   - 执行任务                                                         │
│   - 本地运行 Grader 评估（grader.py 从 git 同步获取）                  │
│   - 上报分数到 Hub（获得 improved/regressed 状态反馈）                 │
│   - 拉取共享知识（开始执行前）                                         │
│   - 写入笔记/技能（进化沉淀）                                         │
│   - 接收并执行心跳 prompt（reflect/consolidate/pivot）                 │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ HTTP
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  CAO Hub (:9889)                                                     │
│  ─────────────────────────────────────────────────────────────       │
│  ★ 同步中心 — 不做进化计算，只存储和分发                                │
│                                                                      │
│  负责:                                                               │
│   - 接收 & 存储分数 (attempts JSON → git checkpoint)                 │
│   - 比较历史 → 确定 status (improved/baseline/regressed)             │
│   - 检查心跳触发 → 通过 inbox 下发 prompt                             │
│   - 存储 & 分发共享知识 (notes, skills)                               │
│   - 提供排行榜查询（按 task_id 分区）                                 │
│   - 管理 grader.py（纳入 git 版本管理，远程 Agent 可拉取）             │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.2 新增模块（最小改动原则）

```
security-agent-orchestrator/
│
├── src/cli_agent_orchestrator/
│   │
│   ├── evolution/                   # ★ 新增独立包（从 CORAL 移植，不改已有代码）
│   │   ├── __init__.py
│   │   ├── types.py                 # 移植 coral/types.py → Score, ScoreBundle, Attempt
│   │   ├── checkpoint.py            # 移植 coral/hub/checkpoint.py → git + flock
│   │   ├── attempts.py              # 移植 coral/hub/attempts.py → JSON CRUD + leaderboard
│   │   ├── notes.py                 # 移植 coral/hub/notes.py → Markdown + YAML frontmatter
│   │   ├── skills.py                # 移植 coral/hub/skills.py → SKILL.md 管理
│   │   ├── heartbeat.py             # 合并 coral/agent/heartbeat.py + hub/heartbeat.py
│   │   ├── grader_base.py           # 移植 coral/grader/task_grader.py（远程侧也用）
│   │   ├── recall_index.py          # ★ BM25 + 元数据精排（recall 发现层）
│   │   └── repo_manager.py          # ★ 路径抽象层（单仓/多仓兼容）
│   │
│   ├── api/main.py                  # 追加 ~100 行 /evolution/* 路由（不改已有路由）
│   └── constants.py                 # 追加 ~10 行常量
│
├── cao-bridge/
│   ├── plugin/cao-bridge.ts         # 追加进化上报（~30 行）
│   ├── cao_bridge.py                # 追加进化 HTTP 方法（~20 行）
│   ├── cao_bridge_mcp.py            # 追加进化 MCP 工具（~40 行）
│   └── skill/cao-bridge/SKILL.md    # 追加进化协议说明
│
├── prompts/                         # ★ 新增（3 个 Markdown 文件，从 CORAL 复制）
│   ├── reflect.md
│   ├── consolidate.md
│   └── pivot.md
│
└── .cao-evolution/                  # ★ 运行时创建（Hub 侧）
    ├── shared/                      # ← 独立 git repo（同步中心，未来拆多仓）
    │   ├── .git/
    │   ├── tasks/                   # 任务维度（分数跟任务走）
    │   │   └── {task_id}/
    │   │       ├── task.yaml        # { name, description, grader: "security/sql-grader.py" }
    │   │       ├── attempts/{run_id}.json
    │   │       └── heartbeat.json   # 该任务的心跳计数器
    │   ├── graders/                 # ★ 评分脚本（可复用、可进化，未来独立仓）
    │   │   ├── security/sql-grader.py
    │   │   └── general/code-quality-grader.py
    │   └── knowledge/               # 知识维度（独立于任务，带标签）
    │       ├── notes/*.md           # YAML frontmatter: tags, origin_task, confidence
    │       ├── skills/{name}/SKILL.md
    │       ├── _synthesis/*.md      # consolidate 产出
    │       └── _connections.md      # 跨领域关联
    └── heartbeat/
        ├── _global.json
        └── {agent_id}.json
```

**对 CAO 已有代码的改动量**：仅 `api/main.py` 追加路由 + `constants.py` 追加常量。其余全部是新增独立文件。

### 1.3 数据类型（移植自 CORAL types.py，精简版）

```python
@dataclass
class Score:
    value: float | None
    name: str
    explanation: str | None = None

@dataclass
class ScoreBundle:
    scores: dict[str, Score]
    aggregated: float | None = None
    feedback: str | None = None

@dataclass
class Attempt:
    run_id: str               # UUID
    agent_id: str             # terminal_id
    task_id: str              # ★ 任务分区键
    title: str                # 描述
    score: float | None
    status: str               # improved | baseline | regressed | crashed | timeout
    timestamp: str            # ISO 8601
    feedback: str = ""
    shared_state_hash: str | None = None   # checkpoint 时的 git SHA
    score_detail: dict[str, float] | None = None  # ★ 多维评分（预留接口）
```

**`score_detail` 多维评分说明**：
- Grader 可返回多个维度的分数（如 `{"accuracy": 0.9, "speed": 0.7, "coverage": 0.85}`）
- `score` 字段保持为聚合后的单一分数，用于排行榜排序
- `score_detail` 存储各维度原始分数，供未来按维度分析、排序使用
- 通过 `POST /evolution/{task_id}/scores` 的 `score_detail` 字段上报
- 当前排行榜按 `score` 排序；未来可扩展为按任意维度排序

---


## 二、远程进化完整执行路径

### 路径 1：远程 Agent 启动 → 拉取共享知识 → 接收任务

```
远程机器: opencode 启动（装有 plugin 或配置了 MCP）
    │
    │  ===== 注册 =====
    ▼
Plugin/MCP: POST /remotes/register { agent_profile: "remote-opencode" }
    → Hub 创建 RemoteProvider(terminal_id=xyz789)
    → 返回 { terminal_id: "xyz789" }
    │
    │  ===== 拉取共享知识（执行前同步） =====
    ▼
MCP 工具调用 / Plugin 自动:
    GET /evolution/knowledge/notes?tags=security  → 按标签召回相关知识
    GET /evolution/knowledge/skills               → 获取共享技能
    GET /evolution/{task_id}/leaderboard           → 获取同任务排行榜（如有历史）
    │
    ├─ Hub 侧处理:
    │   notes.search_notes(knowledge_dir, tags=["security"])
    │     → glob .cao-evolution/shared/knowledge/notes/*.md
    │     → 解析 YAML frontmatter，按 tags 过滤
    │     → 返回 [{ title, body, tags, origin_task, confidence, creator, date }]
    │
    │   skills.list_skills(knowledge_dir)
    │     → glob .cao-evolution/shared/knowledge/skills/*/SKILL.md
    │     → 返回 [{ name, description, tags, creator }]
    │
    │   attempts.get_leaderboard(tasks_dir / task_id)
    │     → 读取所有 tasks/{task_id}/attempts/*.json → 按 score 排序 → 返回 top N
    │
    └─ 远程 Agent 获得背景知识，准备开始工作
    │
    │  ===== 接收任务 =====
    ▼
Plugin 轮询: GET /remotes/xyz789/poll
    │
    ├─ Hub 侧:
    │   1. 检查 provider._pending_input
    │   2. 若空 → 检查 inbox 有无 pending 消息
    │   3. consume_pending_input() → 返回任务
    │
    └─ 返回 { has_input: true, input: "任务内容..." }
    │
    ▼
Plugin 注入到 Agent TUI:
    client.tui.appendPrompt(input)
    client.tui.submitPrompt()
```

---

### 路径 2：远程 Agent 完成任务 → 本地评估 → 上报分数

这是进化循环的核心路径，**全部在远程侧发起**：

```
远程 Agent 执行任务完毕
    │
    │  ===== 阶段 A：本地 Grader 评估 =====
    ▼
远程 Agent / Bridge:
    Grader 来源：.cao-evolution/shared/tasks/{task_id}/grader.py
    （通过 git pull 同步到本地，或首次通过 GET /evolution/{task_id}/grader 拉取）
    │
    ▼
远程侧加载 Grader:
    ├─ import grader.py → 实例化 Grader(config)
    ├─ grader.codebase_path = Agent 工作目录（如果需要）
    │
    ▼
远程侧执行评估:
    bundle = grader.evaluate()
    │
    ├─ TaskGrader 基类方法:
    │   ├─ self.score(0.91, "完成度 91%")     → 快捷返回
    │   ├─ self.fail("执行超时")               → 失败返回
    │   └─ self.run_script("...")              → 运行评估脚本
    │
    └─ 返回: ScoreBundle(aggregated=0.91)
    │
    │  ===== 阶段 B：上报分数到 Hub =====
    ▼
远程 Bridge (三种方式均可):

  ┌─ Plugin: 自动在 session.idle 事件后调用
  │   POST /evolution/{task_id}/scores
  │
  ├─ MCP: Agent 主动调用 MCP 工具
  │   cao_report_score(task_id, message="...", score=0.91)
  │
  └─ Skill: Agent 按 SKILL.md 指引，调用 MCP 工具
      "根据协议，我需要上报分数..."
    │
    ▼
Hub 接收并处理 (api/main.py → evolution_submit_score):
    │
    ├─ 1. 比较历史最佳（同 task_id 内）
    │     prev = attempts.get_agent_attempts(tasks_dir / task_id, "xyz789")
    │     prev_best = max(a.score for a in prev if a.score is not None)
    │     ├─ score > prev_best → status = "improved"
    │     ├─ score == prev_best → status = "baseline"
    │     └─ score < prev_best → status = "regressed"
    │
    ├─ 2. 创建 Attempt
    │     attempt = Attempt(run_id=uuid4(), agent_id="xyz789",
    │       task_id=task_id, title=message, score=0.91, status="improved", ...)
    │
    ├─ 3. 写入 JSON
    │     attempts.write_attempt(tasks_dir / task_id, attempt)
    │       → .cao-evolution/shared/tasks/{task_id}/attempts/{run_id}.json
    │
    ├─ 4. Git Checkpoint
    │     checkpoint.checkpoint(dir, "xyz789", message)
    │       ├─ fcntl.flock(LOCK_EX)          # 文件锁
    │       ├─ git add -A
    │       ├─ git commit -m "checkpoint: xyz789 - ..."
    │       ├─ git rev-parse HEAD → shared_state_hash
    │       └─ 解锁
    │
    ├─ 5. 检查心跳触发
    │     (详见路径 3)
    │
    └─ 6. 返回给远程:
          {
            "attempt": { run_id, score, status, feedback },
            "leaderboard_position": 2,
            "heartbeat_triggered": ["reflect"]
          }
```

### 三个控制点的分工

```
┌─────────────────────────────────────────────────────────────────────┐
│                 三种远程控制点对比                                     │
├────────────┬──────────────┬──────────────┬──────────────────────────┤
│            │ Plugin       │ MCP          │ Skill                    │
│            │ (自动化)      │ (工具调用)    │ (提示词引导)              │
├────────────┼──────────────┼──────────────┼──────────────────────────┤
│ 注册       │ 自动         │ cao_register │ Agent 按指引调 MCP        │
│ 接收任务   │ poll+inject  │ cao_poll     │ Agent 按指引调 MCP        │
│ 上报结果   │ 自动(idle时)  │ cao_report   │ Agent 按指引调 MCP        │
│ 评估+上报  │ ★可自动触发   │ cao_report_  │ Agent 按指引调 MCP        │
│  分数      │  reportScore │  score       │                          │
│ 拉取知识   │ ★可自动触发   │ cao_get_     │ Agent 按指引调 MCP        │
│            │              │  shared_notes│                          │
│ 写入笔记   │ ─            │ cao_share_   │ Agent 按指引调 MCP        │
│            │              │  note        │                          │
│ 心跳接收   │ ★自动注入    │ poll 自动获取│ poll 自动获取             │
│            │(HEARTBEAT=1) │              │                          │
├────────────┼──────────────┼──────────────┼──────────────────────────┤
│ 适用场景   │ 全自动进化    │ Agent 有     │ Agent 无 MCP 但能        │
│            │ 无需 Agent   │ MCP 支持时   │ 读取 SKILL.md 时         │
│            │ 主动参与      │              │                          │
└────────────┴──────────────┴──────────────┴──────────────────────────┘
```

---

### 路径 3：心跳检测 → Prompt 注入（Hub 触发，远程执行）

心跳是在 Hub 侧的 `submit_score()` 处理中**同步触发**的（不是独立轮询）：

```
远程 Agent 上报分数
    │
    ▼
Hub: evolution_submit_score() 处理完 attempt 后...
    │
    ▼
heartbeat.check_triggers(agent_id, task_id, evolution_dir):
    │
    ├─ 1. 加载配置
    │     agent_config = .cao-evolution/heartbeat/{agent_id}.json
    │     global_config = .cao-evolution/heartbeat/_global.json
    │     → 合并 actions 列表
    │
    ├─ 2. 计算计数器（从 attempt 文件派生，无状态）
    │     agent_attempts = get_agent_attempts(tasks_dir / task_id, agent_id)
    │     eval_count = len(agent_attempts)                    # 此任务的评估次数
    │     all_agent_tasks = count_completed_tasks(agent_id)   # Agent 已完成的任务总数
    │     evals_since_improvement = 从末尾数连续非 "improved" 的次数
    │
    ├─ 3. HeartbeatRunner.check()
    │     对每个 action:
    │     │
    │     ├─ interval 类型:
    │     │   eval_count/all_agent_tasks % action.every == 0 → 触发
    │     │   例: reflect(every=1) → 每次上报后都触发
    │     │   例: consolidate(every=5, use_task_count=true) → 每完成 5 个任务后
    │     │
    │     └─ plateau 类型:
    │         evals_since_improvement >= action.every → 触发（仅同 task 多次执行时有意义）
    │         + cooldown 防止重复触发
    │         例: pivot(every=5) → 连续 5 次无提升（同 task 少时几乎不触发）
    │
    ├─ 4. 渲染 Prompt 模板
    │     prompt = prompts/reflect.md
    │       .replace("{agent_id}", "xyz789")
    │       .replace("{task_id}", task_id)
    │       .replace("{leaderboard}", format_leaderboard(...))
    │
    └─ 5. 返回触发信息（含完整 prompt）到 ScoreResponse
          ScoreResponse {
            heartbeat_triggered: ["reflect"],           # 触发名称列表
            heartbeat_prompts: [                         # ★ 完整 prompt 内容
              { name: "reflect", prompt: "请回顾..." }
            ]
          }
          │
          ├─ 路径 A: Plugin 自动注入（CAO_HEARTBEAT_ENABLED=1）
          │   Plugin 收到 ScoreResponse → 检查 heartbeat_prompts
          │   → 缓存到 pendingHeartbeats 队列
          │   → 在下次 session.idle 时，从队列取出注入 TUI
          │   → Agent 执行反思/综合/转向
          │
          └─ 路径 B: 通过 inbox 下发（默认方式）
              POST /terminals/xyz789/inbox/messages
              Body: { sender: "heartbeat", message: rendered_prompt }
              → 远程 Plugin 下次 poll → inject → Agent 执行
```

**Plugin 心跳环境变量**：
- `CAO_HEARTBEAT_ENABLED=1`：启用后 Plugin 在 `session.idle` 时自动注入心跳 prompt
- 默认关闭（`0`），避免意外打断 Agent 工作流
- Plugin 心跳流程：`reportScore → 检查 heartbeat_prompts → 缓存 → idle 时注入 → Agent 执行`

---

### 路径 4：知识沉淀 → 同步到 Hub → 其他 Agent 拉取

```
远程 Agent A 执行 reflect 后写笔记
    │
    │  === 写入 ===
    ▼
MCP: cao_share_note(title="发现X策略有效", content="### 分析\n...", tags=["security","策略"])
  或 POST /evolution/knowledge/notes
    │
    ▼
Hub 处理:
    ├─ 生成 Markdown 文件 (YAML frontmatter + body):
    │     ---
    │     title: "发现X策略有效"
    │     tags: [security, 策略]
    │     origin_task: "security-audit"
    │     origin_score: 0.91
    │     confidence: high
    │     creator: "xyz789"
    │     created: "2026-04-13T16:00:00Z"
    │     ---
    │     ### 分析
    │     ...
    │
    ├─ 写入 .cao-evolution/shared/knowledge/notes/发现x策略有效.md
    │
    └─ checkpoint(dir, "xyz789", "note: 发现X策略有效")
        → git add -A && git commit
        → 笔记进入 git 历史，可追溯

    │
    │  === 拉取 (另一个远程 Agent B 执行前同步) ===
    ▼
远程 Agent B 开始新任务前:
    MCP: cao_search_knowledge(query="安全扫描策略", tags=["security"], top_k=5)
    或 GET /evolution/knowledge/notes?tags=security
    │
    ▼
Hub 返回:
    [
      { "title": "发现X策略有效", "body": "### 分析\n...",
        "tags": ["security","策略"], "origin_task": "security-audit",
        "confidence": "high", "creator": "xyz789", "date": "..." },
      { "title": "Y方法在Z场景失败", "body": "...",
        "tags": ["security","debugging"], "confidence": "medium", ... }
    ]
    │
    ▼
Agent B 参考相关知识开始工作 → 避免重复已知失败路径

    │
    │  === 技能沉淀 ===
    ▼
MCP: cao_share_skill(name="data-augmentation", content="...", tags=["ml","data"])
    │
    ▼
Hub:
    ├─ 创建 .cao-evolution/shared/knowledge/skills/data-augmentation/SKILL.md
    └─ checkpoint → git commit
```

**同步模型**：
```
远程 Agent A ──上报分数──→ Hub ──→ tasks/{task_id}/attempts/  → git commit  ┐
远程 Agent A ──写入笔记──→ Hub ──→ knowledge/notes/           → git commit  ├─ 同一 git repo
远程 Agent A ──写入技能──→ Hub ──→ knowledge/skills/           → git commit  │
                                ↑                                           │
远程 Agent B ──拉取知识──→ Hub ──→ 按标签/语义搜索 knowledge/  → 返回相关    ┘
远程 Agent B ──拉取排行──→ Hub ──→ tasks/{task_id}/attempts/  → 返回排名
```

**一致性保证**：
- Hub 用 `fcntl.flock` 文件锁保证写入串行化
- 每次写入后 git commit，`shared_state_hash` 记录在 Attempt 中
- 读取时直接读文件系统（git repo 的工作树），无锁
- 并发读写安全：写锁仅在 git add/commit 期间持有（毫秒级）

---

### 路径 5：完整进化循环（多 Agent 同任务场景）

多个远程 Agent 并行进化同一个 task_id：

```
时间 →

Hub (同步中心)              远程 Agent A            远程 Agent B
 │   task_id="sec-audit"     │                       │
 │                           │                       │
 │◄── register ──────────────┤                       │
 │◄── register ──────────────────────────────────────┤
 │                           │                       │
 │◄── search knowledge ──────┤  (搜索 tags=security) │
 │── [] (空) ───────────────►│                       │
 │                           │                       │
 │◄── search knowledge ──────────────────────────────┤
 │── [] ────────────────────────────────────────────►│
 │                           │                       │
 │   (Agent A 获取任务       │   (Agent B 获取任务    │
 │    via poll)               │    via poll)           │
 │                           │                       │
 │                           ├── 执行任务 v1         │
 │                           │                       ├── 执行任务 v1
 │                           │                       │
 │◄── POST /{task}/scores ───┤                       │
 │   score=0.72, "improved"  │                       │
 │   checkpoint → git SHA1   │                       │
 │   heartbeat → reflect     │                       │
 │── reflect prompt ────────►│                       │
 │                           │                       │
 │                           ├── 执行反思             │
 │                           │   写入 knowledge/notes/ │
 │◄── POST /knowledge/notes ─┤  (带 tags)             │
 │   checkpoint → git SHA2   │                       │
 │                           │                       │
 │◄── POST /{task}/scores ───────────────────────────┤
 │   score=0.68, "improved"  │                       │
 │   (B的第一次，所以也是improved)                      │
 │   checkpoint → git SHA3   │                       │
 │   heartbeat → reflect     │                       │
 │── reflect prompt ─────────────────────────────────►│
 │                           │                       │
 │                           │                       ├── 执行反思
 │                           │                       │
 │◄── search knowledge ───────────────────────────────┤
 │── [A的笔记(tags匹配)] ───────────────────────────►│
 │                           │   B 看到 A 的笔记      │
 │                           │   参考 A 的策略改进     │
 │                           │                       │
 │                           ├── 迭代 v2             │
 │                           │                       ├── 迭代 v2（参考A笔记）
 │                           │                       │
 │◄── POST /{task}/scores ───┤                       │
 │   score=0.85, "improved"  │                       │
 │                           │                       │
 │◄── POST /{task}/scores ───────────────────────────┤
 │   score=0.88, "improved"  │                       │
 │                           │                       │
 │  排行榜 (task=sec-audit): │                       │
 │  #1 Agent B: 0.88         │                       │
 │  #2 Agent A: 0.85         │                       │
 │  #3 Agent A: 0.72         │                       │
 │  #4 Agent B: 0.68         │                       │
 │                           │                       │
 │   ... 继续迭代 ...         │                       │
 │                           │                       │
 │  第 10 次全局 eval         │                       │
 │  → consolidate 触发       │                       │
 │── consolidate prompt ────►│                       │
 │   Agent A 综合所有笔记     │                       │
 │   写入 notes/_synthesis/  │                       │
 │                           │                       │
 │  Agent A 连续 5 次未提升   │                       │
 │  → pivot 触发             │                       │
 │── pivot prompt ──────────►│                       │
 │   Agent A 查看排行榜       │                       │
 │   发现 B 的方法更好        │                       │
 │   改变策略方向             │                       │
 ▼                           ▼                       ▼
```

---


## 三、数据流总图

```
    远程 Agent A                    CAO Hub                    远程 Agent B
    ───────────                    ────────                    ───────────
         │                            │                            │
         │── register ───────────────►│◄──────────── register ────┤
         │                            │                            │
         │── search knowledge ───────►│  (按 tags/语义搜索)        │
         │◄── [相关知识] ─────────────┤                            │
         │                            │                            │
  ┌──────┤  (grader.py 已从 git 同步)  │                            │
  │      │                            │                            │
  │ 本地 │                            │                            │
  │ 评估 │                            │                            │
  │      │                            │                            │
  └──────┼── POST /{task}/scores ───►│ compare → status            │
         │◄── {attempt, position} ────┤ checkpoint → tasks/ git    │
         │                            │ heartbeat → check          │
         │                            │   │                        │
         │◄── [heartbeat prompt] ─────┤←──┘(via inbox)             │
         │                            │                            │
         │── POST /knowledge/notes ──►│ checkpoint → knowledge/ git│
         │      (带 tags 元数据)       │                            │
         │                            │◄── search knowledge ───────┤
         │                            ├── [含A笔记(tags匹配)] ───►│
         │                            │                            │
         │                            │                    ┌───────┤
         │                            │                    │ 本地  │
         │                            │                    │ 评估  │
         │                            │                    └───────┤
         │                            │◄── POST /{task}/scores ────┤
         │                            ├── {attempt} ──────────────►│
         │                            │                            │
```

---


## 四、Hub 新增 API 端点

**仅新增以下路由，不改任何已有路由：**

| 方法 | 路径 | 功能 | 调用方 |
|------|------|------|--------|
| POST | `/evolution/tasks` | 注册任务 (task.yaml + grader.py 写入 git) | 管理员 |
| GET | `/evolution/tasks` | 列出所有任务 | WebUI / 管理员 |
| GET | `/evolution/{task_id}` | 获取任务详情 | 远程 Agent |
| GET | `/evolution/{task_id}/grader` | 获取 grader.py 内容 | 远程 Agent (首次拉取) |
| POST | `/evolution/{task_id}/scores` | **上报分数（核心）** | 远程 Agent |
| GET | `/evolution/{task_id}/leaderboard` | 排行榜 | 远程 Agent / WebUI |
| GET | `/evolution/{task_id}/attempts` | 全部评估记录 | WebUI |
| GET | `/evolution/knowledge/notes` | 搜索/获取笔记（支持 tags 过滤） | 远程 Agent / WebUI |
| POST | `/evolution/knowledge/notes` | 写入笔记（带标签元数据） | 远程 Agent |
| GET | `/evolution/knowledge/skills` | 获取共享技能 | 远程 Agent / WebUI |
| POST | `/evolution/knowledge/skills` | 写入技能（带标签元数据） | 远程 Agent |
| GET | `/evolution/knowledge/search` | **知识语义搜索**（阶段 1: grep；阶段 2: memsearch） | 远程 Agent |

**不需要的端点**：
- ~~`POST /evolution/checkpoint`~~ — checkpoint 在 submit_score 中自动触发
- ~~`GET/PUT /evolution/heartbeat/*`~~ — heartbeat 配置直接读写文件即可

### Bridge 端新增 MCP 工具

```
cao_report_score(task_id, message, score, feedback?)         # 上报分数
cao_get_leaderboard(task_id, top_n?)                         # 排行榜
cao_search_knowledge(query, tags?, top_k?)                   # ★ 知识搜索（跨任务）
cao_share_note(title, content, tags?)                        # 写入笔记
cao_share_skill(name, content, tags?)                        # 写入技能
cao_get_shared_notes(tags?)                                  # 获取笔记（按标签）
cao_get_shared_skills()                                      # 获取技能列表
```

---


## 五、存储结构与 Git 同步机制

```
.cao-evolution/
├── shared/                         # ★ 独立 git repo — 进化同步中心
│   ├── .git/
│   │   └── coral.lock              # flock 锁文件
│   │
│   ├── tasks/                      # === 任务维度（分数跟任务走）===
│   │   ├── security-audit/         # task_id = "security-audit"
│   │   │   ├── task.yaml           # { name: "安全审计", description: "..." }
│   │   │   ├── grader.py           # ★ 评估代码（git 版本管理）
│   │   │   ├── heartbeat.json      # 该任务的心跳计数器
│   │   │   └── attempts/           # 每次评估的记录
│   │   │       ├── {run_id_1}.json
│   │   │       └── {run_id_2}.json
│   │   │
│   │   └── doc-review/             # task_id = "doc-review"
│   │       ├── task.yaml
│   │       ├── grader.py
│   │       ├── heartbeat.json
│   │       └── attempts/
│   │
│   └── knowledge/                  # === 知识维度（独立于任务，带标签）===
│       ├── notes/                  # 共享笔记（YAML frontmatter 带标签）
│       │   ├── finding-a.md        #   tags, origin_task, origin_score, confidence
│       │   ├── lesson-b.md
│       │   └── _synthesis/         # consolidate 产出
│       │       └── security-patterns.md
│       ├── skills/                 # 共享技能（YAML frontmatter 带标签）
│       │   └── vuln-scanner/
│       │       └── SKILL.md
│       ├── _connections.md         # 跨领域关联图
│       └── _open-questions.md      # 知识空白清单
│
└── heartbeat/                      # 心跳全局配置（不进 shared git）
    ├── _global.json                # { actions: [{ name, every, trigger }] }
    └── {agent_id}.json
```

**Git checkpoint 逻辑（移植自 CORAL checkpoint.py，~40 行核心代码）：**
```python
def checkpoint(evolution_dir, agent_id, message):
    shared = Path(evolution_dir) / "shared"
    lock = shared / ".git" / "coral.lock"
    lock.touch(exist_ok=True)
    with open(lock) as fd:
        fcntl.flock(fd, fcntl.LOCK_EX)        # 互斥锁
        run(["git", "add", "-A"], cwd=shared)
        # 检查是否有变更
        if run(["git", "diff", "--cached", "--quiet"], cwd=shared).returncode != 0:
            run(["git", "commit", "-m", f"checkpoint: {agent_id} - {message}"], cwd=shared)
            sha = run(["git", "rev-parse", "HEAD"], cwd=shared).stdout.strip()
            _sync_remote(shared)   # ★ 自动推送到远程仓库
            return sha
    return None
```

**Git 远程同步机制（多 Hub / 灾备场景）：**

通过环境变量 `CAO_EVOLUTION_REMOTE` 配置远程仓库 URL，启用后每次 checkpoint 自动推送：

```python
# 环境变量设置
CAO_EVOLUTION_REMOTE=https://github.com/team/evo-shared.git

# 初始化时自动 git remote add origin
def _setup_remote(shared_dir):
    remote_url = os.environ.get("CAO_EVOLUTION_REMOTE", "")
    if remote_url:
        git(shared_dir, "remote", "add", "origin", remote_url)

# 每次 checkpoint 后自动同步
def _sync_remote(shared_dir):
    if not os.environ.get("CAO_EVOLUTION_REMOTE"):
        return
    try:
        git(shared_dir, "pull", "--rebase", "origin", "master")  # 先拉
    except:
        pass  # 首次推送或空仓库
    git(shared_dir, "push", "-u", "origin", "master")  # 后推
```

**冲突处理策略**：
- JSON 文件（attempts）：每个 `run_id` 独立文件，不会冲突
- Markdown 文件（notes）：rebase 时如冲突，git 保留两方内容（可人工解决）
- 推送失败不阻塞主流程（仅记录 warning，下次 checkpoint 会重试）

---


## 六、CORAL 模块移植清单

| CORAL 源文件 | 行数 | 移植目标 | 改动说明 |
|-------------|------|---------|---------|
| `coral/types.py` | 181 | `evolution/types.py` | 精简：去掉 Task，去掉 commit_hash/parent_hash，加 task_id |
| `coral/hub/checkpoint.py` | 143 | `evolution/checkpoint.py` | 几乎原样：改路径 `.coral` → `.cao-evolution`，路径拆为 tasks/ + knowledge/ |
| `coral/hub/attempts.py` | 156 | `evolution/attempts.py` | 原样移植：JSON CRUD + leaderboard，路径改为 `tasks/{task_id}/attempts/` |
| `coral/hub/notes.py` | 210 | `evolution/notes.py` | 改动：路径改为 `knowledge/notes/`，YAML frontmatter 增加 tags/origin_task/confidence |
| `coral/hub/skills.py` | 100 | `evolution/skills.py` | 改动：路径改为 `knowledge/skills/`，YAML frontmatter 增加 tags |
| `coral/agent/heartbeat.py` | 79 | `evolution/heartbeat.py` | 改动：增加 use_task_count 计数模式（用已完成任务总数） |
| `coral/hub/heartbeat.py` | 173 | `evolution/heartbeat.py` | 合并：config CRUD 部分 |
| `coral/grader/task_grader.py` | 212 | `evolution/grader_base.py` | 精简：保留 evaluate/score/fail/bundle |
| `coral/hub/prompts/*.md` | 238 | `prompts/*.md` | 改动：增加混合维度提示词（任务维度+知识维度），增加知识搜索指引 |
| **新增** | ~60 | `evolution/knowledge_search.py` | 知识搜索（阶段 1: grep+tags；阶段 2: memsearch 替换） |
| **总计** | **~1300行** | **9 个新文件** | **大部分原样移植，知识层有改动** |

**不需要移植的**：
- ~~`coral/hooks/post_commit.py`~~ 的 run_eval() — 逻辑拆到 api 路由中（~30行）
- ~~`coral/grader/loader.py`~~ — 远程侧单独实现（~20行）
- ~~`coral/agent/manager.py`~~ (911行) — CAO 已有 provider 管理，不需要
- ~~`coral/config.py`~~ — 不需要 OmegaConf，用已有 constants.py
- ~~所有 CLI 命令~~ — 通过 HTTP API 替代
- ~~所有 Runtime~~ — CAO 已有 provider 替代
- ~~Gateway~~ — 不需要 API 流量拦截
- ~~Web UI~~ — 不移植 CORAL WebUI，在 CAO WebUI 中新增展示（见第八节）

---


## 七、知识召回层 — memsearch 渐进式集成

### 为什么需要语义召回

CORAL 原生方案的知识召回靠 `ls` + `grep`（关键词匹配）。在同一任务内笔记都相关还行，但**跨任务时 Agent 不知道该看哪些笔记**——搜"防火墙规则"找不到之前写的"iptables 检查"笔记。

memsearch 提供**语义搜索**（Milvus 向量 + BM25 混合 + RRF 排序），能理解语义相关性。

### 两阶段实施

#### 阶段 1（MVP）：git 全量同步 + grep 搜索

```
knowledge/ 下所有 notes/skills 通过 git push/pull 全量同步
Agent 通过 cao_search_knowledge(query, tags) 搜索
底层实现: grep + YAML frontmatter tags 过滤
适用: 知识量 < 数百个文件时
```

**接口提前定义，底层可替换**：
```python
# 阶段 1 实现
def search_knowledge(query: str, tags: list = None, top_k: int = 10):
    results = grep_notes(query, knowledge_dir)
    if tags:
        results = [r for r in results if set(tags) & set(r.tags)]
    return results[:top_k]
```

#### 阶段 2（知识膨胀后）：memsearch 语义召回

当积累内容增多时（数百 → 数千笔记），git 全量 pull 变慢，grep 无法处理语义关联：

```
Hub 端:
  memsearch watch .cao-evolution/shared/knowledge/   # 后台自动索引
  → 文件变更 → 自动切分 → embedding → Milvus 索引

Remote Agent 端:
  不再 git pull 全量 knowledge/，而是：
  1. cao_search_knowledge("与当前任务相关的知识") → Hub 用 memsearch 检索 top-K
  2. Hub 返回精选相关内容
  3. Agent 本地使用知识执行任务
  4. Agent 产出新 note/skill → HTTP POST → Hub → git commit（增量）
  5. Skill 仍可 git pull 缓存本地（数量少、变化慢）
```

**底层替换，接口不变**：
```python
# 阶段 2 实现（替换阶段 1，API 不变）
def search_knowledge(query: str, tags: list = None, top_k: int = 10):
    return memsearch.search(query, top_k=top_k, filter_tags=tags)
```

### 具体实现方案

#### 实现步骤 1：memsearch 作为 sidecar 服务

```yaml
# docker-compose.yml（Hub 侧部署）
services:
  cao-hub:
    command: python3 -m cli_agent_orchestrator
    ports: ["9889:9889"]
    volumes:
      - ~/.cao-evolution:/root/.cao-evolution
    
  memsearch:
    image: zilliztech/memsearch:latest
    environment:
      - MEMSEARCH_DATA_DIR=/data/knowledge
      - MEMSEARCH_PORT=8765
    volumes:
      - ~/.cao-evolution/shared/knowledge:/data/knowledge
    ports: ["8765:8765"]
```

#### 实现步骤 2：知识搜索适配层 `knowledge_search.py`

```python
# evolution/knowledge_search.py
"""知识搜索 — 阶段 1 用 grep，阶段 2 透明切换到 memsearch。"""
import os, requests
from pathlib import Path

MEMSEARCH_URL = os.environ.get("CAO_MEMSEARCH_URL", "")  # 空=阶段1

def search_knowledge(knowledge_dir: str, query: str,
                     tags: list = None, top_k: int = 10) -> list[dict]:
    if MEMSEARCH_URL:
        return _memsearch_search(query, tags, top_k)
    else:
        return _grep_search(knowledge_dir, query, tags, top_k)

def _memsearch_search(query, tags, top_k):
    """阶段 2：调用 memsearch HTTP API"""
    params = {"query": query, "top_k": top_k}
    if tags:
        params["filter"] = f"tags IN {tags}"
    resp = requests.get(f"{MEMSEARCH_URL}/search", params=params, timeout=10)
    return resp.json().get("results", [])

def _grep_search(knowledge_dir, query, tags, top_k):
    """阶段 1：grep + tags 过滤（当前实现）"""
    # ... 现有 grep 逻辑 ...
```

#### 实现步骤 3：文件监控自动索引

memsearch 内置 `watch` 模式，会自动监听 knowledge/ 目录变化并更新索引。
当 Hub 通过 `POST /evolution/knowledge/notes` 写入新文件 → git commit → memsearch 自动检测并索引。

#### 切换条件

```python
# 判断是否启用 memsearch
if os.environ.get("CAO_MEMSEARCH_URL"):
    logger.info("Using memsearch for semantic knowledge search")
else:
    logger.info("Using grep for keyword knowledge search (set CAO_MEMSEARCH_URL to upgrade)")
```

**切换时机**：当 `knowledge/notes/` 下文件数 > 200 或搜索质量不满意时，部署 memsearch 并设置环境变量即可，**API 零改动**。

### 架构图

```
┌─────────────────────────────────────────┐
│  进化知识存储 (Source of Truth)          │
│  .cao-evolution/shared/knowledge/       │
│    notes/*.md    skills/*.md            │
│    (git 管理，.md 文件是真相)            │
└─────────────┬───────────────────────────┘
              │ 阶段 1: grep        阶段 2: memsearch watch
              ▼
┌─────────────────────────────────────────┐
│  搜索引擎                                │
│  阶段 1: grep + tags 过滤               │
│  阶段 2: Milvus Lite 向量 + BM25 混合   │
└─────────────┬───────────────────────────┘
              │ cao_search_knowledge(query, tags, top_k)
              ▼
┌─────────────────────────────────────────┐
│  Agent 知识消费                          │
│  ├─ warmstart: 搜索相关历史知识          │
│  ├─ reflect: 搜索类似经验               │
│  ├─ pivot: 搜索其他策略                 │
│  └─ 日常工作: MCP 工具按需查询          │
└─────────────────────────────────────────┘
```

### 心跳提示词升级

知识召回集成后，心跳提示词中的知识引用方式升级：

```
原版:  "Browse .claude/notes/ and read notes"
阶段1: "Use cao_search_knowledge to find notes related to '{task_description}'"
阶段2: 同上（底层自动切换为语义搜索）
```

---


## 八、hermes-agent 融合方案

### 8.1 Agent 接入 CAO 的通用模式

所有 remote agent（opencode / claude code / hermes / codex）接入 CAO 的标准方式是 **MCP + SKILL + Plugin**（三件套），数据同步有两条路径：
- **上行（Agent → Hub）**：CaoBridge → HTTP API → Hub 写文件 → git checkpoint → git push
- **下行（Hub → Agent）**：Agent 侧 git clone/pull `~/.cao-evolution-client/` → 本地读取 skills/notes/tasks

```
┌───────────────────────────────────────────────────────────────────┐
│  通用接入三件套（所有 agent 一致）                                  │
│                                                                   │
│  ① MCP Server (cao_bridge_mcp.py)                                │
│     → 11 个工具(含 cao_sync/cao_pull_skills)，agent LLM 主动调用  │
│     → 底层复用 CaoBridge 类做 HTTP 通信 + git_sync 做 git 操作    │
│                                                                   │
│  ② SKILL (SKILL.md / CLAUDE.md)                                  │
│     → 协议指引，教 agent 如何使用 MCP 工具                        │
│                                                                   │
│  ③ Plugin / Hooks                                                │
│     → 自动化生命周期（git sync/注册/推送/心跳注入）                │
│     → 底层复用 CaoBridge 类(HTTP) + git_sync 模块(git)            │
│     → opencode: cao-bridge.ts / claude: hooks.sh / hermes: plugin│
│                                                                   │
│  数据同步（对所有 agent 统一）：                                    │
│     上行: Agent → CaoBridge → HTTP API → Hub 写文件               │
│           → .cao-evolution/ → git commit → git push               │
│     下行: Agent → git_sync → git clone/pull ~/.cao-evolution-client/│
│           → pull_skills_to_local() → agent 本地 skills 目录       │
│     所有 agent（含 hermes）均使用 git 同步，无 HTTP 降级           │
└───────────────────────────────────────────────────────────────────┘
```

**各 Agent 实际接入组合**：

| Agent | MCP | SKILL | Plugin/Hooks | 进化层 | 实现状态 |
|-------|-----|-------|-------------|--------|---------|
| **opencode** | ✅ `cao_bridge_mcp.py` | ✅ `SKILL.md` | ✅ `cao-bridge.ts` | 我们的 judge/evals（可选） | ✅ 已实现 |
| **Claude Code** | ✅ 复用同一 MCP | ✅ `CLAUDE.md` | ✅ `session_start/stop.sh` | 我们的 judge/evals（可选） | ✅ 已实现 |
| **hermes** | ✅ 复用同一 MCP | ✅ `SKILL.md`（via external_dirs） | ✅ `cao-evolution` Plugin | **hermes 自进化**（默认）| 🔧 实现中 |
| **codex/copilot** | ✅ 复用同一 MCP | ✅ `SKILL.md` | 无（SKILL 引导手动调用） | 我们的 judge/evals（可选） | ✅ 已实现 |

### 8.2 hermes 自进化机制（不修改）

hermes-agent 已有三个本地进化路径，**我们不注入任何进化逻辑**：

| 路径 | 触发时机 | 产物 | 存储 |
|------|---------|------|------|
| **技能自动创建** | 复杂对话后（5+ tool calls），review agent 自主决定 | `~/.hermes/skills/*/SKILL.md` | 本地文件，含 YAML frontmatter |
| **技能编辑/优化** | 发现更好方法时，通过 `skill_manage` 的 edit/patch | 更新 `SKILL.md` 内容和 version | 本地文件 |
| **记忆积累** | 每 N 轮对话后台 review | `~/.hermes/memories/MEMORY.md`（§ 分隔，2200字符上限，满后 consolidate） | 本地文件 |

**策略**：直接消费 hermes 的进化产物（push 到共享池），不改变它的进化节奏。

### 8.3 hermes 接入架构与数据流

```
┌─────────────────────────────────────────────────────────────────────┐
│  Hermes Agent (远程机器)                                            │
│                                                                     │
│  ┌─── hermes 自进化（不动） ────────────────────────────────┐       │
│  │  skill_manage → ~/.hermes/skills/*/SKILL.md              │       │
│  │  memory tool  → ~/.hermes/memories/MEMORY.md             │       │
│  └──────────────────────────────────────────────────────────┘       │
│                     │ 本地文件                                       │
│  ┌──────────────────▼───────────────────────────────────────┐       │
│  │  ③ cao-evolution Plugin (Hermes Plugin)                  │       │
│  │     底层复用 CaoBridge 类 + git_sync 模块                │       │
│  │                                                          │       │
│  │  on_session_start:                                       │       │
│  │    → git_sync.init_client_repo()  ← git clone/pull       │       │
│  │    → _pull_skills_from_clone()    ← 共享skill→本地       │       │
│  │    → bridge.register()                                   │       │
│  │    → bridge.search_knowledge() → inject context          │       │
│  │                                                          │       │
│  │  on_session_end:                                         │       │
│  │    → bridge.share_skill(...)  × N  (每个 hermes skill)   │       │
│  │    → bridge.share_note(...)   × N  (MEMORY.md § 条目)    │       │
│  │    → git_sync.pull()          ← 拉取最新                 │       │
│  │                                                          │       │
│  │  pre_llm_call:                                           │       │
│  │    → 检查 pending_heartbeats → inject prompt             │       │
│  └──────────────────────────────────────────────────────────┘       │
│                                                                     │
│  ~/.cao-evolution-client/  ← agent-side git clone                   │
│  ├── skills/  ← 共享技能（git pull 获取）                           │
│  ├── notes/   ← 共享笔记（git pull 获取）                           │
│  ├── tasks/   ← 任务定义（git pull 获取）                           │
│  └── .git/                                                          │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │  ① MCP Server: cao_bridge_mcp.py (11 个工具)            │       │
│  │     底层也是 CaoBridge 类 + git_sync                     │       │
│  │     hermes LLM 对话中主动调用                             │       │
│  │     新增: cao_sync / cao_pull_skills                     │       │
│  └──────────────────────────────────────────────────────────┘       │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │  ② SKILL.md (通过 external_dirs 加载)                    │       │
│  │     教 hermes 如何使用 MCP 工具 + git sync 的协议指引     │       │
│  └──────────────────────────────────────────────────────────┘       │
└─────────────────────────┬───────────────────────────────────────────┘
                          │ HTTP 上行 + git 下行
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  CAO Hub (:9889)                                                    │
│                                                                     │
│  HTTP API 接收请求                                                  │
│    ↓                                                                │
│  写入文件到 .cao-evolution/                                         │
│    ├── skills/{name}/SKILL.md                                       │
│    ├── notes/{title}.md                                             │
│    └── tasks/{id}/task.yaml + attempts/{hash}.json                  │
│    ↓                                                                │
│  git add -A → git commit → git push (CAO_EVOLUTION_REMOTE)          │
│    ↓                                                                │
│  远程 Agent 通过 git pull 同步到 ~/.cao-evolution-client/            │
│  hermes 进化产物也对其他 agent 可见                                  │
└─────────────────────────────────────────────────────────────────────┘
```

**同步路径一致性**：
- opencode Plugin `cao-bridge.ts` → git clone/pull 启动时 + 完成任务后
- claude code Hooks `session_start.sh` → git clone/pull + 启动时
- hermes Plugin `cao-evolution` → git_sync.init_client_repo() + pull() 会话前后
- **所有 agent（含 hermes）使用同一 git 仓库同步，无 HTTP 降级路径**

#### 数据流详解

**上行（hermes → Hub），Plugin `on_session_end` 触发**：
```
hermes 本地                      CaoBridge 方法                      Hub 侧
───────────                      ──────────────                      ──────
~/.hermes/skills/detect-sqli/    bridge.share_skill(                 → 写入 skills/
  SKILL.md (v2)                    name="detect-sqli",                 detect-sqli/SKILL.md
                                   content="...",                    → git commit "[hermes-001] skill"
                                   tags=["hermes","security"])       → git push (CAO_EVOLUTION_REMOTE)

~/.hermes/memories/MEMORY.md     bridge.share_note(                  → 写入 notes/
  § PHP prepared statement...      title="PHP prepared...",            hermes-{hash}.md
  § bandit B101 误报               content="...",                   → git commit "[hermes-001] note"
                                   tags=["hermes","memory"])         → git push
```

**下行（Hub → hermes），Plugin `on_session_start` + git_sync**：
```
Hub git repo                     Agent 侧                            hermes 本地
────────────                     ──────────                          ────────────
skills/xss-detect/SKILL.md       git clone/pull →                    ~/.cao-evolution-client/
notes/security-patterns.md         ~/.cao-evolution-client/            skills/xss-detect/SKILL.md
tasks/sqli-v1/task.yaml                                              notes/security-patterns.md
                                 _pull_skills_from_clone()  →        ~/.hermes/skills/
                                   复制共享 skill 到 hermes 本地       xss-detect/SKILL.md
                                                                     (hermes 启动时自动加载)
```

**心跳（Hub → hermes），Plugin `pre_llm_call` 注入**：
```
Hub                              CaoBridge 方法                      hermes
───                              ──────────────                      ──────
check_triggers() → reflect       report_score() 响应中携带            on_end 推送后触发 report_score
  evolution_signals 注入           heartbeat_prompts 列表              → 存入 pending_heartbeats 缓冲
                                 pre_llm_call 返回缓冲中的 prompt     hermes 自行决定是否响应
```

### 8.4 Hermes Plugin 实现（cao-evolution）

**目录**：`cao-bridge/hermes/`

```
cao-bridge/hermes/
├── plugin.yaml          # Hermes 插件清单
├── __init__.py          # register(ctx) 入口 — 复用 CaoBridge
├── memory_parser.py     # MEMORY.md § 解析 + SHA-256 去重
├── README.md            # 安装说明
```

**关键设计**：`__init__.py` 直接 `from cao_bridge import CaoBridge`，复用和 MCP Server 同一个 HTTP 客户端类。

**plugin.yaml**：
```yaml
name: cao-evolution
version: "1.0"
description: "CAO co-evolution — syncs hermes artifacts to shared pool via CaoBridge"
settings:
  hub_url:
    type: string
    default: "http://127.0.0.1:9889"
  agent_id:
    type: string
    default: ""
  push_skills:
    type: boolean
    default: true
  push_memory:
    type: boolean
    default: true
  heartbeat_enabled:
    type: boolean
    default: true
  our_evolution_enabled:
    type: boolean
    default: false
    description: "Use CAO judge/evals (disabled — hermes has its own)"
```

**核心逻辑** (`__init__.py`)：
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cao_bridge import CaoBridge            # ← 复用同一个类
from .memory_parser import parse_memory

def register(ctx):
    bridge = CaoBridge(
        hub_url=ctx.settings.get("hub_url", "http://127.0.0.1:9889"),
        agent_profile="remote-hermes",
    )
    pending_heartbeats: list[str] = []      # 心跳缓冲区

    def on_start(session):
        bridge.register()
        results = bridge.search_knowledge(query="", tags="", top_k=5)
        if results:
            return "[CAO Shared Knowledge]\n" + format_results(results)

    def on_end(session):
        if not bridge.terminal_id:          # register 失败时重试一次
            try: bridge.register()
            except: return
        pushed = 0
        if ctx.settings.get("push_skills"):
            for name, content in scan_hermes_skills():
                bridge.share_skill(name, content, tags=["hermes"])
                pushed += 1
        if ctx.settings.get("push_memory"):
            for title, content in parse_memory():
                bridge.share_note(title, content, tags=["hermes", "memory"])
                pushed += 1
        # 推送后 report_score → 触发心跳检查 → 响应中携带 heartbeat_prompts
        if pushed > 0:
            resp = bridge.report_score(task_id="hermes-sync", score=None,
                                       title=f"hermes sync: {pushed} items")
            for hb in resp.get("heartbeat_prompts", []):
                prompt = hb.get("prompt", "") if isinstance(hb, dict) else str(hb)
                if prompt:
                    pending_heartbeats.append(prompt)

    def pre_llm(messages, tools):
        if ctx.settings.get("heartbeat_enabled") and pending_heartbeats:
            return pending_heartbeats.pop(0)  # 从缓冲区取
        return None

    ctx.register_hook("on_session_start", on_start)
    ctx.register_hook("on_session_end", on_end)
    ctx.register_hook("pre_llm_call", pre_llm)
```

### 8.5 MCP 配置（hermes 侧）

hermes 支持 MCP 工具，加载 **同一个** `cao_bridge_mcp.py`：

```yaml
# ~/.hermes/config.yaml
mcp:
  cao-bridge:
    command: ["python3", "/path/to/cao_bridge_mcp.py"]
    environment:
      CAO_HUB_URL: "http://127.0.0.1:9889"
      CAO_AGENT_PROFILE: "remote-hermes"
```

加载后 hermes LLM 可直接调用 `cao_register`, `cao_share_note`, `cao_share_skill` 等 9 个 MCP 工具。这些工具底层也是 `CaoBridge` 类。

### 8.6 SKILL.md 加载（external_dirs）

```yaml
# ~/.hermes/config.yaml
skills:
  external_dirs:
    - /path/to/cao-bridge/skill        # 加载 SKILL.md 协议指引
    - ~/.cao-evolution-client/skills  # 加载共享池 skill (agent-side git clone)
```

hermes 启动时自动扫描 external_dirs，skill 以只读方式可用。本地同名 skill 优先。

### 8.7 MEMORY.md 解析规则

```
══════════════════════════════════════════════
MEMORY (your personal notes) [67% — 1,474/2,200 chars]
══════════════════════════════════════════════
User's project is a Rust web service
§
bandit B101 assert 误报率高
§
```

解析规则（`memory_parser.py`）：
1. 跳过 `═` 开头的 header 行
2. 以 `§` 分隔为独立条目
3. 每条目 SHA-256 去重（相同内容不重复推送）
4. 通过 `CaoBridge.share_note()` 推送，tags 含 `hermes, memory`

### 8.8 降级方案：hermes-sync.sh

无法安装 Plugin 时，提供 shell 脚本降级方案，**同样复用 Hub HTTP API**（和 Plugin 路径一致）：

```bash
#!/bin/bash
# hermes-sync.sh — cron 驱动的降级同步
HUB="${CAO_HUB_URL:-http://127.0.0.1:9889}"
# 推送 skills
for d in ~/.hermes/skills/*/; do
  name=$(basename "$d")
  content=$(cat "$d/SKILL.md" 2>/dev/null) || continue
  curl -sX POST "$HUB/evolution/knowledge/skills" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"$name\",\"content\":$(echo "$content"|jq -Rs .),\"tags\":[\"hermes\"]}"
done
# 推送 MEMORY.md 条目
python3 -c "
from memory_parser import parse_memory
import requests, json
for title, content in parse_memory():
    requests.post('$HUB/evolution/knowledge/notes',
        json={'title':title,'content':content,'tags':['hermes','memory']})
"
```

### 8.9 实施计划

| 步骤 | 内容 | 复杂度 | 文件 |
|------|------|--------|------|
| **H1** | external_dirs 配置示例 + SKILL.md 部署 | 🟢 零代码 | README.md |
| **H2** | MCP 配置示例（复用 cao_bridge_mcp.py） | 🟢 配置 | README.md |
| **H3** | Hermes Plugin（复用 CaoBridge） | 🟡 ~150行 | `__init__.py` + `memory_parser.py` |
| **H4** | hermes-sync.sh 降级脚本 | 🟢 ~60行 | `hermes-sync.sh` |
| **H5** | 测试 | 🟡 ~100行 | `test/evolution/test_hermes_plugin.py` |

---


## 八·二、Claude Code CLI 接入方案

### Claude Code 扩展机制分析

Claude Code（anthropics/claude-code）支持多种扩展方式，与 opencode 类似但有差异：

| 机制 | opencode | Claude Code | 说明 |
|------|----------|-------------|------|
| **Plugin** | `.opencode/plugins/*.ts` | `.claude/plugins/*/plugin.json` | Claude Code 有完整插件系统 |
| **MCP** | `opencode.json` 的 `mcp` 段 | `claude mcp add` 或 `--mcp-config` | 两者均支持 stdio MCP |
| **Skill** | `.opencode/skills/*/SKILL.md` | `.claude/plugins/*/skills/SKILL.md` | Claude Code 的 skill 在 plugin 目录内 |
| **Hooks** | event-based（session.idle 等） | lifecycle hooks（SessionStart, Stop 等） | Claude Code hooks 更细粒度 |
| **Instructions** | 无 | `CLAUDE.md` + `.claude/rules/*.md` | 类似 skill，但是全局注入 |
| **Commands** | 无 | `.claude/commands/*.md` 自定义斜杠命令 | 可用于手动触发进化操作 |

### 三个控制点实现

#### 控制点 1：MCP Server（推荐，零代码复用）

**现有 `cao_bridge_mcp.py` 直接适配 Claude Code**，无需修改：

```bash
# 方式 A：命令行配置
claude mcp add cao-bridge -- python3 /path/to/cao_bridge_mcp.py

# 方式 B：配置文件 .mcp.json（项目级）
{
  "mcpServers": {
    "cao-bridge": {
      "command": "python3",
      "args": ["/path/to/cao_bridge_mcp.py"],
      "env": {
        "CAO_HUB_URL": "http://127.0.0.1:9889",
        "CAO_AGENT_PROFILE": "remote-claude-code"
      }
    }
  }
}
```

MCP 启用后，Claude Code 可直接调用所有 9 个 MCP 工具（cao_register、cao_poll、cao_report、cao_report_score、cao_get_grader、cao_get_leaderboard、cao_share_note、cao_share_skill、cao_search_knowledge）。

#### 控制点 2：Skill（CLAUDE.md / Plugin Skills）

两种方式让 Claude Code 了解进化协议：

**方式 A：CLAUDE.md（全局指令，最简单）**

```markdown
# CLAUDE.md（项目根目录）

## CAO Evolution Protocol
You are connected to a CAO Hub for collaborative evolution.
Use the cao-bridge MCP tools to participate:
1. Call cao_register at session start
2. Call cao_poll to check for tasks
3. After completing tasks, call cao_report_score
4. Search shared knowledge with cao_search_knowledge before starting work
5. Share insights with cao_share_note when you learn something useful
```

**方式 B：Plugin + SKILL.md（与 opencode 格式兼容）**

```
.claude/plugins/cao-bridge/
├── plugin.json
├── skills/
│   └── cao-bridge/
│       └── SKILL.md     # ← 复用 opencode 的 SKILL.md 内容
└── .mcp.json            # MCP server 配置
```

```json
// plugin.json
{
  "name": "cao-bridge",
  "version": "1.0.0",
  "description": "CAO Remote Bridge for collaborative evolution",
  "skills": ["skills/cao-bridge"],
  "mcp": ".mcp.json"
}
```

#### 控制点 3：Plugin + Hooks（全自动进化）

Claude Code 的 hooks 系统可实现类似 opencode plugin 的全自动流程：

```
.claude/plugins/cao-bridge/
├── plugin.json
├── hooks/
│   ├── session-start.js    # SessionStart → 自动注册 + 拉取知识
│   ├── pre-tool-use.js     # PreToolUse → 可选：监控工具调用
│   └── stop.js             # Stop → 自动上报结果 + 写笔记
├── skills/
│   └── cao-bridge/SKILL.md
└── .mcp.json
```

**session-start.js（SessionStart hook）**：
```javascript
// 在 session 开始时自动注册、拉取共享知识
export default async function({ session }) {
  const HUB = process.env.CAO_HUB_URL || "http://127.0.0.1:9889";
  const resp = await fetch(`${HUB}/remotes/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agent_profile: "remote-claude-code" }),
  });
  const { terminal_id } = await resp.json();
  process.env.CAO_TERMINAL_ID = terminal_id;

  // 拉取共享知识作为 context
  const notes = await fetch(`${HUB}/evolution/knowledge/notes`).then(r => r.json());
  return { context: `Shared knowledge:\n${JSON.stringify(notes.slice(0, 5))}` };
}
```

**stop.js（Stop hook）**：
```javascript
// Agent 完成时自动上报
export default async function({ session, result }) {
  const HUB = process.env.CAO_HUB_URL || "http://127.0.0.1:9889";
  const tid = process.env.CAO_TERMINAL_ID;
  if (!tid) return;
  
  await fetch(`${HUB}/remotes/${tid}/report`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: "completed", output: result?.summary || "" }),
  });
}
```

### 自定义斜杠命令（手动触发进化操作）

```markdown
<!-- .claude/commands/evolve.md -->
---
description: Trigger evolution cycle — reflect, report score, share notes
---

Please perform the following evolution steps:
1. Call cao_report_score with your evaluation of the just-completed task
2. Reflect on what worked and what didn't
3. Call cao_share_note to share your key insight
4. Call cao_get_leaderboard to check your ranking
```

用户在 Claude Code 中输入 `/evolve` 即可手动触发进化循环。

### Claude Code 接入优先级

| 方式 | 复杂度 | 自动化程度 | 建议 |
|------|--------|-----------|------|
| MCP 复用 | 🟢 零代码 | 手动调用 | ✅ 首先做 |
| CLAUDE.md | 🟢 一个文件 | Skill 引导 | ✅ 首先做 |
| Plugin + Skill | 🟡 4个文件 | Skill 引导 | ✅ 其次做 |
| Plugin + Hooks | 🟡 5个文件 | 全自动 | 需要时做 |
| /evolve 命令 | 🟢 1个文件 | 手动触发 | ✅ 首先做 |

---


## 八·三、本地 Skill 自动同步到共享池

### 问题

opencode / Claude Code / hermes 各自本地有 skills（如 `secskill-evo`、`scan-manage`、`skill-creator`），这些 skill 的价值应能共享到 CAO 共享池，让所有 Agent 受益。

### 方案：`cao-skill-sync` 工具

一个轻量脚本，扫描本地 skill 目录，与共享池双向同步，纳入 git 版本管理：

```
本地 skill 目录                     CAO 共享池 (Hub + git clone)
~/.config/opencode/skills/    ←→   Hub: .cao-evolution/skills/
~/.claude/skills/             ←→     ↕ git push/pull
~/.hermes/skills/             ←→   Agent: ~/.cao-evolution-client/skills/
```

#### 同步逻辑

```python
# cao_skill_sync.py
"""Sync local agent skills to/from the CAO shared evolution pool."""
import shutil, hashlib
from pathlib import Path

SKILL_SOURCES = [
    Path.home() / ".config/opencode/skills",       # opencode 全局
    Path.home() / ".claude/plugins",                # claude code
    Path.home() / ".hermes/skills",                 # hermes
    Path.cwd() / ".opencode/skills",                # opencode 项目级
]

def sync_skills(evo_dir: str, direction: str = "both"):
    shared_skills = Path(evo_dir) / "shared" / "knowledge" / "skills"
    
    # local → shared（新增或更新的 skill 推入共享池）
    if direction in ("push", "both"):
        for source_dir in SKILL_SOURCES:
            if not source_dir.exists(): continue
            for skill_dir in source_dir.iterdir():
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists(): continue
                target = shared_skills / skill_dir.name
                # 仅在内容变化时更新
                if not target.exists() or file_hash(skill_md) != file_hash(target / "SKILL.md"):
                    shutil.copytree(skill_dir, target, dirs_exist_ok=True)
    
    # shared → local（共享池的新 skill 拉到首选本地目录）
    # 环境变量 CAO_SKILL_WRITEBACK=1 开启回写（默认关闭）
    # 环境变量 CAO_SKILL_WRITEBACK_TARGET 指定首选目标（默认 "claude-code"）
    if direction in ("pull", "both") and os.environ.get("CAO_SKILL_WRITEBACK") == "1":
        target_pref = os.environ.get("CAO_SKILL_WRITEBACK_TARGET", "claude-code")
        local_target = resolve_writeback_target(target_pref)  # claude-code > opencode > hermes
        local_target.mkdir(parents=True, exist_ok=True)
        for skill_dir in shared_skills.iterdir():
            if not (skill_dir / "SKILL.md").exists(): continue
            local_skill = local_target / skill_dir.name
            if local_skill.exists():
                # 冲突处理：备份原文件再覆盖
                backup = local_skill / "SKILL.md.bak"
                shutil.copy2(local_skill / "SKILL.md", backup)
            shutil.copytree(skill_dir, local_skill, dirs_exist_ok=True)
```

#### 回写策略

- **环境变量开关**：`CAO_SKILL_WRITEBACK=1` 启用回写（默认 `0` 不回写）
- **首选目标**：`CAO_SKILL_WRITEBACK_TARGET=claude-code`（默认），可选 `opencode`、`hermes`
- **冲突处理**：回写前若目标已有同名 skill，先备份为 `SKILL.md.bak` 再覆盖
- **回写目标解析优先级**：claude-code → opencode → hermes → 第一个存在的目录

#### 触发方式

1. **手动**：`python3 -m cli_agent_orchestrator.evolution.skill_sync`
2. **MCP 工具**：新增 `cao_sync_skills` MCP 工具
3. **Plugin 自动**：在 opencode plugin 的 register 完成后自动执行一次 pull
4. **定时任务**：crontab 每 5 分钟执行一次

---


## 九、WebUI 进化展示（整合到 CAO 前端，最后实现）

在 CAO 已有 WebUI 中新增 `/evolution` 页面。

### 9.1 分数曲线图

**分数是什么**：Grader 对 Agent 每次任务执行结果的评估分值。分数的含义由 `grader.py` 定义，完全取决于任务类型。例如：
- 安全审计：`score = 发现漏洞数 * 0.1 + 严重漏洞数 * 0.3`（越高越好）
- 配置优化：`score = 响应延迟_ms`（越低越好，direction="minimize"）
- 文档质量：`score = 覆盖度(0~1) * 0.5 + 准确性(0~1) * 0.5`

**展示内容（参考 CORAL 的 ScoreChart）**：
- X 轴：评估次序 或 时间
- Y 轴：分数值
- 每个 Agent 一条折线，颜色区分
- task_id 选择器：切换查看不同任务的进化曲线
- 关键数据：最佳分数、当前分数、改善趋势
- **多维评分展示**：点击 attempt 可查看 `score_detail` 雷达图（预留）

**数据源**：`GET /evolution/{task_id}/attempts`

### 9.2 排行榜

- 按 task_id 展示排名表
- 列：Rank、Score、Agent ID、描述(title)、时间、Status
- 可排序、可筛选
- 高亮 "improved" 行
- **多维评分列**：若 attempt 有 `score_detail`，展示各维度小数值（预留）

**数据源**：`GET /evolution/{task_id}/leaderboard?top=20`

### 9.3 笔记浏览

- 全局知识视图：展示 knowledge/notes/ 下所有笔记
- 可按 tags 过滤、按 origin_task 分组
- 每条笔记：标题、标签、来源任务、confidence、作者、日期、正文（可展开）
- 综合文档 (`_synthesis/*`) 和普通笔记区分显示
- 按时间倒序

**数据源**：`GET /evolution/knowledge/notes`

### 9.4 Skill 预览

- 全局技能视图：展示 knowledge/skills/ 下所有技能
- 每个 Skill：名称、描述、标签、创建者、创建日期
- 点击可查看 SKILL.md 全文
- **来源标记**：显示 origin（opencode-local / claude-code / hermes-local / hub-shared）

**数据源**：`GET /evolution/knowledge/skills`

### 9.5 具体实现方案

**技术栈**：独立单页应用（不依赖 CAO 已有前端框架），便于独立部署

```
webui/
├── index.html          # 单文件 SPA
├── app.js              # Vue 3 CDN + Chart.js CDN
└── style.css           # 样式
```

**核心组件**：
```javascript
// 纯前端，通过 fetch 调用 Hub API
const app = Vue.createApp({
  data() {
    return { tasks: [], currentTask: null, attempts: [], notes: [], skills: [] }
  },
  methods: {
    async loadTasks()       { this.tasks = await fetch('/evolution/tasks').then(r => r.json()) },
    async loadAttempts(tid) { this.attempts = (await fetch(`/evolution/${tid}/attempts`).then(r => r.json())) },
    async loadNotes()       { this.notes = await fetch('/evolution/knowledge/notes').then(r => r.json()) },
    async loadSkills()      { this.skills = await fetch('/evolution/knowledge/skills').then(r => r.json()) },
  },
  mounted() { this.loadTasks(); this.loadNotes(); this.loadSkills(); }
})
```

**部署方式**：Hub 的 FastAPI 静态文件挂载
```python
# api/main.py 追加
from fastapi.staticfiles import StaticFiles
app.mount("/webui", StaticFiles(directory="webui", html=True))
```

### 9.6 UI 布局建议

```
CAO WebUI
├── 原有页面（Agent 列表、状态、Terminal...）
└── /evolution                          # ★ 新增
    ├── Task 选择器（下拉）              # 选择 task_id
    ├── 分数曲线图（左上，占主要区域）    # Chart.js 折线图
    ├── 排行榜（左下）                   # 表格
    ├── 笔记列表（右上）                 # 可展开列表
    └── Skill 预览（右下）               # 卡片网格
```

**不实现的 CORAL WebUI 功能**：
- ~~回放功能~~ — 好玩但非必须
- ~~日志查看器~~ — remote Agent 没有本地日志流
- ~~Agent 状态卡片~~ — CAO 已有类似功能
- ~~Token/Cost 追踪~~ — remote Agent 无法提供此数据

---


## 十、分布式人工反馈机制

### 10.1 问题

当前进化循环为「Agent 执行 → Grader 自动评估 → 上报分数 → 心跳反思」的全自动闭环。
但在安全场景中，**自动 Grader 无法覆盖所有判断维度**（如漏洞是否为误报、严重程度评估、业务上下文合理性）。
需要引入人工反馈作为进化依据，且该机制必须适配分布式多 Agent 架构。

### 10.2 Unique Report ID 机制

每个 Agent 扫描出结果后，向 Hub 注册一个 **Report**，获得 Unique Report ID。
该 ID 对应的报告被推送到标注队列，由人类专家标注后，Agent 在后续进化中拉取反馈。

```
Agent A 扫描出漏洞           Hub                          人类专家
  │                           │                            │
  │── POST /evolution/reports ─►│                            │
  │   {task_id, agent_id,     │── 存储到 reports/{id}.json  │
  │    findings: [...],       │── 推送到标注队列 ───────────►│
  │    auto_score: 0.72}      │                            │
  │◄── {report_id: "rpt-xxx"} │                            │
  │                           │                            │
  │   ... 人类标注中 ...       │   ◄── PUT /reports/{id}     │
  │                           │       {labels: [...],      │
  │                           │        verdict: "partial",  │
  │                           │        human_score: 0.65,   │
  │                           │        comments: "..."}     │
  │                           │                            │
  │── GET /reports?agent_id=A&─►│                            │
  │   status=annotated        │                            │
  │◄── [{report_id, labels,   │                            │
  │     human_score, comments}]│                            │
  │                           │                            │
  │   Agent A 消化反馈 →       │                            │
  │   调整策略 → 下轮进化      │                            │
```

### 10.3 数据模型

```python
@dataclass
class Finding:
    """单个发现条目"""
    file_path: str              # 文件路径
    line: int | None = None     # 行号
    finding_type: str = ""      # 类型：vuln/entry_point/config_issue
    severity: str = "info"      # info/low/medium/high/critical
    description: str = ""       # Agent 的描述
    snippet: str = ""           # 代码片段

@dataclass
class HumanLabel:
    """人工标注"""
    finding_idx: int            # 对应 findings 列表的下标
    verdict: str                # tp (true positive) / fp (false positive) / uncertain
    severity_override: str = "" # 人工修正严重程度（空=同意 Agent 判断）
    comment: str = ""           # 标注备注

@dataclass
class Report:
    """漏洞报告"""
    report_id: str              # UUID (Hub 生成)
    task_id: str
    agent_id: str
    run_id: str                 # 关联的 attempt run_id
    findings: list[Finding]
    auto_score: float | None    # Grader 自动评分
    auto_score_detail: dict[str, float] | None
    status: str = "pending"     # pending → annotating → annotated → consumed
    created_at: str = ""        # ISO 8601
    # 人工标注（标注后填入）
    human_labels: list[HumanLabel] | None = None
    human_score: float | None = None  # 人工综合评分
    human_comments: str = ""
    annotated_at: str | None = None
    annotated_by: str = ""      # 标注者 ID
```

### 10.4 Hub API 端点

| Method | Endpoint | 描述 |
|--------|----------|------|
| POST | `/evolution/reports` | Agent 提交报告，返回 report_id |
| GET | `/evolution/reports` | 按 task_id/agent_id/status 过滤 |
| GET | `/evolution/reports/{report_id}` | 获取单个报告详情 |
| PUT | `/evolution/reports/{report_id}/annotate` | 人工提交标注 |
| PATCH | `/evolution/reports/{report_id}/status` | 更新状态 |

### 10.5 存储结构

**Hub 侧**（中心存储）：
```
.cao-evolution/shared/
└── reports/
    └── {task_id}/
        └── {report_id}.json    # 完整报告 + 标注
```

**Agent 侧**（本地工作目录）：
```
.cao-reports/                     # Agent 工作目录下自动创建
├── {report_id}.report            # 提交报告的本地副本（JSON）
│   # { report_id, task_id, findings: [...], auto_score, timestamp }
├── {report_id}.result            # 拉取到的人工标注结果（JSON）
│   # { report_id, human_labels: [...], human_score, comments, annotated_by }
└── ...
```

**设计要点**：
- 每次 `cao_submit_report` 后，自动在 `.cao-reports/` 保存 `{id}.report`
- 每次 `cao_fetch_feedback` 后，将标注结果写入 `{id}.result`
- `.report` 和 `.result` 对应同一个 report_id，Grader 可以配对读取
- 目录默认在 Agent 当前工作目录下（`$PWD/.cao-reports/`），可通过 `CAO_REPORTS_DIR` 覆盖

### 10.6 Agent 侧集成

**MCP 新增 3 个工具**：

```
cao_submit_report(task_id, findings, auto_score?)
  → POST /evolution/reports → 返回 report_id
  → 本地写入 .cao-reports/{report_id}.report

cao_fetch_feedback(terminal_id)
  → GET /evolution/reports?terminal_id={terminal_id}&status=annotated
  → 对每个已标注报告，本地写入 .cao-reports/{report_id}.result
  → 返回本次拉取的报告数量

cao_list_reports(terminal_id?, status?)
  → GET /evolution/reports?terminal_id=...&status=...
  → 返回报告列表摘要（不下载完整内容）
```

**Grader 集成**（grader.py 签名扩展）：

```python
class SecurityGrader(GraderBase):
    def evaluate(self, workdir: str, reports_dir: str = ".cao-reports") -> dict:
        """
        workdir: Agent 工作目录
        reports_dir: .report/.result 文件所在目录

        Grader 可以读取 .report 和 .result 进行评估：
        - .report 文件：Agent 本次的发现（自动评估输入）
        - .result 文件：人工标注结果（若已有，作为 ground truth）
        """
        from pathlib import Path
        rdir = Path(workdir) / reports_dir
        reports = list(rdir.glob("*.report"))
        results = list(rdir.glob("*.result"))

        # 计算精度：有 .result 的报告可以对比 tp/fp
        if results:
            tp = fp = 0
            for rf in results:
                data = json.loads(rf.read_text())
                for label in data.get("human_labels", []):
                    if label["verdict"] == "tp": tp += 1
                    elif label["verdict"] == "fp": fp += 1
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            return {"precision": precision, "coverage": len(reports) / expected, ...}

        # 无人工标注时，仅基于自动分析
        return {"auto_coverage": len(reports), ...}
```

**Plugin 自动流程**（cao-bridge.ts）：

```typescript
// session.idle 回调中自动执行
async function onSessionIdle(taskId: string, terminalId: string) {
  // 1. 上报分数（已有逻辑）
  const scoreResp = await reportScore(taskId, ...);

  // 2. 拉取人工反馈 → 本地 .result 文件
  const fetched = await bridge.get(
    `/evolution/reports/fetch?terminal_id=${terminalId}`
  );
  if (fetched.count > 0) {
    // 写入本地 .cao-reports/{id}.result 文件
    for (const r of fetched.reports) {
      writeFile(`.cao-reports/${r.report_id}.result`, JSON.stringify(r));
    }
    // 注入摘要到 Agent 上下文
    const summary = fetched.reports.map(r =>
      `Report ${r.report_id}: human_score=${r.human_score}, ` +
      `tp=${r.tp_count}, fp=${r.fp_count}`
    ).join('\n');
    injectTask(`[Human Feedback — ${fetched.count} reports annotated]\n${summary}\n` +
      `Review .cao-reports/*.result for details and adjust your strategy.`);
  }
}
```

**Terminal ID 关联**：
- `cao_submit_report` 自动附带当前 terminal_id（从 bridge 状态获取）
- Hub 存储 `report.terminal_id` 字段
- `cao_fetch_feedback(terminal_id)` 按 terminal_id 过滤，只拉取该 session 相关的报告
- 支持跨 session 查询：`cao_list_reports(status="annotated")` 返回所有

**心跳整合**：
- 当 Agent 有未消化的 `.result` 文件时（`.report` 存在但对应 `.result` 缺失或状态=pending），heartbeat 自动触发 `reflect` 并附带反馈摘要
- `heartbeat.py` 新增 `has_pending_feedback(reports_dir)` 检查

### 10.7 WebUI 标注界面

在 EvolutionPanel 中新增 **Reports** 子面板：

- **报告列表**：按 task/agent/status 过滤，显示 findings 数量、auto_score
- **标注视图**：逐条显示 findings，每条可标记 tp/fp/uncertain + severity override + comment
- **批量标注**：支持全选/反选，一键标记所有为 tp
- **标注统计**：误报率、严重程度分布、Agent 间对比

### 10.8 进化反馈回路

```
┌──────────────────────────────────────────────────────────────────┐
│  自进化闭环（全自动）                                             │
│  Agent → Grader → Score → Heartbeat → Reflect → 改进            │
│     ▲                                                            │
│     │  human_score & labels                                      │
│     │                                                            │
│  ┌──┴──────────────────────────────────────────────────┐         │
│  │  人工反馈回路（异步）                                  │         │
│  │  Agent 提交 Report → 人类标注 → Agent 拉取 Feedback   │         │
│  │  → 反馈纳入 reflect prompt → 策略调整                  │         │
│  └────────────────────────────────────────────────────┘         │
└──────────────────────────────────────────────────────────────────┘
```

**关键设计原则**：
1. **异步不阻塞**：人工标注是异步的，Agent 不等待标注完成就继续进化
2. **双分轨制**：`auto_score`（Grader 自动）和 `human_score`（人工）共存，排行榜可按任一排序
3. **渐进消化**：Agent 每次 poll 时检查是否有新反馈，逐步消化而非一次全量
4. **标注者多样性**：支持多人标注同一报告（annotated_by 字段），未来可扩展为共识机制

---

## 十一、错误处理

| 场景 | 处理 |
|------|------|
| 远程 Grader 超时 | Agent 自行管理超时，上报 `status="timeout"` |
| 远程 Grader 崩溃 | Agent 捕获异常，上报 `status="crashed", feedback=str(e)` |
| Hub checkpoint 冲突 | `flock(LOCK_EX)` 自动等待，串行写入 |
| JSON 文件损坏 | 跳过，日志警告 |
| 远程 Agent 断联 | Hub 无影响，下次 Agent 上线继续拉取 |
| Heartbeat 投递失败 | 日志记录，不影响 score 返回 |
| task_id 不存在 | API 返回 404，远程 Agent 自行处理 |

---


## 十二、总结

**核心设计**：进化在远程、同步在中心。任务维度（分数）和知识维度（notes/skills）双层结构。

```
远程 Agent 侧:                  Hub 侧:
  执行任务                        接收分数（按 task_id 存储到 tasks/）
  本地评估(Grader从git获取)       比较历史 → status
  上报分数(HTTP,含score_detail)   写入 attempt JSON（含多维分数）
  接收心跳(poll+inject)           git checkpoint → 远程仓库同步
  拉取知识(HTTP/语义搜索)         检查心跳 → ScoreResponse 返回 prompt
  写入笔记/技能(HTTP,带标签)      存储笔记/技能（到 knowledge/，带元数据）
                                  提供排行榜（按 task_id）
                                  提供知识搜索（按标签/语义）
```

**支持的 Agent 类型**：

| Agent | Plugin | MCP | Skill | Hooks | 自动进化 |
|-------|--------|-----|-------|-------|---------|
| **opencode** | ✅ cao-bridge.ts | ✅ cao_bridge_mcp.py | ✅ SKILL.md | — | Plugin 全自动 |
| **Claude Code** | ✅ plugin.json + hooks | ✅ 同上 (复用) | ✅ CLAUDE.md / SKILL.md | ✅ SessionStart/Stop | Hooks 全自动 |
| **hermes** | ✅ cao-evolution plugin | ✅ 同上 (复用) | ✅ external_dirs 加载 | ✅ on_session_end/pre_llm | hermes 自进化 + Plugin 自动同步 |
| **codex/copilot** | — | ✅ 同上 (复用) | ✅ SKILL.md | — | Skill 引导 |

**两层数据模型**：
- **任务层** `tasks/{task_id}/`：分数、attempts、grader、heartbeat 计数器 — 驱动进化心跳
- **知识层** `knowledge/`：notes、skills — 独立于任务，带标签元数据，支持跨任务召回

**多维评分（score_detail + evolution_signals）**：
- Attempt 支持 `score_detail: dict[str, float]` 存储多维度原始分数
- 新增 `evolution_signals: dict[str, Any]` 透明传递完整信号包（grader/judge/human/...）
- 各信号独立，不强制提供，不压缩为单一 blended_score
- 心跳 prompt 将 signals JSON 完整注入，模型自行判断如何利用
- `score` 保持为排行榜聚合值

**运行模式（默认 local）**：
- **local**（默认 ★）：纯本地进化，secskill-evo 风格，不需要 Hub。LLM-Judge + evals + 结构化重试
- **distributed**：完整分布式进化，需要 Hub，支持 grader + 心跳 + 知识共享
- **hybrid**：本地进化 + Hub 同步，两者并行
- 通过 `CAO_EVOLUTION_MODE` 环境变量切换，默认值为 `local`

**Skill 进化（secskill-evo 整合）**：
- LLM-as-Judge 语义评估（binary + soft score + confidence）
- 强制 evals.json 回归验证
- 结构化重试（max 2 attempts，每次换策略）
- TIP.md 进化经验积累
- 详见第十三节

**Git 远程同步**：
- 通过 `CAO_EVOLUTION_REMOTE` 环境变量配置远程仓库
- 每次 checkpoint 后自动 `pull --rebase` + `push`
- 推送失败不阻塞主流程（warning + 下次重试）

**心跳适配**：
- reflect：每次任务完成后（不变）
- consolidate：每完成 N 个任务后（改为按任务总数计数）
- pivot：仅当同 task 有多次执行时启用（弱化）
- Plugin 通过 `CAO_HEARTBEAT_ENABLED=1` 支持自动注入心跳 prompt

**知识召回（两阶段）**：
- 阶段 1（MVP）：git 全量同步 + grep + tags 过滤
- 阶段 2（知识膨胀后）：memsearch 语义搜索 + 选择性召回（接口不变，底层替换）

**Skill 双向同步**：
- 本地 skill（opencode/claude-code/hermes）→ cao_skill_sync → 共享池
- 共享池 skill → git pull → 本地各 Agent 自动加载

**hermes 融合**：
- 通过 external_dirs 读取共享 skill（零代码）
- 通过同步脚本将 hermes 本地进化产物推入共享池

**对 CAO 源代码的改动量**：
- `api/main.py`：追加 ~120 行路由（不改已有路由）
- `constants.py`：追加 ~10 行常量
- 新增 `evolution/` 包：~1200 行（绝大部分从 CORAL 原样移植）
- 新增 `prompts/` 目录：3 个 Markdown 文件
- `cao-bridge/` 各文件：各追加 20-40 行

**不改的**：providers、mcp_server、services、clients、models、cli — 全部不动。

**WebUI 进化展示**：在 CAO 前端追加 `/evolution` 页面，包含分数曲线图、排行榜、笔记浏览、Skill 预览（最后实现）。

**人工反馈机制**：Agent 提交漏洞报告 → Hub 注册 Unique Report ID → 人类标注 tp/fp + severity → Agent 拉取反馈 → 纳入 reflect 调整策略。双分轨制（auto_score + human_score），异步不阻塞进化主循环。


---

## 十三、Skill 进化机制 + secskill-evo 整合 + 运行模式

### 13.1 现状问题

当前系统支持 skill 的 **创建、检索、同步**，但不支持 **迭代优化**。具体来说：
- ✅ `cao_share_skill()` 创建新 skill → 写入共享池
- ✅ `cao_get_shared_skills()` 检索他人 skill
- ✅ `skill_sync.py` 本地 ↔ 共享池双向同步
- ❌ 无法评估 skill 质量（没有 eval 机制）
- ❌ 无法迭代改进 skill（写入后不可变）
- ❌ 心跳 prompt 只产出 notes，不触发 skill 优化
- ❌ 进化经验不积累（无 TIP.md）

### 13.2 secskill-evo 核心算法提取

从 secskill-evo 提取的 4 个关键机制：

#### ① LLM-as-Judge 语义评估

```
输入: skill 内容 + 失败案例 + 预期结果
输出:
  binary:  { is_correct: bool, confidence: 0.0-1.0, rationale: str }
  soft:    { score: 0-10 }
  detail:  { strengths: [...], weaknesses: [...] }
  hints:   ["Add instruction for X", "Include example of Y"]
```

核心: 无需编写 Python grader 即可评估 skill 质量。

#### ② 强制 evals 回归验证

每个 skill 目录下维护 `evals/evals.json`:
```json
{
  "skill_name": "sql-injection-scanner",
  "evals": [
    {
      "id": 1,
      "prompt": "Scan login.py for SQL injection",
      "expected_output": "Found parameterized query bypass at line 42",
      "assertions": [
        { "id": "a1", "text": "Identifies line 42 as vulnerable" },
        { "id": "a2", "text": "Suggests parameterized queries as fix" }
      ]
    }
  ]
}
```

进化前后必须通过所有 evals，防止回归。失败案例自动 seed 进 evals。

#### ③ 结构化重试（max 2 attempts）

```
git snapshot v{N}
  → 修改 skill
  → 运行 evals 验证
    ├── 提升/持平 → commit v{N+1} ✅
    └── 回归 → 诊断原因 → 换策略重试
                ├── 重试成功 → commit v{N+1} ✅
                └── 2次都失败 → revert 到 v{N} + 报告失败原因
```

#### ④ TIP.md 进化经验积累

每次进化后写入结构化经验:
```markdown
## Evolution: 2026-04-14
### Root Cause: 检测规则忽略了 prepared statement
### Changes: v3 → v4, 增加 PDO/MySQLi 模式匹配
### Learning: PHP 框架中 prepared statement 的写法多样
### Next Tip: 测试时覆盖 Laravel/Symfony/CodeIgniter 三种框架
```

### 13.3 多信号透明评分（不压缩为单一分数）

**设计原则**：不做 blended_score，保持评分来源和维度透明，让模型直接看到结构化 JSON。

#### 评分信号包（evolution_signals）

```json
{
  "signals": {
    "grader": {
      "source": "grader.py",
      "score": 0.75,
      "dimensions": {
        "precision": 0.8,
        "recall": 0.6,
        "f1": 0.686
      }
    },
    "judge": {
      "source": "llm-as-judge",
      "score": 7,
      "scale": "0-10",
      "confidence": 0.85,
      "strengths": ["Accurate SQL injection detection"],
      "weaknesses": ["Misses stored XSS patterns"]
    },
    "human": {
      "source": "human-annotation",
      "precision": 0.667,
      "tp": 2,
      "fp": 1,
      "annotated_reports": 1
    }
  },
  "meta": {
    "task_id": "scan-webapp",
    "agent_id": "agent-1",
    "eval_count": 5,
    "evals_since_improvement": 2
  }
}
```

**关键特性**：
- 各信号独立，不强制提供——grader 没有就不填，judge 没配就不填
- 信号数量不限于 3 个，未来可加 `peer_review`、`regression_test` 等
- 心跳 prompt 模板将完整 `signals` JSON 注入，模型自行判断如何利用
- 排行榜仍按 `score`（聚合值）排序，但 `score_detail` 和 `signals` 同时存储

#### 数据存储

```python
class Attempt:
    score: float                        # 主分数（排行榜用）
    score_detail: dict[str, float]      # 多维分数（已实现）
    evolution_signals: dict[str, Any]   # 新增：完整信号包（透明传递给模型）
```

#### 心跳 prompt 注入方式

```markdown
## 你的评估信号

```json
{evolution_signals_json}
```

基于以上多维信号，分析你的优势和不足，决定下一步策略。
注意：各信号来源不同（自动评分/语义评估/人工标注），权重由你自行判断。
```

### 13.4 三种运行模式

#### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `CAO_EVOLUTION_MODE` | `local` | `local` / `distributed` / `hybrid` |
| `CAO_HUB_URL` | (空) | Hub 地址，`local` 模式不需要 |
| `CAO_BRIDGE_ENABLED` | `0` | 是否启用 Hub 注册/轮询 |
| `CAO_HEARTBEAT_ENABLED` | `0` | 是否启用分布式心跳 |
| `CAO_GRADER_ENABLED` | `0` | 是否启用 grader.py 评分信号 |
| `CAO_JUDGE_ENABLED` | `1` | 是否启用 LLM-as-Judge 评分信号 |
| `CAO_LOCAL_EVOLUTION` | `1` | 是否启用本地进化循环 |
| `CAO_SKILL_WRITEBACK` | `1` | 是否回写 skill 到本地 Agent 目录 |

#### 模式 A: local（默认 ★）

面向 secskill-evo 用户和单机使用场景。**不需要启动 Hub。**

```
用户说 "evolve this skill" 或 心跳自动触发
    ↓
读取 skill + evals.json
    ↓
LLM-Judge 评估当前版本 → 生成 signals.judge
    ↓
git snapshot v{N} → 修改 skill
    ↓
运行 evals 验证
    ├── 通过 → commit v{N+1} + 更新 TIP.md
    └── 回归 → 诊断 + 重试(max 2) or revert
    ↓
signals 存入本地 .cao-evolution/
（不上报 Hub、不触发分布式心跳）
```

**环境变量**:
```bash
CAO_EVOLUTION_MODE=local    # 默认
CAO_JUDGE_ENABLED=1         # 默认
# 其他 Hub 相关开关均为 0（默认）
```

#### 模式 B: distributed

面向多 Agent 协作场景。需要 Hub。

```bash
CAO_EVOLUTION_MODE=distributed
CAO_HUB_URL=http://hub:9889
CAO_BRIDGE_ENABLED=1
CAO_HEARTBEAT_ENABLED=1
CAO_GRADER_ENABLED=1        # Hub 下发 grader.py
CAO_JUDGE_ENABLED=1          # 可选
```

完整 Hub 注册 → 轮询 → 评分 → 心跳 → 知识共享流程。

#### 模式 C: hybrid

本地进化 + 分布式同步。本地先跑 secskill-evo 风格的进化循环，同时将结果同步到 Hub。

```bash
CAO_EVOLUTION_MODE=hybrid
CAO_HUB_URL=http://hub:9889
CAO_LOCAL_EVOLUTION=1        # 本地进化循环
CAO_BRIDGE_ENABLED=1         # 同步到 Hub
CAO_HEARTBEAT_ENABLED=0      # Hub 心跳关闭，用本地进化触发
```

### 13.5 Skill 进化 prompt（新增）

新增 `prompts/evolve_skill.md`:

```markdown
## Skill 进化

技能 "{skill_name}" 需要改进。

### 评估信号
```json
{evolution_signals_json}
```

### 进化流程
1. 读取 skill 内容和 evals.json
2. 分析信号中的 weaknesses 和失败案例
3. 确定根因（逻辑错误/缺失能力/边界情况/方向错误）
4. git snapshot 当前版本
5. 修改 skill（保留已验证的功能，最小改动）
6. 运行 evals 验证
   - 通过 → 提交新版本 + 更新 TIP.md
   - 回归 → 诊断 + 换策略重试（最多2次）
7. 记录进化经验到 TIP.md

### 约束
- evals.json 必须存在，不存在则从失败案例创建
- 每次修改后必须过全量 evals
- 最多重试2次，全失败则 revert 并报告
- 更新 TIP.md 记录本次经验
```

### 13.6 本地模式进化：Agent 自行驱动

**核心原则**：在 local 模式下，**你就是 agent**——你加载了 skill 并在执行任务。不存在一个外部 Python 脚本来调度你。因此，进化由 **agent 自行驱动**，而非由代码编排器调度。

**触发方式**：用户在提示词中指定进化意图，agent 自行调用各独立模块完成流程。

**示例提示词**：
```
请改进 detect-sqli 这个 skill：
1. 先看一下 evals/detect-sqli.json 里的测试用例
2. 用当前 skill 内容对每个用例进行评估，找出失败的
3. 分析失败原因，改进 skill
4. 用全部 evals 验证改进后的版本没有回归
5. 把本次进化经验写入 TIP.md
```

**Agent 可用的独立模块**（⚠️ 已在 §14 重构中删除，功能迁移至 `evo-skills/` SKILL.md）：

| 模块 | 原函数 | 迁移至 |
|---|---|---|
| ~~`evals.py`~~ | `read_evals()`, `seed_from_failure()` | `evo-skills/secskill-evo/SKILL.md` Step 6 |
| ~~`judge.py`~~ | `evaluate_with_judge()`, `evaluate_batch()` | `evo-skills/secskill-evo/agents/judge.md` |
| ~~`evolve.py`~~ | `evolve_with_retry()` | `evo-skills/secskill-evo/SKILL.md` Step 5-8 |
| ~~`tip.py`~~ | `read_tip()`, `append_tip()` | `evo-skills/secskill-evo/SKILL.md` Step 9 |
| ~~`modes.py`~~ | `get_mode()`, `get_mode_config()` | 不再需要（SKILL.md 自带模式逻辑） |

> **注意**：上述 Python 模块已删除。Agent 现在通过读取 `evo-skills/` 下的 SKILL.md 来执行相同逻辑。
> 详见 **§14：自进化逻辑重构（evo-skills 迁移）**。

**与分布式模式的区别**：

| | Local（Agent 自行驱动） | Distributed（Hub 调度） |
|---|---|---|
| 进化触发 | 用户提示词 / skill 内嵌说明 | Hub 心跳触发（plateau/stagnation） |
| 信号来源 | Agent 自行运行 judge/evals | Hub 汇总 + grader.py + 心跳注入 |
| 信号消费 | Agent 直接看到，自行决策 | `{evolution_signals_json}` 注入 prompt |
| 适用场景 | 单 agent 交互式开发 | 多 agent 协同进化 |

**关键设计**：
- `evolve_fn` 签名为 4 参数 `(content, attempt_num, feedback, evolution_signals)`，确保进化函数能看到完整信号
- `evolve_with_retry()` 接受 `evolution_signals` 参数，透传给 evolve_fn
- 所有模块均为独立函数，agent 可按需组合，无需固定流程

### 13.7 实现计划

| 子步骤 | 内容 | 约行数 |
|---|---|---|
| 14a | `evolution_signals` 数据模型 + Attempt 扩展 + 心跳模板注入 signals JSON | ~80 |
| 14b | `evolve_skill.md` prompt + heartbeat 新增 `evolve_skill` 触发 + evals.json 读取/验证 | ~100 |
| 14c | LLM-as-Judge 评估函数 `evaluate_with_judge()` (调用模型 API 或本地) | ~80 |
| 14d | 结构化重试 `evolve_with_retry()` — snapshot/modify/validate/revert 循环 | ~80 |
| 14e | TIP.md 读写 + 运行模式开关 (`CAO_EVOLUTION_MODE` 环境变量路由) | ~60 |
| 14f | 测试 + E2E 验证 | ~120 |
| 14g | Code Review 修复 + 4-arg evolve_fn + 模板补全 | ~50 |


---

## 十四、自进化逻辑重构（evo-skills 迁移）

### 14.1 重构背景

Section 13 描述的 Python 模块（evolve.py、judge.py、evals.py、tip.py、modes.py）
存在以下问题：

1. **平台绑定**：Python 模块只能被运行 Python 的 Agent 使用，远程 Claude Code / opencode / Copilot 无法执行
2. **Hub 侧孤立代码**：这 5 个模块在 Hub 端零生产调用者（通过 `grep -rn` 确认），heartbeat 只发送 prompt 文本，不调用这些模块
3. **与 SKILL.md 范式冲突**：CAO 的 Agent 执行范式已经是"读 SKILL.md 指令执行"，Python 模块是上一代设计残余

### 14.2 重构方案：进化算法 → 平台无关 SKILL.md

将所有进化算法从 Hub 端 Python 模块迁移到独立的 **evo-skills/** 目录，作为平台无关的 SKILL.md 文件。
任何能读 Markdown 的 Agent（Claude Code、opencode、Codex、Copilot）都可以直接执行。

#### 目录结构

```
security-agent-orchestrator/evo-skills/
├── secskill-evo/                    ← 核心 FIX 算法（从 /secskill-evo 移入）
│   ├── SKILL.md                     ← 完整 Evolution Mode（10 步）
│   ├── agents/                      ← judge.md, analyzer.md, comparator.md, grader.md
│   ├── scripts/                     ← git_version.py, run_eval.py 等
│   ├── references/                  ← schemas.md
│   └── assets/                      ← eval_review.html
├── openspace-evo/                   ← OpenSpace 风格进化（DERIVED + CAPTURED）
│   └── SKILL.md                     ← 变异/交叉 + 模式提炼 + 谱系管理
├── cao-reflect/                     ← 反思 note 生成
│   └── SKILL.md                     ← 6 步结构化反思
├── cao-consolidate/                 ← 知识综合
│   └── SKILL.md                     ← 5 步跨 Agent 知识综合
└── cao-pivot/                       ← 策略转向
    └── SKILL.md                     ← 5 步激进策略变更
```

### 14.3 secskill-evo 适配

secskill-evo 已有完整的 Evolution Mode（Step 1-10），适配 CAO 的关键修改：

1. **`/tmp/cao-evo-workspace/` 隔离**：
   - `git_version.py` 中的 `_is_inside_git_repo()` 检测会发现 `.cao-evolution-client/` 的父 repo
   - 在父 repo 中操作会导致 tag 冲突（`v1`、`v2` 污染整个仓库）和 revert 影响所有文件
   - 解决：Step 4（Git Snapshot）先复制 skill 到 `/tmp/cao-evo-workspace/{skill-name}/`，在隔离目录中进化
   - Step 7（Git Commit）把结果复制回原目录 + 同步到 `.cao-evolution-client/`

2. **CAO Heartbeat 集成**：
   - SKILL.md 顶部增加 "CAO Heartbeat Integration" 说明
   - heartbeat prompt 传入的 `evolution_signals_json` 和 `leaderboard` 可直接使用

### 14.4 openspace-evo 设计

三大策略合一个 SKILL.md：

1. **DERIVED（变异/交叉）**：从现有 skill 派生新变体
   - 变异算子：specialize、generalize、augment、simplify、reframe
   - 交叉：combine 两个 skill 的优势部分
2. **CAPTURED（模式提炼）**：从工作过程中提取可复用 skill
   - 分析最近的工作记录和成功模式
   - 抽象为独立的可复用 skill
3. **谱系管理（.lineage.json）**：
   - 每个 skill 目录下维护 `.lineage.json` 跟踪血统关系
   - 单仓模式下通过 `ancestors` 字段构建完整谱系图

`.lineage.json` schema:
```json
{
  "skill_id": "scan-v3",
  "version": "3.0.0",
  "derivation": "DERIVED",
  "parent_ids": ["scan-v2"],
  "evolution_method": "openspace-evo",
  "created_at": "2025-01-01T00:00:00Z",
  "mutation_operators": ["specialize"],
  "mutation_description": "Added edge case handling",
  "parent_scores": {"scan-v2": 0.65},
  "child_score": null,
  "lineage_depth": 3,
  "ancestors": ["scan-v1", "scan-v2"]
}
```

### 14.5 heartbeat prompt 重写

原来 heartbeat prompt 内嵌完整指令（反思步骤、分析指导等），重构后改为 **轻量调度指令**：

| prompt 文件 | 旧内容 | 新内容 |
|---|---|---|
| `evolve_skill.md` | 内嵌进化步骤 | → 加载 secskill-evo SKILL.md |
| `reflect.md` | 内嵌反思指导 | → 加载 cao-reflect SKILL.md |
| `consolidate.md` | 内嵌综合步骤 | → 加载 cao-consolidate SKILL.md |
| `pivot.md` | 内嵌转向策略 | → 加载 cao-pivot SKILL.md |

详细指令由各 evo-skill SKILL.md 提供，prompt 仅传递上下文（signals、leaderboard）和调度目标。

### 14.6 Bridge Protocol 更新

**cao-bridge SKILL.md** 新增 Step 4.5 和 4.6：

```
Step 4.5: Handle Heartbeat
  如果 cao_report_score 返回的 heartbeat_prompts 非空：
  → 对每个 prompt：
    1. 读取 prompt — 指定了要执行哪个 evo-skill
    2. 从 evo-skills/ 或本地 skills 目录加载该 skill
    3. 按 SKILL.md 指令执行
    4. 同步：cd ~/.cao-evolution-client && git add -A && git commit && git push

Step 4.6: Post-Heartbeat Continuation
  所有 heartbeat 动作完成后：
  → 继续主任务
  → 下次完成时再 grader + cao_report_score
  → 循环回 Step 2
```

### 14.7 清理的孤立代码

| 文件 | 行数 | 原用途 | 迁移去向 |
|---|---|---|---|
| `evolution/evolve.py` | 131 | evolve_with_retry() | secskill-evo SKILL.md Step 5-8 |
| `evolution/judge.py` | 144 | evaluate_with_judge() | secskill-evo agents/judge.md |
| `evolution/evals.py` | 104 | read_evals/seed_from_failure | secskill-evo SKILL.md Step 6 |
| `evolution/tip.py` | 53 | read_tip/append_tip | secskill-evo SKILL.md Step 9 |
| `evolution/modes.py` | 89 | get_mode/is_feature_enabled | 不再需要（SKILL.md 自带模式逻辑） |

**保留的模块**（仍有生产调用者）：
- `heartbeat.py` — 触发逻辑 + prompt 渲染（Hub API 调用）
- `checkpoint.py` — Git checkpoint 操作
- `attempts.py` — Attempt CRUD
- `reports.py` — 人工反馈
- `grader_base.py` — Grader 基类
- `skill_sync.py` — Skill 双向同步
- `repo_manager.py` — 仓库管理
- `types.py` — 数据类型

### 14.8 测试验证

重构后测试结果：
- **255 / 255 通过**（原 289，移除 34 个测试孤立模块的测试）
- 保留的 8 个测试覆盖：
  - `TestEvolveSkillPrompt`（3 个）：prompt 加载、渲染、skill 引用检查
  - `TestEvolveSkillTrigger`（4 个）：plateau 触发、提前不触发、signals 传递
  - `TestApiSignalsFlow`（1 个）：API 端到端 signals 流

### 14.9 Heartbeat 完整触发链（重构后）

```
Hub: cao_report_score(score=0.5, signals={...})
  │
  ├── write attempt to .cao-evolution/shared/attempts/
  ├── check: evals_since_improvement >= 3?
  │     YES → heartbeat triggered
  │
  ├── HeartbeatRunner.check() → triggered actions: [reflect, pivot, evolve_skill]
  │
  ├── For each action:
  │     render_prompt(action, agent_id, task_id, evolution_signals=signals)
  │     → 替换 {evolution_signals_json}, {leaderboard}, {task_id} 占位符
  │
  └── HTTP Response: {heartbeat_prompts: [{name: "evolve_skill", prompt: "...secskill-evo..."}]}

Agent 端（MCP/Plugin/Skill bridge）:
  收到 heartbeat_prompts
  │
  ├── 读取 prompt → 发现要加载 evo-skills/secskill-evo/SKILL.md
  ├── 从本地 skills 目录或 evo-skills/ 加载 SKILL.md
  ├── 按 SKILL.md 指令执行 Evolution Mode（Step 1-10）
  │     ├── Step 4: 复制 skill 到 /tmp/cao-evo-workspace/
  │     ├── Step 5-6: 在隔离环境中改进 + 验证
  │     └── Step 7: 复制回原目录 + git sync
  │
  ├── cd ~/.cao-evolution-client && git add -A && git commit && git push
  └── 继续主任务 → 下次上报新分数
```

---

## 附录 A：进化原理详解

### A.1 分数与排行榜 — 选择压力

CORAL 的进化类比生物进化的三个环节：**变异 → 选择 → 遗传**。

**分数**是任务执行质量的量化指标，由 Grader（评估器）给出。Grader 是一段用户编写的评估代码，针对特定任务定义"好"的标准。例如：
- 安全审计任务：发现漏洞数量 × 严重程度 → 分数
- 文档撰写任务：覆盖度 + 准确性 + 可读性 → 分数
- 配置优化任务：运行评估脚本 → 性能指标 → 分数

分数上报到 Hub 后，Hub 做两件事：

1. **写入 Attempt 记录**：每次评估的完整快照（agent_id、score、score_detail、status、feedback），存为 JSON，纳入 git 管理
   - `score`：聚合后的单一分数，用于排行榜排序
   - `score_detail`：可选的多维分数 `dict[str, float]`（如 `{"accuracy": 0.9, "speed": 0.7}`），用于精细分析
2. **比较历史**：将本次分数与该 Agent 在同一任务下的历史最佳分数比较，得出 status：
   - `improved` — 超过历史最佳（正向信号）
   - `baseline` — 与最佳持平
   - `regressed` — 低于最佳（负向信号）
   - `crashed` / `timeout` — 执行失败

**排行榜 = 全局选择信号。** 它的核心消费者不是人，而是 Agent：
- **Pivot（转向）时参考**：当 Agent 陷入停滞，pivot 提示词会指引 Agent "去看排行榜前 3 名，分析他们的方法跟你有什么不同"
- **Reflect（反思）时参考**：Agent 回顾"我这次比上次分高还是低"，理解因果
- **Consolidate（综合）时参考**：决定哪些经验值得沉淀为知识

排行榜按 task_id 分区，不同任务的分数不可比较。

### A.2 历史比较 — 高原检测

每次 Agent 上报分数后，Hub 会追踪一个关键计数器：`evals_since_improvement`（连续无提升次数）。

```
Agent A 的评估历史（task_id=安全审计）:
  eval #1: score=0.72 → improved (首次)          evals_since_improvement = 0
  eval #2: score=0.78 → improved (超过0.72)       evals_since_improvement = 0
  eval #3: score=0.75 → regressed (低于0.78)      evals_since_improvement = 1
  eval #4: score=0.76 → regressed (仍低于0.78)    evals_since_improvement = 2
  eval #5: score=0.77 → regressed (仍低于0.78)    evals_since_improvement = 3
  eval #6: score=0.76 → regressed                 evals_since_improvement = 4
  eval #7: score=0.77 → regressed                 evals_since_improvement = 5 ← 触发 pivot!
```

当 `evals_since_improvement >= 5` 时，Hub 判定 Agent 陷入"高原"（局部最优），触发 pivot 心跳。

### A.3 心跳触发 — "教练喊暂停"

**心跳不是健康检查，而是"教练在比赛中叫暂停"。** 它是进化系统的核心调度机制。

三种心跳动作，各有不同的触发条件和目的：

| 动作 | 触发机制 | 触发条件 | 目的 | Agent 产出 |
|------|---------|---------|------|-----------|
| **reflect**（反思） | 间隔 | 每次 eval 后 (every=1) | 回顾最近改动的因果，总结经验 | 写入 `notes/` |
| **consolidate**（综合） | 间隔 | 全局每 10 次 eval (every=10, global=true) | 综合所有 Agent 的知识，提炼共性 | 写入 `notes/_synthesis/` |
| **pivot**（转向） | 高原 | 连续 5 次 eval 无提升 (plateau, every=5) | 跳出局部最优，尝试全新方向 | 写入 `notes/` + 改变策略 |

**触发后的执行流程：**
1. Hub 检测到条件满足
2. Hub 渲染 Prompt 模板（reflect.md / consolidate.md / pivot.md）
3. Hub 将 Prompt 通过 inbox 投递给远程 Agent
4. 远程 Plugin 在下次 poll 时获取 Prompt → 注入 TUI → Agent 执行反思/综合/转向

**CORAL 原版 vs CAO 的区别：**
- CORAL：Manager 通过 SIGINT 中断 Agent 进程 → 注入 prompt → 恢复
- CAO：Hub 通过 inbox 投递 → Plugin 在 TUI 注入（**无需中断进程**，更温和）

### A.4 知识生成 — LLM 驱动的沉淀

**知识不是系统自动生成的，而是 Agent 在收到心跳 Prompt 后自己写出来的。**

提示词就是"算法"，LLM 就是"执行引擎"。三种 Prompt 各引导不同类型的知识产出：

#### `reflect.md`（反思提示词）引导 Agent：
1. **锚定具体结果**：回顾最近尝试，哪些改动导致了分数提升或下降
2. **检查意外**：什么出乎意料？意外揭示了认知盲区
3. **分析因果**：最显著的结果为什么会发生？底层机制是什么
4. **评估信心**：对当前方向有多确定？什么证据会改变判断
5. **规划下一步**：基于反思，下一步具体试什么

#### `consolidate.md`（综合提示词）引导 Agent：
1. **阅读所有笔记**：浏览 `notes/` 目录，建立知识全景
2. **综合发现**：对 3+ 条相关笔记，生成综合文档到 `notes/_synthesis/`
3. **绘制关联**：更新 `notes/_connections.md`，记录跨类别的模式
4. **记录空白**：更新 `notes/_open-questions.md`，标注矛盾和知识缺口
5. **提取技能**：如果综合揭示了成熟的可复用技术 → 提升为 Skill

#### `pivot.md`（转向提示词）引导 Agent：
1. **诊断天花板**：分析为什么卡住了，当前方法的结构性局限
2. **研究排行榜**：看其他 Agent（尤其高分者）用的什么不同方法
3. **选择新方向**：不是微调，而是换一个根本不同的算法/框架/方法论
4. **从高分基线出发**：Checkout 排行榜最佳，在此基础上实施新方向

#### 三种知识产物的关系：

```
笔记（Notes）                     技能（Skills）
  = Agent 的发现和经验               = 可复用的操作配方
  ┌─────────────────────┐          ┌─────────────────────┐
  │ notes/               │          │ skills/{name}/      │
  │   insight-a.md       │  提升为  │   SKILL.md          │
  │   lesson-b.md       ─┼────────►│   scripts/          │
  │   _synthesis/*.md    │          │   examples/         │
  │   _connections.md    │          └─────────────────────┘
  │   _open-questions.md │
  └─────────────────────┘

Attempt 记录
  = 评估快照（隐含正例/反例）
  ┌─────────────────────┐
  │ attempts/{id}.json   │
  │  status: "improved"  │  ← 隐含正例
  │  status: "regressed" │  ← 隐含反例
  │  feedback: "..."     │  ← Grader 的具体反馈
  └─────────────────────┘
```

**不设显式正例/反例存储**。正负信号已隐含在 Attempt 的 status 和 feedback 中，Agent 在 reflect 时自然会引用。

#### Agent 如何使用积累的知识

**CORAL 的方式：指引式，而非自动注入。** Agent 不会自动获得知识，而是在特定时机被提示词"指引"去读取：

| 时机 | 提示词示例 | Agent 行为 |
|------|-----------|-----------|
| 启动/warmstart | "Review research notes in notes/" | 自己 `ls` 和 `cat` 文件 |
| reflect 心跳 | "Browse existing notes, review recent attempts" | 自己查阅 attempts 和 notes |
| pivot 心跳 | "Run leaderboard, show top attempts" | 主动查看排行榜 |
| consolidate 心跳 | "Read all notes, create synthesis" | 浏览所有笔记，写综合 |

**CORAL 的局限：没有语义召回。** Agent 被告知"去那个目录看看"，在同一任务下笔记都相关还行，但**跨任务时 Agent 不知道该看哪些笔记**。这是 memsearch 语义搜索可以补上的短板（见"知识召回层"一节）。

### A.5 多任务与混合评分设计

**场景**：系统中接入多个 Agent，执行不同任务（扫描 C++ 仓库、扫描 Java 仓库、配置检查、日志分析……）。即使提示词相同、对象不同（如两个仓库），也是不同的 task。**同 task 反复跑的情况少，每次基本是新任务。**

#### 两层评分模型

不是"分数跟 task_id 走"还是"跟 knowledge 走"二选一，而是**两层并存**：

```
第一层：任务评分（task_id 维度）
  → 分数跟任务走，驱动心跳触发（eval_count, evals_since_improvement）
  → 回答"这次任务做得好不好"
  → 即使同 task 只跑一次，也有意义：建立基线

第二层：知识评分（knowledge 维度）
  → note/skill 带标签元数据，独立于 task_id
  → 带 origin_task_id 和 origin_score（产生时的任务和分数）
  → confidence 随"被后续任务引用且后续任务得分高"而提升
  → 支持跨任务语义召回
```

#### 存储结构（任务 vs 知识分离）

```
.cao-evolution/shared/
  ├── tasks/                          # 任务维度（分数、attempts、grader）
  │   ├── security-audit/             # task_id = "security-audit"
  │   │   ├── grader.py               # 此任务的评分代码
  │   │   ├── task.yaml               # { name, description }
  │   │   ├── attempts/               # 此任务的所有评估记录
  │   │   └── heartbeat.json          # 此任务的心跳计数器
  │   └── config-check/               # task_id = "config-check"
  │       ├── grader.py
  │       ├── task.yaml
  │       └── attempts/
  │
  └── knowledge/                      # 知识维度（独立于任务）
      ├── notes/                      # 带 YAML frontmatter 标签
      │   ├── iptables-check.md
      │   ├── log-rotation.md
      │   └── _synthesis/             # consolidate 产出
      │       └── security-patterns.md
      ├── skills/                     # 带 YAML frontmatter 标签
      │   └── vuln-scanner/
      │       └── SKILL.md
      └── _connections.md             # 跨领域关联图
```

#### 知识元数据格式（YAML frontmatter）

每个 note/skill 文件自带上下文元数据：

```yaml
---
title: "检查 iptables 规则的高效方法"
tags: [security, networking, linux, firewall]
origin_task: security-audit          # 产生此知识时的任务
origin_score: 0.85                   # 产生时的任务得分
origin_attempt: abc123               # 对应的 attempt run_id
confidence: high                     # high（来自高分 attempt）/ medium / low
created_by: remote-opencode          # 产生此知识的 Agent
created_at: 2026-04-13T16:00:00Z
---
（正文内容）
```

#### 心跳适配（多任务、低重复场景）

原 CORAL 心跳适合"同一任务反复跑"。我们的场景下同 task 重复少，心跳触发需要适配：

| 心跳动作 | CORAL 原版触发 | 适配后触发 | 说明 |
|---------|---------------|-----------|------|
| **reflect** | 每次 eval (per-agent-per-task) | **每次任务完成后** (per-agent，不限 task) | 不变，每次都反思 |
| **consolidate** | 全局每 10 次 eval (same task) | **累计每 N 个已完成任务后** (global，按任务数) | 计数基准改为已完成任务总数 |
| **pivot** | 连续 5 次无提升 (same task) | **跨任务停滞检测**：连续 N 个不同任务的分数低于各自基线 | 或弱化：仅当同 task 有多次执行时才启用 |

远程 Agent 在心跳触发时可以**双维度回顾**：

```markdown
## 心跳反思（混合维度提示词模板）

### A. 任务维度
你在 task "{task_id}" 上的得分: {current_score}, 状态: {status}
{如有历史: 历史分数: {score_history}}

### B. 知识维度
你近期产出的知识:
  - note: "{note_title}" (tags: {tags}, confidence: {confidence})
  - skill: "{skill_name}" (被引用 {ref_count} 次)
相关领域已有知识（搜索结果）:
  - "{related_note}" (score: {relevance})

根据以上信息，决定是改进当前任务策略，还是提炼可复用知识。
```

#### 规则

1. **分数比较** — 仅在同一 task_id 内
2. **排行榜** — 按 task_id 独立
3. **心跳触发** — reflect/consolidate 按 Agent 的已完成任务总数；pivot 仅当同 task 有多次执行时启用
4. **知识（notes/skills）** — 独立于 task_id，放在 `knowledge/` 下，带标签和来源信息
5. **Grader** — 每个 task_id 有独立的 `grader.py`，随 git 同步
6. **知识 confidence** — 初始由 origin_score 决定（高分 → high），后续被其他任务引用并得高分时可提升
7. **分数反馈即时返回**：Agent 上报分数后，Hub 返回 `{ status: "improved", leaderboard_position: 2 }`

---

## 十五、Recall + 选择性同步

> **详细设计文档**：`recall-selective-sync-design.md`

### 15.1 问题

当共享知识库增长（大量 skill/note/attempt），远程 Agent 不能全量同步。
需要 **远程发现** → **选择性拉取整个文件** → **本地进化** → **增量推回**。

### 15.2 架构概览

```
                         Hub (Central)
                         ┌────────────────────────────┐
                         │  RecallIndex (BM25 内存索引) │
Agent ──recall()──────>  │  扫描所有仓：               │
       query="sql inj"  │  skills/ notes/ attempts/   │
                         │  graders/                   │
Agent <──metadata────── │  BM25 粗排 + 元数据精排     │
       [{id, score, ...}]│                             │
                         │                             │
Agent ──fetch()/git──>   │  返回完整文件              │
Agent <──full file────── │                             │
                         │                             │
Agent ──push/git push─>  │  写入 + checkpoint          │
                         │  recall_index.add()         │
                         └────────────────────────────┘
```

### 15.3 实施分期

#### Phase A（已完成 ✅）：扁平目录 + 路径抽象 + 增强 task.yaml

直接采用目标多仓目录结构，为 Phase B 多仓拆分做零修改准备：

1. **RepoManager**（`evolution/repo_manager.py`）— 路径抽象层
   - 单仓模式：`get_dir("skills")` → `skills/`
   - 多仓模式（Phase B）：`get_dir("skills")` → `skills/`（路径不变，git root 变为 `skills/.git`）
2. **扁平目录布局** — 移除 `shared/` 和 `knowledge/` 中间层，直接 `skills/`、`notes/`、`attempts/`、`graders/` 等
3. **`shared_dir()` 返回根目录** — `Path(evolution_dir)` 而非 `Path(evolution_dir) / "shared"`
4. **增强 task.yaml** — 新增 `grader`（引用路径）、`tips`、`eval_data_path`、`created_by`、`last_updated`
5. **远程 Agent 注册任务** — Bridge `create_task()` + MCP `cao_create_task` / `cao_list_tasks`
6. **Grader 引用解析** — 内联 `grader.py` → `task.yaml` 中 `grader:` 字段 → `graders/` 目录查找

#### Phase B（未来实施）：完整 recall + 多仓

1. **RecallIndex**（`evolution/recall_index.py`）— Hub 端 BM25 + 元数据精排索引
2. **recall API**（3 个端点）：`GET /recall`（发现）、`GET /recall/{type}/{id}`（拉取）、`POST /recall/batch`（批量）
3. **search_knowledge()** — grep → RecallIndex.search()
4. **CaoBridge** 新增 `recall()` / `fetch()` / `selective_sync()`
5. **MCP tool** — `recall_knowledge`
6. **多仓拆分** — skills.git / notes.git / attempts.git / graders.git

### 15.4 未来仓库演进

```
当前 (Phase A, 已完成):              未来 (Phase B):
~/.cao-evolution/                   ~/.cao-evolution/
├── .git/         ← 一个 git 仓     ├── skills/      ← Git 仓 1
├── skills/                          ├── notes/       ← Git 仓 2
├── notes/                           ├── attempts/    ← Git 仓 3
├── attempts/                        ├── graders/     ← Git 仓 4
├── graders/                         ├── tasks/       ← 普通目录
├── tasks/                           └── heartbeat/   ← git-ignored
├── reports/
└── heartbeat/    ← git-ignored
```

迁移时只改 RepoManager 的 `mode` 参数，Agent 侧代码无需改动。

### 15.5 Agent 端同步方式（已实现 ✅）

所有远程 Agent 统一使用 `git clone + pull` 同步，克隆到 `~/.cao-evolution-client/`：

| Agent 环境 | 同步模块 | 触发时机 | 实现文件 |
|---|---|---|---|
| opencode | `cao-bridge.ts` → `gitSync()` | 启动 + 每次任务完成 | `cao-bridge/plugin/cao-bridge.ts` |
| Claude Code | `cao-session-start.sh` → `git clone/pull` | session start/stop hooks | `cao-bridge/claude-code/hooks/*.sh` |
| hermes | `git_sync.init_client_repo()` + `pull()` | on_session_start/end | `cao-bridge/hermes/__init__.py` |
| codex/copilot | MCP `cao_sync` + `cao_pull_skills` | agent 主动调用 | `cao-bridge/cao_bridge_mcp.py` |
| 降级/手动 | `hermes-sync.sh` | cron 或手动 | `cao-bridge/hermes/hermes-sync.sh` |

```
Hub Machine                              Remote Agent Machine
┌──────────────────────┐                ┌──────────────────────────────┐
│ ~/.cao-evolution/     │                │ ~/.cao-evolution-client/     │
│ ├── skills/           │   git push     │ ├── skills/     ← git pull  │
│ ├── notes/            │ ──────────→    │ ├── notes/                  │
│ ├── tasks/            │  (bare repo)   │ ├── tasks/                  │
│ ├── attempts/         │ ←──────────    │ ├── attempts/               │
│ └── .git/             │   git push     │ └── .git/                   │
│                       │  (agent侧)    │                              │
│ Hub API (:9889)       │                │ pull_skills_to_local()       │
│ POST /evolution/...   │                │ → ~/.config/opencode/skills/ │
│ 写文件 → checkpoint   │                │ → ~/.hermes/skills/          │
│ → git push            │                │ → ~/.claude/skills/          │
└──────────────────────┘                └──────────────────────────────┘
```

**环境变量**：

| 变量 | 作用 | Hub 侧 | Agent 侧 |
|---|---|---|---|
| `CAO_EVOLUTION_REMOTE` | git 远程仓库 URL | ✅ Hub push 目标 | — |
| `CAO_GIT_REMOTE` | git 远程仓库 URL | — | ✅ Agent clone 来源 |
| `CAO_CLIENT_DIR` | Agent 本地 clone 路径 | — | 默认 `~/.cao-evolution-client` |

**两个 URL 指向同一个 git 仓库**（bare repo / GitHub / GitLab 等）。
同机部署时 `CAO_GIT_REMOTE=file:///home/user/.cao-evolution` 也可直接 clone Hub 本地 repo。

**不存在 HTTP 降级路径**：所有 Agent（含 hermes）统一使用 git 同步。

### 15.6 与 Step 11（memsearch）的关系

recall 机制覆盖了原 Step 11 的 memsearch 需求：
- **Phase A**（当前）：目录结构 + 路径抽象准备
- **Phase B**（未来）：BM25 零依赖 recall，预留 `embed_fn` 接口可接入 memsearch 语义增强

Step 11 的原定"memsearch 知识搜索适配"目标已被 recall 机制覆盖。

---
