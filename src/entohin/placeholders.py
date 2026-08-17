"""Shield non-translatable spans (URLs, emails, paths, code) from the model.

A neural model asked to translate ``Visit https://example.com/a_b today`` will
happily "translate" the URL and corrupt it.  Such spans are swapped for a
numeric placeholder before translation and restored afterwards.

Placeholders use the form ``#1#`` because every character is in the model's
vocabulary and survives sub-word tokenisation.  The decoder may still insert
spaces around them, so restoration tolerates ``# 1 #``.  Restoration is
verified: if a placeholder is dropped or duplicated by the model, the caller
is told so it can fall back to translating the unprotected text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

# Ordered by priority -- the first pattern that matches a position wins.
_PATTERNS: Tuple[re.Pattern, ...] = (
    # URLs with a scheme, and bare www./domain-style hosts with a path.
    re.compile(r"\b(?:https?|ftp|file)://[^\s<>\"']+", re.IGNORECASE),
    re.compile(r"\bwww\.[^\s<>\"']+", re.IGNORECASE),
    # Email addresses.
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    # Windows and UNC paths.
    re.compile(r"\b[A-Za-z]:\\[^\s<>\"'|]*"),
    re.compile(r"\\\\[^\s<>\"'|]+"),
    # Inline code spans.
    re.compile(r"`[^`\n]+`"),
    # {placeholders} used by templating systems.
    re.compile(r"\{[A-Za-z0-9_.]+\}"),
    # <tags> and &entities;
    re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>\n]*)?/?>"),
)

_RESTORE_RE = re.compile(r"#\s*(\d+)\s*#")


@dataclass
class Protected:
    """Text with non-translatable spans replaced by placeholders."""

    text: str
    values: List[str]

    @property
    def is_placeholder_only(self) -> bool:
        """True if nothing is left to translate once placeholders are removed."""
        stripped = _RESTORE_RE.sub("", self.text)
        return not re.search(r"[A-Za-z]", stripped)


def protect(text: str) -> Protected:
    """Replace non-translatable spans in ``text`` with ``#n#`` placeholders."""
    spans: List[Tuple[int, int]] = []
    for pattern in _PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span()
            # Skip spans overlapping one already claimed by a higher-priority
            # pattern (a URL, say, contains something path-shaped).
            if any(start < e and end > s for s, e in spans):
                continue
            spans.append((start, end))

    if not spans:
        return Protected(text=text, values=[])

    spans.sort()
    values: List[str] = []
    out: List[str] = []
    cursor = 0
    for start, end in spans:
        out.append(text[cursor:start])
        out.append(" #%d# " % (len(values) + 1))
        values.append(text[start:end])
        cursor = end
    out.append(text[cursor:])

    # The padding spaces keep placeholders as separate tokens; collapse any
    # doubles they introduced.
    merged = re.sub(r"[ \t]{2,}", " ", "".join(out))
    return Protected(text=merged.strip(), values=values)


def restore(text: str, values: List[str]) -> Tuple[str, bool]:
    """Substitute placeholder values back into ``text``.

    Returns the restored text and whether restoration was complete -- that is,
    every placeholder appeared exactly once and no unknown index was produced.
    """
    if not values:
        # A model that invents a placeholder out of nowhere is misbehaving,
        # but there is nothing to restore, so leave the text alone.
        return text, True

    seen: List[int] = []
    ok = True

    def substitute(match: re.Match) -> str:
        nonlocal ok
        index = int(match.group(1))
        if not 1 <= index <= len(values):
            ok = False
            return match.group(0)
        seen.append(index)
        return values[index - 1]

    restored = _RESTORE_RE.sub(substitute, text)

    if sorted(seen) != list(range(1, len(values) + 1)):
        ok = False

    # Tidy spacing introduced around placeholders.
    restored = re.sub(r"[ \t]{2,}", " ", restored)
    restored = re.sub(r"\s+([,.;:!?।])", r"\1", restored)
    return restored.strip(), ok
