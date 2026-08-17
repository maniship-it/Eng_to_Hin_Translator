"""Build the offline English-Hindi dictionary database.

Run this on a machine with internet access.  It gathers three open sources
and compiles them into a single SQLite file the application reads offline:

  * Princeton WordNet 3.0 -- parts of speech, definitions, synonyms,
    antonyms and example sentences (WordNet licence, BSD-like).
  * FreeDict eng-hin -- Hindi meanings and example sentences, derived from
    the IIIT Hyderabad English-Hindi dictionary (GPL-2.0-or-later).
  * data/admin_glossary.tsv -- this project's curated glossary of central
    government administrative terminology, in English and Hindi.

Usage::

    python tools/build_dictionary.py
    python tools/build_dictionary.py --wordnet wordnet.zip --freedict eng-hin.tei
    python tools/build_dictionary.py --dest D:\\dict\\dictionary.sqlite

The two downloaded sources keep their own licences; see the README.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
import tempfile
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEST = PROJECT_ROOT / "models" / "dictionary" / "dictionary.sqlite"
DEFAULT_ADMIN = PROJECT_ROOT / "data" / "admin_glossary.tsv"

WORDNET_URL = (
    "https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/"
    "packages/corpora/wordnet.zip"
)
FREEDICT_URL = (
    "https://raw.githubusercontent.com/freedict/fd-dictionaries/master/"
    "eng-hin/eng-hin.tei"
)

TEI_NS = "{http://www.tei-c.org/ns/1.0}"

#: Schema version; the application refuses a database it does not understand.
SCHEMA_VERSION = 1

SOURCE_ADMIN = "admin"
SOURCE_FREEDICT = "freedict"
SOURCE_WORDNET = "wordnet"

#: Lower sorts first when senses are presented to the user.
SOURCE_ORDER = {SOURCE_ADMIN: 0, SOURCE_FREEDICT: 1, SOURCE_WORDNET: 2}

POS_NOUN = "noun"
POS_VERB = "verb"
POS_ADJECTIVE = "adjective"
POS_ADVERB = "adverb"

_WORDNET_POS = {
    "n": POS_NOUN,
    "v": POS_VERB,
    "a": POS_ADJECTIVE,
    "s": POS_ADJECTIVE,  # adjective satellite
    "r": POS_ADVERB,
}

_FREEDICT_POS = {
    "n": POS_NOUN,
    "v": POS_VERB,
    "adj": POS_ADJECTIVE,
    "adv": POS_ADVERB,
    "pron": "pronoun",
    "prep": "preposition",
    "conj": "conjunction",
    "det": "determiner",
    "art": "determiner",
    "interj": "interjection",
    "int": "interjection",
    "num": "numeral",
    "abbr": "abbreviation",
    "phrase": "phrase",
    "prefix": "prefix",
    "suffix": "suffix",
}

_EXAMPLE_RE = re.compile(r'"([^"]*)"')
_PAREN_SUFFIX_RE = re.compile(r"\(\w+\)$")


# ---------------------------------------------------------------- download


def download(url: str, destination: Path) -> Path:
    """Fetch ``url`` to ``destination`` with a progress indicator."""
    print("Downloading %s" % url)
    request = Request(url, headers={"User-Agent": "Setu/1.0"})
    try:
        with urlopen(request, timeout=120) as response:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            with open(destination, "wb") as handle:
                while True:
                    chunk = response.read(256 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        print("\r  %.1f / %.1f MB" % (
                            downloaded / 1048576, total / 1048576), end="")
                    else:
                        print("\r  %.1f MB" % (downloaded / 1048576), end="")
            print()
    except (URLError, OSError) as exc:
        raise SystemExit(
            "Could not download %s\n  %s\n\n"
            "Download it manually and pass it with --wordnet / --freedict."
            % (url, exc)
        )
    return destination


# ----------------------------------------------------------------- WordNet


class Synset:
    """One WordNet synset: a set of synonymous words sharing a definition."""

    __slots__ = ("offset", "pos", "words", "definition", "examples", "pointers")

    def __init__(self, offset, pos, words, definition, examples, pointers):
        self.offset = offset
        self.pos = pos
        self.words = words
        self.definition = definition
        self.examples = examples
        self.pointers = pointers


def _clean_wordnet_word(word: str) -> str:
    """``dog(a)`` -> ``dog``; ``hot_dog`` -> ``hot dog``."""
    return _PAREN_SUFFIX_RE.sub("", word).replace("_", " ").strip()


def parse_data_file(path: Path) -> Dict[Tuple[str, str], Synset]:
    """Parse one ``data.<pos>`` file into synsets keyed by (offset, pos)."""
    synsets: Dict[Tuple[str, str], Synset] = {}

    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            # The licence header lines all start with two spaces.
            if line.startswith("  ") or not line.strip():
                continue

            data_part, _, gloss = line.partition("|")
            fields = data_part.split()
            if len(fields) < 4:
                continue

            try:
                offset = fields[0]
                ss_type = fields[2]
                word_count = int(fields[3], 16)

                index = 4
                words: List[str] = []
                for _ in range(word_count):
                    words.append(_clean_wordnet_word(fields[index]))
                    index += 2  # word, lex_id

                pointer_count = int(fields[index])
                index += 1
                pointers: List[Tuple[str, str, str, str]] = []
                for _ in range(pointer_count):
                    pointers.append((
                        fields[index],       # symbol
                        fields[index + 1],   # target offset
                        fields[index + 2],   # target pos
                        fields[index + 3],   # source/target word numbers
                    ))
                    index += 4
            except (IndexError, ValueError):
                continue

            examples = [e.strip() for e in _EXAMPLE_RE.findall(gloss) if e.strip()]
            definition = _EXAMPLE_RE.sub("", gloss)
            definition = re.sub(r"[\s;]+$", "", definition.strip()).strip()

            pos = _WORDNET_POS.get(ss_type, ss_type)
            synsets[(offset, ss_type)] = Synset(
                offset, pos, words, definition, examples, pointers
            )
    return synsets


def parse_index_file(path: Path) -> "OrderedDict[str, List[str]]":
    """Parse ``index.<pos>``: lemma -> synset offsets in sense order."""
    index: "OrderedDict[str, List[str]]" = OrderedDict()
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("  ") or not line.strip():
                continue
            fields = line.split()
            try:
                lemma = _clean_wordnet_word(fields[0])
                pointer_count = int(fields[3])
                # lemma pos synset_cnt p_cnt <ptrs> sense_cnt tagsense_cnt <offsets>
                offsets = fields[4 + pointer_count + 2:]
            except (IndexError, ValueError):
                continue
            if lemma and offsets:
                index.setdefault(lemma, []).extend(offsets)
    return index


def parse_exception_file(path: Path) -> Dict[str, str]:
    """Parse ``<pos>.exc``: irregular inflected form -> base form."""
    exceptions: Dict[str, str] = {}
    if not path.is_file():
        return exceptions
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) >= 2:
                exceptions.setdefault(parts[0].replace("_", " "),
                                      parts[1].replace("_", " "))
    return exceptions


def load_wordnet(root: Path) -> Tuple[Dict[str, List[dict]], Dict[str, str]]:
    """Read a WordNet directory into ``lemma -> senses`` plus the exceptions."""
    if not (root / "data.noun").is_file():
        candidates = list(root.rglob("data.noun"))
        if not candidates:
            raise SystemExit("No WordNet data files found under %s" % root)
        root = candidates[0].parent

    print("Reading WordNet from %s" % root)

    all_synsets: Dict[Tuple[str, str], Synset] = {}
    for suffix in ("noun", "verb", "adj", "adv"):
        data_path = root / ("data.%s" % suffix)
        if data_path.is_file():
            all_synsets.update(parse_data_file(data_path))
    print("  %d synsets" % len(all_synsets))

    def resolve_antonyms(synset: Synset, word_index: int) -> List[str]:
        """Antonyms recorded for a specific word inside a synset."""
        antonyms: List[str] = []
        for symbol, target_offset, target_pos, numbers in synset.pointers:
            if symbol != "!":
                continue
            try:
                source_number = int(numbers[:2], 16)
                target_number = int(numbers[2:], 16)
            except ValueError:
                continue
            # 0 means the pointer applies to the whole synset.
            if source_number not in (0, word_index + 1):
                continue
            target = all_synsets.get((target_offset, target_pos))
            if target is None:
                continue
            if target_number == 0:
                antonyms.extend(target.words)
            elif 0 < target_number <= len(target.words):
                antonyms.append(target.words[target_number - 1])
        return antonyms

    senses_by_lemma: Dict[str, List[dict]] = {}
    for suffix, ss_types in (("noun", ("n",)), ("verb", ("v",)),
                             ("adj", ("a", "s")), ("adv", ("r",))):
        index_path = root / ("index.%s" % suffix)
        if not index_path.is_file():
            continue
        for lemma, offsets in parse_index_file(index_path).items():
            for offset in offsets:
                synset = None
                for ss_type in ss_types:
                    synset = all_synsets.get((offset, ss_type))
                    if synset is not None:
                        break
                if synset is None:
                    continue

                try:
                    word_index = [w.lower() for w in synset.words].index(lemma.lower())
                except ValueError:
                    word_index = 0

                synonyms = [w for w in synset.words if w.lower() != lemma.lower()]
                senses_by_lemma.setdefault(lemma, []).append({
                    "pos": synset.pos,
                    "definition_en": synset.definition,
                    "examples_en": synset.examples,
                    "synonyms": synonyms,
                    "antonyms": _unique(resolve_antonyms(synset, word_index)),
                })

    exceptions: Dict[str, str] = {}
    for name in ("noun.exc", "verb.exc", "adj.exc", "adv.exc"):
        exceptions.update(parse_exception_file(root / name))

    print("  %d lemmas, %d irregular forms" % (len(senses_by_lemma), len(exceptions)))
    return senses_by_lemma, exceptions


# ---------------------------------------------------------------- FreeDict


def _normalise_freedict_pos(raw: str) -> str:
    value = (raw or "").strip().lower().rstrip(".")
    return _FREEDICT_POS.get(value, value or "")


def _clean_hindi(text: str) -> str:
    """FreeDict joins multi-word Hindi phrases with ``~``."""
    return re.sub(r"\s+", " ", (text or "").replace("~", " ")).strip()


def load_freedict(path: Path) -> Dict[str, List[dict]]:
    """Parse the FreeDict TEI file into ``headword -> senses``."""
    import xml.etree.ElementTree as ET

    print("Reading FreeDict from %s" % path)
    entries: Dict[str, List[dict]] = {}
    count = 0

    # iterparse keeps memory flat on a 12 MB document.
    for event, element in ET.iterparse(str(path), events=("end",)):
        if element.tag != TEI_NS + "entry":
            continue
        count += 1

        orth = element.find("./%sform/%sorth" % (TEI_NS, TEI_NS))
        headword = (orth.text or "").strip() if orth is not None else ""
        if not headword:
            element.clear()
            continue

        pos_element = element.find("./%sgramGrp/%spos" % (TEI_NS, TEI_NS))
        pos = _normalise_freedict_pos(pos_element.text if pos_element is not None else "")

        for sense in element.findall("./%ssense" % TEI_NS):
            hindi: List[str] = []
            examples: List[str] = []
            for cit in sense.findall("./%scit" % TEI_NS):
                quote = cit.find("./%squote" % TEI_NS)
                if quote is None or not (quote.text or "").strip():
                    continue
                text = quote.text.strip()
                if cit.get("type") == "trans":
                    cleaned = _clean_hindi(text)
                    if cleaned:
                        hindi.append(cleaned)
                elif cit.get("type") == "example":
                    examples.append(re.sub(r"\s+", " ", text))
            if hindi or examples:
                entries.setdefault(headword, []).append({
                    "pos": pos,
                    "hindi": _unique(hindi),
                    "examples_en": _unique(examples),
                })
        element.clear()

    print("  %d entries parsed from %d TEI entries" % (len(entries), count))
    return entries


# ------------------------------------------------------------------- admin


ADMIN_COLUMNS = [
    "english", "hindi", "pos", "category",
    "definition_en", "definition_hi", "example_en", "example_hi",
]


def load_admin_glossary(path: Path) -> List[dict]:
    """Read the curated administrative terminology glossary."""
    if not path.is_file():
        print("No administrative glossary at %s (skipping)" % path)
        return []

    print("Reading administrative glossary from %s" % path)
    rows: List[dict] = []
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing = [c for c in ADMIN_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(
                "Administrative glossary is missing column(s): %s" % ", ".join(missing)
            )
        for number, row in enumerate(reader, start=2):
            english = (row.get("english") or "").strip()
            hindi = (row.get("hindi") or "").strip()
            if not english or not hindi:
                raise SystemExit(
                    "%s line %d: both 'english' and 'hindi' are required"
                    % (path.name, number)
                )
            rows.append({key: (row.get(key) or "").strip() for key in ADMIN_COLUMNS})
    print("  %d administrative terms" % len(rows))
    return rows


# ---------------------------------------------------------------- database


SCHEMA = """
PRAGMA journal_mode = OFF;

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE entries (
    id         INTEGER PRIMARY KEY,
    word       TEXT NOT NULL,          -- as displayed
    word_lower TEXT NOT NULL           -- as searched
);

CREATE TABLE senses (
    id            INTEGER PRIMARY KEY,
    entry_id      INTEGER NOT NULL REFERENCES entries(id),
    rank          INTEGER NOT NULL,
    source        TEXT NOT NULL,
    pos           TEXT NOT NULL DEFAULT '',
    category      TEXT NOT NULL DEFAULT '',
    hindi         TEXT NOT NULL DEFAULT '[]',   -- JSON array
    definition_en TEXT NOT NULL DEFAULT '',
    definition_hi TEXT NOT NULL DEFAULT '',
    synonyms      TEXT NOT NULL DEFAULT '[]',   -- JSON array
    antonyms      TEXT NOT NULL DEFAULT '[]',   -- JSON array
    examples_en   TEXT NOT NULL DEFAULT '[]',   -- JSON array
    examples_hi   TEXT NOT NULL DEFAULT '[]'    -- JSON array
);

CREATE TABLE hindi_terms (
    term       TEXT NOT NULL,
    term_lower TEXT NOT NULL,
    entry_id   INTEGER NOT NULL REFERENCES entries(id)
);

CREATE TABLE lemma_exceptions (
    form TEXT PRIMARY KEY,
    base TEXT NOT NULL
);
"""

INDEXES = """
CREATE UNIQUE INDEX idx_entries_word_lower ON entries(word_lower);
CREATE INDEX idx_senses_entry ON senses(entry_id, rank);
CREATE INDEX idx_hindi_lower ON hindi_terms(term_lower);
CREATE INDEX idx_hindi_entry ON hindi_terms(entry_id);
"""


def _unique(values: Iterable[str]) -> List[str]:
    """De-duplicate, preserving order and dropping blanks."""
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


def build_database(dest: Path, wordnet: Dict[str, List[dict]],
                   exceptions: Dict[str, str], freedict: Dict[str, List[dict]],
                   admin: List[dict]) -> None:
    """Write every source into a single SQLite database."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()

    connection = sqlite3.connect(str(dest))
    try:
        connection.executescript(SCHEMA)

        entry_ids: Dict[str, int] = {}
        next_entry_id = 1
        next_sense_id = 1
        sense_rows: List[tuple] = []
        hindi_rows: List[tuple] = []
        entry_rows: List[tuple] = []
        rank_counter: Dict[int, int] = {}

        def entry_id_for(word: str) -> int:
            nonlocal next_entry_id
            key = word.lower()
            existing = entry_ids.get(key)
            if existing is not None:
                return existing
            entry_ids[key] = next_entry_id
            entry_rows.append((next_entry_id, word, key))
            next_entry_id += 1
            return entry_ids[key]

        def add_sense(word: str, source: str, pos: str = "", category: str = "",
                      hindi=(), definition_en: str = "", definition_hi: str = "",
                      synonyms=(), antonyms=(), examples_en=(), examples_hi=()) -> None:
            nonlocal next_sense_id
            identifier = entry_id_for(word)
            rank = rank_counter.get(identifier, 0)
            rank_counter[identifier] = rank + 1
            sense_rows.append((
                next_sense_id, identifier, rank, source, pos, category,
                json.dumps(_unique(hindi), ensure_ascii=False),
                definition_en, definition_hi,
                json.dumps(_unique(synonyms), ensure_ascii=False),
                json.dumps(_unique(antonyms), ensure_ascii=False),
                json.dumps(_unique(examples_en), ensure_ascii=False),
                json.dumps(_unique(examples_hi), ensure_ascii=False),
            ))
            next_sense_id += 1
            for term in _unique(hindi):
                hindi_rows.append((term, term.lower(), identifier))

        # Administrative terms come first so they lead the results.
        for row in admin:
            add_sense(
                row["english"], SOURCE_ADMIN,
                pos=row["pos"], category=row["category"] or "administration",
                hindi=[h.strip() for h in row["hindi"].split(";")],
                definition_en=row["definition_en"],
                definition_hi=row["definition_hi"],
                examples_en=[row["example_en"]] if row["example_en"] else [],
                examples_hi=[row["example_hi"]] if row["example_hi"] else [],
            )

        for word, senses in freedict.items():
            for sense in senses:
                add_sense(word, SOURCE_FREEDICT, pos=sense["pos"],
                          hindi=sense["hindi"], examples_en=sense["examples_en"])

        for word, senses in wordnet.items():
            for sense in senses:
                add_sense(word, SOURCE_WORDNET, pos=sense["pos"],
                          definition_en=sense["definition_en"],
                          synonyms=sense["synonyms"], antonyms=sense["antonyms"],
                          examples_en=sense["examples_en"])

        connection.executemany(
            "INSERT INTO entries (id, word, word_lower) VALUES (?, ?, ?)", entry_rows
        )
        connection.executemany(
            "INSERT INTO senses (id, entry_id, rank, source, pos, category, hindi,"
            " definition_en, definition_hi, synonyms, antonyms, examples_en,"
            " examples_hi) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            sense_rows,
        )
        connection.executemany(
            "INSERT INTO hindi_terms (term, term_lower, entry_id) VALUES (?,?,?)",
            hindi_rows,
        )
        connection.executemany(
            "INSERT OR IGNORE INTO lemma_exceptions (form, base) VALUES (?,?)",
            list(exceptions.items()),
        )

        connection.executescript(INDEXES)

        meta = {
            "schema_version": str(SCHEMA_VERSION),
            "entries": str(len(entry_rows)),
            "senses": str(len(sense_rows)),
            "admin_terms": str(len(admin)),
            "hindi_terms": str(len(hindi_rows)),
            "sources": json.dumps([
                {"name": "Princeton WordNet 3.0", "licence": "WordNet 3.0 licence"},
                {"name": "FreeDict eng-hin", "licence": "GPL-2.0-or-later"},
                {"name": "Administrative glossary", "licence": "MIT (this project)"},
            ], ensure_ascii=False),
        }
        connection.executemany(
            "INSERT INTO meta (key, value) VALUES (?, ?)", list(meta.items())
        )

        connection.commit()
        connection.execute("VACUUM")
        connection.commit()
    finally:
        connection.close()

    print("\nWrote %s (%.1f MB)" % (dest, dest.stat().st_size / 1048576))
    print("  %d head words, %d senses (%d administrative)"
          % (len(entry_rows), len(sense_rows), len(admin)))


# -------------------------------------------------------------------- main


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", default=str(DEFAULT_DEST),
                        help="Database to write (default: %s)" % DEFAULT_DEST)
    parser.add_argument("--wordnet", default="",
                        help="Local wordnet.zip or an unpacked WordNet folder.")
    parser.add_argument("--freedict", default="",
                        help="Local FreeDict eng-hin.tei file.")
    parser.add_argument("--admin", default=str(DEFAULT_ADMIN),
                        help="Administrative glossary TSV.")
    parser.add_argument("--skip-wordnet", action="store_true",
                        help="Build without WordNet (no definitions or thesaurus).")
    parser.add_argument("--skip-freedict", action="store_true",
                        help="Build without FreeDict (no general Hindi meanings).")
    args = parser.parse_args(argv)

    dest = Path(args.dest).expanduser().resolve()

    with tempfile.TemporaryDirectory() as tmp:
        temporary = Path(tmp)

        wordnet: Dict[str, List[dict]] = {}
        exceptions: Dict[str, str] = {}
        if not args.skip_wordnet:
            source = Path(args.wordnet) if args.wordnet else download(
                WORDNET_URL, temporary / "wordnet.zip")
            if source.is_file() and zipfile.is_zipfile(source):
                unpacked = temporary / "wordnet"
                with zipfile.ZipFile(source) as archive:
                    _safe_extract(archive, unpacked)
                source = unpacked
            wordnet, exceptions = load_wordnet(source)

        freedict: Dict[str, List[dict]] = {}
        if not args.skip_freedict:
            source = Path(args.freedict) if args.freedict else download(
                FREEDICT_URL, temporary / "eng-hin.tei")
            freedict = load_freedict(source)

        admin = load_admin_glossary(Path(args.admin))

        if not (wordnet or freedict or admin):
            raise SystemExit("Nothing to build: every source was empty or skipped.")

        build_database(dest, wordnet, exceptions, freedict, admin)

    return 0 if _verify(dest) else 1


def _safe_extract(archive: zipfile.ZipFile, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    resolved = target.resolve()
    for member in archive.infolist():
        destination = (resolved / member.filename).resolve()
        if not str(destination).startswith(str(resolved)):
            raise SystemExit("Refusing to extract unsafe path: %s" % member.filename)
    archive.extractall(resolved)


def _verify(dest: Path) -> bool:
    """Open the finished database through the application's own reader."""
    sys.path.insert(0, str(PROJECT_ROOT / "src"))
    try:
        from setu.dictionary import Dictionary
    except ImportError as exc:
        print("Could not import the app to verify the database: %s" % exc)
        return True

    print("\nVerifying…")
    try:
        with Dictionary.open(dest) as dictionary:
            for word in ("government", "abandon", "sanction"):
                entry = dictionary.lookup(word)
                if entry is None:
                    print("  [warn] no entry for %r" % word)
                    continue
                print("  %-12s %s | %s" % (
                    word,
                    ", ".join(entry.parts_of_speech) or "-",
                    ", ".join(entry.hindi_meanings[:4]) or "-",
                ))
    except Exception as exc:
        print("  [FAIL] %s: %s" % (type(exc).__name__, exc))
        return False
    print("Dictionary is ready.")
    return True


if __name__ == "__main__":
    sys.exit(main())
