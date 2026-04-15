# Recall + 选择性同步 设计文档

> **核心思路**：BM25 recall 做发现（轻量），git 做传输（完整文件同步）。
> 当前采用单仓方案，以下保留**未实现**的远期目标设计。

---

## 一、已实现（当前状态）

| 组件 | 文件 | 说明 |
|------|------|------|
| RecallIndex (BM25) | `evolution/recall_index.py` ~436 行 | Hub 端 BM25 Okapi 内存索引，自动 build + 增量 update |
| recall API | `api/evolution_routes.py` | `GET /recall?q=&top_k=` 返回排序结果；`GET /recall/{doc_id}` 获取完整内容 |
| Checkpoint 回调 | `evolution/checkpoint.py` | commit 和 pull 后自动触发 `on_commit` -> `update_incremental()` |
| Bridge MCP 工具 | `cao_bridge_mcp.py` | `cao_recall(query, top_k)`, `cao_fetch_document(doc_id)` |
| Hub MCP 工具 | `evolution_tools.py` | 同上，供本地 Agent 使用 |
| Agent Git 同步 | `checkpoint.py` | Agent push 后 Hub `_sync_remote()` pull -> BM25 增量更新 |

**单仓扁平布局**（已从 `shared/` 迁移为扁平目录）：

```
.cao-evolution/
├── tasks/{task_id}/task.yaml
├── attempts/{task_id}/{run_id}.json
├── skills/{name}/SKILL.md
├── notes/*.md
│   └── _synthesis/
├── graders/
└── reports/
```

---

## 二、未实现：多仓架构（远期）

### 2.1 仓库拆分

```
~/.cao-evolution/
├── skills/        # Git 仓 1: 技能文件
│   └── .git/
├── notes/         # Git 仓 2: 知识笔记
│   └── .git/
├── attempts/      # Git 仓 3: 评分记录
│   └── .git/
└── graders/       # Git 仓 4: 评分脚本
    └── .git/
```

### 2.2 选择性同步：Partial Clone + Sparse Checkout

Agent 端只拉需要的文件，而非全量同步：

```bash
# Partial Clone（仅元数据，不下载文件内容）
git clone --filter=blob:none --sparse <remote> ~/.cao-evolution/local/skills

# recall 发现后，Sparse Checkout 指定路径
git sparse-checkout add sql-inject-v2 xss-detector

# 本地进化 + 推回
git add sql-inject-v2/ && git commit -m "evolve: v3" && git push
```

### 2.3 批量拉取 API（未实现）

```
POST /evolution/recall/batch
  body: { ids: [{ type: "skill", id: "sql-inject-v2" }, ...] }
  -> list[{ meta, content }]
```

### 2.4 RepoManager 路径抽象层（未实现）

```python
class RepoManager:
    def __init__(self, evolution_dir, mode="single"):  # "single" | "multi"
        ...
    def get_dir(self, content_type: str) -> Path:
        ...
    def checkpoint(self, content_type, agent_id, message):
        ...
```

### 2.5 CaoBridge selective_sync（未实现）

```python
def selective_sync(self, query, doc_type="skill", top_k=5) -> list[Path]:
    # recall() + fetch() + save -> 返回本地文件路径列表
    ...
```

---

## 三、迁移路径

| 阶段 | 状态 | 内容 |
|------|------|------|
| Phase A: 单仓 + BM25 recall | ✅ 已完成 | RecallIndex, API, MCP 工具, git sync |
| Phase B: 多仓拆分 | 未实施 | RepoManager multi 模式, git filter-branch 拆仓 |
| Phase C: Sparse checkout | 未实施 | Agent 端按需拉取, 降低网络和存储开销 |

**迁移对 Agent 侧的影响**：零。Agent 通过 recall API 发现 + git/HTTP 拉取，
不关心 Hub 内部是一个仓还是多个仓。

---

## 四、FAQ

**Q: 为什么不用 memsearch 做召回？**
A: memsearch 需要 Milvus + embedding API，重依赖。BM25 零依赖足够覆盖初期需求。
RecallIndex 预留了 `embed_fn` 接口，未来可接入向量检索。

**Q: RecallIndex 重启后丢失怎么办？**
A: Hub 启动时调用 `recall_index.build()` 从文件重建。几千文件 < 1 秒。

**Q: 两个 Agent 同时 push 同一个 skill 怎么办？**
A: 后 push 收到 merge conflict。推荐每次 push 前 `git pull --rebase`。
不同 skill 是独立目录，跨 skill 不会冲突。
