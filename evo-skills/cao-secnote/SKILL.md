---
name: cao-secnote
description: >
  Generate high-value security hunting notes for cross-agent sharing.
  Strict quality gates prevent noise — only confirmed vulns, architectural
  insights, proven techniques, and well-documented dead-ends pass.
  Triggers on: "write security note", "share finding", "分享发现",
  "写安全笔记", "share technique", "分享技巧", "document dead end".
triggers:
  - "write security note"
  - "share finding"
  - "share technique"
  - "document dead end"
  - "分享发现"
  - "写安全笔记"
  - "分享技巧"
  - "记录死胡同"
---

# CAO Security Hunting Note

Write a structured, high-value note to share with other agents hunting
vulnerabilities in the same target project. Every note must pass the
quality gate below. If it doesn't pass, do NOT write it.

This skill exists because context is expensive. A bad note wastes every
agent's attention. Be ruthless about quality.

## Quality Gate (Mandatory — ALL 5 Must Pass)

Before writing anything, run through these checks in order.
If ANY check fails, STOP. Do not write the note.

### 1. SPECIFICITY

Does your note reference CONCRETE artifacts?
File paths, class names, method names, endpoints, line numbers, HTTP methods.

- PASS: "`UserController.java:142`, method `searchUsers(String name)`"
- FAIL: "the auth module seems weak"

### 2. NOVELTY

Search existing notes first:
```
cao_search_knowledge(query="<your topic keywords>", tags="sec-hunting")
```

If a note already covers this finding, technique, or dead-end — STOP.
Only proceed if you have genuinely new information. If you have an update
to an existing note, append to it rather than creating a duplicate.

### 3. ACTIONABILITY

Can another agent ACT on this immediately?

- Reproduce a vulnerability with the steps you provide?
- Apply your technique to a different component?
- Skip a dead-end path without re-investigating?

If the answer is "interesting but no concrete next step" — STOP.

### 4. EVIDENCE

Is your claim backed by at least one of:
- Code snippet or file path with line number
- HTTP request/response pair
- Stack trace or error message
- Configuration line
- Concrete reproduction steps

Speculation without evidence is not a note. "Might be vulnerable" is not a note.

### 5. SEVERITY THRESHOLD

| Type | Threshold |
|------|-----------|
| vuln | severity ≥ medium. Skip low/info findings — they're noise. |
| insight | Must have clear security relevance. "Uses Spring Boot" is not an insight. |
| technique | Must be non-obvious. "I ran a scanner" is not a technique. |
| dead-end | Must have spent meaningful effort (>15 min) OR the dead-end is non-obvious enough that others would waste time on it too. |
| recon | Must reveal non-obvious attack surface that required significant effort to map (>20 min of tracing). Listing publicly visible routes from a Swagger doc is NOT recon. Tracing hidden internal endpoints, undocumented admin routes, or complex data-flow entry points IS recon. |

## What NOT to Write

| Example | Why Rejected |
|---------|-------------|
| "The application uses Spring Boot 2.7.x" | Observable from pom.xml, zero security insight |
| "Found some potential XSS" | Vague — no endpoint, no payload, no evidence |
| "Tried testing the login page" | No finding, no technique, no insight |
| "The API returns 500 on invalid input" | Standard behavior, not a vulnerability |
| "Authentication might be bypassable" | Speculation without evidence |
| "Scanned with tool X, found Y" | Raw tool output without analysis — paste the tool output into a report, not a note |
| "This endpoint is interesting" | Not actionable — interesting how? For what attack? |
| "Similar to CVE-2024-XXXX" | Similarity is not confirmation — prove it or don't note it |

## Note Categories

### `vuln` — Confirmed Vulnerability

A vulnerability you have confirmed or have high confidence in.

Required:
- Severity: critical, high, or medium
- Category: sqli, xss, auth-bypass, ssrf, idor, rce, path-traversal, deserialization, xxe, csrf, insecure-deser, info-leak, etc.
- Target: specific endpoint, class, or method
- Reproduction steps: another agent must be able to reproduce this

### `insight` — Architectural / Design Discovery

A discovery about the target's architecture or design that has security implications.
Not a vulnerability itself, but opens or closes attack vectors.

Required:
- Affected components (classes, modules, config files)
- Security implication: what attack vectors does this open or close?
- Why non-obvious: what would a reader miss without this note?

### `technique` — Proven Approach

A specific technique or approach that yielded results (full or partial).

Required:
- What you tried (exact steps)
- What you found (concrete result)
- Why it worked (the insight behind the technique)

### `dead-end` — Documented Dead End

A path you explored that turned out to be unproductive. Saves others from
repeating the same work.

Required:
- What you tried (exact steps)
- Why it failed (specific reason, not just "didn't work")
- Time invested or complexity of the investigation

### `recon` — Attack Surface Mapping

A non-trivial mapping of the target's attack surface that required significant
effort to uncover. This is NOT a dump of obvious routes — it's the hard-won
understanding of how data enters the system through paths that aren't immediately
visible.

Required:
- Discovery method: how you found these entry points (code tracing, config analysis, runtime observation)
- Entry points: specific endpoints, handlers, message listeners, scheduled tasks, or internal APIs with their input parameters and auth requirements
- Data flow: where user-controlled data enters and which components it reaches
- Effort evidence: what made this non-trivial (hidden routes, undocumented APIs, dynamic dispatch, reflection-based routing, etc.)

Quality bar (strict):
- REJECT: routes copied from Swagger/OpenAPI spec, `@RequestMapping` grep output, or any list that could be generated by a 1-minute scan
- ACCEPT: hidden admin endpoints found by tracing `FilterRegistration` configs, internal RPC handlers discovered through message queue bindings, dynamically registered routes via `HandlerMapping` customization, undocumented file upload paths behind feature flags

## Note Format

```markdown
---
creator: {agent_id}
created: {ISO 8601 timestamp}
tags: [sec-hunting, {task_id}, {category}]
type: {vuln|insight|technique|dead-end|recon}
severity: {critical|high|medium}
category: {sqli|xss|auth-bypass|ssrf|idor|rce|path-traversal|...}
target: {specific component, endpoint, or class}
---
# [{TYPE}] {one-line summary with affected component}

## Evidence
{Max 10 lines. Concrete: code path, HTTP request, config line, stack trace.
 For vuln: full reproduction steps.
 For technique: exact steps that worked.
 For dead-end: what was tried and the specific failure.
 For recon: entry points with parameters, auth requirements, and how you found them.
 Link to files rather than pasting large blocks.}

## Implication
{1-3 sentences. What this means for the hunt.
 For vuln: blast radius, exploitability, chaining potential.
 For insight: which attack vectors this opens/closes.
 For technique: where else to apply this.
 For dead-end: what to skip and why.
 For recon: which entry points are highest-risk and why.}

## Suggested Action
{1-2 sentences. What another agent should DO next.
 Must be concrete — not "investigate further".}
```

Notes for `insight` and `dead-end` types: omit the `severity` field.
Notes for `dead-end` type: omit the `category` field if not applicable.
Notes for `recon` type: omit the `severity` field; use `category: attack-surface`.

## Process

### Step 1: Identify What to Share

You've found something worth sharing. Classify it:
- Found a confirmed vuln? → type `vuln`
- Discovered how the target is built/configured? → type `insight`
- A technique worked (or partially worked)? → type `technique`
- Spent real effort on something that went nowhere? → type `dead-end`
- Mapped non-obvious attack surface through significant effort? → type `recon`

### Step 2: Run the Quality Gate

Go through all 5 checks above. Be honest. If it doesn't pass, move on
with your main task. Not everything is worth a note.

### Step 3: Check for Duplicates

```
cao_search_knowledge(query="{relevant keywords}", tags="sec-hunting")
```

If a matching note exists, either skip or update the existing note with
new information (read it, append, rewrite, push).

### Step 4: Write the Note

Write to the session notes directory:
```
~/.cao-evolution-client/notes/sec-{type}-{target-slug}-{YYYYMMDD-HHMM}.md
```

File naming examples:
- `sec-vuln-user-controller-sqli-20260424-1530.md`
- `sec-insight-auth-filter-path-norm-20260424-1545.md`
- `sec-technique-jwt-none-alg-20260424-1600.md`
- `sec-deadend-image-proxy-ssrf-20260424-1615.md`

Use the note format template above. Keep it compact — aim for 200-400 tokens.

### Step 5: Push

```
cao_push(message="secnote: {type} — {one-line summary}")
```

### Step 6: Resume Main Task

Do not get stuck writing notes. Write, push, move on.

## Examples

### Example: vuln note

```markdown
---
creator: agent-opencode-02
created: 2026-04-24T15:30:00+08:00
tags: [sec-hunting, task-webapp-audit, sqli]
type: vuln
severity: high
category: sqli
target: com.app.controller.UserController#searchUsers
---
# [VULN] SQL injection in UserController.searchUsers via name parameter

## Evidence
`UserController.java:142` concatenates user input directly into JPQL:
`"SELECT u FROM User u WHERE u.name LIKE '%" + name + "%'"`

Reproduction:
GET /api/users?name=test' OR '1'='1' -- 
→ Returns all users (200 OK, 847 records vs normal 3)

No parameterized query, no input sanitization. The `@RequestParam name`
flows directly from Spring MVC into the query string.

## Implication
Any unauthenticated user can dump the entire users table. The same pattern
likely exists in other search endpoints (check ProductController, OrderController).
UNION-based extraction of other tables is feasible.

## Suggested Action
Grep for string concatenation in JPQL/HQL queries across all controllers:
`grep -rn "SELECT.*\" +" src/main/java/ --include="*.java"`
```

### Example: insight note

```markdown
---
creator: agent-opencode-01
created: 2026-04-24T15:45:00+08:00
tags: [sec-hunting, task-webapp-audit, auth-bypass]
type: insight
target: com.app.security.AuthFilter
---
# [INSIGHT] AuthFilter skips JWT validation for /api/public/* but path normalization happens after filter

## Evidence
`AuthFilter.java:38` checks `request.getRequestURI().startsWith("/api/public/")`.
But Spring's `DispatcherServlet` normalizes paths (resolves `..`, decodes `%2F`)
AFTER the filter chain. Confirmed by reading `FilterChainProxy` ordering in
`SecurityConfig.java:25`.

This means `/api/public/../admin/users` bypasses AuthFilter but routes to
`AdminController.listUsers()` after normalization.

## Implication
Any endpoint behind auth can potentially be reached by prefixing `/api/public/..`.
This is a systemic auth bypass — not limited to one endpoint.

## Suggested Action
Test all authenticated endpoints with the `/api/public/../{original-path}` pattern.
Start with admin endpoints (highest impact).
```

### Example: technique note

```markdown
---
creator: agent-opencode-03
created: 2026-04-24T16:00:00+08:00
tags: [sec-hunting, task-webapp-audit, deserialization]
type: technique
category: deserialization
target: com.app.util.SessionSerializer
---
# [TECHNIQUE] Tracing custom deserializers via Spring's RedisTemplate configuration

## Evidence
Standard gadget scanning found nothing — the app doesn't use Java native
serialization on HTTP endpoints. But `RedisConfig.java:42` configures
`RedisTemplate` with `JdkSerializationRedisSerializer` for session storage.

Traced the flow: `SessionController.java:28` → `SessionService.restore()` →
`RedisTemplate.opsForValue().get(sessionId)` → deserialization of attacker-
controlled session blob if session ID is predictable (sequential UUIDs,
`UUIDGenerator.java:15` uses `UUID.randomUUID()` — not predictable, but
session fixation via `JSESSIONID` cookie injection is possible).

## Implication
The attack surface is not HTTP request bodies but Redis session blobs.
If session fixation works, this becomes an RCE chain via deserialization.

## Suggested Action
Test session fixation: set `JSESSIONID` cookie to a known value, authenticate,
check if the server adopts the attacker-supplied session ID.
```

### Example: dead-end note

```markdown
---
creator: agent-opencode-01
created: 2026-04-24T16:15:00+08:00
tags: [sec-hunting, task-webapp-audit, ssrf]
type: dead-end
target: com.app.service.ImageProxyService
---
# [DEAD-END] SSRF via ImageProxyService — blocked by URL whitelist + no redirect following

## Evidence
`ImageProxyService.java:55` fetches external images via `HttpURLConnection`.
Tested SSRF with `url=http://169.254.169.254/latest/meta-data/`.

Blocked by:
1. `UrlValidator.java:23` — whitelist of allowed domains (*.imgur.com, *.cloudinary.com)
2. `HttpURLConnection` configured with `setInstanceFollowRedirects(false)` at line 62
3. Response content-type checked: must be `image/*` (line 71)

Tried DNS rebinding (rebind.network) — blocked because validation and fetch
use the same resolved IP (connection reuse). Tried `file://` — rejected by
`UrlValidator` protocol check (line 18, only http/https allowed).

Spent ~25 minutes on this path.

## Implication
ImageProxyService is well-defended against SSRF. Not worth further investigation
unless the whitelist or redirect config changes.

## Suggested Action
Skip ImageProxyService for SSRF. Look for other HTTP-fetching code paths —
grep for `HttpURLConnection`, `RestTemplate`, `WebClient` in non-proxy contexts.
```

### Example: recon note

```markdown
---
creator: agent-opencode-02
created: 2026-04-24T16:30:00+08:00
tags: [sec-hunting, task-webapp-audit, attack-surface]
type: recon
category: attack-surface
target: com.app.internal.InternalApiDispatcher
---
# [RECON] Hidden internal RPC endpoints behind InternalApiDispatcher — no auth, accepts arbitrary JSON

## Evidence
`InternalApiDispatcher.java:34` registers routes dynamically from `internal-api.yml`
(not in Swagger). Found by tracing `WebMvcConfigurer.addResourceHandlers()` in
`InternalWebConfig.java:18`.

Discovered 4 undocumented endpoints:
- POST /internal/cache/flush — `CacheManager.evictAll()`, no auth check
- POST /internal/user/merge — `UserService.mergeAccounts(srcId, dstId)`, no auth check
- GET  /internal/config/dump — returns full `application.yml` including DB credentials
- POST /internal/job/trigger — `SchedulerService.triggerJob(jobName)`, no auth check

All routes bypass `AuthFilter` because `InternalWebConfig` registers them on a
separate `DispatcherServlet` mapped to `/internal/*` (`ServletRegistrationBean`
at `InternalWebConfig.java:45`), which is not covered by `SecurityConfig`.

Effort: ~30 min tracing from `WebApplicationInitializer` through servlet registration
to handler mapping. These routes are invisible to Swagger and standard endpoint scanning.

## Implication
4 unauthenticated internal endpoints with high-impact operations (credential leak,
account manipulation, cache poisoning, arbitrary job execution). The `/internal/*`
servlet is a completely separate attack surface from the main API.

## Suggested Action
Test each endpoint directly. Priority: /internal/config/dump (info leak) and
/internal/user/merge (account takeover). Check if `/internal/*` is exposed
externally or only on a management port.
```
