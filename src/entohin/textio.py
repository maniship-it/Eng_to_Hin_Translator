"""Reading and writing text files the way Windows users actually save them.

Notepad alone can produce UTF-8, UTF-8 with a BOM, UTF-16 LE ("Unicode") and
the local ANSI code page.  Guessing wrong does not fail loudly -- most byte
sequences decode as cp1252 into nonsense -- so byte-order marks are checked
first and UTF-16 without a BOM is detected from its NUL pattern.
"""

from __future__ import annotations

import codecs
from pathlib import Path
from typing import Optional

#: Longest BOM first: the UTF-32 LE mark starts with the UTF-16 LE mark.
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)

#: Tried in order once BOM detection has come up empty.
_FALLBACKS = ("utf-8", "cp1252", "latin-1")


def detect_encoding(data: bytes) -> Optional[str]:
    """Guess the encoding of ``data``, or ``None`` if nothing fits."""
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return encoding

    sample = data[:4096]
    if sample:
        # UTF-16 text without a BOM is mostly ASCII interleaved with NULs.
        even_nulls = sample[0::2].count(0)
        odd_nulls = sample[1::2].count(0)
        half = max(len(sample) // 2, 1)
        if odd_nulls > half * 0.3 and even_nulls == 0:
            return "utf-16-le"
        if even_nulls > half * 0.3 and odd_nulls == 0:
            return "utf-16-be"

    for encoding in _FALLBACKS:
        try:
            data.decode(encoding)
            return encoding
        except (UnicodeDecodeError, LookupError):
            continue
    return None


def decode(data: bytes) -> Optional[str]:
    """Decode ``data`` to text, or return ``None`` if it is not text."""
    encoding = detect_encoding(data)
    if encoding is None:
        return None
    try:
        return data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        return None


def read_text_file(path: Path) -> Optional[str]:
    """Read a text file, or return ``None`` if it cannot be read as text."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    text = decode(data)
    if text is None:
        return None
    # Normalise line endings so the rest of the app only sees "\n".
    return text.replace("\r\n", "\n").replace("\r", "\n")


def write_text_file(path: Path, content: str) -> None:
    """Write text as UTF-8 with a BOM and CRLF endings.

    The BOM is what makes Notepad and Excel display Devanagari correctly
    instead of mojibake.
    """
    Path(path).write_text(content, encoding="utf-8-sig", newline="\r\n")
