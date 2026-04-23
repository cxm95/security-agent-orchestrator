# CAO Local-Only Mode — 快速上手指南

> 无需 Hub 服务器，多个 opencode 实例通过本地 git 共享 notes 和 skills。

## 一键安装（推荐）

```bash
cd /path/to/security-agent-orchestrator
bash cao-bridge/opencode/install_local.sh
```

脚本自动完成：插件安装 → skills 安装 → Python 依赖 → opencode.json MCP 配置 → 验证。
安装完成后设置环境变量并启动：

```bash
export CAO_LOCAL_ONLY=1
opencode /path/to/project
```

> 非交互模式（CI/Docker）：`bash install_local.sh --yes`

以下是手动安装的详细步骤，一键安装成功后可跳过。

---

## 前置条件

| 依赖 | 最低版本 | 检查命令 |
|------|---------|---------|
| opencode | 1.14+ | `opencode --version` |
| git | 2.25+ | `git --version` |
| python3 | 3.9+ | `python3 --version` |
| pip 包: fastmcp, requests | — | `pip3 install fastmcp requests` |

## 手动安装第一步：安装 cao-bridge 插件

```bash
cd /path/to/security-agent-orchestrator
bash cao-bridge/opencode/install.sh --global
```

安装完成后检查：
```bash
ls ~/.config/opencode/plugins/cao-bridge.ts    # 插件
ls ~/.config/opencode/skills/                   # skills 列表
```

## 手动安装第二步：配置 opencode.json

编辑 `~/.config/opencode/opencode.json`（没有就新建）：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "permission": "allow",
  "mcp": {
    "cao-bridge": {
      "type": "local",
      "command": ["python3", "<绝对路径>/cao-bridge/cao_bridge_mcp.py"],
      "environment": {
        "CAO_LOCAL_ONLY": "1",
        "CAO_AGENT_PROFILE": "remote-opencode"
      }
    }
  }
}
```

> **注意**：把 `<绝对路径>` 替换为 `security-agent-orchestrator` 的实际路径。

## 手动安装第三步：设置环境变量

```bash
# 加到 ~/.bashrc 或 ~/.zshrc 中持久化
export CAO_LOCAL_ONLY=1
```

这一个变量控制所有行为：
- 跳过 Hub 注册/上报/心跳
- 自动创建本地 bare repo (`~/.cao-evolution-local/shared.git`)
- notes/skills 通过本地 git 在实例间共享

## 启动 opencode

### TUI 模式（交互式）
```bash
CAO_LOCAL_ONLY=1 opencode /path/to/your/project
```

### Serve 模式（无头 HTTP 服务）
```bash
# 实例 1
CAO_LOCAL_ONLY=1 opencode serve --port 19001

# 实例 2（另一个终端）
CAO_LOCAL_ONLY=1 opencode serve --port 19002
```

Serve 模式 HTTP API：
```bash
# 创建 session
curl -X POST http://127.0.0.1:19001/session -H "Content-Type: application/json" -d '{}'

# 发送 prompt（替换 SESSION_ID）
curl -X POST http://127.0.0.1:19001/session/<SESSION_ID>/message \
  -H "Content-Type: application/json" \
  -d '{"parts":[{"type":"text","text":"你的 prompt"}]}'
```

## 使用：写 Note 并共享

在对话中让 agent 执行：

```
请帮我写一个关于 XXX 的 note，保存到 ~/.cao-evolution-client/notes/xxx.md，
然后调用 cao_push 工具推送到共享仓库。
```

或者分步操作：
1. Agent 调用 `cao_register` → 初始化 session
2. Agent 写 note 文件到 `~/.cao-evolution-client/notes/`
3. Agent 调用 `cao_push` → git commit + push 到本地 bare repo

其他实例下次 `cao_register` 或 `cao_push` 时会自动 pull 到最新。

## 使用：搜索共享知识

```
请调用 cao_search_knowledge 工具，搜索 "关键词"。
```

Agent 会在本地 `notes/` 目录中进行关键词匹配搜索。

## 使用：构建 L1 知识索引

当积累了 3 篇以上 note 后，手动触发：

```
build l1 index
```

或中文触发：

```
构建知识索引
```

Agent 会读取所有 notes，综合生成 `~/.cao-evolution-client/index.md`，
并推送到共享 repo。其他实例可以读取该索引获得全局知识概览。

## 目录结构

```
~/.cao-evolution-local/
  shared.git/              ← 本地 bare repo（自动创建，所有实例共享）

~/.cao-evolution-client/
  .git/                    ← 从 shared.git clone 的工作副本
  notes/                   ← 共享笔记
    snake-techniques.md
    tetris-techniques.md
  skills/                  ← 共享 skills
    cao-reflect/
    cao-consolidate/
  index.md                 ← L1 知识索引（手动触发生成）
  state/                   ← agent 状态文件

~/.config/opencode/
  plugins/cao-bridge.ts    ← CAO Bridge 插件
  skills/                  ← 本地 skills（含 cao-build-l1-index）
  opencode.json            ← MCP + 权限配置
```

## 常见问题

### Q: 第一次启动报 git 错误？
A: 首次启动时 `ensure_local_shared_repo()` 会自动创建 bare repo 并 seed 初始 commit。
如果遇到问题，手动删除后重试：
```bash
rm -rf ~/.cao-evolution-local ~/.cao-evolution-client
```

### Q: 两个实例的 note 没有同步？
A: 确认两个实例都设置了 `CAO_LOCAL_ONLY=1`，且都调用了 `cao_push`。
手动检查：
```bash
git -C ~/.cao-evolution-local/shared.git log --oneline
git -C ~/.cao-evolution-client pull origin main
```

### Q: 如何切换回 Hub 模式？
A: 去掉 `CAO_LOCAL_ONLY=1` 环境变量，设置 `CAO_HUB_URL` 指向 Hub 地址即可。

### Q: MCP 工具不可用？
A: 检查 `opencode.json` 中 `cao-bridge` MCP 配置的 python3 路径是否正确：
```bash
python3 /path/to/cao-bridge/cao_bridge_mcp.py --help
```

### Q: 如何查看 agent 的 CAO 状态？
A: 让 agent 调用 `cao_session_info` 工具，会返回 session_id、目录、状态等信息。
