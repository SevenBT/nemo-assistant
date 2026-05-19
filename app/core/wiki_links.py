"""
Wiki-link parser for Markdown text.
Ported from noteration/editor/wiki_links.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_WIKI_PATTERN = re.compile(r'\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|([^\]]+))?\]\]')


@dataclass
class WikiLink:
    target: str          # target note name (without .md)
    heading: str | None  # anchor heading if present
    alias: str | None    # display text if present
    start: int           # character position in text
    end: int


def parse_wiki_links(text: str) -> list[WikiLink]:
    """Extract all [[wiki-link]] tokens from text."""
    links = []
    for m in _WIKI_PATTERN.finditer(text):
        links.append(WikiLink(
            target=m.group(1).strip(),
            heading=m.group(2).strip() if m.group(2) else None,
            alias=m.group(3).strip() if m.group(3) else None,
            start=m.start(),
            end=m.end(),
        ))
    return links


def extract_headings(text: str) -> list[tuple[int, str]]:
    """
    Extract headings from Markdown content.
    Returns a list of (level, title).
    """
    headings = []
    in_code = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
        if in_code:
            continue
        m = re.match(r'^(#{1,6})\s+(.+)', line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            headings.append((level, title))
    return headings


def resolve_link(target: str, notes_dir: Path) -> Path | None:
    """
    Resolve a wiki-link target to its corresponding note file.
    Supports:
    - standard filename: "idea-1" -> notes/idea-1.md
    - relative path: "drafts/idea-1" -> notes/drafts/idea-1.md
    - case-insensitive matching
    """
    if "/" in target:
        direct = notes_dir / f"{target}.md"
        if direct.exists():
            return direct
        direct = notes_dir / target
        if direct.exists() and direct.is_file():
            return direct

    candidates = [
        notes_dir / f"{target}.md",
        notes_dir / target,
    ]
    for c in candidates:
        if c.exists():
            return c

    # Case-insensitive global search
    target_lower = target.lower()
    for md_file in notes_dir.rglob("*.md"):
        if md_file.stem.lower() == target_lower:
            return md_file

    return None
