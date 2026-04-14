"""Parse Hermes MEMORY.md into individual entries with SHA-256 dedup."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterator

DEFAULT_MEMORY_PATH = Path.home() / ".hermes" / "memories" / "MEMORY.md"


def parse_memory(
    path: Path | str = DEFAULT_MEMORY_PATH,
) -> Iterator[tuple[str, str]]:
    """Yield (title, content) tuples from a Hermes MEMORY.md file.

    Skips ═ header lines, splits on §, deduplicates by SHA-256.
    """
    path = Path(path)
    if not path.exists():
        return

    text = path.read_text(encoding="utf-8", errors="replace")
    yield from parse_memory_text(text)


def parse_memory_text(text: str) -> Iterator[tuple[str, str]]:
    """Parse raw MEMORY.md text into (title, content) tuples."""
    # Strip ═ header lines and the title line between them
    text = re.sub(r"^═.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^MEMORY\s*\(.*?\)\s*\[.*?\]\s*$", "", text, flags=re.MULTILINE)

    seen: set[str] = set()
    for entry in text.split("§"):
        entry = entry.strip()
        if not entry:
            continue

        digest = hashlib.sha256(entry.encode("utf-8")).hexdigest()[:12]
        if digest in seen:
            continue
        seen.add(digest)

        title = f"hermes-memory-{digest}"
        yield title, entry
