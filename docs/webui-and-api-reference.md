# WebUI 与 API Server 参考文档

> 本文档面向需要开发、调试或扩展 CAO 前端与 API 层的开发者。
>
> **变更记录**：Step 19 移除 `GET /{task_id}/grader` 端点（grader.py -> grader skill）；
> Step 18 新增 recall/document/rebuild 三个端点；Step 20 git-centric 重构
> （Agent 知识同步走 git push，HTTP POST notes/skills 保留供 Hub 内部使用）。

---

## 1. 架构总览

```
浏览器 (localhost:5173)                     后端 (localhost:9889)
┌──────────────────────────┐               ┌──────────────────────────────────┐
│  React SPA (Vite)        │  Vite Proxy   │  FastAPI Application             │
│                          │──────────────▶│                                  │
│  Tab: Home / Agents /    │  /sessions    │  main.py (31 路由)               │
│       Flows / Evolution  │  /terminals   │    ├─ /health                    │
│       / Settings         │  /agents      │    ├─ /agents/*                  │
│                          │  /settings    │    ├─ /settings/*                │
│  api.ts ─ fetchJSON()    │  /flows       │    ├─ /sessions/*                │
│  store.ts ─ Zustand      │  /evolution   │    ├─ /terminals/*               │
│                          │  /remotes     │    ├─ /remotes/*                 │
│  xterm.js ─ WebSocket ───│──────────────▶│    └─ WebSocket /terminals/*/ws  │
│                          │  ws://        │                                  │
└──────────────────────────┘               │  evolution_routes.py (21 路由)   │
                                           │    └─ /evolution/*               │
                                           └──────────────────────────────────┘
```

**关键设计**：
- 开发模式下，Vite dev server (`localhost:5173`) 通过 proxy 将 API 请求转发到 FastAPI (`localhost:9889`)
- 生产模式下，需要反向代理 (nginx 等) 或同源部署
- WebSocket 用于实时 PTY 终端流，走 `/terminals/{id}/ws`

---

## 2. 前端结构

### 2.1 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| React | 18.2 | UI 框架 |
| TypeScript | 5.0 | 类型安全 |
| Vite | 6.4 | 构建工具 + 开发服务器 |
| Zustand | 4.4 | 全局状态管理 |
| Tailwind CSS | 3.4 | 样式 |
| xterm.js | 6.0 | 终端模拟器 |
| lucide-react | 0.562 | 图标库 |
| Vitest | 3.2 | 单元测试 |

### 2.2 目录结构

```
web/
├── src/
│   ├── api.ts                          # HTTP 客户端 + 所有 API 调用函数
│   ├── store.ts                        # Zustand 全局状态
│   ├── App.tsx                         # 根组件，Tab 导航
│   ├── main.tsx                        # React 入口
│   ├── index.css                       # Tailwind 配置 + 自定义滚动条
│   ├── components/
│   │   ├── DashboardHome.tsx           # Home Tab — 会话概览
│   │   ├── AgentPanel.tsx              # Agents Tab — Agent 启动/管理
│   │   ├── FlowsPanel.tsx             # Flows Tab — 定时任务
│   │   ├── EvolutionPanel.tsx          # Evolution Tab — 进化面板
│   │   ├── SettingsPanel.tsx           # Settings Tab — Agent 目录配置
│   │   ├── TerminalView.tsx            # 终端弹窗 (xterm + WebSocket)
│   │   ├── InboxPanel.tsx              # Agent 消息收件箱
│   │   ├── OutputViewer.tsx            # 终端输出查看器
│   │   ├── StatusBadge.tsx             # 状态标记组件
│   │   ├── ConfirmModal.tsx            # 确认对话框
│   │   ├── CustomSelect.tsx            # 下拉选择组件
│   │   └── ErrorBoundary.tsx           # 错误边界
│   └── test/
│       ├── setup.ts                    # Vitest 配置 (jsdom)
│       ├── api.test.ts                 # API 层测试 (17 tests)
│       ├── store.test.ts              # 状态管理测试 (5 tests)
│       ├── components.test.tsx         # 组件渲染测试 (12 tests)
│       └── evolution.test.tsx          # 进化功能测试 (19 tests)
├── vite.config.ts                      # Vite + 代理 + Vitest 配置
├── tailwind.config.js
├── tsconfig.json
├── package.json
└── index.html
```

### 2.3 Tab 页面

| Tab | 快捷键 | 组件 | 功能 |
|-----|--------|------|------|
| Home | Alt+1 | `DashboardHome.tsx` | 会话列表、终端管理、快速操作 |
| Agents | Alt+2 | `AgentPanel.tsx` | Agent Profile 浏览、Provider 选择、启动 Agent |
| Flows | Alt+3 | `FlowsPanel.tsx` | 定时 Agent 任务 (cron)、手动触发 |
| Evolution | Alt+4 | `EvolutionPanel.tsx` | 进化排行榜、分数历史、知识库、报告标注 |
| Settings | Alt+5 | `SettingsPanel.tsx` | Agent Profile 目录配置 |

### 2.4 状态管理 (Zustand)

```typescript
// store.ts — 全局状态
{
  sessions: Session[]              // 所有会话
  activeSession: string | null     // 当前选中会话
  activeSessionDetail: SessionDetail | null
  connected: boolean               // 后端连通状态
  snackbar: { type, message }      // 通知消息
  terminalStatuses: Record<id, status>  // 终端状态缓存
}
```

特性：
- `jsonEqual()` 防止不必要的重渲染
- Snackbar 3 秒自动消失
- 终端状态独立缓存，避免频繁请求

### 2.5 WebSocket (终端)

```
TerminalView.tsx
  ↓ ws://localhost:5173/terminals/{id}/ws (通过 Vite 代理)
  ↓ → ws://localhost:9889/terminals/{id}/ws (FastAPI)

客户端 → 服务端:
  { type: 'resize', rows: N, cols: M }    # 终端尺寸变化
  { type: 'input', data: '...' }          # 键盘输入

服务端 → 客户端:
  ArrayBuffer (二进制 PTY 输出)             # 终端输出帧
```

---

## 3. API Server 设计

### 3.1 入口与路由注册

```python
# src/cli_agent_orchestrator/api/main.py
app = FastAPI(title="CLI Agent Orchestrator", lifespan=lifespan)

# 主路由 — 直接注册在 app 上 (31 个)
@app.get("/health")
@app.get("/agents/profiles")
@app.get("/agents/providers")
@app.get("/settings/agent-dirs")
@app.post("/settings/agent-dirs")
@app.post("/sessions")
@app.get("/sessions")
@app.get("/sessions/{session_name}")
@app.delete("/sessions/{session_name}")
@app.post("/sessions/{session_name}/terminals")
@app.get("/sessions/{session_name}/terminals")
@app.get("/terminals/{terminal_id}")
@app.get("/terminals/{terminal_id}/working-directory")
@app.post("/terminals/{terminal_id}/input")
@app.get("/terminals/{terminal_id}/output")
@app.post("/terminals/{terminal_id}/exit")
@app.delete("/terminals/{terminal_id}")
@app.post("/terminals/{receiver_id}/inbox/messages")
@app.get("/terminals/{terminal_id}/inbox/messages")
@app.post("/remotes/register")
@app.get("/remotes/{terminal_id}/poll")
@app.post("/remotes/{terminal_id}/report")
@app.get("/remotes/{terminal_id}/status")
@app.websocket("/terminals/{terminal_id}/ws")
# + Flows (GET/POST/DELETE /flows, enable/disable/run)

# 进化路由 — 通过 APIRouter 挂载
# evolution_routes.py → router = APIRouter(prefix="/evolution")
app.include_router(router)
```

### 3.2 完整 API 端点一览

#### 3.2.1 健康检查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 返回 `{status: "ok"}` |

#### 3.2.2 Agent 管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/agents/profiles` | 发现可用 Agent Profile |
| GET | `/agents/providers` | 列出已安装的 Provider |

#### 3.2.3 设置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/settings/agent-dirs` | 获取 Agent Profile 搜索目录 |
| POST | `/settings/agent-dirs` | 更新 Agent Profile 搜索目录 |

#### 3.2.4 会话与终端

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/sessions` | 创建会话 + 首个终端 |
| GET | `/sessions` | 列出所有会话 |
| GET | `/sessions/{name}` | 获取会话详情 (含终端列表) |
| DELETE | `/sessions/{name}` | 删除会话及所有终端 |
| POST | `/sessions/{name}/terminals` | 在已有会话中添加终端 |
| GET | `/sessions/{name}/terminals` | 列出会话内终端 |
| GET | `/terminals/{id}` | 获取终端状态 |
| GET | `/terminals/{id}/working-directory` | 获取终端工作目录 |
| POST | `/terminals/{id}/input` | 向终端发送输入 |
| GET | `/terminals/{id}/output` | 获取终端输出 (`mode=full\|last`) |
| POST | `/terminals/{id}/exit` | 优雅退出终端 |
| DELETE | `/terminals/{id}` | 强制关闭终端 |
| WS | `/terminals/{id}/ws` | PTY 实时流 (WebSocket) |

#### 3.2.5 Agent 间消息 (Inbox)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/terminals/{id}/inbox/messages` | 发送消息给另一个 Agent |
| GET | `/terminals/{id}/inbox/messages` | 获取消息列表 (`?status=pending\|delivered\|failed`) |

#### 3.2.6 远程 Agent (Bridge)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/remotes/register` | 远程 Agent 注册 (返回 terminal_id) |
| GET | `/remotes/{id}/poll` | 轮询待执行命令 |
| POST | `/remotes/{id}/report` | 上报执行结果 |
| GET | `/remotes/{id}/status` | 获取远程 Agent 状态 |

#### 3.2.7 定时任务 (Flows)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/flows` | 列出所有 Flow |
| POST | `/flows` | 创建 Flow (name, schedule, agent_profile, prompt_template) |
| DELETE | `/flows/{name}` | 删除 Flow |
| POST | `/flows/{name}/enable` | 启用 Flow |
| POST | `/flows/{name}/disable` | 禁用 Flow |
| POST | `/flows/{name}/run` | 立即执行 Flow |

#### 3.2.8 进化系统 (Evolution)

| 方法 | 路径 | 前端使用 | 说明 |
|------|------|----------|------|
| POST | `/evolution/tasks` | ✗ | 创建进化任务（grader_skill 字段指定评分 skill） |
| GET | `/evolution/tasks` | ✓ | 列出所有任务 |
| GET | `/evolution/{task_id}` | ✗ | 获取任务详情（含 grader_skill） |
| POST | `/evolution/{task_id}/scores` | ✗ | 上报分数 (Agent 调用) |
| GET | `/evolution/{task_id}/leaderboard` | ✓ | 排行榜 (top_n) |
| GET | `/evolution/{task_id}/attempts` | ✓ | 所有尝试记录 |
| POST | `/evolution/knowledge/notes` | ✗ | 创建知识笔记（Hub 内部使用，Agent 走 git push） |
| GET | `/evolution/knowledge/notes` | ✓ | 列出笔记 |
| POST | `/evolution/knowledge/skills` | ✗ | 创建共享 Skill（Hub 内部使用，Agent 走 git push） |
| GET | `/evolution/knowledge/skills` | ✓ | 列出 Skill |
| GET | `/evolution/knowledge/search` | ✓ | 搜索知识库 (grep) |
| GET | `/evolution/knowledge/recall` | ✓ | BM25 排序召回（支持 tag 过滤、include_content） |
| GET | `/evolution/knowledge/document/{doc_id}` | ✗ | 按 ID 获取完整文档（选择性同步） |
| POST | `/evolution/knowledge/recall/rebuild` | ✗ | 手动触发 BM25 索引全量重建 |
| POST | `/evolution/{task_id}/reports` | ✗ | 提交报告 (Agent 调用) |
| GET | `/evolution/{task_id}/reports` | ✓ | 获取报告列表 |
| GET | `/evolution/{task_id}/reports/stats` | ✓ | 报告统计 |
| PUT | `/evolution/{task_id}/reports/{id}/annotate` | ✓ | 人工标注报告 |
| GET | `/evolution/{task_id}/reports/{id}/result` | ✗ | 获取标注结果 |
| GET | `/evolution/heartbeat/{agent_id}` | ✗ | 获取心跳配置 (Agent 调用) |
| PUT | `/evolution/heartbeat/{agent_id}` | ✗ | 更新心跳配置 |

> **标记 ✗ 的端点** 仅由 Agent/MCP/CLI 使用，WebUI 不直接调用。

---

## 4. 前后端对应关系

### 4.1 数据类型映射

| 前端类型 (TypeScript) | 后端模型 | 说明 |
|----------------------|----------|------|
| `Session` | `dict` (sessions_service) | `{name, terminals[]}` |
| `SessionDetail` | `dict` | `{name, terminals: Terminal[]}` |
| `Terminal` | `Terminal` (Pydantic) | `{id, name, provider, session_name, status}` |
| `AgentProfileInfo` | `dict` (agent_profiles) | `{name, description, source}` |
| `ProviderInfo` | `dict` | `{name, binary, installed}` |
| `Flow` | `dict` (flow_service) | `{name, schedule, agent_profile, ...}` |
| `EvolutionTask` | `dict` (task.yaml) | `{task_id, name, description, attempt_count, best_score}` |
| `EvolutionAttempt` | `dict` (attempts/) | `{run_id, agent_id, score, status, score_detail?}` |
| `EvolutionNote` | `dict` (notes/) | `{filename, meta, content}` |
| `EvolutionSkill` | `dict` (skills/) | `{name, meta, content}` |
| `Report` | `dict` (reports/) | `{report_id, findings[], auto_score, human_score, ...}` |

### 4.2 Provider Source 值

| 后端 source | 含义 |
|-------------|------|
| `built-in` | CAO 内置 Profile |
| `local` | 本地目录发现 |
| `claude_code` | Claude Code Provider 目录 |
| `codex` | Codex Provider 目录 |
| `installed` | cao install 安装的 Profile |
| `custom` | 用户自定义 extra_dirs |

---

## 5. Evolution 面板详解

### 5.1 组件结构

```
EvolutionPanel.tsx (700+ 行)
├── ScoreChart          # 最近 30 次分数柱状图
│   └── 颜色: improved(绿) / baseline(蓝) / regressed(橙) / crashed(红)
├── ScoreDetailBars     # 多维分数横向条形图
├── Leaderboard         # 排行榜表格 (rank, score, agent, status, time)
├── KnowledgeBrowser    # 知识库浏览
│   ├── Notes 列表 (可展开查看内容)
│   ├── Skills 列表 (可展开查看内容)
│   └── Search (query + tags + top_k)
└── ReportsPanel        # 报告与人工标注
    ├── Stats (total, pending, annotated, precision%)
    ├── Report 列表 (可展开查看 findings)
    └── Annotation 模式 (TP/FP/Uncertain per finding)
```

### 5.2 数据加载流

```
组件挂载
  ↓
Promise.all([
  api.listEvolutionTasks()        → GET /evolution/tasks
  api.listNotes()                 → GET /evolution/knowledge/notes
  api.listSkills()                → GET /evolution/knowledge/skills
])
  ↓
选择第一个 task (selectedTask)
  ↓
Promise.all([
  api.getLeaderboard(taskId)      → GET /evolution/{taskId}/leaderboard
  api.getAttempts(taskId)         → GET /evolution/{taskId}/attempts
  api.getReports(taskId)          → GET /evolution/{taskId}/reports
  api.getReportStats(taskId)      → GET /evolution/{taskId}/reports/stats
])
  ↓
渲染: ScoreChart + ScoreDetailBars + Leaderboard + KnowledgeBrowser + ReportsPanel
```

### 5.3 人工标注流程

```
用户点击 Report → 展开 findings 表格
  ↓
点击 "Annotate" → 进入标注模式
  ↓
为每个 finding 选择: TP (True Positive) / FP (False Positive) / Uncertain
  ↓
点击 "Submit Annotation"
  ↓
PUT /evolution/{taskId}/reports/{reportId}/annotate
  body: { human_score, labels: [{finding_id, verdict}], annotated_by }
  ↓
报告状态变为 "annotated"，precision% 更新
```

---

## 6. Vite 代理配置

```typescript
// web/vite.config.ts
proxy: {
  '/sessions':  { target: 'http://localhost:9889', changeOrigin: true },
  '/terminals': { target: 'http://localhost:9889', changeOrigin: true, ws: true },
  '/health':    { target: 'http://localhost:9889', changeOrigin: true },
  '/agents':    { target: 'http://localhost:9889', changeOrigin: true },
  '/settings':  { target: 'http://localhost:9889', changeOrigin: true },
  '/flows':     { target: 'http://localhost:9889', changeOrigin: true },
  '/evolution': { target: 'http://localhost:9889', changeOrigin: true },
  '/remotes':   { target: 'http://localhost:9889', changeOrigin: true },
}
```

> **注意**: `/terminals` 开启了 `ws: true` 以支持 WebSocket 代理。

---

## 7. 测试

### 7.1 运行

```bash
cd web
npm test           # 单次运行 (53 tests)
npm run test:watch # 监听模式
```

### 7.2 测试文件

| 文件 | 测试数 | 覆盖 |
|------|--------|------|
| `api.test.ts` | 17 | 所有 API 调用函数，mock fetch |
| `store.test.ts` | 5 | Zustand 状态管理 |
| `components.test.tsx` | 12 | 组件渲染、交互 |
| `evolution.test.tsx` | 19 | 进化面板全功能 |

---

## 8. 开发指南

### 8.1 启动开发环境

```bash
# 终端 1: 启动后端
cd security-agent-orchestrator
cao server --port 9889

# 终端 2: 启动前端
cd security-agent-orchestrator/web
npm install
npm run dev    # → http://localhost:5173
```

### 8.2 添加新的 API 端点

1. **后端**: 在 `main.py` 或 `evolution_routes.py` 添加路由
2. **前端 API 层**: 在 `api.ts` 添加调用函数
3. **前端组件**: 在对应组件中调用
4. **代理**: 如果使用新的路径前缀，需要在 `vite.config.ts` 的 `proxy` 中添加
5. **测试**: 在 `api.test.ts` 和对应组件测试中添加用例

### 8.3 添加新的 Tab 页面

1. 在 `components/` 创建新组件 (`NewPanel.tsx`)
2. 在 `App.tsx` 的 `tabs` 数组中添加条目
3. 在 `App.tsx` 的渲染逻辑中添加 case
4. 在 `components.test.tsx` 中添加渲染测试

### 8.4 终端状态与颜色

| 状态 | 颜色 | 含义 |
|------|------|------|
| `IDLE` | 绿 (emerald) | 空闲等待 |
| `PROCESSING` | 蓝 (blue, 脉冲) | 正在处理 |
| `COMPLETED` | 紫 (purple) | 已完成 |
| `ERROR` | 红 (red) | 出错 |
| `WAITING_USER_ANSWER` | 琥珀 (amber) | 等待用户响应 |

---

## 9. 生产部署注意事项

- `api.ts` 中 `BASE = ''` — 假设 API 与前端同源
- 生产环境需配置反向代理 (如 nginx) 将 `/sessions`, `/terminals`, `/evolution` 等路径转发到 FastAPI
- WebSocket 需要配置 `proxy_pass` + `Upgrade` 头
- `npm run build` 输出到 `dist/`，可作为静态文件部署

```nginx
# nginx 示例
location / {
    root /path/to/web/dist;
    try_files $file $file/ /index.html;
}
location ~ ^/(sessions|terminals|agents|settings|flows|evolution|remotes|health) {
    proxy_pass http://127.0.0.1:9889;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```
