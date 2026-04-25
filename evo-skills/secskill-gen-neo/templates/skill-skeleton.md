# Skill Skeleton Template

Use this template when generating a new skill at Step 3. Fill in each
section, then delete this header comment and any unused optional sections.

```markdown
---
name: <kebab-case-name>
description: >
  <What this skill does and when to use it. Include trigger phrases.
  Focus on user intent. Stay under 1024 characters.>
---

# <Skill Title>

<1-2 sentence summary: what this skill helps an agent accomplish.>

## When to Use

<Describe the situation or task type where this skill applies.
Be specific enough to avoid false triggers.>

## Prerequisites

<What the agent needs before starting. Tools, access, prior steps.
Delete this section if there are no prerequisites.>

## Method

### Step 1: <Action verb + object>

<What to do, why it matters, and how to know it worked.>

### Step 2: <Action verb + object>

<What to do, why it matters, and how to know it worked.>

### Step 3: <Action verb + object>

<What to do, why it matters, and how to know it worked.>

<Add more steps as needed. Each step should be:
- Actionable (starts with a verb)
- Justified (explains why)
- Verifiable (how to confirm success)
- General (no target-specific details)>

## Decision Points

<Where the agent needs to exercise judgment. Format as:
"If [condition], then [action A]. Otherwise, [action B]."
These are the most valuable part of a skill — they encode
the expertise that makes the method work.>

## Common Pitfalls

<What NOT to do, based on failures observed during the execution
that led to this skill. Format as warnings with explanations.
Delete this section if there are no notable pitfalls.>

## Success Criteria

<How to know the method worked. Concrete, verifiable outcomes.>
```

## Guidelines for Filling the Template

- **≤200 lines** for the entire SKILL.md body (after frontmatter)
- **Imperative voice**: "Check X" not "The agent should check X"
- **Explain why**: every step should have a brief justification
- **No specifics**: no IPs, ports, paths, domain names, API keys,
  or findings from the source execution
- **Decision points are gold**: the more judgment guidance you
  encode, the more valuable the skill
- **Pitfalls save time**: knowing what NOT to do is often more
  valuable than knowing what to do
- If the skill needs reference material (detailed checklists,
  protocol specs, tool usage guides), put them in `references/`
  and point to them from the main SKILL.md
