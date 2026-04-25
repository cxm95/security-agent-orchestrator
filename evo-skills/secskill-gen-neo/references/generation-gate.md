# Generation Gate Framework

This document defines the gates a method must pass before it becomes a
skill. Read it in full at Step 2 before deciding whether to generate.

The gates are sequential — fail at any gate and stop. The recommended
alternative (secnote) is always stated. Choosing to write a secnote
instead of a skill is not a failure; it's correct granularity selection.

---

## Gate 1: Generalizability

**Question: Does this method work beyond the current task and target?**

Perform this thought experiment: strip every detail specific to the
current session — the target application, its tech stack, the specific
vulnerabilities found, the exact tools used. What remains?

**Passes if:**
- A coherent, multi-step method remains after stripping specifics
- The method applies to a CLASS of targets (e.g., "web APIs with
  token-based auth") not a single target
- The core reasoning and decision logic are target-independent
- You can name at least 3 different applications where this method
  would be useful

**Fails if:**
- The method depends on a specific technology, framework, or
  architecture that most targets don't share
- Removing target-specific details leaves only generic advice
  ("test thoroughly", "check for vulnerabilities")
- The method's value comes from a specific discovery about the
  current target, not from the approach itself
- The "method" is really just "do what worked this time"

**If Gate 1 fails:** Write a secnote via cao-secnote. Secnotes are
the right home for target-specific techniques and discoveries.

---

## Gate 2: Incremental Value

**Question: Does existing shared knowledge already cover this?**

Before generating a new skill, search what already exists:

```
cao_recall("<keywords from the method>", top_k=10, include_content=True)
```

Check three categories:

### 2a. Existing skills

- Does an existing skill cover 80%+ of this method?
  → **Don't generate.** If the existing skill is missing the remaining
  20%, consider filing an evolution request (secskill-evo-neo) to add
  the missing piece. That's better than creating a near-duplicate.

- Does an existing skill cover a different aspect of the same domain?
  → **May generate**, but ensure the new skill is clearly complementary,
  not overlapping. Define the boundary explicitly in the description.

### 2b. Existing notes

- Does an existing secnote already capture the key insight?
  → **Don't generate.** A note is sufficient for a single insight.
  Skills are for multi-step methodologies.

- Do multiple notes together cover the method?
  → **May generate** — consolidating scattered notes into a coherent
  skill is valuable. Reference the source notes in TIP.md.

### 2c. Common knowledge

- Is this method something any competent practitioner would know?
  (e.g., "run nmap to discover open ports", "check for SQL injection
  with a single quote")
  → **Don't generate.** Skills should encode non-obvious methodology,
  not textbook basics.

**If Gate 2 fails:** Explain which existing resource already covers
the method. If it's a partial overlap, suggest evolving the existing
skill instead.

---

## Gate 3: Granularity

**Question: Is this a skill or a note?**

Skills and notes serve different purposes:

| Dimension | Skill | Note (secnote) |
|-----------|-------|-----------------|
| Content | Multi-step methodology | Single finding, trick, or insight |
| Structure | Ordered steps with decision points | Flat description |
| Reuse | Agent loads and follows as a workflow | Agent reads for context |
| Size | 50–200 lines | 10–50 lines |
| Maintenance | Evolves via secskill-evo-neo | Append-only, rarely updated |

### The 3-step test

Describe the method as a numbered list of steps. Then:

1. **Fewer than 3 steps?** → It's a note, not a skill.
2. **Can you remove any step without breaking the method?** → If yes
   for most steps, it's a collection of independent tricks (notes),
   not a cohesive method (skill).
3. **Do the steps have a meaningful ORDER?** → If the order doesn't
   matter, it's a checklist (note), not a methodology (skill).

### Edge cases

- **A technique with setup + execution + verification** (3 steps,
  ordered, interdependent) → Skill-worthy.
- **Five unrelated tips for the same domain** → Five separate notes.
  Don't bundle unrelated tips into a fake "skill".
- **A complex technique that only works in one specific scenario** →
  Note. Complexity alone doesn't make it a skill; generalizability
  does (Gate 1).

**If Gate 3 fails:** Write a secnote via cao-secnote. Explain that
the method is valuable but better expressed as a note.

---

## Decision Flowchart

```
Method identified from successful execution
    │
    ├─ Strip target-specific details.
    │  Coherent method remains? ──── No ──→ secnote
    │
    Yes
    │
    ├─ cao_recall: existing skill
    │  covers 80%+? ──────────────── Yes ─→ evolve existing (secskill-evo-neo)
    │
    No
    │
    ├─ cao_recall: existing note
    │  covers the key insight? ───── Yes ─→ stop (note is sufficient)
    │
    No
    │
    ├─ Method has ≥3 ordered,
    │  interdependent steps? ──────── No ──→ secnote
    │
    Yes
    │
    └─ All gates passed → generate skill
```

---

## After Deciding NOT to Generate

If any gate fails, the method still has value. Always capture it:

- **Gate 1 failed** (not generalizable): Write a secnote with type
  `technique` or `recon`. Tag it with the specific target/framework
  so agents working on similar targets can find it.

- **Gate 2 failed** (already covered): If the existing coverage is
  incomplete, file a TIP.md entry on the relevant skill suggesting
  what to add. If coverage is complete, no action needed.

- **Gate 3 failed** (wrong granularity): Write one or more secnotes.
  Each note captures one atomic insight. Don't try to force multiple
  independent insights into a single note.
