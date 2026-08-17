"""Normalising Devanagari so search finds what the user meant.

The same Hindi word is written several defensible ways. ``मंज़ूरी`` and
``मंजूरी`` differ only by a nukta; ``संस्कृत`` may carry an anusvara where
another source uses a candrabindu; text copied from the web often carries
zero-width joiners that are invisible but break an exact match.

Every one of those turns up in the dictionary's own sources, so search keys
are folded to a common form. Folding is for *matching only* — the original
spelling is what gets displayed.
"""

from __future__ import annotations

import re
import unicodedata

#: Devanagari block, plus the extended block and the danda punctuation.
DEVANAGARI_RE = re.compile(r"[ऀ-ॿ꣠-ꣿ]")

ZERO_WIDTH = "‌‍﻿"

NUKTA = "़"

#: Pre-composed nukta letters folded to their base letter for matching.
_NUKTA_FOLD = {
    "ऩ": "न",  # ऩ -> न
    "ऱ": "र",  # ऱ -> र
    "ऴ": "ळ",  # ऴ -> ळ
    "क़": "क",  # क़ -> क
    "ख़": "ख",  # ख़ -> ख
    "ग़": "ग",  # ग़ -> ग
    "ज़": "ज",  # ज़ -> ज
    "ड़": "ड",  # ड़ -> ड
    "ढ़": "ढ",  # ढ़ -> ढ
    "फ़": "फ",  # फ़ -> फ
    "य़": "य",  # य़ -> य
}

#: Nasal marks that writers use interchangeably.
_NASAL_FOLD = {
    "ँ": "ं",  # candrabindu ँ -> anusvara ं
}

_PUNCTUATION = "।॥.,;:!?\"'()[]{}«»“”‘’-–—/\\|"

_SPACE_RE = re.compile(r"\s+")


def has_devanagari(text: str) -> bool:
    """True if ``text`` contains any Devanagari character."""
    return bool(DEVANAGARI_RE.search(text or ""))


def strip_zero_width(text: str) -> str:
    return "".join(ch for ch in (text or "") if ch not in ZERO_WIDTH)


def normalize(text: str) -> str:
    """Fold Hindi text into a search key.

    Applies Unicode NFC, drops zero-width marks, folds nukta and nasal
    variants, removes punctuation, and collapses whitespace.
    """
    if not text:
        return ""

    folded = unicodedata.normalize("NFC", text)
    folded = strip_zero_width(folded)

    out = []
    for char in folded:
        if char == NUKTA:
            continue  # combining nukta contributes nothing to matching
        char = _NUKTA_FOLD.get(char, char)
        char = _NASAL_FOLD.get(char, char)
        if char in _PUNCTUATION:
            out.append(" ")
            continue
        out.append(char)

    return _SPACE_RE.sub(" ", "".join(out)).strip().lower()


def display(text: str) -> str:
    """Tidy Hindi for display without changing how it is written."""
    if not text:
        return ""
    return _SPACE_RE.sub(" ", strip_zero_width(
        unicodedata.normalize("NFC", text)).replace("~", " ")).strip()


def split_terms(text: str) -> list:
    """Split a semicolon or comma separated list of Hindi meanings."""
    if not text:
        return []
    parts = re.split(r"[;,]", text)
    return [display(part) for part in parts if display(part)]
