"""Split English text into translatable units while preserving layout.

Neural MT models are trained on single sentences and degrade badly on long
inputs, so the text is broken into sentences before translation and stitched
back together afterwards.  Everything that is not a sentence -- blank lines,
indentation, bullet markers, numbering -- is carried through untouched so the
translated document keeps the shape of the original.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator, List

# Abbreviations that end in a period without ending the sentence.  Kept lower
# case; the lookup is case-insensitive.
_ABBREVIATIONS = {
    # Titles
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "rev", "hon", "gen",
    "col", "capt", "lt", "sgt", "supt", "insp", "smt", "shri", "kum",
    # Latin / editorial
    "e.g", "i.e", "etc", "viz", "cf", "vs", "al", "ibid", "op", "cit", "esp",
    # Business / organisation
    "inc", "ltd", "co", "corp", "pvt", "dept", "univ", "assn", "bros", "govt",
    "approx", "est", "min", "max",
    # Time and measurement
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct",
    "nov", "dec", "mon", "tue", "wed", "thu", "fri", "sat", "sun",
    "hr", "hrs", "sec", "secs", "wk", "yr", "yrs", "kg", "km", "cm", "mm",
    "ft", "sq", "no", "nos", "vol", "pp", "fig", "figs", "ref", "ed", "eds",
    # Geography
    "u.s", "u.k", "u.a.e", "n", "s", "e", "w",
}

# A sentence terminator, optionally followed by closing quotes/brackets.
_TERMINATORS = ".!?।॥"  # includes danda / double danda
_CLOSERS = "\"'’”)]}»"

_SENTENCE_END_RE = re.compile(
    r"[" + re.escape(_TERMINATORS) + r"]+[" + re.escape(_CLOSERS) + r"]*"
)

# Leading list markers: bullets, numbers, letters, roman-ish forms.
_MARKER_RE = re.compile(
    r"""^(
        [-*•‣◦⁃∙+>]\s+      # bullet glyphs
      | \(?\d+[.)]\s+                                 # 1.  1)  (1)
      | \(?[a-zA-Z][.)]\s+                            # a.  b)  (c)
      | \#{1,6}\s+                                    # markdown heading
    )""",
    re.VERBOSE,
)

_HAS_LETTER_RE = re.compile(r"[A-Za-z]")


@dataclass
class Line:
    """One physical line of the source text.

    ``prefix`` (indentation plus any list marker) and ``trailing`` whitespace
    are preserved verbatim; only ``body`` is translated.
    """

    prefix: str = ""
    body: str = ""
    trailing: str = ""

    @property
    def translatable(self) -> bool:
        return bool(_HAS_LETTER_RE.search(self.body))


def split_line(line: str) -> Line:
    """Separate a line into indentation + marker, content, and trailing space."""
    stripped = line.rstrip()
    trailing = line[len(stripped):]
    indent_len = len(stripped) - len(stripped.lstrip())
    prefix = stripped[:indent_len]
    rest = stripped[indent_len:]

    marker = _MARKER_RE.match(rest)
    if marker:
        prefix += marker.group(0)
        rest = rest[marker.end():]

    return Line(prefix=prefix, body=rest, trailing=trailing)


def split_lines(text: str) -> List[Line]:
    """Split text into :class:`Line` objects, one per physical line."""
    return [split_line(line) for line in text.split("\n")]


def _is_abbreviation(text: str, end: int) -> bool:
    """True if the period at ``end - 1`` closes a known abbreviation."""
    word_start = end - 1
    while word_start > 0 and (text[word_start - 1].isalnum() or text[word_start - 1] == "."):
        word_start -= 1
    token = text[word_start:end - 1].lower().strip(".")
    if not token:
        return False
    if token in _ABBREVIATIONS:
        return True
    # Single initials ("J. R. R. Tolkien") and dotted acronyms ("U.S.A.").
    if len(token) == 1 and token.isalpha():
        return True
    if re.fullmatch(r"(?:[a-z]\.)+[a-z]?", token):
        return True
    return False


def _is_decimal_point(text: str, index: int) -> bool:
    """True if the period at ``index`` sits between two digits (e.g. 3.14)."""
    return (
        index > 0
        and index + 1 < len(text)
        and text[index - 1].isdigit()
        and text[index + 1].isdigit()
    )


def split_sentences(text: str) -> List[str]:
    """Split a single line of text into sentences.

    The concatenation of the returned pieces always equals the input, so the
    caller can translate each piece and rejoin without losing characters.
    """
    if not text.strip():
        return [text] if text else []

    sentences: List[str] = []
    start = 0
    pos = 0
    length = len(text)

    while pos < length:
        match = _SENTENCE_END_RE.search(text, pos)
        if not match:
            break

        end = match.end()
        terminator_index = match.start()

        # "3.14" and "Mr." do not end a sentence.
        if text[terminator_index] == "." and (
            _is_decimal_point(text, terminator_index)
            or _is_abbreviation(text, terminator_index + 1)
        ):
            pos = end
            continue

        # An ellipsis mid-sentence ("wait ... then") is not a boundary unless
        # the next word starts a new sentence.
        following = text[end:]
        if following and not following[0].isspace():
            pos = end
            continue

        candidate = text[start:end]
        remainder = following.lstrip()
        # A boundary needs something after it; a lower-case continuation such
        # as "etc. and then" is treated as the same sentence.
        if remainder and remainder[0].islower():
            pos = end
            continue

        # Absorb the whitespace that follows so pieces concatenate exactly.
        space_len = len(following) - len(following.lstrip(" \t"))
        candidate += following[:space_len]

        if candidate.strip():
            sentences.append(candidate)
            start = end + space_len
        pos = end + space_len

    if start < length:
        sentences.append(text[start:])

    return sentences or [text]


@dataclass
class Segment:
    """A unit handed to the translator, with its position in the document."""

    line_index: int
    text: str
    translated: str = ""


@dataclass
class Document:
    """A parsed document: the layout plus the segments needing translation."""

    lines: List[Line] = field(default_factory=list)
    segments: List[Segment] = field(default_factory=list)
    # Sentence pieces per line, in order; translated text is substituted in.
    _pieces: List[List[str]] = field(default_factory=list)
    _piece_segments: List[List[int]] = field(default_factory=list)

    def render(self) -> str:
        """Rebuild the document using translated segment text."""
        out: List[str] = []
        for index, line in enumerate(self.lines):
            pieces = list(self._pieces[index])
            for piece_index, segment_index in enumerate(self._piece_segments[index]):
                if segment_index >= 0:
                    pieces[piece_index] = self.segments[segment_index].translated
            out.append(line.prefix + "".join(pieces) + line.trailing)
        return "\n".join(out)


def parse(text: str) -> Document:
    """Parse ``text`` into a :class:`Document` ready for translation."""
    doc = Document(lines=split_lines(text))

    for index, line in enumerate(doc.lines):
        if not line.translatable:
            doc._pieces.append([line.body])
            doc._piece_segments.append([-1])
            continue

        pieces = split_sentences(line.body)
        segment_ids: List[int] = []
        for piece in pieces:
            if _HAS_LETTER_RE.search(piece):
                segment_ids.append(len(doc.segments))
                doc.segments.append(Segment(line_index=index, text=piece))
            else:
                segment_ids.append(-1)
        doc._pieces.append(pieces)
        doc._piece_segments.append(segment_ids)

    return doc


def iter_batches(items: List[str], size: int) -> Iterator[List[str]]:
    """Yield ``items`` in chunks of at most ``size``."""
    if size <= 0:
        yield list(items)
        return
    for start in range(0, len(items), size):
        yield items[start:start + size]
