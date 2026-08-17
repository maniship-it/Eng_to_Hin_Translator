"""Offline English-Hindi dictionary lookup.

Reads the SQLite database produced by ``tools/build_dictionary.py``: Hindi
meanings, parts of speech, English and Hindi definitions, synonyms, antonyms,
example sentences, and a curated glossary of central government administrative
terminology.

The database is opened read-only and never written to, so several parts of the
application can share one file safely.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .model import app_root, user_data_dir

DICTIONARY_ENV_VAR = "ENTOHIN_DICTIONARY"

#: Location of the database relative to a search root.
DICTIONARY_PATH = os.path.join("models", "dictionary", "dictionary.sqlite")

#: The schema this reader understands.
SUPPORTED_SCHEMA_VERSION = 1

SOURCE_ADMIN = "admin"
SOURCE_FREEDICT = "freedict"
SOURCE_WORDNET = "wordnet"

_SOURCE_ORDER = {SOURCE_ADMIN: 0, SOURCE_FREEDICT: 1, SOURCE_WORDNET: 2}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")
_DEVANAGARI_RE = re.compile(r"[ऀ-ॿ]")


class DictionaryNotFoundError(RuntimeError):
    """Raised when no dictionary database can be located."""


class DictionaryError(RuntimeError):
    """Raised when a database exists but cannot be used."""


@dataclass
class Sense:
    """One meaning of a word, from one source."""

    source: str
    pos: str = ""
    category: str = ""
    hindi: List[str] = field(default_factory=list)
    definition_en: str = ""
    definition_hi: str = ""
    synonyms: List[str] = field(default_factory=list)
    antonyms: List[str] = field(default_factory=list)
    examples_en: List[str] = field(default_factory=list)
    examples_hi: List[str] = field(default_factory=list)

    @property
    def is_administrative(self) -> bool:
        return self.source == SOURCE_ADMIN


@dataclass
class Entry:
    """Everything known about one head word."""

    word: str
    senses: List[Sense] = field(default_factory=list)
    #: Set when the search term was an inflected form, e.g. "running" -> "run".
    matched_form: str = ""

    @property
    def hindi_meanings(self) -> List[str]:
        """Every Hindi meaning, most authoritative first, de-duplicated."""
        return _unique(hindi for sense in self.senses for hindi in sense.hindi)

    @property
    def parts_of_speech(self) -> List[str]:
        return _unique(sense.pos for sense in self.senses if sense.pos)

    @property
    def synonyms(self) -> List[str]:
        return _unique(word for sense in self.senses for word in sense.synonyms)

    @property
    def antonyms(self) -> List[str]:
        return _unique(word for sense in self.senses for word in sense.antonyms)

    @property
    def examples(self) -> List[str]:
        return _unique(text for sense in self.senses for text in sense.examples_en)

    @property
    def administrative_senses(self) -> List[Sense]:
        return [sense for sense in self.senses if sense.is_administrative]

    @property
    def is_administrative(self) -> bool:
        return any(sense.is_administrative for sense in self.senses)

    def senses_by_pos(self) -> "Dict[str, List[Sense]]":
        """Senses grouped by part of speech, in first-seen order."""
        grouped: Dict[str, List[Sense]] = {}
        for sense in self.senses:
            grouped.setdefault(sense.pos or "other", []).append(sense)
        return grouped


def _unique(values: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for value in values:
        cleaned = (value or "").strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _loads(value: str) -> List[str]:
    try:
        parsed = json.loads(value or "[]")
    except ValueError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def candidate_paths(extra: Optional[Sequence[Path]] = None) -> List[Path]:
    """Every location the dictionary may live in, in search order."""
    candidates: List[Path] = []
    if extra:
        candidates.extend(Path(p) for p in extra if p)
    env_value = os.environ.get(DICTIONARY_ENV_VAR)
    if env_value:
        candidates.append(Path(env_value))
    candidates.append(app_root() / DICTIONARY_PATH)
    candidates.append(user_data_dir() / DICTIONARY_PATH)
    return candidates


def discover_dictionary(extra: Optional[Sequence[Path]] = None) -> Path:
    """Return the first dictionary database found on the search path."""
    tried: List[Path] = []
    for candidate in candidate_paths(extra):
        tried.append(candidate)
        if candidate.is_file():
            return candidate
    raise DictionaryNotFoundError(
        "No dictionary database found. Looked in:\n  "
        + "\n  ".join(str(p) for p in tried)
        + "\n\nBuild it on a machine with internet access:\n"
        "    python tools/build_dictionary.py"
    )


# Suffix rules applied when a word is not found verbatim.  Each entry is
# (suffix to remove, suffixes to try in its place).  Order matters.
_SUFFIX_RULES = (
    ("ies", ("y",)),
    ("ied", ("y",)),
    ("ier", ("y",)),
    ("iest", ("y",)),
    ("sses", ("ss",)),
    ("ches", ("ch",)),
    ("shes", ("sh",)),
    ("xes", ("x",)),
    ("zes", ("z",)),
    ("ses", ("s",)),
    ("ves", ("f", "fe")),
    ("es", ("", "e")),
    ("s", ("",)),
    ("ing", ("", "e")),
    ("ed", ("", "e")),
    ("er", ("", "e")),
    ("est", ("", "e")),
    ("ly", ("",)),
)


class Dictionary:
    """Read-only access to the dictionary database."""

    def __init__(self, connection: sqlite3.Connection, path: Path):
        self._connection = connection
        self._connection.row_factory = sqlite3.Row
        self.path = path
        self._exceptions_cache: Dict[str, str] = {}

    # -- lifecycle -----------------------------------------------------

    @classmethod
    def open(cls, path=None, extra=None) -> "Dictionary":
        """Open a dictionary, discovering its location when not given."""
        resolved = Path(path) if path else discover_dictionary(extra)
        if not resolved.is_file():
            raise DictionaryNotFoundError("No dictionary database at %s" % resolved)

        try:
            # Read-only so the file can be on shared or write-protected media.
            uri = "file:%s?mode=ro" % resolved.as_posix().replace("?", "%3f")
            connection = sqlite3.connect(uri, uri=True, check_same_thread=False)
            connection.execute("SELECT 1 FROM entries LIMIT 1")
        except sqlite3.Error as exc:
            raise DictionaryError(
                "%s is not a usable dictionary database (%s)" % (resolved, exc)
            )

        dictionary = cls(connection, resolved)
        version = dictionary.meta().get("schema_version")
        if version is not None and int(version) != SUPPORTED_SCHEMA_VERSION:
            connection.close()
            raise DictionaryError(
                "Dictionary schema version %s is not supported by this version "
                "of the application (expected %d). Rebuild it with "
                "tools/build_dictionary.py." % (version, SUPPORTED_SCHEMA_VERSION)
            )
        return dictionary

    def close(self) -> None:
        try:
            self._connection.close()
        except sqlite3.Error:  # pragma: no cover - best effort
            pass

    def __enter__(self) -> "Dictionary":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- metadata ------------------------------------------------------

    def meta(self) -> Dict[str, str]:
        try:
            rows = self._connection.execute("SELECT key, value FROM meta").fetchall()
        except sqlite3.Error:
            return {}
        return {row["key"]: row["value"] for row in rows}

    def count_entries(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) AS n FROM entries").fetchone()
        return int(row["n"]) if row else 0

    # -- lookup --------------------------------------------------------

    def _senses_for(self, entry_id: int) -> List[Sense]:
        rows = self._connection.execute(
            "SELECT source, pos, category, hindi, definition_en, definition_hi,"
            " synonyms, antonyms, examples_en, examples_hi"
            " FROM senses WHERE entry_id = ? ORDER BY rank",
            (entry_id,),
        ).fetchall()

        senses = [
            Sense(
                source=row["source"],
                pos=row["pos"] or "",
                category=row["category"] or "",
                hindi=_loads(row["hindi"]),
                definition_en=row["definition_en"] or "",
                definition_hi=row["definition_hi"] or "",
                synonyms=_loads(row["synonyms"]),
                antonyms=_loads(row["antonyms"]),
                examples_en=_loads(row["examples_en"]),
                examples_hi=_loads(row["examples_hi"]),
            )
            for row in rows
        ]
        # Administrative first, then meanings, then definitions.
        senses.sort(key=lambda s: _SOURCE_ORDER.get(s.source, 9))
        return senses

    def _lookup_exact(self, word: str) -> Optional[Entry]:
        row = self._connection.execute(
            "SELECT id, word FROM entries WHERE word_lower = ?", (word.lower(),)
        ).fetchone()
        if row is None:
            return None
        return Entry(word=row["word"], senses=self._senses_for(row["id"]))

    def base_forms(self, word: str) -> List[str]:
        """Candidate dictionary forms for a possibly inflected ``word``."""
        lowered = word.lower().strip()
        candidates: List[str] = []

        irregular = self._exception_for(lowered)
        if irregular:
            candidates.append(irregular)

        for suffix, replacements in _SUFFIX_RULES:
            if len(lowered) > len(suffix) + 1 and lowered.endswith(suffix):
                stem = lowered[: -len(suffix)]
                for replacement in replacements:
                    candidates.append(stem + replacement)
                # A doubled consonant is dropped: "running" -> "run".
                if suffix in ("ing", "ed", "er", "est") and len(stem) > 2 \
                        and stem[-1] == stem[-2] and stem[-1].isalpha():
                    candidates.append(stem[:-1])
        return _unique(candidates)

    def _exception_for(self, word: str) -> str:
        if word in self._exceptions_cache:
            return self._exceptions_cache[word]
        try:
            row = self._connection.execute(
                "SELECT base FROM lemma_exceptions WHERE form = ?", (word,)
            ).fetchone()
        except sqlite3.Error:
            row = None
        value = row["base"] if row else ""
        self._exceptions_cache[word] = value
        return value

    def lookup(self, word: str, follow_inflections: bool = True) -> Optional[Entry]:
        """Look up ``word``, falling back to its base form when inflected."""
        cleaned = (word or "").strip().strip(".,;:!?\"'()[]{}")
        if not cleaned:
            return None

        entry = self._lookup_exact(cleaned)
        if entry is not None:
            return entry

        if not follow_inflections:
            return None

        for candidate in self.base_forms(cleaned):
            entry = self._lookup_exact(candidate)
            if entry is not None:
                entry.matched_form = cleaned
                return entry

        # "post-office" may be stored as "post office", and vice versa.
        for variant in (cleaned.replace("-", " "), cleaned.replace(" ", "-")):
            if variant != cleaned:
                entry = self._lookup_exact(variant)
                if entry is not None:
                    entry.matched_form = cleaned
                    return entry
        return None

    def suggest(self, prefix: str, limit: int = 25) -> List[str]:
        """Head words starting with ``prefix``, for autocomplete."""
        cleaned = (prefix or "").strip().lower()
        if not cleaned:
            return []
        rows = self._connection.execute(
            "SELECT word FROM entries WHERE word_lower >= ? AND word_lower < ?"
            " ORDER BY LENGTH(word_lower), word_lower LIMIT ?",
            (cleaned, cleaned + "￿", int(limit)),
        ).fetchall()
        return [row["word"] for row in rows]

    def reverse_lookup(self, hindi: str, limit: int = 25) -> List[Entry]:
        """English head words whose Hindi meanings match ``hindi``."""
        cleaned = (hindi or "").strip()
        if not cleaned:
            return []
        rows = self._connection.execute(
            "SELECT DISTINCT entry_id FROM hindi_terms WHERE term_lower = ?"
            " LIMIT ?",
            (cleaned.lower(), int(limit)),
        ).fetchall()
        if not rows:
            rows = self._connection.execute(
                "SELECT DISTINCT entry_id FROM hindi_terms"
                " WHERE term_lower >= ? AND term_lower < ? LIMIT ?",
                (cleaned.lower(), cleaned.lower() + "￿", int(limit)),
            ).fetchall()

        entries: List[Entry] = []
        for row in rows:
            record = self._connection.execute(
                "SELECT id, word FROM entries WHERE id = ?", (row["entry_id"],)
            ).fetchone()
            if record is not None:
                entries.append(
                    Entry(word=record["word"], senses=self._senses_for(record["id"]))
                )
        return entries

    def search(self, query: str, limit: int = 25) -> List[Entry]:
        """Look up ``query`` in whichever direction its script implies."""
        cleaned = (query or "").strip()
        if not cleaned:
            return []
        if _DEVANAGARI_RE.search(cleaned):
            return self.reverse_lookup(cleaned, limit=limit)
        entry = self.lookup(cleaned)
        return [entry] if entry is not None else []

    def administrative_terms(self, limit: int = 0) -> List[Entry]:
        """Every term from the curated administrative glossary."""
        query = (
            "SELECT DISTINCT e.id, e.word FROM entries e"
            " JOIN senses s ON s.entry_id = e.id"
            " WHERE s.source = ? ORDER BY e.word_lower"
        )
        parameters: tuple = (SOURCE_ADMIN,)
        if limit:
            query += " LIMIT ?"
            parameters = (SOURCE_ADMIN, int(limit))
        rows = self._connection.execute(query, parameters).fetchall()
        return [
            Entry(word=row["word"], senses=self._senses_for(row["id"]))
            for row in rows
        ]

    def administrative_categories(self) -> List[str]:
        rows = self._connection.execute(
            "SELECT DISTINCT category FROM senses WHERE source = ? AND category <> ''"
            " ORDER BY category",
            (SOURCE_ADMIN,),
        ).fetchall()
        return [row["category"] for row in rows]


#: Human-readable part-of-speech names, in both languages.
POS_LABELS = {
    "noun": "noun / संज्ञा",
    "verb": "verb / क्रिया",
    "adjective": "adjective / विशेषण",
    "adverb": "adverb / क्रियाविशेषण",
    "pronoun": "pronoun / सर्वनाम",
    "preposition": "preposition / संबंधबोधक",
    "conjunction": "conjunction / समुच्चयबोधक",
    "interjection": "interjection / विस्मयादिबोधक",
    "determiner": "determiner / निर्धारक",
    "numeral": "numeral / संख्यावाचक",
    "phrase": "phrase / वाक्यांश",
    "abbreviation": "abbreviation / संक्षिप्ति",
}


def pos_label(pos: str) -> str:
    """A readable name for a part-of-speech code."""
    return POS_LABELS.get(pos, pos or "other")


def words_in(text: str) -> List[str]:
    """Every English word in ``text``, in order, de-duplicated."""
    return _unique(_WORD_RE.findall(text or ""))
