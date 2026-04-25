---
name: cao-build-l1-secindex
description: >
  Build or incrementally update the L1 Security Hunting Index from sec-* notes.
  Compact pointer index (≤600 tokens, hard cap 1000) injected into agent context
  at session start. Each entry is a one-line hook that guides agents to read the
  full note when relevant.
  Triggers on: "build security index", "update security index",
  "构建安全索引", "更新安全索引".
triggers:
  - "build security index"
  - "update security index"
  - "构建安全索引"
  - "更新安全索引"
---

# Build L1 Security Hunting Index

Read `sec-*.md` notes from the session notes directory, and build or
incrementally update a compact hunting index at `<session_dir>/sec-index.md`.
Then push via `cao_push` so other agent instances get the updated index.

The index is NOT a vulnerability report or a summary. It is a **pointer layer**
— each entry is a one-line hook that tells the agent "when you encounter this
situation, go read the full note". Agents use `cao_fetch_document` or
`cao_search_knowledge` to get details.

## Token Budget

- Target: ≤600 tokens
- Hard cap: 1000 tokens
- Format: one entry per line, each entry = hook sentence → note filename
- Do NOT write full conclusions — write hooks that trigger agents to read more

When the index exceeds 1000 tokens, compress:
1. Merge same-category vuln entries (e.g., "搜索类接口容易出现JPQL注入，案例见 → note1, note2")
2. Drop oldest dead-end entries first (least likely to be re-encountered)
3. Keep all insight and recon entries (highest reuse value)

## Index Structure

Sections align directly with secnote types. Plus one cross-note section (Chains).

```markdown
---
generated: {ISO 8601 timestamp}
indexed_notes: [{list of sec-*.md filenames already indexed}]
---
# Sec Hunting Index ({N} notes)

## Vulns
{From vuln notes. Pattern-level hooks — what type of component/interface
 is prone to what type of vulnerability. NOT specific findings.}

## Insights
{From insight notes. Architectural or design discoveries with security
 relevance. State the discovery, point to details.}

## Techniques
{From technique notes. When you need to achieve X, here's a proven approach.}

## Dead Ends
{From dead-end notes. Advise against specific attempts that have been
 confirmed fruitless.}

## Recon
{From recon notes. Areas with undocumented or hidden attack surface.}

## Chains
{Cross-note inference. Partial findings from different notes that may
 combine into higher-impact attacks.}

---
以上为历史经验索引，仅供参考。请专注于当前任务目标，只在以下情况
获取note详情：(1) 当前正在审计的组件/模式与某条索引直接相关；
(2) 即将尝试的方法已被Dead Ends标记。不要主动拉取所有note。
```

Sections with zero items: omit entirely (don't write empty headers).
The trailing guidance block is MANDATORY — always append it after the last section.

## Entry Format by Type

Each entry is one line: a hook sentence followed by `→ {note filename}`.

The hook must give enough context for the agent to judge relevance to their
current task, but must NOT give the full conclusion — the goal is to drive
the agent to read the original note.

### Vulns

Style: `{组件类型/模式}容易出现{漏洞类型}，案例见`

The hook describes the PATTERN, not the specific instance. When an agent
encounters a similar component, the hook triggers them to read the case study.

Examples:
- `搜索类接口容易出现JPQL注入，案例见 → sec-vuln-user-controller-sqli-20260424-1530.md`
- `CRUD接口容易出现IDOR，案例见 → sec-vuln-order-controller-idor-20260424-1625.md`

NOT: `UserController.searchUsers存在SQL注入` — that's a finding, not a hook.

### Insights

Style: `{发现了什么}，详情见`

State the discovery as a fact. Don't explain the full implication — let the
agent read the note for that.

Examples:
- `Spring路径归一化发生在filter chain之后，详情见 → sec-insight-auth-filter-path-norm-20260424-1545.md`
- `Redis session使用了Java原生序列化，详情见 → sec-insight-session-redis-20260424-1620.md`

NOT: `当审计auth filter时，path normalization发生在filter之后，/api/public/../可绕过` — too much detail, agent won't read the note.

### Techniques

Style: `要{达成某目标}时，参考`

Describe the goal/scenario, not the method. The method is in the note.

Examples:
- `要找隐藏的反序列化攻击面时，参考 → sec-technique-redis-deser-20260424-1600.md`
- `要绕过基于URI前缀的认证检查时，参考 → sec-technique-path-norm-bypass-20260424-1700.md`

NOT: `追踪RedisTemplate的serializer配置可以找到反序列化面` — that gives away the technique.

### Dead Ends

Style: `不建议{尝试某事}，原因见`

Directly advise against the attempt. The agent reads the note only if they
were about to try the same thing.

Examples:
- `不建议对ImageProxyService尝试SSRF，原因见 → sec-deadend-image-proxy-ssrf-20260424-1615.md`
- `不建议尝试/actuator端点探测，原因见 → sec-deadend-actuator-disabled-20260424-1700.md`

NOT: `ImageProxyService有域名白名单+禁止重定向+content-type校验` — that's the conclusion, not a hook.

### Recon

Style: `{区域}存在未文档化攻击面，详情见`

Signal that hidden attack surface exists in an area. The agent reads the note
to get the specific endpoints and entry points.

Examples:
- `/internal/*存在独立未认证攻击面，详情见 → sec-recon-internal-api-dispatcher-20260424-1630.md`
- `MQ消息监听器存在未验证的数据入口，详情见 → sec-recon-mq-listeners-20260424-1700.md`

NOT: `/internal/*有4个无认证端点(cache/flush, user/merge, config/dump, job/trigger)` — too detailed for an index.

### Chains

Style: `{发现A} + {发现B}，可能存在关联，见`

Point to multiple notes whose findings may combine. The chain hypothesis
itself is the hook.

Examples:
- `AuthFilter路径绕过 + /internal/*无认证，可能存在关联，见 → sec-insight-auth-filter-path-norm-20260424-1545.md, sec-recon-internal-api-dispatcher-20260424-1630.md`

Only include chains where the combination is non-obvious.

## Process

### Step 1: Check for Existing Index

Read `<session_dir>/sec-index.md` if it exists. Extract the `indexed_notes`
list from YAML frontmatter.

If the file doesn't exist, start with an empty index (all notes are "new").

### Step 2: Find New Notes

List all `sec-*.md` files in `<session_dir>/notes/`.
Exclude `sec-index.md` itself if present in notes dir.

Compare against `indexed_notes`. Identify files NOT in the list — these
are new and need to be indexed.

If no new notes exist, report "Security index is up to date ({N} notes indexed)."
and STOP. Do not rewrite the index unnecessarily.

### Step 3: Read New Notes

Read only the new `sec-*.md` files. For each, extract:
- `type` from frontmatter (vuln, insight, technique, dead-end, recon)
- `target` from frontmatter
- `category` from frontmatter (if present)
- The title line (# [...] one-line summary)

These fields are sufficient to write the hook. Do NOT summarize the Evidence
or Implication sections — that defeats the purpose of the pointer layer.

### Step 4: Write Hook Entry

For each new note, write one hook entry following the format rules above.
Place it in the matching section:

| Note type | Section |
|-----------|---------|
| `vuln` | Vulns |
| `insight` | Insights |
| `technique` | Techniques |
| `dead-end` | Dead Ends |
| `recon` | Recon |

Then scan across ALL indexed notes for potential Chains (cross-note combinations).

### Step 5: Merge into Index

Merge rules:
- If a hook for the same target/component already exists, UPDATE it (don't duplicate)
- If two vuln notes describe the same pattern in different components, merge:
  `搜索类接口容易出现JPQL注入，案例见 → note1, note2`

### Step 6: Check Token Budget

Estimate the index size. If it exceeds ~1000 tokens:
1. Merge same-pattern vuln entries into one line with multiple note refs
2. Drop oldest dead-end entries first
3. Keep all insight and recon entries (highest cross-task reuse value)
4. Collapse chains to top 2 most impactful

### Step 7: Write and Push

Write the updated index to `<session_dir>/sec-index.md`.
Update the `generated` timestamp and `indexed_notes` list in frontmatter.

```
cao_push(message="secindex: updated with N new notes (total M)")
```

### Step 8: Report

Output a one-line summary:
"Security hunting index updated: +{new} notes, {total} indexed."

Then resume your main task.

## Example: Full Index

```markdown
---
generated: 2026-04-24T16:30:00+08:00
indexed_notes:
  - sec-vuln-user-controller-sqli-20260424-1530.md
  - sec-insight-auth-filter-path-norm-20260424-1545.md
  - sec-technique-redis-deser-20260424-1600.md
  - sec-deadend-image-proxy-ssrf-20260424-1615.md
  - sec-insight-session-redis-20260424-1620.md
  - sec-vuln-order-controller-idor-20260424-1625.md
  - sec-recon-internal-api-dispatcher-20260424-1630.md
---
# Sec Hunting Index (7 notes)

## Vulns
- 搜索类接口容易出现JPQL注入，案例见 → sec-vuln-user-controller-sqli-20260424-1530.md
- CRUD接口容易出现IDOR，案例见 → sec-vuln-order-controller-idor-20260424-1625.md

## Insights
- Spring路径归一化发生在filter chain之后，详情见 → sec-insight-auth-filter-path-norm-20260424-1545.md
- Redis session使用了Java原生序列化，详情见 → sec-insight-session-redis-20260424-1620.md

## Techniques
- 要找隐藏的反序列化攻击面时，参考 → sec-technique-redis-deser-20260424-1600.md

## Dead Ends
- 不建议对ImageProxyService尝试SSRF，原因见 → sec-deadend-image-proxy-ssrf-20260424-1615.md

## Recon
- /internal/*存在独立未认证攻击面，详情见 → sec-recon-internal-api-dispatcher-20260424-1630.md

## Chains
- AuthFilter路径绕过 + /internal/*无认证，可能存在关联，见 → sec-insight-auth-filter-path-norm-20260424-1545.md, sec-recon-internal-api-dispatcher-20260424-1630.md
- Redis session反序列化 + session fixation，可能存在关联，见 → sec-insight-session-redis-20260424-1620.md, sec-technique-redis-deser-20260424-1600.md

---
以上为历史经验索引，仅供参考。请专注于当前任务目标，只在以下情况
获取note详情：(1) 当前正在审计的组件/模式与某条索引直接相关；
(2) 即将尝试的方法已被Dead Ends标记。不要主动拉取所有note。
```

This example is ~330 tokens — well within budget with room for 20+ more notes.
