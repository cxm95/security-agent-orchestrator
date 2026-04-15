---
name: openspace-evo
description: >
  Evolve skills using OpenSpace-inspired strategies: DERIVED (mutate/crossover
  existing skills to create new variants), CAPTURED (extract reusable skills from
  agent work), and lineage tracking (.lineage.json). Use when the heartbeat
  suggests creating new skill variants, when you notice a reusable pattern in
  your work, or when asked to "derive a new skill", "capture this as a skill",
  "创建技能变体", "提炼技能".
---

# OpenSpace-Evo

Evolve the skill ecosystem using three strategies inspired by the OpenSpace
framework. Unlike secskill-evo (which **fixes** an existing skill in place),
openspace-evo **creates new skills** and **manages lineage** across the skill
population.

## Three Strategies

| Strategy | Input | Output | When to Use |
|----------|-------|--------|-------------|
| **DERIVED** | Existing skill(s) | New skill variant | Plateau — try mutations of what works |
| **CAPTURED** | Agent's recent work | New skill | You discovered a reusable pattern |
| **Lineage Management** | Any skill creation/modification | `.lineage.json` | Always — track every skill's ancestry |

## Strategy Detection

Determine which strategy to use:

- **DERIVED** triggers on: heartbeat "evolve_skill" with plateau, "derive a variant",
  "create a mutation", "try a different version", "创建技能变体"
  → Jump to [DERIVED Strategy](#derived-strategy)
- **CAPTURED** triggers on: "capture this as a skill", "extract a skill from this",
  "提炼技能", "I keep doing this pattern", or when you notice repeated tool/workflow usage
  → Jump to [CAPTURED Strategy](#captured-strategy)
- **Lineage update** happens automatically after any DERIVED or CAPTURED operation

If invoked by heartbeat without explicit strategy, default to **DERIVED** (mutate
the weakest skill to create a new variant).

---

## DERIVED Strategy

Create a new skill by mutating or combining existing skills. This is analogous to
biological evolution: take what works, introduce variation, and select for improvement.

### Step 1: Select Parent Skill(s)

Identify one or two parent skills to derive from:

**Single parent (mutation):**
- Choose the skill most relevant to the current task plateau
- Review its SKILL.md, evals, and recent scores

**Two parents (crossover):**
- Choose two skills that each partially solve the problem
- Identify complementary strengths to combine

**Via MCP:** `cao_get_shared_skills()` to list available skills
**Via git:** Read `~/.cao-evolution-client/skills/` directory

### Step 2: Design the Mutation

Choose one or more mutation operators:

| Operator | Description | Example |
|----------|-------------|---------|
| **Specialize** | Narrow scope for better performance | Generic "scan" → "scan-web-apps" |
| **Generalize** | Broaden scope to handle more cases | "scan-python" → "scan-any-language" |
| **Augment** | Add a new capability | Add error recovery to a fragile skill |
| **Simplify** | Remove complexity that hurts performance | Strip rarely-used edge case handling |
| **Reframe** | Change the fundamental approach | Rule-based → pattern-matching |
| **Crossover** | Combine parts from two parents | Take analysis from A + output format from B |

Write a one-paragraph description of what the new skill will be and how it differs
from its parent(s).

### Step 3: Create the Workspace

```bash
WORKSPACE=/tmp/cao-evo-workspace/derived-$(date +%s)
mkdir -p "$WORKSPACE"

# Copy parent skill as starting point
cp -r <parent-skill-dir>/* "$WORKSPACE/"

# Initialize version tracking
python -m scripts.git_version init "$WORKSPACE"
python -m scripts.git_version commit "$WORKSPACE" --message "baseline: copied from <parent>" --tag v0
```

### Step 4: Apply the Mutation

Edit the SKILL.md in `$WORKSPACE/`:

1. **Update frontmatter**: New name, updated description and triggers
2. **Apply the mutation operator(s)** from Step 2
3. **Preserve what works**: Don't break the parent's strengths
4. **Document the derivation**: Add a section explaining what changed and why

Principles:
- The derived skill must be **meaningfully different** from the parent
- It should have a clear hypothesis: "this variant will be better at X because Y"
- Keep it under 500 lines for SKILL.md

### Step 5: Validate (if evals exist)

If the parent had `evals/evals.json`, adapt them for the derived skill:

1. Copy and modify evals to match the new skill's scope
2. Run validation (spawn subagent with the new skill)
3. Compare results to parent's scores:
   - **Better or comparable**: Proceed
   - **Worse on all cases**: Reconsider the mutation — try a different operator

### Step 6: Name and Deploy

Choose a name that reflects the derivation: `<parent-name>-<mutation-type>`
(e.g., `scan-v2-specialized`, `analyze-crossover-1`)

```bash
# Copy to skills directory
NEW_NAME="<chosen-name>"
cp -r "$WORKSPACE" ~/.cao-evolution-client/skills/"$NEW_NAME"/

# Clean up workspace
rm -rf "$WORKSPACE"
```

### Step 7: Update Lineage and Sync

Write `.lineage.json` in the new skill directory (see [Lineage Management](#lineage-management)),
then push:

```bash
cao_push  # via MCP
# or manually:
cd ~/.cao-evolution-client && git add -A && \
  git commit -m "derive: $NEW_NAME from <parent>" && git push
```

---

## CAPTURED Strategy

Extract a reusable skill from your recent work. This is knowledge crystallization:
you've been doing something repeatedly or discovered an effective pattern — formalize
it as a skill so it persists and can be shared.

### Step 1: Identify the Pattern

Look at your recent work for:

1. **Repeated sequences**: Same 3+ steps executed multiple times
2. **Effective techniques**: An approach that consistently works well
3. **Hard-won knowledge**: Something that took multiple attempts to figure out
4. **Tool combinations**: Specific tool chains that produce good results

Describe the pattern in 2-3 sentences.

### Step 2: Extract and Formalize

Create the skill in a workspace:

```bash
WORKSPACE=/tmp/cao-evo-workspace/captured-$(date +%s)
mkdir -p "$WORKSPACE"
```

Write `$WORKSPACE/SKILL.md` with:

```markdown
---
name: <descriptive-name>
description: >
  <What this skill does. When it should trigger. What phrases activate it.>
---

# <Skill Name>

<1-2 sentence overview of what this skill does and when to use it>

## Process

### Step 1: <First action>
<Instructions>

### Step 2: <Second action>
<Instructions>

...

## Notes
- Captured from: <description of the work session that produced this>
- Key insight: <the non-obvious thing that makes this work>
```

Follow the principles from secskill-evo's Create Mode:
- Be specific and actionable (not vague advice)
- Include examples where helpful
- Target < 300 lines for captured skills
- Include trigger phrases in the description

### Step 3: Optional — Create Seed Evals

If the skill's output is objectively verifiable, create `evals/evals.json`:

```json
{
  "skill_name": "<name>",
  "evals": [
    {
      "id": 1,
      "prompt": "<realistic user prompt that should trigger this skill>",
      "expected_output": "<what correct execution looks like>",
      "assertions": [
        {"id": "a1", "text": "<verifiable check>"}
      ]
    }
  ]
}
```

### Step 4: Name and Deploy

```bash
NEW_NAME="<chosen-name>"
cp -r "$WORKSPACE" ~/.cao-evolution-client/skills/"$NEW_NAME"/
rm -rf "$WORKSPACE"
```

### Step 5: Update Lineage and Sync

Write `.lineage.json` (see [Lineage Management](#lineage-management)), then sync:

```bash
cd ~/.cao-evolution-client && git add -A && \
  git commit -m "capture: $NEW_NAME" && git push
```

---

## Lineage Management

Every skill created or modified by openspace-evo MUST have a `.lineage.json` in
its directory. This enables building a complete lineage graph across the skill
population.

### `.lineage.json` Schema

```json
{
  "skill_id": "<skill-name>",
  "version": 1,
  "derivation": "DERIVED | CAPTURED | MANUAL",
  "parent_ids": ["<parent-skill-name>"],
  "evolution_method": "openspace-evo",
  "created_at": "<ISO 8601>",
  "created_by": "<agent_id>",
  "mutation_operators": ["specialize"],
  "mutation_description": "Narrowed scope from generic scan to web-app-specific scan",
  "parent_scores": {"<parent-name>": 0.65},
  "child_score": null,
  "lineage_depth": 1,
  "ancestors": ["<root-skill-name>"]
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `skill_id` | string | This skill's unique name (matches directory name) |
| `version` | int | Lineage record version (increment on re-derivation) |
| `derivation` | enum | How this skill was created: DERIVED, CAPTURED, or MANUAL |
| `parent_ids` | string[] | Parent skill(s). Empty for CAPTURED/MANUAL. 1 for mutation, 2 for crossover |
| `evolution_method` | string | Which evo-skill created this ("openspace-evo", "secskill-evo", "manual") |
| `created_at` | string | ISO 8601 timestamp |
| `created_by` | string | Agent ID that created this skill |
| `mutation_operators` | string[] | Which operators were applied (DERIVED only) |
| `mutation_description` | string | Human-readable description of what changed |
| `parent_scores` | object | Parent skill scores at time of derivation |
| `child_score` | float? | This skill's score (null until evaluated) |
| `lineage_depth` | int | How many generations from the root (0 = original) |
| `ancestors` | string[] | Full ancestry chain, oldest first |

### Updating Lineage on Score

When a derived skill gets its first score (via `cao_report_score`), update
`.lineage.json`:

```json
{
  "child_score": 0.78
}
```

This allows comparing parent vs child scores to measure evolution effectiveness.

### Building the Lineage Graph

To visualize the lineage of all skills:

```bash
# Collect all .lineage.json files
find ~/.cao-evolution-client/skills/ -name ".lineage.json" -exec cat {} \;
```

Each file's `parent_ids` field defines edges in a directed graph:
`parent → child`. The `ancestors` field provides the full path from root.

Skills without `.lineage.json` are roots (original, manually created skills).
To bootstrap lineage tracking for existing skills, create a minimal `.lineage.json`:

```json
{
  "skill_id": "<name>",
  "version": 1,
  "derivation": "MANUAL",
  "parent_ids": [],
  "evolution_method": "manual",
  "created_at": "<best guess or now>",
  "created_by": "<agent_id or unknown>",
  "mutation_operators": [],
  "mutation_description": "Original skill, lineage tracking bootstrapped",
  "parent_scores": {},
  "child_score": null,
  "lineage_depth": 0,
  "ancestors": []
}
```

---

## Integration with secskill-evo

openspace-evo and secskill-evo are complementary:

| Aspect | secskill-evo | openspace-evo |
|--------|-------------|---------------|
| Creates new skills? | No (fixes in place) | Yes (DERIVED + CAPTURED) |
| Modifies existing skills? | Yes (FIX algorithm) | No (creates new variants) |
| Uses /tmp workspace? | Yes (evolution isolation) | Yes (same pattern) |
| Manages .lineage.json? | No | Yes |
| Git version tracking? | Yes (git_version.py) | Yes (same scripts) |

When secskill-evo fixes a skill, it does NOT create a `.lineage.json` (it's the
same skill, just improved). When openspace-evo derives or captures, it ALWAYS
creates a `.lineage.json`.

If a heartbeat triggers both, they run sequentially:
1. secskill-evo fixes the weakest existing skill
2. openspace-evo derives a new variant from a promising skill
