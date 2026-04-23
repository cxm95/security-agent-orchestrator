---
name: cao-build-l1-index
description: Build L1 knowledge index from local notes (for local-only mode or manual refresh)
triggers:
  - "build l1 index"
  - "update knowledge index"
  - "构建知识索引"
  - "更新L1索引"
---

# Build L1 Knowledge Index

Read all notes from the session's `notes/` directory, synthesize them into
a ranked knowledge index, and write the result to `index.md` in the session
clone directory. Then call `cao_push` to share with other agent instances.

## Steps

1. Call `cao_session_info` to get the current session directory.
2. List all `.md` files in `<session_dir>/notes/`.
3. Read each note's content.
4. Synthesize a knowledge index:
   - Group notes by topic or theme
   - Rank by relevance and recency
   - Extract key insights across all notes
5. Write the index to `<session_dir>/index.md` using this format:

```markdown
# Knowledge Index
Generated: <YYYY-MM-DD HH:MM>
Notes: <count>

## Key Insights
<2-5 bullet points synthesizing the most important findings across all notes>

## Note Summaries
- **<note-title>**: <one-line summary>
- **<note-title>**: <one-line summary>
...
```

6. Call `cao_push` with message `"update L1 knowledge index"` to share the
   updated index with other agent instances.
7. Report: "L1 index updated with N notes."

## When to Use

- After writing 3 or more notes, to make accumulated knowledge searchable
- When you want other agent instances to benefit from your findings
- Periodically during long sessions to keep the index fresh
