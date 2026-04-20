# Settings

CAO stores user configuration in `~/.aws/cli-agent-orchestrator/settings.json`. This file is managed by the settings service and can be edited via the Web UI Settings page or the REST API.

## Agent Profile Directories

CAO discovers agent profiles by scanning multiple directories. When loading or listing profiles, directories are scanned in this order (first match wins):

1. **Local store** — `~/.aws/cli-agent-orchestrator/agent-store/`
2. **Provider-specific directories** — Configured per provider (see defaults below)
3. **Extra custom directories** — User-added paths
4. **Built-in store** — Bundled with the CAO package

### Default Directories

| Key | Provider | Default Path |
|-----|----------|-------------|
| `kiro_cli` | Kiro CLI | `~/.kiro/agents` |
| `q_cli` | Q CLI | `~/.aws/amazonq/cli-agents` |
| `claude_code` | Claude Code | `~/.aws/cli-agent-orchestrator/agent-store` |
| `codex` | Codex | `~/.aws/cli-agent-orchestrator/agent-store` |
| `cao_installed` | CAO Installed | `~/.aws/cli-agent-orchestrator/agent-context` |

The `cao_installed` directory is where `cao install` places agent profiles. This keeps installed profiles separate from hand-authored ones in `agent-store`.

### Overriding Directories

Override any provider directory via the REST API or Web UI Settings page:

```bash
# Via REST API
curl -X POST http://localhost:9889/settings/agent-dirs \
  -H "Content-Type: application/json" \
  -d '{"kiro_cli": "/custom/path/to/agents"}'
```

Or edit `settings.json` directly:

```json
{
  "agent_dirs": {
    "kiro_cli": "/custom/path/to/agents"
  }
}
```

Only specified providers are updated; others retain their defaults.

### Extra Directories

Add additional directories that are scanned for agent profiles across all providers:

```json
{
  "extra_agent_dirs": [
    "/path/to/team-shared-agents",
    "/path/to/project-specific-agents"
  ]
}
```

## settings.json Format

```json
{
  "agent_dirs": {
    "kiro_cli": "~/.kiro/agents",
    "q_cli": "~/.aws/amazonq/cli-agents",
    "claude_code": "~/.aws/cli-agent-orchestrator/agent-store",
    "codex": "~/.aws/cli-agent-orchestrator/agent-store",
    "cao_installed": "~/.aws/cli-agent-orchestrator/agent-context"
  },
  "extra_agent_dirs": []
}
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/settings/agent-dirs` | Get current agent directories (merged with defaults) |
| `POST` | `/settings/agent-dirs` | Update agent directories |
| `GET` | `/settings/extra-agent-dirs` | Get extra custom directories |
| `POST` | `/settings/extra-agent-dirs` | Set extra custom directories |

See [api.md](api.md) for the full API reference.

---

## config.yaml — Hub 级配置

除了 `settings.json`（运行时 Agent 目录配置），CAO 还支持 YAML 格式的 Hub 级配置文件，用于控制 Root Orchestrator 等 Hub 侧功能。

### 路径

默认路径：`~/.aws/cli-agent-orchestrator/config.yaml`

可通过环境变量覆盖：
```bash
export CAO_CONFIG=/path/to/custom/config.yaml
```

### 格式

```yaml
root_orchestrator:
  enabled: true              # 是否启动 Root Orchestrator（默认 true）
  provider: clother_closeai   # 使用的 Agent 提供者（默认 clother_closeai）
  profile: root_orchestrator  # Agent Profile 名称（默认 root_orchestrator）
  session: ROOT               # tmux session 名称后缀（默认 ROOT，实际为 cao-ROOT）
```

### 默认值

如果 `config.yaml` 不存在或某字段缺失，使用以下默认值：

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `root_orchestrator.enabled` | `true` | 启用/禁用 Root Orchestrator |
| `root_orchestrator.provider` | `clother_closeai` | provider 类型 |
| `root_orchestrator.profile` | `root_orchestrator` | 内置的 Root Orchestrator profile |
| `root_orchestrator.session` | `ROOT` | tmux session = `cao-ROOT` |

### 与 settings.json 的关系

| 配置 | 格式 | 用途 | 修改方式 |
|------|------|------|----------|
| `settings.json` | JSON | Agent profile 目录映射 | Web UI / REST API |
| `config.yaml` | YAML | Hub 级功能配置 | 手动编辑 |
