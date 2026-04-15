# secskill-evo

基于 **Memento-S** 思路衍生的 Claude Code skill 演化框架。核心理念：skill 不是写完就结束的静态产物，而是可以基于执行反馈**自主反思、自动改进、版本化迭代**的活体。

---

## 设计原则

加载 SKILL.md 后，**agent 本身就是 LLM**——评判、反馈分析、技能重写等全部由 agent 按照指令直接执行，无需额外子进程。只有两类操作需要 Python 脚本：

1. **Git 版本管理**（`scripts/git_version.py`）
2. **描述优化循环**（继承自 skill-creator 的 `run_loop.py`）

---

## 双模式架构

### 创建模式

从零起草 skill → 编写测试用例 → 运行评估 → 人工审查 → 迭代改进 → 打包交付。

### 演化模式（Memento-S 衍生）

当 skill 在实际执行中表现不佳时，触发自动演化循环：

```
用户: "基于本次执行反思并进化"
    │
    ▼
收集上下文（哪个 skill、哪里失败了、期望 vs 实际）
    │
    ▼
LLM-as-Judge 自动评估
  ├── 二元判定：对/错 + 置信度
  ├── 0-10 软评分 + 优缺点分析
  └── 生成改进建议
    │
    ▼
失败模式分析 → 制定改进方案
    │
    ▼
Git 快照当前版本 (v{N})
    │
    ▼
应用改进（最小化、有针对性的修改）
    │
    ▼
验证：重跑 eval，Judge 重新打分
    │
    ├─ 提升/持平 → Git 提交 v{N+1}，展示 diff
    │
    └─ 退步 → Git 回退至 v{N}，报告失败原因
    │
    ▼
记录经验 (TIP.md) + 追踪演化效用 (utility.json)
```

---

## 从 Memento-S 借鉴的核心思想

| 思想 | 实现方式 |
|------|---------|
| **LLM-as-Judge** 二元 + 软评分 | `agents/judge.md` — agent 读取后直接执行评估，输出结构化评分 |
| **失败反馈分析** | 演化模式 Step 3 — 自动归类失败根因（逻辑错误/缺失能力/边界情况/方向错误） |
| **优化后验证门控** | 演化模式 Step 6 — 改完不直接发布，必须重跑 eval 验证不退步才提交 |
| **版本管理 + 安全回退** | `scripts/git_version.py` — 每次演化前后 git commit + tag，退步时 revert |
| **经验累积（TIP）** | 演化模式 Step 9 — 将本轮发现的失败模式和设计决策写入 TIP.md |
| **效用追踪** | `utility.json` — 记录每次演化的触发原因、变更内容、前后分数、成败状态 |

---

## 目录结构

```
secskill-evo/
├── SKILL.md                    # 主文档：双模式（创建 + 演化）
├── agents/
│   ├── grader.md               # 断言评估
│   ├── comparator.md           # 盲比 A/B 对照
│   ├── analyzer.md             # 基准分析
│   └── judge.md                # ★ LLM-as-Judge 评估指令
├── assets/
│   └── eval_review.html        # 触发率评估 HTML 模板
├── eval-viewer/
│   └── generate_review.py      # 评审视图生成器
├── references/
│   └── schemas.md              # 所有 JSON schema 定义
└── scripts/
    ├── git_version.py           # ★ Git 版本管理 CLI
    ├── utils.py                 # 共享工具函数
    ├── run_eval.py              # 触发率评估
    ├── improve_description.py   # 描述优化
    ├── run_loop.py              # 描述优化循环
    ├── generate_report.py       # 报告生成
    ├── aggregate_benchmark.py   # 基准聚合
    ├── package_skill.py         # 打包 .skill 文件
    └── quick_validate.py        # 快速校验
```

标 ★ 为 secskill-evo 新增文件。

---

## git_version.py 命令

所有命令输出 JSON，便于 agent 解析：

```bash
# 初始化（检测是否已在 git 仓库内，避免嵌套初始化）
python3 -m scripts.git_version init <skill-dir>

# 提交快照 + 可选 tag
python3 -m scripts.git_version commit <skill-dir> -m "v2: fix edge case" --tag v2

# 查看版本历史
python3 -m scripts.git_version log <skill-dir>

# 查看两版本间差异
python3 -m scripts.git_version diff <skill-dir> --from v1 --to v2

# 非破坏性回退到指定版本
python3 -m scripts.git_version revert <skill-dir> --to v1

# 获取当前版本信息
python3 -m scripts.git_version current <skill-dir>
```

---

## 触发方式

以下用户输入会激活演化模式：

- `"反思并进化"` / `"基于本次执行反思并进行进化"`
- `"reflect and evolve"` / `"evolve this skill"`
- `"the skill failed on X"` / `"fix the skill"`
- 任何描述 skill 执行失败并希望改进的上下文
