---
name: cao-build-l1-secindex
description: >
  Build or incrementally update the L1 Security Hunting Briefing from sec-* notes.
  Compact index (≤600 tokens, hard cap 800) injected into agent context at session start.
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
incrementally update a compact hunting briefing at `<session_dir>/sec-index.md`.
Then push via `cao_push` so other agent instances get the updated index.

The index is NOT a vulnerability report. It is a **hunting guide** — it tells
the next agent where to look, what works, what to skip, and what traps to avoid.

## Token Budget

- Target: ≤600 tokens
- Hard cap: 800 tokens
- Format: one line per item, no paragraphs, no explanations
- The index is a pointer layer — agents use `cao_search_knowledge` for details

When the index exceeds 800 tokens, compress:
1. Merge same-category items into a single line (e.g., "3 SQLi in search endpoints: UserCtrl, ProductCtrl, OrderCtrl")
2. Drop note filename references (agents can search by keyword)
3. Collapse Pitfalls and Cold Zones to comma-separated lists

## Index Structure

```markdown
---
generated: {ISO 8601 timestamp}
indexed_notes: [{list of sec-*.md filenames already indexed}]
---
# Sec Hunting Briefing ({N} notes)

## Architecture
{From insight notes. Key architectural facts with security relevance.
 One bullet per fact. Max 5 bullets.}

## Hot Zones
{From vuln notes — NOT the vulns themselves, but areas where similar
 patterns likely exist. One bullet per zone. Max 5 bullets.}

## Tips & Tricks
{From technique/insight/vuln notes. Interesting discoveries, small tricks,
 and experience that help hunt more effectively. Max 4 bullets.}

## Chains
{Cross-note connections: partial findings that combine into higher impact.
 One bullet per chain. Max 3 bullets.}

## Pitfalls
{From dead-end notes. Specific approaches/methods that failed or wasted time.
 Saves others from repeating the same mistakes. Max 4 bullets.}

## Cold Zones
{From dead-end notes. Areas confirmed well-defended — skip entirely.
 One bullet per zone. Max 4 bullets.}
```

Sections with zero items: omit entirely (don't write empty headers).

## Section Rules

### Architecture (source: `insight` notes)

Extract structural facts that affect how to attack:
- Auth mechanism and where it's enforced
- ORM/query patterns (parameterized? raw concat?)
- Serialization formats and where they're used
- Trust boundaries between components
- Framework-specific behaviors (filter ordering, path normalization)

DO NOT include: framework versions, dependency lists, or anything
observable from pom.xml/build.gradle without security relevance.

### Hot Zones (source: `vuln` notes)

A confirmed vuln means the PATTERN likely exists elsewhere. Extract:
- The vulnerable pattern (not the specific vuln)
- Where else the same pattern appears
- Why this zone is "hot" (what to grep for)

Example:
- `Search endpoints: raw JPQL concat (UserCtrl confirmed → check ProductCtrl, OrderCtrl)`

NOT: `[HIGH] SQLi in UserController.searchUsers` — that's a finding, not a zone.

### Tips & Tricks (source: `technique` + `insight` + `vuln` notes)

Interesting discoveries, small tricks, and experience-based advice that help
other agents hunt more effectively on THIS specific target. Broader than
"techniques" — captures any useful knowledge nugget worth sharing.

Include:
- Non-obvious approaches that yielded results
- Shortcuts or patterns specific to this codebase
- Observations that change how you'd approach the target

Example:
- `Trace RedisTemplate serializer config → hidden deserialization surfaces`
- `/api/public/../{path} bypasses URI-prefix auth filters (normalization after filter)`

NOT: `Used sqlmap` — that's a tool, not a trick.
NOT: `Read the source code carefully` — that's generic advice, not target-specific.

### Chains (source: cross-note inference)

Look across ALL notes for partial findings that could combine:
- Agent A found X + Agent B found Y → together they might enable Z

Example:
- `AuthFilter path bypass (agent-01) + AdminController no extra auth check (agent-02) → unauthenticated admin access? (unverified)`

Only include chains where the combination is non-obvious. If it's obvious
from a single note, it belongs in that note's Suggested Action, not here.

### Pitfalls (source: `dead-end` + `technique` notes)

Specific approaches, methods, or assumptions that FAILED or WASTED TIME.
Different from Cold Zones — Pitfalls are about HOW you attacked (method),
Cold Zones are about WHERE you attacked (area).

Include:
- Approaches that looked promising but hit a wall (and why)
- Common assumptions about this target that turn out to be wrong
- Time sinks that other agents should skip

Example:
- `DNS rebinding against ImageProxy fails: validation and fetch reuse same resolved IP`
- `Don't assume /actuator is exposed — Spring Boot actuator is disabled in prod profile`

NOT: `Testing took a long time` — that's a complaint, not a pitfall.

### Cold Zones (source: `dead-end` notes)

Areas confirmed well-defended. One line: component + why it's cold.
Different from Pitfalls — Cold Zones are about WHERE (the area is locked down),
Pitfalls are about HOW (the method doesn't work).

Example:
- `ImageProxyService SSRF: whitelist + no redirect + content-type check`

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
- `type` from frontmatter (vuln, insight, technique, dead-end)
- `target` from frontmatter
- `category` from frontmatter (if present)
- The Evidence and Implication sections (key content)

### Step 4: Merge into Index

For each new note, update the appropriate section:

| Note type | Updates sections |
|-----------|-----------------|
| `insight` | Architecture, Tips & Tricks |
| `vuln` | Hot Zones, Tips & Tricks, Chains |
| `technique` | Tips & Tricks, Pitfalls |
| `dead-end` | Pitfalls, Cold Zones |

Merge rules:
- If a bullet for the same target/component already exists, UPDATE it (don't duplicate)
- If adding a bullet would exceed the section's max count, merge related items

### Step 5: Check Token Budget

Estimate the index size. If it exceeds ~800 tokens:
1. Merge same-category bullets: "3 SQLi in search endpoints: UserCtrl, ProductCtrl, OrderCtrl"
2. Drop filename references
3. Collapse Pitfalls and Cold Zones into comma-separated lists
4. Trim Tips & Tricks to top 3 most impactful items

### Step 6: Write and Push

Write the updated index to `<session_dir>/sec-index.md`.
Update the `generated` timestamp and `indexed_notes` list in frontmatter.

```
cao_push(message="secindex: updated with N new notes (total M)")
```

### Step 7: Report

Output a one-line summary:
"Security hunting index updated: +{new} notes, {total} indexed. {brief description of what changed}."

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
---
# Sec Hunting Briefing (6 notes)

## Architecture
- Auth: JWT via AuthFilter, path-prefix skip for /api/public/* (normalization after filter)
- ORM: JPQL via EntityManager, no global parameterized query enforcement
- Session: Redis + JdkSerializationRedisSerializer (Java native serialization)

## Hot Zones
- Search endpoints: raw JPQL concat (UserCtrl confirmed → ProductCtrl, OrderCtrl same pattern)
- Access control: OrderController uses user-supplied ID without ownership check → other CRUD controllers?

## Tips & Tricks
- Trace RedisTemplate serializer config → hidden deserialization surfaces
- /api/public/../{path} bypasses URI-prefix auth filters (normalization after filter)
- Check @PreAuthorize for object-level vs field-level permission gaps

## Chains
- AuthFilter path bypass + AdminController (no extra auth) → unauthenticated admin access? (unverified)
- Redis session deser + session fixation → potential RCE chain (unverified)

## Pitfalls
- DNS rebinding against ImageProxy fails: validation and fetch reuse same resolved IP
- Don't assume /actuator is exposed — disabled in prod profile (checked application-prod.yml)

## Cold Zones
- ImageProxyService SSRF: domain whitelist + no redirect + content-type check
```

This example is ~350 tokens — well within budget with room to grow.
