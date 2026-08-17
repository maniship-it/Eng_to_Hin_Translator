"""The dictionary build pipeline: source parsers and the glossary itself.

The WordNet and FreeDict parsers are exercised against small synthetic files
in the real formats.  The administrative glossary is checked as shipped.
"""

from __future__ import annotations

import csv
import re
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import build_dictionary  # noqa: E402

GLOSSARY_PATH = PROJECT_ROOT / "data" / "admin_glossary.tsv"
DEVANAGARI = re.compile(r"[ऀ-ॿ]")

# Real WordNet 3.0 record shapes, trimmed to a handful of synsets.
DATA_ADJ = """\
  1 This software and database is being provided to you.
00001740 00 a 02 good 0 goodness 0 001 ! 00002098 a 0101 | benefit; "for your own good"
00002098 00 a 01 bad 0 001 ! 00001740 a 0101 | not good
"""

DATA_NOUN = """\
  1 Licence header line.
00001741 03 n 02 hot_dog 0 frank(a) 0 000 | a smooth-textured sausage; "he ate a hot dog"; "with mustard"
00001742 03 n 01 entity 0 000 | that which is perceived to exist
"""

INDEX_ADJ = """\
  1 Licence header line.
good a 1 1 ! 1 0 00001740
bad a 1 1 ! 1 0 00002098
"""

INDEX_NOUN = """\
  1 Licence header line.
hot_dog n 1 0 1 0 00001741
entity n 1 0 1 0 00001742
"""

TEI = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text><body>
    <entry>
      <form><orth>abandon</orth></form>
      <gramGrp><pos>V</pos></gramGrp>
      <sense n="1">
        <cit type="trans"><quote>छोड़~देना</quote></cit>
        <cit type="trans"><quote>त्यागना</quote></cit>
        <cit type="example"><quote>A baby abandoned by its parents was found.</quote></cit>
      </sense>
    </entry>
    <entry>
      <form><orth>abacus</orth></form>
      <gramGrp><pos>N</pos></gramGrp>
      <sense n="1">
        <cit type="trans"><quote>गिनतारा</quote></cit>
      </sense>
    </entry>
    <entry>
      <form><orth></orth></form>
      <gramGrp><pos>N</pos></gramGrp>
      <sense n="1"><cit type="trans"><quote>कुछ</quote></cit></sense>
    </entry>
  </body></text>
</TEI>
"""


@pytest.fixture
def wordnet_dir(tmp_path):
    root = tmp_path / "wordnet"
    root.mkdir()
    (root / "data.adj").write_text(DATA_ADJ, encoding="utf-8")
    (root / "data.noun").write_text(DATA_NOUN, encoding="utf-8")
    (root / "index.adj").write_text(INDEX_ADJ, encoding="utf-8")
    (root / "index.noun").write_text(INDEX_NOUN, encoding="utf-8")
    (root / "noun.exc").write_text("mice mouse\nfeet foot\n", encoding="utf-8")
    return root


class TestWordNetParsing:
    def test_synsets_are_parsed(self, wordnet_dir):
        synsets = build_dictionary.parse_data_file(wordnet_dir / "data.adj")
        assert ("00001740", "a") in synsets
        assert synsets[("00001740", "a")].words == ["good", "goodness"]

    def test_licence_header_is_skipped(self, wordnet_dir):
        synsets = build_dictionary.parse_data_file(wordnet_dir / "data.adj")
        assert len(synsets) == 2

    def test_definition_and_examples_are_separated(self, wordnet_dir):
        synset = build_dictionary.parse_data_file(wordnet_dir / "data.adj")[
            ("00001740", "a")]
        assert synset.definition == "benefit"
        assert synset.examples == ["for your own good"]

    def test_multiple_examples(self, wordnet_dir):
        synset = build_dictionary.parse_data_file(wordnet_dir / "data.noun")[
            ("00001741", "n")]
        assert synset.examples == ["he ate a hot dog", "with mustard"]
        assert synset.definition == "a smooth-textured sausage"

    def test_underscores_become_spaces_and_markers_are_stripped(self, wordnet_dir):
        synset = build_dictionary.parse_data_file(wordnet_dir / "data.noun")[
            ("00001741", "n")]
        assert synset.words == ["hot dog", "frank"]

    def test_pointers_are_parsed(self, wordnet_dir):
        synset = build_dictionary.parse_data_file(wordnet_dir / "data.adj")[
            ("00001740", "a")]
        assert ("!", "00002098", "a", "0101") in synset.pointers

    def test_index_maps_lemma_to_offsets(self, wordnet_dir):
        index = build_dictionary.parse_index_file(wordnet_dir / "index.noun")
        assert index["hot dog"] == ["00001741"]
        assert index["entity"] == ["00001742"]

    def test_exceptions_are_parsed(self, wordnet_dir):
        exceptions = build_dictionary.parse_exception_file(wordnet_dir / "noun.exc")
        assert exceptions == {"mice": "mouse", "feet": "foot"}

    def test_missing_exception_file_is_not_an_error(self, tmp_path):
        assert build_dictionary.parse_exception_file(tmp_path / "absent.exc") == {}

    def test_load_wordnet_resolves_synonyms_and_antonyms(self, wordnet_dir):
        senses, exceptions = build_dictionary.load_wordnet(wordnet_dir)
        good = senses["good"][0]
        assert good["pos"] == "adjective"
        assert good["synonyms"] == ["goodness"]
        assert good["antonyms"] == ["bad"]
        assert exceptions["mice"] == "mouse"

    def test_load_wordnet_finds_a_nested_directory(self, tmp_path, wordnet_dir):
        outer = tmp_path / "outer"
        outer.mkdir()
        wordnet_dir.rename(outer / "wordnet")
        senses, _ = build_dictionary.load_wordnet(outer)
        assert "good" in senses

    def test_load_wordnet_without_data_files_fails(self, tmp_path):
        with pytest.raises(SystemExit, match="No WordNet data files"):
            build_dictionary.load_wordnet(tmp_path)


class TestFreeDictParsing:
    def test_entries_are_parsed(self, tmp_path):
        path = tmp_path / "eng-hin.tei"
        path.write_text(TEI, encoding="utf-8")
        entries = build_dictionary.load_freedict(path)
        assert set(entries) == {"abandon", "abacus"}

    def test_tilde_is_replaced_by_a_space(self, tmp_path):
        path = tmp_path / "eng-hin.tei"
        path.write_text(TEI, encoding="utf-8")
        entries = build_dictionary.load_freedict(path)
        assert entries["abandon"][0]["hindi"] == ["छोड़ देना", "त्यागना"]

    def test_translations_and_examples_are_distinguished(self, tmp_path):
        path = tmp_path / "eng-hin.tei"
        path.write_text(TEI, encoding="utf-8")
        sense = build_dictionary.load_freedict(path)["abandon"][0]
        assert sense["pos"] == "verb"
        assert sense["examples_en"] == [
            "A baby abandoned by its parents was found."
        ]

    def test_entries_without_a_headword_are_skipped(self, tmp_path):
        path = tmp_path / "eng-hin.tei"
        path.write_text(TEI, encoding="utf-8")
        assert "" not in build_dictionary.load_freedict(path)


class TestAdministrativeGlossaryFile:
    """The glossary ships with the project, so it is validated as data."""

    @pytest.fixture(scope="class")
    def rows(self):
        with open(GLOSSARY_PATH, encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))

    def test_the_file_exists_and_is_not_trivial(self, rows):
        assert len(rows) >= 150

    def test_every_column_is_filled(self, rows):
        for number, row in enumerate(rows, start=2):
            for column in build_dictionary.ADMIN_COLUMNS:
                assert (row.get(column) or "").strip(), \
                    "line %d: %s is empty for %r" % (number, column, row["english"])

    def test_hindi_columns_are_in_devanagari(self, rows):
        for row in rows:
            for column in ("hindi", "definition_hi", "example_hi"):
                assert DEVANAGARI.search(row[column]), \
                    "%s: %s is not Devanagari" % (row["english"], column)

    def test_english_columns_have_no_devanagari(self, rows):
        for row in rows:
            for column in ("definition_en", "example_en"):
                assert not DEVANAGARI.search(row[column]), \
                    "%s: %s should be English" % (row["english"], column)

    def test_no_duplicate_term_pairs(self, rows):
        pairs = [(row["english"].lower(), row["hindi"]) for row in rows]
        assert len(pairs) == len(set(pairs))

    def test_examples_mention_the_term(self, rows):
        """An example that does not use the word is not an example of it."""
        for row in rows:
            head = row["english"].split()[-1].lower().rstrip("s")
            assert head[:5] in row["example_en"].lower(), \
                "%s: example does not use the term" % row["english"]

    def test_categories_are_from_a_small_stable_set(self, rows):
        categories = {row["category"] for row in rows}
        assert len(categories) <= 20
        assert "designation" in categories

    def test_loader_accepts_the_shipped_file(self):
        assert len(build_dictionary.load_admin_glossary(GLOSSARY_PATH)) >= 150

    def test_loader_reports_a_missing_column(self, tmp_path):
        path = tmp_path / "bad.tsv"
        path.write_text("english\thindi\n a\t b\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="missing column"):
            build_dictionary.load_admin_glossary(path)

    def test_loader_rejects_a_row_without_hindi(self, tmp_path):
        path = tmp_path / "bad.tsv"
        header = "\t".join(build_dictionary.ADMIN_COLUMNS)
        path.write_text(header + "\n" + "\t".join(["Term", ""] + ["x"] * 6) + "\n",
                        encoding="utf-8")
        with pytest.raises(SystemExit, match="required"):
            build_dictionary.load_admin_glossary(path)

    def test_a_missing_file_is_not_fatal(self, tmp_path):
        assert build_dictionary.load_admin_glossary(tmp_path / "absent.tsv") == []


class TestBuildDatabase:
    def test_schema_and_contents(self, dictionary_path):
        connection = sqlite3.connect(str(dictionary_path))
        try:
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert {"meta", "entries", "senses", "hindi_terms",
                    "lemma_exceptions"} <= tables

            meta = dict(connection.execute("SELECT key, value FROM meta"))
            assert meta["schema_version"] == str(build_dictionary.SCHEMA_VERSION)
            assert int(meta["admin_terms"]) >= 150

            count = connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            assert count == int(meta["entries"])
        finally:
            connection.close()

    def test_head_words_are_unique(self, dictionary_path):
        connection = sqlite3.connect(str(dictionary_path))
        try:
            duplicates = connection.execute(
                "SELECT word_lower, COUNT(*) c FROM entries GROUP BY word_lower"
                " HAVING c > 1"
            ).fetchall()
            assert duplicates == []
        finally:
            connection.close()

    def test_rebuilding_replaces_the_previous_file(self, tmp_path):
        destination = tmp_path / "dictionary.sqlite"
        for _ in range(2):
            build_dictionary.build_database(
                destination, {"x": [{"pos": "noun", "definition_en": "d",
                                     "examples_en": [], "synonyms": [],
                                     "antonyms": []}]}, {}, {}, [],
            )
        connection = sqlite3.connect(str(destination))
        try:
            assert connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 1
        finally:
            connection.close()

    def test_unsafe_zip_entries_are_refused(self, tmp_path):
        import zipfile

        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("../escaped.txt", "nope")
        with zipfile.ZipFile(archive) as handle:
            with pytest.raises(SystemExit, match="unsafe path"):
                build_dictionary._safe_extract(handle, tmp_path / "out")
