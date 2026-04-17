# 提示词：生成 SecAgentNet 3D 可视化 HTML

## 任务

请生成一个单文件 `secagentnet-viz.html`，用三维可视化展示 SecAgentNet 分布式多 Agent 协同自进化框架的**完整工作原理**。

**最重要的目标**：把整个机制的细节讲清楚 —— 深入到 task.yaml、attempt.json、一系列 MCP 工具、Plugin、heartbeat 机制、Note/Skill 知识系统的具体流转。不追求平滑摄像机动画和交互式面板，而是追求**信息密度和机制可理解性**。

技术要求：纯前端单文件 HTML，使用 Three.js（通过 CDN importmap 加载），OrbitControls 支持拖拽旋转和缩放。

---

## 视觉风格与渲染要点

- 背景：深蓝黑 `#0a0a1a`
- 地面：深色网格 (`GridHelper` + 深色平面)
- 雾：轻微指数雾 `FogExp2(0x0a0a1a, 0.012)` 增加深度感
- 光照：环境光 `(0x556688, 2.0)` + 方向光 `(1.0)` + 边缘光 `(0x4A90D9, 0.5)` + 填充光 `(0x8866aa, 0.3)`。光照要足够亮，确保建筑在深色背景上清晰可见
- 标签：用 CanvasTexture Sprite 实现（`depthTest: false`），支持多行文本（`\n` 分割），sprite scale 除以 60（不是 80，确保标签够大）
- 相机初始位置 `(25, 20, 25)` 看向 `(0, 4, 0)`，比默认更近以确保标签可读

### 方块（makeBox）渲染规则 —— 关键

方块是整个场景的核心视觉元素，必须在深色背景上**清晰可辨**：

1. 材质用 `MeshPhysicalMaterial`，`emissive` 设为自身颜色，`emissiveIntensity: 0.2`（始终微微自发光）
2. 边框用**双层线框**：内层 `EdgesGeometry` 用亮化颜色（原色 `.lerp(white, 0.35)`），`opacity: 1.0`；外层比内层大 `0.06`，`opacity: 0.3`，形成光晕轮廓
3. 建筑颜色不要用纯黑/近黑（如 `0x1a1a3a`），要用可辨识的深色调（如 `0x1e2845` 深蓝、`0x2e1e45` 深紫、`0x3a4060` 深灰蓝）

### 透明物体嵌套的 depth 处理

当小方块嵌套在大方块内部时（如 Agent 中层的子模块），必须：
- 外层大方块设 `material.depthWrite = false`
- 内层小方块设 `renderOrder = 1`
- 内层小方块在 z 轴上偏移到外层前表面（如 `z=2.0`），避免被外层遮挡
- 不这样做会导致 Three.js 透明排序闪烁，同时只能看到一个子模块

---

## 场景设计：办公室/工厂风格

### Hub 区域（场景中央）

Hub 是 CAO Server（端口 :9889），是整个系统的同步中心。它**不执行任何进化逻辑**，只存储分数/报告、比较历史、触发心跳提示。

**不要用一个大的半透明外壳包裹所有隔间**（会遮挡内部）。直接将 9 个隔间排列为 3×3 网格，用**阶梯式高度**确保从默认视角全部可见：

| 行 | z 坐标 | y 高度 | 说明 |
|----|--------|--------|------|
| 后排 | z = -3.5 | y = 4.5 | 离相机最远，放最高 |
| 中排 | z = 0 | y = 2.5 | 中间高度 |
| 前排 | z = 3.5 | y = 0.8 | 离相机最近，放最低 |

每列 x 坐标：-4, 0, 4。

隔间定义（每个是一个 `3×2.2×2.8` 的彩色方块，`opacity: 0.5`）：

| 隔间名 | 颜色 | 行 | 描述标签 | 内部图标 |
|--------|------|----|---------|---------|
| `tasks/` | 蓝 #4A90D9 | 后排左 | 任务定义 YAML | 3 个堆叠的薄平面（文档） |
| `attempts/` | 橙 #F5A623 | 后排中 | 评估记录 JSON | 3 个不同高度的细柱（柱状图） |
| `notes/` | 绿 #7ED321 | 后排右 | 知识笔记 .md | 3 个微倾斜的薄平面（散落笔记） |
| `notes/_synthesis/` | 浅绿 #90EE90 | 中排左 | 综合笔记 | 旋转的二十面体（结晶知识） |
| `skills/` | 紫 #9B59B6 | 中排中 | 共享技能 | 旋转的八面体（宝石/工具） |
| `heartbeat` | 红 #E74C3C | 中排右 | 心跳判定引擎 | 脉冲缩放的球体 |
| `recall/BM25` | 青 #1ABC9C | 前排左 | 倒排索引召回 | 旋转的圆环（搜索环） |
| `checkpoint` | 黄 #F1C40F | 前排中 | git 提交锁 | 圆柱 + 圆环（锁） |
| `reports/` | 粉 #FF69B4 | 前排右 | 漏洞报告 | 扁平方块 + 小旗（剪贴板） |

每个隔间上方有**两行标签**：第一行是隔间名（用隔间自身颜色），第二行是中文描述（`#bbbbbb`）。

Hub 顶部标注 `Hub (CAO :9889)`（大号白色带背景）和 `evolution_routes.py`（次级蓝灰色），位于 y=7 和 y=6.3。

### Agent 建筑（3 个主要 + 远景，围绕 Hub 布置）

3 个主要 Agent 沿半径 22 的圆分布，每个是三层建筑：

1. **底层：Bridge 接入层** — `6×2×5`，深灰蓝 `0x3a4060`，`opacity: 0.4`
2. **中层：Agent LLM 核心** — `6×2.8×5`，深蓝 `0x1e2845`，`opacity: 0.35`，**`depthWrite: false`**
3. **顶层：自进化层** — `6×1.8×5`，深紫 `0x2e1e45`，`opacity: 0.35`

**中层内部包含 3 个子模块**（`1.5×1.2×1.5` 方块，`opacity: 0.45`，`renderOrder: 1`，**z=2.0 前置**）：

| 子模块 | 颜色 | dx |
|--------|------|----|
| notes | 绿 #7ED321 | -1.8 |
| skills | 紫 #9B59B6 | 0 |
| harness | 橙 #F5A623 | 1.8 |

每个子模块上方有对应颜色的标签。

三个 Agent 定义：

| Agent | Bridge 类型 | 入口文件 | 特色 | 角度 |
|-------|-----------|---------|------|------|
| OpenCode | Plugin Bridge | `plugin/cao-bridge.ts` | `session.idle → grader`<br>`CAO_SCORE=0.72 正则提取` | `-π/6` |
| Hermes | Hermes Plugin | `hermes-plugin/__init__.py` | `on_session_end → git push`<br>`pre_llm_call 注入心跳` | `5π/6` |
| Claude Code | CLAUDE.md + Hooks + MCP | `claude-code/CLAUDE.md` | `Hooks 生命周期`<br>`MCP 配置 cao_bridge_mcp` | `π/2 + π/6` |

每个 Agent 旁标注：Agent 名称（大号白色带背景）、Bridge 类型、入口文件、层名称（Bridge 接入层 / Agent LLM 核心 / 自进化层）、本地克隆目录 `~/.cao-evolution-client/`、特色说明。

### 远景 Agent

5 个简化方块（`3×(3~5)×2.5`，深色 `0x2a3050`，`opacity: 0.2`）散布在半径 35~43 处，各带一个 "Agent" 标签。

### Git Sync 地面线

每个 Agent 到 Hub 中心用地面层灰色虚线（`LineDashedMaterial`，`dashSize: 0.6, gapSize: 0.4`）连接，标注 "git sync (双向)"。

---

## 核心：七阶段生命周期自动播放

场景的核心交互是自动循环播放七个阶段（Phase 1 → Phase 7 → Phase 1...），每阶段约 5 秒。

### 顶部控制栏

- 左侧：▶/⏸ 自动播放切换按钮（点击切换 `autoPlay` 布尔值，暂停时按钮变灰）
- 中间：7 个阶段按钮（可点击跳转），当前阶段高亮蓝色

### 阶段描述面板

固定在顶部控制栏下方，居中，最大宽度 820px。包含阶段标题（蓝色 h2）和**分点说明**（`<ul><li>` 格式，不是段落）。`<code>` 标签用橙色高亮。

### Phase 1: 任务创建 → task.yaml 落盘 Hub

- 视觉：Hub 内 `tasks/` 隔间发光脉冲
- 说明（分点）：
  - 通过 `POST /evolution/tasks` 创建 task.yaml，含 `grader_skill` 字段
  - 写入 `.cao-evolution/tasks/{task_id}/task.yaml` → git checkpoint
  - 路径 A: Hub 管理员 → `evolution_routes.py:create_task()`
  - 路径 B: Agent → `cao_create_task()` MCP → Bridge → HTTP POST

### Phase 2: 任务获取 → Agent 拉取 task.yaml

- 视觉：蓝色粒子从 Hub `tasks/` 沿弧线飞向三个 Agent
- 说明：
  - MCP 路径: `cao_get_task(task_id)` → Bridge HTTP GET
  - Plugin 路径: `session.idle → getTaskInfo(taskId)` 自动轮询
  - Git 路径: `cao_sync()` → `git pull` → 读取本地 `~/.cao-evolution-client/tasks/`
  - task.yaml 是 Hub → Agent 单向分发，Agent 不修改 tasks/ 目录

### Phase 3: 任务执行

- 视觉：三个 Agent 中层（LLM 核心）发出蓝色光晕脉冲
- 说明：
  - Agent LLM 根据 task.yaml 中 `description + tips` 执行安全审计任务
  - 产出结果文本，此阶段不涉及 evolution 数据流
  - 纯粹的 Agent 工作阶段

### Phase 4: Grader 评分 → 加载 grader_skill 自评

- 视觉：Agent 顶层（自进化层）发出绿色光晕
- 说明：
  - Agent 加载 `evo-skills/{grader_skill}/SKILL.md` 自评打分
  - OpenCode: `session.idle → 注入 grader prompt → CAO_SCORE=0.72 → 正则提取`
  - Hermes: `on_session_end → bridge.get_task → 排入 pending → pre_llm_call 注入`
  - MCP/Skill: 手动 `cao_get_task → SKILL.md → cao_report_score`
  - 评分在 Agent 端侧执行，Hub 不参与评分逻辑

### Phase 5: 分数上报 → Hub 写 attempt.json + 心跳判定

- 视觉：橙色粒子从 Agent 飞向 Hub `attempts/` 隔间；`checkpoint` 和 `heartbeat` 隔间同时发光
- 说明：
  - `cao_report_score()` → `POST /evolution/{id}/scores`
  - ① `compare_to_history()` → improved / baseline / regressed / crashed
  - ② `write_attempt()` → 写入 attempt.json
  - ③ `checkpoint()` → git commit + on_commit → BM25 索引更新
  - ④ `get_leaderboard()` → 排行榜位置
  - ⑤ `count_evals_since_improvement()`
  - ⑥ `check_triggers()` → 心跳判定
  - ⑦ 返回 `ScoreResponse{heartbeat_prompts}`

### Phase 6: 心跳驱动进化 + 知识产出

- 视觉：红色粒子（heartbeat prompts）从 Hub 飞向 Agent；1.5 秒后绿色粒子（notes）和紫色粒子（skills）从 Agent 飞回 Hub；`notes/` 和 `skills/` 隔间发光
- 说明：
  - `reflect` (every=1, interval) → reflection Note
  - `consolidate` (every=5, interval) → synthesis Note
  - `pivot` (every=5, plateau) → pivot Note
  - `evolve_skill` (every=3, plateau) → 改进 Skill
  - 知识通过 git push 写入 Hub → on_commit → BM25 索引更新
  - 异步通道: 人工反馈 → `cao_submit_report → 标注 → cao_fetch_feedbacks → secskill-evo`

### Phase 7: 闭环 → 持续循环

- 视觉：青色粒子（recall 查询）在 Agent 和 Hub 之间双向流动；`recall/BM25` 隔间发光
- 说明：
  - 进化完成 → 回到 Phase 4 重新评分 → Phase 5 新分数上报
  - 新 attempt.json → 心跳判定 → 持续循环
  - 知识消费: `cao_recall(query, top_k)` BM25 排序召回
  - 知识检索: `cao_search_knowledge(q, tags)` 文本 + tag 过滤
  - 文档获取: `cao_fetch_document(doc_id)`

---

## 数据流线（静态弧线 + 动态粒子）

每条数据流路径用低透明度静态弧线表示（`opacity: 0.12`，激活时 `0.25`），动态粒子只在对应阶段激活。粒子用球体（半径 0.28）+ 外层 glow 半透明球（半径 0.8，`opacity: 0.2`），沿 `QuadraticBezierCurve3` 弧线运动。

| 数据流 | 颜色 | 方向 | 激活阶段 | 粒子数 |
|--------|------|------|---------|--------|
| task.yaml | 蓝 #4A90D9 | Hub tasks/ → Agent | Phase 2 | 5 |
| score/attempt | 橙 #F5A623 | Agent → Hub attempts/ | Phase 5 | 5 |
| heartbeat prompts | 红 #E74C3C | Hub heartbeat → Agent | Phase 6 | 4 |
| notes (git push) | 绿 #7ED321 | Agent → Hub notes/ | Phase 6 (延迟 1.5s) | 4 |
| skills (git push) | 紫 #9B59B6 | Agent → Hub skills/ | Phase 6 (延迟 1.5s) | 3 |
| recall 查询 | 青 #1ABC9C | Agent ↔ Hub recall/ (双向) | Phase 7 | 3×2 |

---

## 底部图例栏（单行紧凑）

底部固定一行 52px 高的图例栏（不是多列面板），包含：
- 6 个彩色方块 + 标签：task.yaml(蓝)、score/attempt(橙)、heartbeat(红)、notes(绿)、skills(紫)、recall(青)
- 分隔符 `|`
- 一行灰色文字：`Hub MCP: 12 tools · Bridge MCP: 15 tools · 双层 Prompt: Hub 模板 → Agent evo-skill SKILL.md`

---

## Bridge 变体标签

在场景中放置 2 个浮动标签说明 Bridge 变体：

| 标签内容 | 位置 |
|---------|------|
| `MCP Bridge: cao_bridge_mcp.py (15 tools)`<br>`Agent 手动 cao_get_task → grader skill`<br>`ScoreResponse → Agent 直接处理` | x=14, z=-14 |
| `Skill Bridge: skill/cao-bridge/SKILL.md`<br>`Step 4: cao_get_task → grader`<br>`Step 4.5: 检查 heartbeat prompts` | x=-16, z=-14 |

---

## 输出要求

- 单个 HTML 文件，所有 JS/CSS 内联
- Three.js 通过 CDN importmap 加载：`https://cdn.jsdelivr.net/npm/three@0.160.0/`
- OrbitControls 支持拖拽旋转和缩放
- 7 阶段自动循环（每阶段 ~5s），支持 ▶/⏸ 切换，顶部阶段条可点击跳转
- 阶段描述用 `<ul><li>` 分点格式，不要用段落
- 中文标签用 Canvas 渲染（CanvasTexture + Sprite），确保字体清晰
- 底部图例栏始终可见（单行紧凑，不要多列面板）
- 输出路径：`security-agent-orchestrator/docs/secagentnet-viz.html`
