# CAO Evolution 实施进度

## 步骤 1：evolution/ 核心数据层（types + checkpoint + attempts）

**目标**：创建 `evolution/` 包，移植 CORAL 的 types、checkpoint、attempts 三个模块。
这是所有后续功能（API、MCP、心跳、知识层）的基础。

**范围**：
- `evolution/__init__.py`
- `evolution/types.py` — Score, ScoreBundle, Attempt（精简自 CORAL types.py）
- `evolution/checkpoint.py` — git init + flock commit（改路径 .coral → .cao-evolution）
- `evolution/attempts.py` — JSON CRUD + leaderboard + compare history（改为 tasks/{task_id}/ 分区）

**验证**：`pytest tests/test_evolution.py` 全部通过

**状态**：✅ 完成 — 22/22 测试通过

---

## 步骤 2：Hub API 端点 + 常量

**目标**：创建 `evolution_routes.py` 路由文件，挂载到 FastAPI app。

**范围**：
- `api/evolution_routes.py` — 独立路由文件（~240 行），包含全部 /evolution/* 端点
- `api/main.py` — 仅追加 3 行（import + ensure_evolution_repo + include_router）

**端点清单**（12 个）：
- 任务管理：POST/GET /evolution/tasks, GET /{task_id}, GET /{task_id}/grader
- 分数上报：POST /{task_id}/scores（核心：自动 compare_to_history + checkpoint）
- 排行榜：GET /{task_id}/leaderboard, GET /{task_id}/attempts
- 知识层：POST/GET /evolution/knowledge/notes, POST/GET /evolution/knowledge/skills
- 搜索：GET /evolution/knowledge/search（阶段 1: grep + tags）

**验证**：`pytest tests/test_evolution_api.py` — 25/25 通过

**状态**：✅ 完成 — 25/25 测试通过，全量 78/78 通过

## 步骤 3：Grader 协议 + MCP 工具

**目标**：实现 GraderBase 抽象基类 + load_grader_from_source()，以及 7 个 Evolution MCP 工具。

**范围**：
- `evolution/grader_base.py` — GraderBase ABC（grade/evaluate），支持 float 和 dict 返回
- `mcp_server/evolution_tools.py` — 7 个 MCP 工具（report_score, leaderboard, search, notes, skills）
- `mcp_server/server.py` — 追加 3 行接入

**验证**：`pytest tests/test_evolution_grader_mcp.py` — 11/11 通过

**状态**：✅ 完成 — 11/11 测试通过，全量 89/89 通过

---

## 步骤 4：Bridge Evolution 集成

**目标**：扩展 cao-bridge 的三种变体（plugin/MCP/skill）支持进化功能。

**范围**：
- `cao-bridge/cao_bridge.py` — CaoBridge 类追加 7 个进化方法（get_grader, report_score, get_leaderboard, share_note, share_skill, search_knowledge）
- `cao-bridge/cao_bridge_mcp.py` — 追加 6 个 MCP 工具（cao_get_grader, cao_report_score, cao_get_leaderboard, cao_share_note, cao_share_skill, cao_search_knowledge）
- `cao-bridge/plugin/cao-bridge.ts` — 追加 3 个进化辅助函数（reportScore, getGrader, shareNote）
- `cao-bridge/skill/cao-bridge/SKILL.md` — 扩展协议说明，增加进化工具使用说明

**验证**：`pytest tests/test_bridge_evolution.py` — 10/10 通过

**状态**：✅ 完成 — 10/10 测试通过，全量 99/99 通过

---

## 步骤 5：端到端测试循环

**目标**：完整 E2E 测试，模拟两个 Agent 竞争安全审计任务的全流程。

**范围**：
- `tests/test_e2e_evolution.py` — 3 个 E2E 测试覆盖：
  - 完整进化流程：Hub 创建任务 → Agent A 注册 → 接收任务 → 本地 Grader 评估 → 上报分数 → 分享知识 → Agent B 加入 → 搜索知识 → 竞争 → 排行榜验证
  - 崩溃 Grader 流程：Grader 抛异常 → 上报 crashed 状态
  - 多任务隔离：不同 task_id 的分数互不干扰

**验证**：`pytest tests/test_e2e_evolution.py` — 3/3 通过

**状态**：✅ 完成 — 3/3 测试通过，全量 102/102 通过

---

## 步骤 6：心跳（heartbeat + prompts）

**目标**：实现心跳系统 — 基于评估历史自动触发 reflect/consolidate/pivot 提示。

**范围**：
- `evolution/heartbeat.py` — HeartbeatAction + HeartbeatRunner（interval/plateau）+ 配置持久化 + check_triggers()
- `evolution/prompts/reflect.md` — 反思提示模板
- `evolution/prompts/consolidate.md` — 知识综合提示模板
- `evolution/prompts/pivot.md` — 策略转向提示模板
- `api/evolution_routes.py` — submit_score 集成心跳检查 + 2 个配置端点（GET/PUT heartbeat）
- ScoreResponse 新增 `heartbeat_triggered` 字段

**特性**：
- interval 类型：每 N 次评估触发（reflect=1, consolidate=5）
- plateau 类型：连续 N 次无提升后触发（pivot=5）+ cooldown 防刷
- 默认配置自动生效，可通过 API 自定义
- check_triggers() 在 submit_score 中同步调用，返回触发的 action 名称

**验证**：`pytest tests/test_heartbeat.py` — 18/18 通过

**状态**：✅ 完成 — 18/18 测试通过，全量 120/120 通过

---

## Code Review + Bug 修复

**发现并修复的 3 个问题**：

1. **shared_state_hash 未持久化**（Medium）
   - `submit_score()` 中 checkpoint 后设置了 hash 但没有重新写入磁盘
   - 修复：checkpoint 后调用第二次 `write_attempt()`
   - 回归测试：`TestCodeReviewFixes::test_shared_state_hash_persisted`

2. **global_eval_count 未传递**（High）
   - `check_triggers()` 调用时缺少 `global_eval_count`，导致 `is_global=True` 的 consolidate 永远不触发
   - 修复：遍历 tasks/ 目录累计所有任务的 attempt 总数
   - 回归测试：`TestCodeReviewFixes::test_global_heartbeat_consolidate_triggers`

3. **Grader exec() 无防护**（Critical → 缓解）
   - `load_grader_from_source()` 使用 `exec()` 无任何过滤
   - 修复：添加 AST 静态分析，阻止 os/subprocess/sys/shutil/socket/ctypes 的 import
   - 5 个新测试覆盖：blocks_os, blocks_subprocess, blocks_from_os, allows_safe, rejects_syntax_error

**验证**：全量 127/127 通过

---

## 步骤 7：四项改进 + 多维评分接口

**目标**：实现讨论中达成一致的四项改进和多维评分预留接口。

### 7.1 多维评分 score_detail

**改动**：
- `evolution/types.py`：Attempt 新增 `score_detail: dict[str, float] | None = None`，更新 `to_dict()` / `from_dict()`
- `api/evolution_routes.py`：ScoreReport 新增 `score_detail` 字段；ScoreResponse 新增 `score_detail` 字段；submit_score 传递 score_detail 到 Attempt

**新增测试**（8 个）：
- `TestScoreDetail`：roundtrip、json_roundtrip、none_omitted、persisted_on_disk
- `TestScoreDetailAPI`：submit_with_detail、submit_without_detail、persisted_in_attempts

### 7.2 Git 远程仓库同步

**改动**：
- `evolution/checkpoint.py`：
  - 读取 `CAO_EVOLUTION_REMOTE` 环境变量
  - 新增 `_setup_remote()`：在 init 时自动 `git remote add origin`
  - 新增 `_sync_remote()`：每次 checkpoint 后 `pull --rebase` + `push`
  - 推送失败不阻塞主流程（warning + 下次重试）

**新增测试**（3 个）：
- `TestGitRemoteSync`：noop_when_no_remote、setup_adds_origin、handles_unreachable

### 7.3 Plugin 心跳自动注入

**改动**：
- `api/evolution_routes.py`：新增 `HeartbeatPrompt` 模型；ScoreResponse 新增 `heartbeat_prompts: list[HeartbeatPrompt]`
- `cao-bridge/plugin/cao-bridge.ts`：
  - 新增 `CAO_HEARTBEAT_ENABLED` 环境变量（默认 "0"）
  - 新增 `pendingHeartbeats` 队列和 `injectHeartbeat()` 函数
  - `session.idle` 后自动 reportScore，检查 heartbeat_prompts 并缓存
  - 无 Hub 任务时自动从队列注入心跳 prompt

**新增测试**（2 个）：
- `TestHeartbeatPrompts`：prompts_returned、prompts_contain_agent_id

### 7.4 设计文档更新

**改动**：
- `cao-integrated-execution-paths.md`：
  - 1.3 节：Attempt 类型增加 score_detail 说明
  - 五节：checkpoint 逻辑增加远程同步伪代码和冲突策略
  - 路径 3：心跳流程增加 Plugin 自动注入路径（路径 A/B 分支）
  - 控制点对比表：Plugin 心跳行更新
  - 附录 A.1：Attempt 记录增加 score_detail 说明
  - 十一节：总结增加多维评分、远程同步、Plugin 心跳说明

**验证**：全量 139/139 通过（新增 12 个测试）

---

## 步骤 8：Skill 双向同步工具

**目标**：实现 `skill_sync.py` — 在本地 Agent skill 目录与 CAO 共享池之间双向同步。

**范围**：
- `evolution/skill_sync.py` — 核心模块（~170 行），包含：
  - `discover_skill_dirs()` — 扫描 opencode/claude-code/hermes + 自定义目录
  - `scan_skills(dir)` — 枚举目录下的 SKILL.md 条目
  - `push_skills()` — 本地 → 共享池（仅推送新增/变更）
  - `pull_skills()` — 共享池 → 本地（带冲突备份）
  - `sync_all()` — 完整双向同步
  - `resolve_writeback_target()` — 首选 claude-code 目录，按优先级 fallback

**环境变量**：
- `CAO_SKILL_DIRS` — 额外的逗号分隔 skill 目录
- `CAO_SKILL_WRITEBACK` — "1" 启用回写（默认关闭）
- `CAO_SKILL_WRITEBACK_TARGET` — 回写首选目标（默认 "claude-code"）

**回写策略**：
- 首选 claude-code 目录（`~/.claude/skills/`），若不存在则 fallback 到 opencode → hermes
- 冲突时自动备份为 `SKILL.md.bak` 再覆盖
- 通过 `CAO_SKILL_WRITEBACK=1` 环境变量开关控制

**验证**：`pytest tests/test_skill_sync.py` — 20/20 通过

**状态**：✅ 完成 — 20/20 测试通过，全量 159/159 通过

---

## 步骤 9：Claude Code Bridge

**目标**：为 Claude Code CLI 创建完整的 CAO 接入套件（MCP 复用 + CLAUDE.md + Hooks + /evolve 命令 + 安装脚本）。

**范围**：
- `cao-bridge/claude-code/` 目录，包含：
  - `CLAUDE.md` — 进化协议指令（Claude Code 全局注入）
  - `.mcp.json` — MCP 配置（复用 `cao_bridge_mcp.py`）
  - `hooks/cao-session-start.sh` — SessionStart hook（自动注册 + 拉取知识）
  - `hooks/cao-session-stop.sh` — Stop hook（自动上报 + push skills）
  - `commands/evolve.md` — `/evolve` 斜杠命令
  - `install.sh` — 安装脚本（创建 .claude/ 结构、配置 hooks）

**验证**：`pytest tests/test_claude_code_bridge.py` — 16/16 通过

**状态**：✅ 完成 — 16/16 测试通过，全量 175/175 通过

---

## 步骤 10：hermes 全套接入（MCP + SKILL + Plugin）

**目标**：为 hermes-agent 实现完整的 CAO 接入三件套，数据同步方式与其他 agent（opencode/claude code）完全一致：CaoBridge → HTTP API → 文件 → git checkpoint → git push/pull。

**范围**：
- `cao-bridge/hermes/plugin.yaml` — Hermes 插件清单
- `cao-bridge/hermes/__init__.py` — 插件入口，复用 `CaoBridge` 类
- `cao-bridge/hermes/memory_parser.py` — MEMORY.md § 解析 + SHA-256 去重
- `cao-bridge/hermes/hermes-sync.sh` — 降级同步脚本
- `cao-bridge/hermes/README.md` — 安装说明（Option A/B/C）
- `tests/test_hermes_plugin.py` — 15 个测试

**关键设计**：
- Plugin `__init__.py` 直接 `from cao_bridge import CaoBridge`，和 MCP Server 用同一个 HTTP 客户端类
- `on_session_end`: `bridge.share_skill()` × N + `bridge.share_note()` × N → `report_score()` 触发心跳
- `on_session_start`: `bridge.register()` + `bridge.search_knowledge()` → inject context
- `pre_llm_call`: 从 `pending_heartbeats` 缓冲区取心跳 prompt（由 `report_score` 响应填充）
- MEMORY.md 解析：跳过 ═ header 和 MEMORY(...) title 行 → § 分隔 → SHA-256 去重
- hermes 自进化逻辑不修改（`our_evolution_enabled: false` 默认）
- `on_end` 注册失败自动重试一次（register retry guard）

**详细方案**：见 `cao-integrated-execution-paths.md` §8 + `hermes-memsearch-implementation.md` §1

**Code Review + E2E 修复**（4 项）：
1. `memory_parser.py` — 移除 `first_line` 死代码
2. `hermes-sync.sh` — 添加 MEMORY title 行剥离（与 memory_parser.py 一致）
3. `__init__.py` — `on_end` 添加 register retry guard（原 bridge.terminal_id=None 时静默失败）
4. `__init__.py` — `pre_llm` 不再调用 `bridge.poll()`（语义不匹配），改用 `pending_heartbeats` 缓冲区（由 `report_score` 响应填充，与 opencode plugin 心跳机制一致）

**E2E 测试**（8 项全过）：
1. CaoBridge register ✓
2. _push_skills → Hub skills API ✓
3. _push_memory → Hub notes API ✓
4. search_knowledge 返回 hermes 数据 ✓
5. _format_knowledge 格式化 ✓
6. report_score + heartbeat_prompts 响应 ✓
7. 文件内去重 ✓
8. hermes-sync.sh 降级脚本 ✓（1 skill + 2 memory entries）

**状态**：✅ 完成 — 15 单元测试 + 8 E2E 测试全过，280 后端总测试通过

---

## 步骤 11：Recall + 选择性同步

**目标**：替代原定 memsearch 方案。为未来多仓拆分和 recall 机制做前向兼容准备。

> 原 Step 11（memsearch 知识搜索适配）已被本步骤覆盖。
> 完整 recall 功能（BM25 索引 + recall API + CaoBridge recall/fetch）留作 Phase B 实施。

**设计文档**：`recall-selective-sync-design.md`（完整方案），`cao-integrated-execution-paths.md` 第十五节

### Phase A（已完成 ✅）：扁平目录 + 路径抽象 + 增强 task.yaml

**核心改动**：
1. **RepoManager**（`evolution/repo_manager.py`）— 路径抽象层，支持 single/multi 模式
2. **扁平目录布局** — 移除 `shared/` 和 `knowledge/` 中间目录，直接使用 `skills/`、`notes/`、`attempts/`、`graders/`、`tasks/`、`reports/` 顶层目录
3. **`shared_dir()` 返回根目录** — 所有路径代码自动适配新布局
4. **增强 task.yaml** — 新增 `grader`（引用）、`tips`、`eval_data_path`、`created_by`、`last_updated` 字段
5. **远程 Agent 可注册任务** — Bridge `create_task()` + MCP `cao_create_task` + `cao_list_tasks` 工具
6. **Grader 引用解析** — 内联 `grader.py` 优先，否则解析 `task.yaml` 的 `grader:` 字段指向 `graders/`

**子步骤**（已全部完成）：
- 11a：✅ `repo_manager.py` — CONTENT_TYPES、get_dir()、git_root()、ensure_dirs()
- 11b：✅ 路径迁移 — checkpoint.py、attempts.py、skill_sync.py、evolution_routes.py
- 11c：✅ 测试通过 — 289 tests（含 9 项新增），无退化

### Phase B（未来实施）：完整 recall 功能

- RecallIndex BM25 引擎（`evolution/recall_index.py`）
- recall API 端点（GET /recall + GET /recall/{type}/{id} + POST /recall/batch）
- search_knowledge() 改用 RecallIndex
- CaoBridge recall/fetch/selective_sync 方法
- MCP recall_knowledge 工具
- 多仓拆分（skills.git / notes.git / attempts.git / graders.git）

**状态**：✅ Phase A 已完成 | 🔲 Phase B 待设计

---

## 步骤 12：WebUI 进化展示

**目标**：在已有 React 18 + Tailwind + Vite WebUI 中新增 Evolution tab，展示分数曲线、排行榜、多维评分、知识浏览与搜索。

**范围**：
- `web/src/api.ts` — 新增 5 个 Evolution 类型接口 + 6 个 API 方法
- `web/src/components/EvolutionPanel.tsx` — 主面板组件（~280 行），含：
  - ScoreChart（纯 CSS 柱状图，无外部依赖）
  - ScoreDetailBars（多维评分条形图）
  - Leaderboard（排行榜表格 + StatusPill）
  - KnowledgeBrowser（Notes/Skills 折叠展开）
  - Knowledge Search（搜索框 + 结果列表）
- `web/src/App.tsx` — 新增 evolution tab（TrendingUp 图标）
- `web/src/test/evolution.test.tsx` — 12 个组件测试

**验证**：
- 前端 46/46 测试通过（vitest）
- 后端 175/175 测试通过（pytest）
- `npm run build` 生产构建成功

**状态**：✅ 完成

---

## 步骤 13：分布式人工反馈机制

**目标**：Agent 扫描出漏洞后注册 Unique Report ID，人工标注后 Agent 拉取反馈作为进化依据。

**核心设计**（本地文件机制）：
- Agent 提交报告 → Hub 返回 report_id → 本地保存 `.cao-reports/{id}.report`
- 人工标注完成后 → Agent 按 terminal_id 拉取 → 本地保存 `.cao-reports/{id}.result`
- `grader.py(workdir, reports_dir=".cao-reports")` — .report 和 .result 作为评估输入

**范围**：
- `evolution/types.py` — 新增 Finding, HumanLabel, Report 数据类
- `api/evolution_routes.py` — 新增 5 个 /evolution/reports/* 端点
  - POST submit (注册 report) + GET fetch (按 terminal_id 拉取已标注)
  - GET list + PUT annotate + GET stats
- `mcp_server/evolution_tools.py` — 新增 `cao_submit_report`, `cao_fetch_feedback`, `cao_list_reports`
- `cao-bridge/plugin/cao-bridge.ts` — `onSessionIdle()` 自动拉取 .result 文件并注入反馈摘要
- `cao-bridge/cao_bridge_mcp.py` — 新增 3 个 MCP 工具
- `evolution/heartbeat.py` — `has_pending_feedback(reports_dir)` 检查
- `web/src/components/EvolutionPanel.tsx` — Reports 子面板 + 标注界面

**详细方案**：见 `cao-integrated-execution-paths.md` 第十节

**子步骤**：
- 13a：✅ 后端 Report 数据模型 + API 端点 + 存储 + .report/.result 文件规范（16 tests）
- 13b：✅ MCP/Plugin/Bridge 集成（3 MCP tools + plugin fetchFeedback + heartbeat has_pending_feedback）
- 13c：✅ WebUI 报告列表 + 标注界面（ReportsPanel + 7 component tests）
- 13d：✅ 心跳整合（feedback_reflect prompt + has_new_feedback + .consumed marker + check_triggers integration）
- 13e：✅ grader.py 扩展（feedback_stats + grade_with_feedback 70/30 blended scoring）

**状态**：✅ 完成（213 backend + 53 frontend = 266 tests 全通过）

### Code Review 修复（Step 13 后续）

**发现 4 个问题，全部修复**：

1. **Critical: `.result` 文件未写入** — annotate endpoint 只更新 JSON，不生成 `.result` 文件
   - 修复：annotate 后自动写入 `shared/reports/{task_id}/{report_id}.result`
   - 心跳/grader 现在可以发现人工反馈

2. **High: API 字段不一致** — 后端返回 `total_reports`，前端期望 `total`
   - 修复：`report_stats()` 返回 `total`，测试同步更新

3. **Critical: 路径穿越** — `task_id`/`report_id` 未校验
   - 修复：API 层添加 `_validate_path_id()` 正则校验 `[a-zA-Z0-9_-]+`

4. **Medium: `feedback_stats()` 类型** — 参数仅接受 `Path`，不接受 `str`
   - 修复：参数类型改为 `str | Path`

**新增测试**（2 个）：
- `test_annotate_creates_result_file` — 验证 .result 文件写入
- `test_path_traversal_rejected` — 验证非法 ID 被拒绝

**E2E 验证**：完整反馈闭环 — 提交→标注→.result 写入→心跳检测→grader 统计 ✅

**状态**：✅ 全量 215 backend + 52 frontend = 267 tests 通过

---

## 远期：Harness 自主进化

**目标**：Agent 和评估标准（Harness）协同进化。

**详细方案**：见 `harness-evolution-design.md`（含 Meta-Harness 论文分析、MemSearch-Harness 进化、secskill-evo 整合分析）

**状态**：📋 规划中

---

## 参考：secskill-evo 技能进化框架

**仓库**：`/home/ubuntu/projects/SecAgentNet-v1/secskill-evo/`

**概要**：Claude Code skill，用于创建/测试/进化 AI agent 技能。双模式（Create + Evolution），含 4 个评估 Agent（Judge/Grader/Comparator/Analyzer）+ 10 个 Python 工具 + 回归测试安全门。

**整合策略**：核心算法整合入本项目（见步骤 14），而非作为独立 skill。详见 `cao-integrated-execution-paths.md` 第十三节。

---

## 步骤 14：Skill 进化机制 + secskill-evo 整合 + 运行模式

**目标**：补齐 skill 迭代优化能力，整合 secskill-evo 的核心算法，实现三种运行模式（默认 local）。

**设计文档**：`cao-integrated-execution-paths.md` 第十三节

**核心改动**：
1. **多信号透明评分**：`evolution_signals` 字段，各信号独立不压缩，JSON 完整注入心跳 prompt
2. **LLM-as-Judge**：语义评估 skill 质量（binary + soft score + confidence）
3. **强制 evals 回归验证**：skill 目录下 `evals/evals.json`，进化前后必须通过
4. **结构化重试**：max 2 attempts，每次换策略，全失败 revert
5. **TIP.md 经验积累**：每次进化后记录根因、改动、经验
6. **三种运行模式**：`CAO_EVOLUTION_MODE=local|distributed|hybrid`，默认 local

**子步骤**：
- 14a：✅ `evolution_signals` 数据模型 + Attempt 扩展 + 心跳模板注入
  - Attempt 增加 `evolution_signals: dict[str, Any] | None`，to_dict/from_dict 支持
  - ScoreReport/ScoreResponse 增加 evolution_signals 字段
  - submit_score() 传递 signals → Attempt + check_triggers + 响应
  - render_prompt() 注入 `{evolution_signals_json}` 占位符
  - reflect.md / pivot.md / feedback_reflect 模板已更新
  - 新增 8 个测试（5 unit + 3 API），全部通过
- 14b：✅ `evolve_skill.md` prompt + heartbeat 新增触发 + evals.json 读写
  - 创建 `prompts/evolve_skill.md` — 完整 skill 进化 prompt（含信号注入）
  - `evolve_skill` 加入默认心跳动作（plateau=3 触发）
  - `evals.py` — read/write/add/seed/remove eval cases（~100 行）
  - 新增 13 个测试（7 evals + 3 prompt + 3 trigger），全部通过
- 14c：✅ LLM-as-Judge 评估函数 `evaluate_with_judge()`
  - `judge.py` — 模型无关的 Judge 接口，支持 binary + soft score + strengths/weaknesses
  - `evaluate_batch()` + `judge_summary()` → evolution_signals 格式输出
  - Markdown fence 自动剥离，失败降级处理
  - 新增 8 个测试，全部通过
- 14d：✅ 结构化重试 `evolve_with_retry()` — snapshot/modify/validate/revert
  - `evolve.py` — 最多 2 次重试，回归检测自动 revert
  - EvolutionResult 数据类含完整 attempt 历史
  - 新增 6 个测试（成功/回归/穷尽/异常/无改善/序列化），全部通过
- 14e：✅ TIP.md 读写 + 运行模式开关 (`CAO_EVOLUTION_MODE`)
  - `tip.py` — read/write/append TIP.md（带时间戳的学习记录）
  - `modes.py` — local/distributed/hybrid 三模式 + ModeConfig feature flags
  - 默认 local 模式：judge + local_evolution 开启，bridge/heartbeat/grader 关闭
  - 新增 11 个测试（4 TIP + 7 modes），全部通过
- 14f：✅ E2E 集成测试验证
  - 完整本地进化循环：create skill → seed evals → judge → evolve_with_retry → TIP.md → signals
  - API 级 E2E：submit score with signals → heartbeat returns signals in prompts
  - 新增 2 个 E2E 测试，全部通过

**状态**：✅ 全部完成 — 263 后端 + 53 前端 = 316 测试全过

### Code Review + 修复（Step 14 后续）

**范围**：对 Step 14 全部 6 个新文件 + 所有 prompt 模板进行 code review 和 E2E 动态测试。

**发现并修复 7 个问题**：

1. **Critical — evolve_with_retry 缺少 evolution_signals 参数**
   - `evolve_fn` 签名从 3 参数改为 4 参数：`(content, attempt, feedback, signals)`
   - `evolve_with_retry()` 新增 `evolution_signals` 参数，透传给 evolve_fn
   - 影响文件：`evolve.py` + 所有测试中的 evolve_fn mock

2. **Critical — 本地模式进化由 Agent 自行驱动（非编排器调度）**
   - 本地模式下 agent 就是执行者，不存在外部脚本来调度
   - 进化通过**用户提示词指定** + agent 调用独立模块完成
   - 各模块（evals / judge / evolve / tip）均为独立函数，可按需组合
   - 设计文档 §13.6 已更新说明 agent 自驱动模式

3. **Medium — `consolidate.md` 缺少 `{evolution_signals_json}` 占位符**
   - 已补充 signals 注入段落

4. **Medium — `feedback_reflect.md` 缺少 `{evolution_signals_json}` 占位符**
   - 已补充 signals 注入段落

5. **Medium — `seed_from_failure()` ID 碰撞风险**
   - 旧方案 `auto-{len+1}` 在删除后重新添加会碰撞
   - 改为 SHA-256 哈希：`auto-{sha256(input:expected)[:8]}`，确定性 + 幂等

6. **Medium — `_parse_judge_response()` fence 剥离过度**
   - 旧代码删除所有含 ``` 的行（可能误删代码块内容）
   - 改为只剥离首行/末行的 fence

7. **Minor — `evolve.py` 未使用的 `copy` 导入**
   - 已移除

**新增测试**：1 个 signals 转发 + 1 个 seed 幂等

**E2E 动态测试**（本地 127.0.0.1:9889 运行）：
- ✅ 创建任务 → 提交多信号评分 → 心跳返回含 signals 的 prompt
- ✅ 评分改善后 leaderboard 正确排序
- ✅ 人工反馈 report → annotate → result → stats 全流程
- ✅ local_orchestrator 模块加载和数据类验证

**状态**：✅ 完成 — 280 后端 + 53 前端 = 333 测试全过

---

## 步骤 15：Agent 端 Git 同步 + RepoManager 多仓迁移

**目标**：实现 agent 端 git clone/pull `~/.cao-evolution-client/`，使远程 Agent 通过 git 与 Hub 双向同步共享知识（技能、笔记、任务等）。之前仅 Hub 端有 git push，agent 端缺失 git 操作。

### 15a：RepoManager 多仓 → 单仓目录结构迁移

**核心改动**：
- 移除 RepoManager 多仓抽象层（4 个独立 repo → 1 个 flat repo）
- `.cao-evolution/` 下直接使用 `skills/`, `notes/`, `attempts/`, `graders/`, `tasks/`, `reports/`, `heartbeat/` 等顶层目录
- 更新 `checkpoint.py` 使用 flat 路径
- 全量 E2E + unit 测试验证

**状态**：✅ 完成 — 289/289 测试通过

### 15b：Agent 端 Git 同步（`git_sync.py` + 全 bridge 集成）

**核心改动**：

1. **新建 `cao-bridge/git_sync.py`**（~100 行）：
   - `init_client_repo(remote_url)` — 首次 `git clone --filter=blob:none`，后续 `git pull --rebase`
   - `pull(cdir)` / `push(cdir, message)` — git 操作封装
   - `skills_dir()` / `notes_dir()` / `tasks_dir()` — 路径工具
   - `_ensure_remote(cdir, url)` — 自动更新 origin URL
   - `DEFAULT_CLIENT_DIR = Path.home() / ".cao-evolution-client"`
   - 环境变量：`CAO_GIT_REMOTE`（远程 URL）、`CAO_CLIENT_DIR`（本地路径覆盖）

2. **`cao_bridge.py` 集成**：
   - 新增 `git_remote` 构造参数
   - 新增 `sync_repo()`, `pull_repo()`, `push_repo()`, `pull_skills_to_local(target_dir)` 方法

3. **`cao_bridge_mcp.py` 新增 2 个 MCP 工具**（9→11）：
   - `cao_sync` — 触发 agent 端 git clone/pull
   - `cao_pull_skills` — git pull + 复制 skills 到本地目录

4. **OpenCode Plugin (`cao-bridge.ts`)**：
   - `gitSync()` + `pullSkillsFromClone()` 函数
   - 启动时 + session.idle 后自动触发

5. **Claude Code Hooks**：
   - `cao-session-start.sh` — git clone/pull + skill 复制到 `~/.claude/skills/`
   - `cao-session-stop.sh` — 追加 git pull 刷新

6. **Hermes Plugin (`__init__.py`)**：
   - `on_start`: git clone/pull → `_pull_skills_from_clone()` → register → inject
   - `on_end`: HTTP push → git pull

7. **`hermes-sync.sh` / `SKILL.md` / `plugin.yaml` / `.mcp.json` / `install.sh`**：
   - 全部同步更新，加入 `CAO_GIT_REMOTE` / `CAO_CLIENT_DIR` 环境变量

8. **`skill_sync.py`**：新增 `use_client_clone` 参数

**环境变量摘要**：

| 变量 | 侧 | 用途 |
|------|-----|------|
| `CAO_EVOLUTION_REMOTE` | Hub | Hub git push 远程 URL |
| `CAO_GIT_REMOTE` | Agent | Agent git clone/pull 远程 URL |
| `CAO_CLIENT_DIR` | Agent | 覆盖 agent 端 clone 路径（默认 `~/.cao-evolution-client`） |

**Git 同步触发点**：

| Agent 类型 | 启动时 | 结束时 | 手动 |
|-----------|--------|--------|------|
| opencode (TS plugin) | gitSync() | session.idle → gitSync() | — |
| Claude Code (shell hooks) | session-start.sh | session-stop.sh | — |
| Hermes (Python plugin) | on_start → init_client_repo | on_end → pull | — |
| MCP (任何 agent) | — | — | cao_sync / cao_pull_skills |
| hermes-sync.sh | 脚本开始 | 脚本结束 | cron/手动 |

**测试结果**：
- 289/289 既有 unit 测试通过（无回归）
- 12/12 新建 git_sync unit 测试通过
- 20/20 E2E 功能检查正确（4 个返回 201 非 200，为测试断言问题）

**文档更新**：
- `cao-integrated-execution-paths.md` §8.1, §8.3, §15.5 已刷新
- `hermes/README.md` 全面更新
- `SKILL.md` 新增 Step 0 (sync) + 2 个新工具说明

**状态**：✅ 完成 — 301 测试通过（289 既有 + 12 新增 git_sync）

---

## 步骤 16：自进化逻辑重构（evo-skills 迁移）

**目标**：将 Hub 端孤立的 Python 进化模块迁移为平台无关的 SKILL.md，任何 Agent 可直接执行。

**背景**：
- Step 14 实现的 evolve.py / judge.py / evals.py / tip.py / modes.py 共 521 行 Python 代码
- 这些模块在 Hub 端零生产调用者（heartbeat 只发 prompt 文本，不调用它们）
- 与 CAO 的 "Agent 读 SKILL.md 执行" 范式冲突

**范围**：

1. 创建 `evo-skills/` 目录，5 个进化 skill：
   - `secskill-evo/` — 核心 FIX 算法（从 /secskill-evo 项目整体移入）
   - `openspace-evo/` — OpenSpace 风格进化（DERIVED + CAPTURED + 谱系管理）
   - `cao-reflect/` — 反思 note 生成（6 步结构化反思）
   - `cao-consolidate/` — 跨 Agent 知识综合
   - `cao-pivot/` — 策略转向

2. secskill-evo 适配：
   - `/tmp/cao-evo-workspace/` 隔离（避免 git_version.py 检测父 repo）
   - 新增 CAO Heartbeat Integration 说明

3. 4 个 heartbeat prompt 重写为轻量调度指令（→ 加载对应 evo-skill）

4. Bridge Protocol 新增 Step 4.5（Handle Heartbeat）+ Step 4.6（Post-Heartbeat）

5. 清理 5 个孤立 Python 模块（521 行）+ 测试文件瘦身（589→156 行）

**创建文件**：
- `evo-skills/secskill-evo/` — 完整 skill（SKILL.md + agents/ + scripts/ + references/ + assets/）
- `evo-skills/openspace-evo/SKILL.md` — DERIVED + CAPTURED + .lineage.json 谱系
- `evo-skills/cao-reflect/SKILL.md` — 6 步反思
- `evo-skills/cao-consolidate/SKILL.md` — 5 步综合
- `evo-skills/cao-pivot/SKILL.md` — 5 步转向

**修改文件**：
- `evolution/prompts/evolve_skill.md` — 重写为 → secskill-evo 调度
- `evolution/prompts/reflect.md` — 重写为 → cao-reflect 调度
- `evolution/prompts/consolidate.md` — 重写为 → cao-consolidate 调度
- `evolution/prompts/pivot.md` — 重写为 → cao-pivot 调度
- `cao-bridge/skill/cao-bridge/SKILL.md` — 新增 Step 4.5 + 4.6
- `cao-bridge/claude-code/CLAUDE.md` — 新增 heartbeat 处理

**删除文件**：
- `evolution/evolve.py` (131 行)
- `evolution/judge.py` (144 行)
- `evolution/evals.py` (104 行)
- `evolution/tip.py` (53 行)
- `evolution/modes.py` (89 行)

**测试文件重构**：
- `tests/test_skill_evolution.py`：589→156 行，保留 8 个 heartbeat 测试

**测试结果**：255/255 通过（移除 34 个测试孤立模块的用例）

**文档更新**：
- `cao-integrated-execution-paths.md` 新增 §14（自进化逻辑重构）

**状态**：✅ 完成 — 255/255 测试通过

---

## 步骤 17：项目清理 + 文档更新

**目标**：清理项目结构，统一测试目录，全面更新文档以反映当前实现状态。

**范围**：

### 17.1 结构清理

1. **删除 `scripts/bump_version.py`** — 上游遗留的版本号工具，项目内无引用
2. **合并测试目录** — 将 `tests/`（12 个进化测试文件）合并到 `test/evolution/`
   - 修复所有相对路径（`parent.parent` → `parent.parent.parent`）
   - 涉及文件：test_bridge_evolution.py, test_e2e_evolution.py, test_claude_code_bridge.py, test_hermes_plugin.py
   - pyproject.toml `testpaths = ["test"]` 已覆盖，无需修改
3. **Code Review 修复**（Step 16 后续）：
   - secskill-evo SKILL.md: 路径遍历防护（`pwd -P` 验证 workspace）
   - secskill-evo SKILL.md: 所有 `python -m scripts.*` 改为 `$SCRIPTS_DIR/*.py` 绝对路径（11 处）
   - heartbeat.py: `{evals_since_improvement}` 占位符渲染修复

### 17.2 文档更新

| 文件 | 操作 | 说明 |
|------|------|------|
| `README.md` | 重写 | 项目概述 + 架构 + 快速开始 + 进化系统 |
| `CODEBASE.md` | 重写 | 完整源码树 + 数据流 + 架构图 |
| `DEVELOPMENT.md` | 重写 | 开发指南 + 进化测试 + Hub 启动 |
| `docs/cao-code-map.md` | 更新 | 进化层架构 + API 路由 + MCP 工具 |
| `docs/cao-integrated-execution-paths.md` | 更新 | 测试路径更新 |
| `docs/implementation-progress.md` | 更新 | Step 17 记录 |
| `docs/evolution-trigger-chain.md` | **新建** | 进化触发链与调用链详解（开发者参考） |

**测试结果**：255/255 通过（合并后路径正确）

**状态**：✅ 完成

---

## 步骤 18：Recall + 选择性同步（BM25 知识召回）

**目标**：在保留现有全仓 git 同步 + 子串搜索的基础上，新增 BM25 排序的知识召回路径。
通过 `CAO_RECALL_MODE=full|selective` 开关在两种模式间切换，对 Agent 透明。

**范围**：

### 18.1 RecallIndex（Hub 端 BM25 引擎）

- **新建** `evolution/recall_index.py` (~320 行)
  - `BM25` 类：纯 Python BM25 Okapi 实现（k1=1.5, b=0.75）
  - `RecallIndex` 类：构建索引、增量更新、查询、按 ID 获取文档
  - `tokenize()` 函数：CJK 单字拆分 + Latin 词级分割
  - `Document` / `RecallResult` 数据类
  - 辅助函数：`_parse_frontmatter()`, `_body_after_frontmatter()`, `_make_snippet()`

### 18.2 API 端点

`api/evolution_routes.py` 新增 3 个端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/evolution/knowledge/recall` | BM25 排序召回，支持 tag 过滤、include_content |
| GET | `/evolution/knowledge/document/{doc_id}` | 按 ID 获取完整文档（选择性同步） |
| POST | `/evolution/knowledge/recall/rebuild` | 手动触发索引全量重建 |

同时新增：
- `get_recall_index()` 单例管理
- `_on_checkpoint_commit()` 回调（增量更新索引）
- `_checkpoint_with_recall()` 包装器（替换全部 6 处 `checkpoint()` 调用）

### 18.3 Checkpoint 回调机制

`evolution/checkpoint.py` 修改：
- `checkpoint()` 新增 `on_commit` 可选参数
- commit 后通过 `git diff --name-only HEAD~1 HEAD` 获取变更文件列表
- 调用 `on_commit(evolution_dir, changed_files)` 触发索引增量更新

### 18.4 Bridge + MCP 工具

**Agent 端** (`cao-bridge/cao_bridge.py`)：
- 新增 `recall_knowledge()` 和 `fetch_document()` 方法

**Agent 端 MCP** (`cao-bridge/cao_bridge_mcp.py`)：
- `CAO_RECALL_MODE` 环境变量（默认 `full`）
- `cao_search_knowledge` 透明升级：selective 模式下自动调用 BM25 recall
- 新增 `cao_recall` 工具（BM25 排序召回，支持 include_content）
- 新增 `cao_fetch_document` 工具（按 ID 获取文档）

**Hub 端 MCP** (`mcp_server/evolution_tools.py`)：
- 新增 `cao_recall` 和 `cao_fetch_document` 工具

### 18.5 WebUI

- `web/src/api.ts`：新增 `RecallResult` 类型 + `recallKnowledge()` / `getDocument()` 函数
- `web/src/components/EvolutionPanel.tsx`：Knowledge Search 新增 BM25/Grep 模式切换按钮，结果显示 score badge

### 18.6 Bug 修复

- `recall_index.py`: `tokenize()` 混合 CJK+Latin 时丢失 Latin 部分 → 使用 buffer 分段处理
- `recall_index.py`: `_remove_document()` 未从 `_doc_map` 移除 → get_document 返回空壳 → 修复
- `recall_index.py`: `_parse_skill()` 使用 `meta.get("name")` → 改为优先 `meta.get("title")`

### 18.7 测试

新增 42 个测试：
- `test/evolution/test_recall_index.py` — 31 个单元测试（tokenize, BM25, RecallIndex）
- `test/evolution/test_recall_api.py` — 11 个 API 集成测试（recall, document, rebuild 端点）

**测试结果**：297/297 通过（含 42 个新增 recall 测试），53/53 前端测试通过

**状态**：✅ 完成

---

## 步骤 19：Grader Skill 重构（grader.py → evo-skill）

**目标**：将 grader 从 Hub 端存储的 Python 脚本（grader.py / grader_code）改为 Agent
侧加载的 evo-skill。Agent 完成任务后，读取 task.yaml 中的 grader_skill 字段，
加载对应的 evo-skills/\<grader_skill\>/SKILL.md，按照 SKILL.md 指导评估输出，
产出 CAO_SCORE=\<float\>，然后调用 cao_report_score 上报。

### 19.1 TaskCreate 模型重构

- evolution_routes.py: TaskCreate 模型移除 grader (py 路径) + grader_code (内联代码)，
  新增 grader_skill（skill 名称，正则 ^[a-zA-Z0-9_-]*$）
- create_task() 不再写 grader.py 文件，task.yaml 使用 grader_skill: 字段
- get_task() 返回 grader_skill 字符串（替代旧的 has_grader 布尔值）

### 19.2 移除 GET /{task_id}/grader 端点

- 完全删除约 30 行的 grader 下载端点
- Agent 不再从 Hub 拉取 grader 代码，而是本地加载 evo-skill

### 19.3 Hub MCP 更新

- evolution_tools.py: cao_create_task 参数从 grader 改为 grader_skill

### 19.4 Bridge 更新

- cao_bridge.py: 移除 get_grader() 方法，新增 get_task() 方法，
  create_task() 参数从 grader/grader_code 改为 grader_skill
- cao_bridge_mcp.py: 移除 cao_get_grader 工具，新增 cao_get_task 和 cao_create_task 工具

### 19.5 OpenCode Plugin Grader 触发

- cao-bridge.ts: 完全重写 session.idle handler，实现两阶段 grader flow：
  1. 任务完成 → 获取 task info → 如果有 grader_skill → 注入 grader prompt → 等待
  2. Grader 完成 → 提取 CAO_SCORE=\<float\> → 调用 reportScore() → 处理心跳

### 19.6 Hermes Plugin Grader 触发

- hermes/__init__.py: on_end() 中增加 grader_skill 检查，
  如果 task context 有 grader_skill，排队 grader prompt 供下次 pre_llm 注入

### 19.7 security-grader Evo-Skill

- 新增 evo-skills/security-grader/SKILL.md
- 四维评分（Completeness 0.3, Accuracy 0.3, Actionability 0.2, Depth 0.2）
- 惩罚项（误报 -0.15/个, 关键遗漏 -0.20, 范围错误 ≤0.1）
- 输出格式: CAO_SCORE=\<float\>
- 非安全任务自动切换为通用评分维度

### 19.8 SKILL.md Protocol 更新

- cao-bridge/skill/cao-bridge/SKILL.md: Step 4 更新为 cao_get_task + 加载 grader skill
- 新增 Creating Tasks Locally 部分：指导 Agent 通过 cao_create_task MCP 工具注册本地任务
- cao-bridge/claude-code/CLAUDE.md: 工具列表更新

### 19.9 测试更新

更新 6 个测试文件中的 grader 引用：
- test_evolution_api.py: grader_code → grader_skill, has_grader → grader_skill, 新增验证测试
- test_e2e_evolution.py: 移除 grader_base 导入，改为模拟 grader skill 评分
- test_bridge_evolution.py: get_grader → get_task, 新增 TestBridgeGraderSkillFlow
- test_evolution_grader_mcp.py: 端到端测试改为 grader_skill flow
- test_evolution.py / test_skill_evolution.py: signals 字段更新
- test_claude_code_bridge.py: 工具名称更新

**测试结果**：297/297 通过

**状态**：✅ 完成

---

## 步骤 20：Git-Centric 重构（知识同步走 git push）

**目标**：移除 Agent 端 `cao_share_note` / `cao_share_skill` MCP 工具，改为本地写入 +
`cao_push` git push。统一数据传输为 git 单通道，简化架构。Hub 端 HTTP POST
notes/skills 保留供 Hub 内部使用（心跳生成的笔记、WebUI）。

### 20.1 Bridge MCP 工具变更

- `cao-bridge/cao_bridge_mcp.py`: 移除 `cao_share_note`、`cao_share_skill` 两个工具
- 新增 `cao_push` 工具（git add + commit + push）
- `cao_sync` 改为双向（push + pull），原来只有 pull

### 20.2 Bridge Python SDK 变更

- `cao-bridge/cao_bridge.py`: 移除 `share_note()`、`share_skill()` 方法

### 20.3 Hub MCP 工具变更

- `mcp_server/evolution_tools.py`: 移除 `cao_share_note`、`cao_share_skill`（14 -> 12 工具）

### 20.4 Checkpoint 远程同步增强

- `evolution/checkpoint.py`: `_sync_remote()` 记录 pull 前后 HEAD SHA，diff 获取拉取的文件列表
- `checkpoint()` 合并 pulled files 到 `all_changed`，即使本地无 commit 也触发 `on_commit`
- 效果：Agent git push -> Hub checkpoint -> `_sync_remote()` pull -> BM25 增量更新

### 20.5 OpenCode Plugin 更新

- `cao-bridge/plugin/cao-bridge.ts`: 新增 `gitPush()` 函数（使用 `spawnSync` 防注入）
- 在 grader 分数提交后和任务完成后自动调用 `gitPush()`

### 20.6 Hermes Plugin 更新

- `cao-bridge/hermes/__init__.py`: `_push_skills()` / `_push_memory()` 改为本地写入
  `~/.cao-evolution-client/` 目录，不再调用 HTTP API
- 添加 `git_push()` 调用，写入完成后自动推送
- 修复文件名碰撞：`_push_memory()` 添加 counter 后缀

### 20.7 Evo-Skills SKILL.md 更新

5 个 evo-skills 的 SKILL.md 移除 `cao_share_note`/`cao_share_skill` 引用，
替换为本地写入 + `cao_push` 指引：
- cao-reflect, cao-consolidate, cao-pivot, openspace-evo, bridge SKILL.md

### 20.8 安全修复

- `gitPush()` 从 `execSync` 模板字符串改为 `spawnSync("git", ["commit", "-m", msg])`
  防止 commit message 命令注入

### 20.9 测试更新

更新 4 个测试文件：
- test_bridge_evolution.py: 移除 share_note/skill 测试，更新 MCP 工具列表
- test_e2e_evolution.py: Phase 5 改为直接 HTTP POST（测试 Hub 内部路径）
- test_claude_code_bridge.py: 更新 EXPECTED_TOOLS 列表
- test_hermes_plugin.py: 验证本地文件写入而非 API 调用

**测试结果**：295/295 通过（移除 2 个过时测试）

**状态**：✅ 完成

---

## 步骤 21：L1 记忆加载 + Root Orchestrator + YAML 配置

**目标**：实现 L1 Insight Index（知识索引）自动构建与注入机制，使 Agent 在会话启动时自动获取共享知识摘要。

### 21.1 Root Orchestrator

Hub 端常驻后台 Agent，随 Hub 启动/关闭自动管理：

- `agent_store/root_orchestrator.md` — Agent Profile（L1 Index Builder 指令）
- `api/main.py` — `_start_root_orchestrator()` 在 lifespan 中创建/销毁
- 通过 inbox 消息接收 `rebuild-index: [files]` 任务
- 读取 `.cao-evolution/notes/` 生成 `.cao-evolution/index.md`（≤1500 tokens）

### 21.2 YAML 配置

- `config.py` — 新增 YAML 配置加载器（`~/.aws/cli-agent-orchestrator/config.yaml`）
- 支持 `CAO_CONFIG` 环境变量覆盖路径
- 可配置项：`root_orchestrator.{enabled, provider, profile, session}`
- 默认值：provider=`clother_closeai`, session=`ROOT`

### 21.3 Clother CloseAI Provider

- `providers/clother_closeai.py` — 新增 provider（继承 ClaudeCodeProvider）
- `providers/clother_minimax_cn.py` — 修复：`--dangerously-skip-permissions` → `--yolo`
- `models/provider.py` — 新增 `CLOTHER_CLOSEAI` 枚举值
- `providers/manager.py` — 注册新 provider 到工厂

### 21.4 L1 Index API 端点

- `GET /evolution/index` — 返回 index.md 内容（PlainTextResponse）
- `POST /evolution/index/rebuild` — 手动触发 index 重建
- **关键修复**：将路由移至 `/{task_id}` 通配路由之前，避免路径冲突

### 21.5 Checkpoint → Index 重建通知

- `_on_checkpoint_commit()` — 当 notes 变更时自动通知 Root Orchestrator
- `_notify_root_rebuild_index()` — 通过 inbox message 触发重建

### 21.6 Bridge 端 L1 Index 注入

- `cao-session-start.sh` — Claude Code SessionStart hook 注入 L1 index
- `cao-bridge.ts` — OpenCode plugin init 注入 L1 index
- 两端均包裹在 `== Knowledge Index ==` 标记中

### 21.7 Bug 修复

1. **路由冲突**：`GET /evolution/index` 被 `GET /evolution/{task_id}` 拦截 → 移至前方
2. **Bash 占位符检测**：`cao-session-start.sh` 中 `!= "# Knowledge Index"` 误判多行默认文本 → 改用 `grep -q "No index available yet"`
3. **fastmcp API 变更**：`get_tools()` → `list_tools()`，dict → list（3.2.3 升级导致）

### 21.8 新增测试（23 个）

- `test_l1_memory.py`：
  - TestConfigLoader (5) — defaults, custom yaml, partial, invalid, empty
  - TestClotherProviders (5) — yolo flag, enum, manager factory
  - TestL1IndexRoutes (4) — get default, get content, rebuild no-root, rebuild with-root
  - TestCheckpointNotification (4) — notify on notes, skip no-root, trigger on commit, skip non-notes
  - TestRootOrchestratorProfile (2) — loadable, no mcp
  - TestRootOrchestratorLifecycle (3) — disabled config, config values, failure handling

**测试结果**：350/350 通过（新增 23 个测试）

### 21.9 Bug 修复 — L1 运行时流程审查

通过端到端 runtime flow trace 发现并修复 3 个关键问题：

1. **Root Orchestrator 路径错误**：`root_orchestrator.md` 使用相对路径 `.cao-evolution/notes/`，但 EVOLUTION_DIR 默认为 `~/.cao-evolution/`。如果 Hub CWD 不是 home 目录，Root Orch 会在错误位置查找 notes → 改为绝对路径 `~/.cao-evolution/notes/` 和 `~/.cao-evolution/index.md`

2. **Root Orchestrator 工作目录未设置**：`_start_root_orchestrator()` 未传入 `working_directory`，默认为 `os.getcwd()`（Hub 的启动目录）→ 添加 `working_directory=str(Path.home())`

3. **Inbox 消息永不送达（严重）**：`_notify_root_rebuild_index()` 创建 inbox 消息后未触发投递。`LogFileHandler` 仅在日志文件变化时投递。如果 Root Orch 已 IDLE（无日志输出），消息永远停留 PENDING 状态 → 在 `_notify_root_rebuild_index()` 和 `rebuild_knowledge_index()` 中添加 `inbox_service.check_and_send_pending_messages(root_tid)` 确保立即投递

涉及文件：
- `agent_store/root_orchestrator.md` — 路径修复
- `api/main.py` — working_directory 修复
- `api/evolution_routes.py` — 添加 asyncio/inbox_service 导入，两处添加即时投递
- `test/evolution/test_l1_memory.py` — 3 个测试更新（验证修复）

### 21.10 L1 端到端验证

- `experiment/test_l1_flow.sh` — 8 步自动化 E2E 验证脚本
  - 支持 `--no-hub`（使用已运行 Hub）和 `--verbose` 模式
  - 验证：Hub → Root Orch → API → notes → rebuild → index → SessionStart 注入
  - 自动清理测试 notes
- `experiment/README.md` — 新增步骤 9（L1 Knowledge Index E2E 验证），含手动分步调试

**状态**：✅ 完成

---

### 21.11 SDK 支持 + Hook 隔离 + env_vars 修复

**目标**：支持基于 SDK（Claude Agent SDK / OpenCode SDK）的 Agent 接入 CAO，修复 Root Orchestrator 触发全局 hook 的循环注册问题。

#### Root Orchestrator Hook 隔离

发现 `clother-closeai` 会读取 `~/.claude/settings.json` 中全局安装的 SessionStart/Stop hooks，导致 Root Orchestrator 自己注册到 Hub 形成循环依赖。

**双重保护**：
1. `--bare` 标志 — provider 层跳过 hooks、plugins、CLAUDE.md
2. `CAO_HOOKS_ENABLED=0` 环境变量 — Bash hook 层检查并提前退出

涉及文件：
- `providers/clother_closeai.py` — 新增 `bare` 参数，`--yolo --bare`
- `providers/clother_minimax_cn.py` — 同步添加 `bare` 参数支持
- `providers/claude_code.py` — **关键修复**：`initialize()` 添加 `self._apply_env_vars()` 调用（之前 env_vars 在 ClaudeCode 系列 provider 中从未应用到 tmux）
- `providers/manager.py` — `create_provider()` 新增 `bare` 参数，传递给 Clother 系列 provider
- `services/terminal_service.py` — `create_terminal()` 新增 `env_vars` 和 `bare` 参数
- `api/main.py` — `_start_root_orchestrator()` 传入 `env_vars={"CAO_HOOKS_ENABLED": "0"}, bare=True`

#### SDK Lifecycle 支持

- `cao-bridge/sdk/lifecycle.py` — `CaoAgentLifecycle` 类：start/stop/build_context/fetch_index
- `cao-bridge/sdk/example_claude_sdk.py` — Claude Agent SDK 集成示例
- `cao-bridge/sdk/example_opencode_sdk.py` — OpenCode SDK 集成示例
- `cao-bridge/cao_bridge.py` — 新增 `fetch_index()` 方法（`GET /evolution/index`）

#### Bug 修复

1. **env_vars 未应用（严重）**：`ClaudeCodeProvider.initialize()` 从不调用 `_apply_env_vars()`，导致 `CAO_HOOKS_ENABLED=0` 无法到达 tmux 环境。修复：在 `initialize()` 的 shell ready 检查后添加 `self._apply_env_vars()`。

#### 测试

- `cao-bridge/sdk/test_sdk_lifecycle.py` — 3 个 E2E 测试（fetch_index / lifecycle / reattach）
- `test/evolution/test_l1_memory.py` — 更新 `test_start_uses_config_values` 验证新参数

**测试结果**：350/350 通过，SDK E2E 3/3 通过

**状态**：✅ 完成

---

## 步骤 22：secskill-evo-neo（保守进化 Skill）

**目标**：替代 secskill-evo，实现纯 Evolution Mode 的 skill 进化框架。
核心改进：双重证据门控（失败证据 + 改进证据缺一不可）、L0-L3 四级变更控制、
泛化性强制检查。砍掉 Create Mode 及其全部基础设施（eval viewer、subagent 并行测试、
description 优化循环、benchmark、打包）。

**动机**：secskill-evo 存在多个结构性问题：
- `eval-viewer/generate_review.py` 缺失（SKILL.md 7 处引用，Create Mode 核心循环断裂）
- `assertions` / `expectations` 术语混用（跨组件数据流断裂）
- Create Mode 和 Evolution Mode 评分体系割裂（grader 0-1 vs judge 0-10）
- git_version.py 缺乏工作区隔离保护（可能污染父仓库）
- 无克制性进化机制（"make minimal changes" 仅是一句建议，无强制门控）

### 22.1 新增文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `evo-skills/secskill-evo-neo/SKILL.md` | 312 | 主指令：6 步流程（收集→评估→克制审查→隔离修改→提交→记录） |
| `evo-skills/secskill-evo-neo/agents/judge.md` | 208 | LLM-as-Judge：binary + 0-100 soft score + root cause 分类 + 泛化性评分 |
| `evo-skills/secskill-evo-neo/references/conservative-evolution.md` | 230 | 保守进化框架：双重证据门、L0-L3 变更级别、泛化性检查清单、5 个反模式 |
| `evo-skills/secskill-evo-neo/references/schemas.md` | 169 | JSON schema：judge_results.json + utility.json（统一术语） |
| `evo-skills/secskill-evo-neo/scripts/git_version.py` | 459 | Git 版本管理：新增 SAFE_PREFIX 检查，mutating 命令拒绝 /tmp/cao-evo-workspace/ 之外操作 |

### 22.2 关键设计决策

- **纯 Evolution Mode**：Create Mode 是不同问题域，不属于 CAO 自主进化场景
- **双重证据门**：失败证据 + 改进证据缺一不可，不是"出了问题就改"
- **L0 是常态**：大多数进化周期应以 L0（不改）结束，如果每次都改说明在过拟合
- **utility.json mandatory**：每次进化周期必须记录（含 L0 跳过），作为 heartbeat 信号源
- **Self-review + 延迟验证**：不 spawn subagent 重新执行 task，改动效果在下一轮自然验证
- **评分统一为 0-100**：与 CAO grader 体系对齐

### 22.3 更新的现有文件

| 文件 | 变更 |
|------|------|
| `src/.../prompts/evolve_skill.md` | heartbeat prompt 指向 secskill-evo-neo |
| `docs/cao-evo-flow.md` | 13 处 secskill-evo → secskill-evo-neo |
| `docs/cao-code-map.md` | evo-skills 目录树更新，evolve_skill.md 引用更新 |

### 22.4 未修改（无需修改）

- `cao-bridge/opencode/install.sh` — 通配符 `evo-skills/*/` 自动拾取
- `cao-bridge/claude-code/install.sh` — 同上
- 代码注释中的 "e.g. secskill-evo"（`.py`, `.ts`, `.sh`）— 仅示例性引用
- `docs/archive/*` — 历史记录，不改

**状态**：✅ 完成

---

## 步骤 22.1：secskill-gen-neo（保守技能生成 Skill）

**目标**：从实战中沉淀可复用技能。agent 在多次探索（有成功有失败）后最终做成某件事，
将成功方法提炼为可复用的 skill。核心理念：skill 不是自上而下设计的，而是自下而上
从实践中沉淀的。

**与 secskill-evo-neo 的关系**：evo-neo 修改已有 skill，gen-neo 创建新 skill。
两者共享保守哲学——宁可不生成/不改，也不产出低质量的 skill。

### 22.1.1 新增文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `evo-skills/secskill-gen-neo/SKILL.md` | 241 | 主指令：5 步流程（回顾→门控→提炼→审查→发布） |
| `evo-skills/secskill-gen-neo/references/generation-gate.md` | 173 | 生成门控：泛化性、增量价值、粒度三级串行检查 |
| `evo-skills/secskill-gen-neo/templates/skill-skeleton.md` | 79 | 生成 skill 的 SKILL.md 骨架模板 |
| `src/.../prompts/generate_skill.md` | 30 | heartbeat prompt：持续高分时建议沉淀 skill |

### 22.1.2 关键设计决策

- **自下而上沉淀**：不是"我想要一个做 X 的 skill"（自上而下），而是"我做成了 X，方法值得沉淀"
- **三级串行门控**：泛化性 → 增量价值 → 粒度，任一不通过则降级为 secnote
- **secnote 是合法出口**：大多数触发应以"写 secnote 而非 skill"结束，这是正确的粒度选择
- **heartbeat 集成**：`generate_skill` prompt 每 5 次评估触发（interval），skill 自身的门控确保不过度生成
- **与 openspace-evo CAPTURED 独立共存**：gen-neo 有严格门控，CAPTURED 没有，定位不同

### 22.1.3 更新的现有文件

| 文件 | 变更 |
|------|------|
| `src/.../evolution/heartbeat.py` | DEFAULT_PROMPTS 新增 generate_skill；get_default_actions 新增 generate_skill（every=5, interval）；render_prompt 新增 local_eval_count 参数 |
| `test/evolution/test_heartbeat.py` | test_defaults 更新为 5 个 action |
| `docs/cao-code-map.md` | evo-skills 目录树 + prompts 列表更新 |
| `docs/cao-evo-flow.md` | evo-skills 目录树 + 心跳 Prompt 类型总览表更新 |

### 22.1.4 同步修正：secskill-evo-neo 证据门措辞

将"双重证据门"（Dual Evidence Gate）修正为"串行证据门"（Sequential Evidence Gate）：
- Gate 1（失败证据）不通过 → 直接停止
- Gate 1 通过后才进入 Gate 2（改进证据）→ 不通过 → 停止
- 涉及文件：secskill-evo-neo/SKILL.md、references/conservative-evolution.md

**测试结果**：5/5 受影响测试通过

**状态**：✅ 完成
