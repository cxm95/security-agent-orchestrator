# Skill 进化同步管线设计：AS-IS → TO-BE

> Auto-Pull 时机 + Skill 收编（Adopt）机制

---

## 1. 核心概念

### 目录角色

| 路径 | 角色 | 说明 |
|------|------|------|
| `evo-skills/` | 源码仓种子 | 项目仓库中的 skill 模板，通过 `install.sh` 一次性安装 |
| `~/.config/opencode/skills/` | Agent 本地 (opencode) | agent 运行时加载的 skill 目录 |
| `~/.claude/skills/` | Agent 本地 (claude-code) | 同上，claude-code 平台 |
| `~/.hermes/skills/` | Agent 本地 (hermes) | 同上，hermes 平台 |
| `~/.cao-evolution-client/skills/` | Git 工作副本 | 从 shared repo clone 的工作目录，双向同步中转站 |
| `~/.cao-evolution-local/shared.git` | 共享 Bare Repo | local 模式下所有 agent 实例的共享仓库 |
| `/tmp/cao-evo-workspace/<skill>/` | 隔离进化工作区 | secskill-evo 在此修改 skill，验证通过后 rsync 回本地 |

### 共享前缀规则

只有 `cao-` 前缀的 skill 参与同步管线。非前缀 skill 视为 agent 私有。

```python
SHARED_SKILL_PREFIX = "cao-"
def is_shared_skill(name): return name.startswith(SHARED_SKILL_PREFIX)
```

---

## 2. AS-IS：当前 Skill 进化同步流程

### 2.1 完整流程图（含路径追踪）

```
═══════════════════════════════════════════════════════════════════════
  AS-IS: Skill 进化 + 同步完整流程（以 opencode 为例）
═══════════════════════════════════════════════════════════════════════

                    ┌─────────────────────────────┐
                    │  源码仓 evo-skills/cao-X/    │
                    │  (项目 git 仓库)             │
                    └──────────────┬──────────────┘
                                   │
                          install.sh --global
                          (一次性种子安装)
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Agent 本地 skills 目录                                              │
│  ~/.config/opencode/skills/cao-X/SKILL.md                           │
│                                                                     │
│  ┌─────────────────┐    ┌─────────────────┐    ┌────────────────┐  │
│  │ cao-secnote/     │    │ cao-reflect/     │    │ my-scanner/    │  │
│  │ (共享，参与同步)  │    │ (共享，参与同步)  │    │ (私有，不同步)  │  │
│  └─────────────────┘    └─────────────────┘    └────────────────┘  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
     cao_push 时           secskill-evo          cao_pull_skills
     自动收集               进化流程               手动拉取
          │                    │                    │
          ▼                    ▼                    │
  ┌──────────────┐   ┌──────────────────┐          │
  │import_local_ │   │ /tmp/cao-evo-    │          │
  │skills()      │   │ workspace/cao-X/ │          │
  │              │   │ (隔离修改+验证)   │          │
  │ 扫描 cao-*   │   └────────┬─────────┘          │
  │ 跳过非前缀   │            │                    │
  └──────┬───────┘    rsync (验证通过后)            │
         │                    │                    │
         │                    ▼                    │
         │     ~/.config/opencode/skills/cao-X/    │
         │     (agent 本地已更新)                    │
         │                    │                    │
         │         cao_push (手动触发)              │
         │                    │                    │
         ▼                    ▼                    │
  ┌───────────────────────────────────────────┐    │
  │  import_local_skills()                     │    │
  │                                           │    │
  │  ~/.config/opencode/skills/cao-X/          │    │
  │    ──shutil.copytree──→                   │    │
  │  ~/.cao-evolution-client/skills/cao-X/     │    │
  │                                           │    │
  │  (只复制 cao-* 前缀，跳过 my-scanner 等)   │    │
  └─────────────────────┬─────────────────────┘    │
                        │                          │
                        ▼                          │
  ┌───────────────────────────────────────────┐    │
  │  git_sync.push()                           │    │
  │  在 ~/.cao-evolution-client/ 内:            │    │
  │                                           │    │
  │  git add -A                               │    │
  │  git commit -m "[agent] evolve: cao-X v2" │    │
  │  git pull --rebase origin main            │    │
  │  git push origin main                     │    │
  │    → ~/.cao-evolution-local/shared.git     │    │
  └─────────────────────┬─────────────────────┘    │
                        │                          │
                        │    ┌─────────────────────┘
                        │    │
                        ▼    ▼
  ┌───────────────────────────────────────────┐
  │  ~/.cao-evolution-local/shared.git         │
  │  (Local Bare Repo — 所有实例共享)           │
  └─────────────────────┬─────────────────────┘
                        │
              其他 Agent 实例
              手动调用 cao_pull_skills()
                        │
                        ▼
  ┌───────────────────────────────────────────┐
  │  pull_skills_to_local()                    │
  │                                           │
  │  ① git pull (更新 ~/.cao-evolution-client/)│
  │                                           │
  │  ② ~/.cao-evolution-client/skills/cao-X/   │
  │     ──shutil.copytree──→                  │
  │     ~/.config/opencode/skills/cao-X/       │
  │                                           │
  │  (只复制 cao-* 前缀)                       │
  └───────────────────────────────────────────┘
```

### 2.2 各平台 Auto-Pull 现状

```
┌─────────────────────────────────────────────────────────────────┐
│                    Session 生命周期                               │
│                                                                 │
│  Session Start          任务执行          任务间隙          End  │
│  ─────┬─────────────────┬───────────────┬──────────────────┬──  │
│       │                 │               │                  │    │
│  ┌────┴────┐       ┌────┴────┐     ┌────┴────┐       ┌────┴──┐ │
│  │ Pull    │       │ Push    │     │ Pull?   │       │ Push  │ │
│  │ Skills  │       │ Notes   │     │ Skills  │       │ Skills│ │
│  └─────────┘       └─────────┘     └─────────┘       └───────┘ │
│                                                                 │
│  OpenCode:  ✅ pull          ✅ push    ✅ pull (grader后)  ✅ push │
│  ClaudeCode:✅ pull          ✅ push    ❌ 无 pull          ✅ push │
│  Hermes:    ✅ pull          ✅ push    ❌ 无 pull          ✅ push │
│  MCP-only:  ❌ 手动          ✅ push    ❌ 手动             ✅ push │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 AS-IS 问题

1. **Claude Code / Hermes 任务间无 pull**：Agent A 在 tick 3 进化了 cao-secnote 并 push，Agent B 在 tick 4 仍使用旧版本，直到下次 session restart。

2. **非 `cao-` skill 无法共享**：用户在本地创建了 `my-scanner` skill，表现良好想共享给其他 agent，但没有机制将其纳入同步管线。必须手动重命名为 `cao-my-scanner`。

3. **secskill-evo 文档 bug**：Step 7 中 `cd ~/.cao-evolution-client && git push` 不会包含进化后的 skill（rsync 目标是 agent 本地目录，不是 git clone）。正确做法是调用 `cao_push`（内部先 `import_local_skills`）。

---

## 3. TO-BE：增强后的 Skill 进化同步流程

### 3.1 变更概览

| 变更 | 说明 |
|------|------|
| Claude Code mid-session pull | `cao-stop-grader.py` 的 `poll_or_allow()` 中加入 skill pull |
| Hermes mid-session pull | `on_end()` push 后立即 pull，为下一 session 准备最新 skill |
| `cao_adopt_skill` MCP 工具 | 将非 `cao-` skill 复制一份加前缀，纳入共享管线 |
| secskill-evo Step 7 修正 | 明确使用 `cao_push` 而非直接 git 操作 |

### 3.2 完整 TO-BE 流程图（含路径追踪）

```
═══════════════════════════════════════════════════════════════════════
  TO-BE: Skill 进化 + 同步 + 收编 完整流程
═══════════════════════════════════════════════════════════════════════

                    ┌─────────────────────────────┐
                    │  源码仓 evo-skills/cao-X/    │
                    │  (项目 git 仓库)             │
                    └──────────────┬──────────────┘
                                   │
                          install.sh --global
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Agent 本地 skills 目录                                              │
│  ~/.config/opencode/skills/                                         │
│                                                                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────────┐  │
│  │ cao-secnote/     │  │ cao-reflect/     │  │ my-scanner/        │  │
│  │ (共享)           │  │ (共享)           │  │ (私有 → 可收编)    │  │
│  └─────────────────┘  └─────────────────┘  └─────────┬──────────┘  │
│                                                       │            │
│                                              cao_adopt_skill       │
│                                              ("my-scanner")        │
│                                                       │  [NEW]     │
│                                                       ▼            │
│                                            ┌────────────────────┐  │
│                                            │ cao-my-scanner/    │  │
│                                            │ (复制品，进入管线)  │  │
│                                            └────────────────────┘  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
     cao_push 时           secskill-evo          auto-pull
     自动收集               进化流程             (平台触发)
          │                    │                    │
          ▼                    ▼                    │
  ┌──────────────┐   ┌──────────────────┐          │
  │import_local_ │   │ /tmp/cao-evo-    │          │
  │skills()      │   │ workspace/cao-X/ │          │
  │              │   │ (隔离修改+验证)   │          │
  │ 扫描 cao-*   │   └────────┬─────────┘          │
  │ 含 cao-my-   │            │                    │
  │ scanner      │    rsync (验证通过后)            │
  └──────┬───────┘            │                    │
         │                    ▼                    │
         │     ~/.config/opencode/skills/cao-X/    │
         │     (agent 本地已更新)                    │
         │                    │                    │
         │         cao_push (手动或自动)             │
         │                    │                    │
         ▼                    ▼                    │
  ┌───────────────────────────────────────────┐    │
  │  import_local_skills()                     │    │
  │                                           │    │
  │  agent 本地 cao-* skills                   │    │
  │    ──copytree──→                          │    │
  │  ~/.cao-evolution-client/skills/           │    │
  └─────────────────────┬─────────────────────┘    │
                        │                          │
                        ▼                          │
  ┌───────────────────────────────────────────┐    │
  │  git push → shared.git                     │    │
  └─────────────────────┬─────────────────────┘    │
                        │                          │
                        ▼                          │
  ┌───────────────────────────────────────────┐    │
  │  ~/.cao-evolution-local/shared.git         │    │
  │  (Local Bare Repo)                         │    │
  └─────────────────────┬─────────────────────┘    │
                        │                          │
              ┌─────────┴──────────┐               │
              │                    │               │
         其他 Agent            当前 Agent           │
         (auto-pull)          (auto-pull)  ◄───────┘
              │                    │
              ▼                    ▼
  ┌───────────────────────────────────────────┐
  │  pull_skills_to_local()                    │
  │                                           │
  │  git pull → copytree cao-* → agent 本地    │
  └───────────────────────────────────────────┘
```

### 3.3 TO-BE 各平台 Auto-Pull 时机

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Session 生命周期 (TO-BE)                          │
│                                                                     │
│  Session Start     任务执行     Grader+HB     任务间隙         End  │
│  ─────┬────────────┬───────────┬─────────────┬────────────────┬──  │
│       │            │           │             │                │    │
│  ┌────┴────┐  ┌────┴────┐ ┌───┴────┐  ┌─────┴─────┐   ┌─────┴──┐ │
│  │ Pull    │  │ Push    │ │ Score  │  │ Pull      │   │ Push   │ │
│  │ Skills  │  │ Notes   │ │ Report │  │ Skills    │   │ Skills │ │
│  └─────────┘  └─────────┘ └────────┘  └───────────┘   └────────┘ │
│                                                                     │
│  OpenCode:  ✅ pull     ✅ push    ✅ score   ✅ pull (已有)   ✅ push │
│  ClaudeCode:✅ pull     ✅ push    ✅ score   ✅ pull [NEW]    ✅ push │
│  Hermes:    ✅ pull     ✅ push    ✅ score   ✅ pull [NEW]    ✅ push │
│  MCP-only:  ❌ 手动     ✅ push    —         ❌ 手动          ✅ push │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.4 Claude Code Auto-Pull 实现点

```
cao-stop-grader.py :: poll_or_allow()
─────────────────────────────────────

  当前 (AS-IS):                      改后 (TO-BE):
  ┌──────────────────┐               ┌──────────────────┐
  │ poll Hub for     │               │ [NEW] git pull    │
  │ next task        │               │ shared repo       │
  │                  │               ├──────────────────┤
  │ if task:         │               │ [NEW] copy cao-*  │
  │   inject prompt  │               │ → ~/.claude/skills │
  │ else:            │               ├──────────────────┤
  │   allow (pass)   │               │ poll Hub for     │
  └──────────────────┘               │ next task        │
                                     │                  │
                                     │ if task:         │
                                     │   inject prompt  │
                                     │ else:            │
                                     │   allow (pass)   │
                                     └──────────────────┘

  触发条件: CAO_PUSH_ONLY != "1"
  调用位置: idle phase 每次进入 poll_or_allow() 时
  涉及路径:
    ~/.cao-evolution-client/  ← git pull
    ~/.cao-evolution-client/skills/cao-*  → ~/.claude/skills/cao-*
```

### 3.5 Hermes Auto-Pull 实现点

```
hermes/__init__.py :: on_end()
──────────────────────────────

  当前 (AS-IS):                      改后 (TO-BE):
  ┌──────────────────┐               ┌──────────────────┐
  │ push skills      │               │ push skills      │
  │ push memory      │               │ push memory      │
  │ git push         │               │ git push         │
  │ grader queue     │               │ grader queue     │
  │ report score     │               │ report score     │
  │ close session    │               ├──────────────────┤
  └──────────────────┘               │ [NEW] git pull   │
                                     │ [NEW] pull skills│
                                     │   to local       │
                                     ├──────────────────┤
                                     │ close session    │
                                     └──────────────────┘

  触发条件: 无条件（push 后立即 pull，为下一 session 准备）
  涉及路径:
    ~/.cao-evolution-client/  ← git pull
    ~/.cao-evolution-client/skills/cao-*  → ~/.hermes/skills/cao-*
```

---

## 4. Skill 收编（Adopt）机制

### 4.1 问题

Agent 在本地创建了一个好用的 skill（如 `my-scanner`），想共享给其他 agent。
但当前同步管线只认 `cao-` 前缀，非前缀 skill 完全被忽略。

### 4.2 设计：`cao_adopt_skill` MCP 工具

```
cao_adopt_skill(skill_name="my-scanner", new_name="")
```

### 4.3 收编流程图

```
  Agent 调用: cao_adopt_skill("my-scanner")
      │
      ▼
  ┌──────────────────────────────────────────────┐
  │ Step 1: 查找源 skill                          │
  │                                              │
  │ 按顺序扫描候选目录:                            │
  │   ~/.claude/skills/my-scanner/SKILL.md        │
  │   ~/.config/opencode/skills/my-scanner/       │
  │   ~/.hermes/skills/my-scanner/                │
  │                                              │
  │ 找到第一个包含 SKILL.md 的目录 → 确定源路径     │
  │ 全部未找到 → 返回错误                          │
  └──────────────────────┬───────────────────────┘
                         │
                         ▼
  ┌──────────────────────────────────────────────┐
  │ Step 2: 检查冲突                              │
  │                                              │
  │ 目标名: cao-my-scanner                        │
  │ 检查同目录下是否已存在 cao-my-scanner/          │
  │                                              │
  │ 已存在 → 返回错误 (不覆盖)                     │
  │ 不存在 → 继续                                 │
  └──────────────────────┬───────────────────────┘
                         │
                         ▼
  ┌──────────────────────────────────────────────┐
  │ Step 3: 复制                                  │
  │                                              │
  │ shutil.copytree(                             │
  │   src:  ~/.config/opencode/skills/my-scanner/ │
  │   dest: ~/.config/opencode/skills/            │
  │         cao-my-scanner/                       │
  │ )                                            │
  │                                              │
  │ 原始 my-scanner/ 保持不变（不移动、不删除）     │
  └──────────────────────┬───────────────────────┘
                         │
                         ▼
  ┌──────────────────────────────────────────────┐
  │ Step 4: 返回结果                              │
  │                                              │
  │ {                                            │
  │   "adopted": "cao-my-scanner",               │
  │   "source": "my-scanner",                    │
  │   "source_path": "~/.config/opencode/skills/ │
  │                   my-scanner",               │
  │   "dest_path": "~/.config/opencode/skills/   │
  │                 cao-my-scanner"               │
  │ }                                            │
  └──────────────────────┬───────────────────────┘
                         │
                         │  (agent 后续操作)
                         ▼
  ┌──────────────────────────────────────────────┐
  │ 收编后进入正常同步管线:                         │
  │                                              │
  │ cao_push()                                   │
  │   → import_local_skills() 发现 cao-my-scanner │
  │   → copytree → ~/.cao-evolution-client/skills/ │
  │   → git push → shared.git                    │
  │                                              │
  │ 其他 Agent:                                   │
  │   cao_pull_skills() 或 auto-pull              │
  │   → 获得 cao-my-scanner                       │
  │                                              │
  │ secskill-evo:                                │
  │   可对 cao-my-scanner 进行进化                 │
  └──────────────────────────────────────────────┘
```

### 4.4 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 复制 vs 移动 | 复制 | 原始 skill 保持不变，agent 仍可用原名触发 |
| 自动 push | 否 | 收编是本地操作，agent 决定何时 push |
| 修改 SKILL.md | 否 | frontmatter name 保持原值，目录名决定共享身份 |
| 已存在时覆盖 | 否 | 返回错误，避免意外覆盖已进化的版本 |
| new_name 参数 | 可选 | 默认 `cao-{原名}`，可自定义（不含 `cao-` 前缀） |

---

## 5. 完整路径追踪：一个 Skill 从创建到跨 Agent 进化的全生命周期

```
═══════════════════════════════════════════════════════════════════════
  Skill 全生命周期路径追踪（TO-BE）
═══════════════════════════════════════════════════════════════════════

  ① 创建
  Agent A 在本地创建 skill:
    ~/.config/opencode/skills/my-scanner/SKILL.md

  ② 收编 [NEW]
  Agent A 调用 cao_adopt_skill("my-scanner"):
    ~/.config/opencode/skills/my-scanner/
      ──copytree──→
    ~/.config/opencode/skills/cao-my-scanner/

  ③ Push 到共享仓
  Agent A 调用 cao_push():
    ~/.config/opencode/skills/cao-my-scanner/
      ──import_local_skills──→
    ~/.cao-evolution-client/skills/cao-my-scanner/
      ──git push──→
    ~/.cao-evolution-local/shared.git

  ④ 其他 Agent 获取
  Agent B auto-pull (或手动 cao_pull_skills):
    ~/.cao-evolution-local/shared.git
      ──git pull──→
    ~/.cao-evolution-client/skills/cao-my-scanner/
      ──copytree──→
    ~/.config/opencode/skills/cao-my-scanner/

  ⑤ 进化
  Agent B 使用 cao-my-scanner 执行任务，发现不足
  Agent B 触发 secskill-evo Evolution Mode:
    ~/.config/opencode/skills/cao-my-scanner/
      ──cp -r──→
    /tmp/cao-evo-workspace/cao-my-scanner/
      (隔离修改 + 验证)
      ──rsync──→
    ~/.config/opencode/skills/cao-my-scanner/  (已进化)

  ⑥ 进化后 Push
  Agent B 调用 cao_push():
    ~/.config/opencode/skills/cao-my-scanner/  (v2)
      ──import_local_skills──→
    ~/.cao-evolution-client/skills/cao-my-scanner/
      ──git push──→
    ~/.cao-evolution-local/shared.git

  ⑦ 进化扩散
  Agent A auto-pull:
    shared.git → git pull → copytree → agent 本地
    Agent A 现在也有 cao-my-scanner v2

  ⑧ 毕业回写（手动，未自动化）
  用户手动将进化稳定的 skill 合并回源码仓:
    ~/.cao-evolution-client/skills/cao-my-scanner/
      ──手动 cp──→
    /path/to/project/evo-skills/cao-my-scanner/
      ──git commit──→ 源码仓
```

---

## 6. 实现清单

| 文件 | 改动 | 说明 |
|------|------|------|
| `cao-bridge/cao_bridge_mcp.py` | 新增 `cao_adopt_skill` tool | MCP 工具入口 |
| `cao-bridge/cao_bridge.py` | 新增 `adopt_skill()` 方法 | 查找 + 复制逻辑 |
| `cao-bridge/claude-code/hooks/cao-stop-grader.py` | `poll_or_allow()` 加 pull | Mid-session auto-pull |
| `cao-bridge/hermes/__init__.py` | `on_end()` 加 pull | Session end auto-pull |
| `evo-skills/secskill-evo/SKILL.md` | Step 7 修正 | 明确使用 `cao_push` |

Local 模式暂不改动，保持手动 `cao_pull_skills`。
