"""Dictionary lookup, lemmatisation and reverse search.

These run against a small database built by the fixture in conftest, so they
do not need the full 48 MB dictionary.
"""

from __future__ import annotations

import sqlite3

import pytest

from setu.dictionary import (
    Dictionary,
    DictionaryError,
    DictionaryNotFoundError,
    Entry,
    Sense,
    discover_dictionary,
    pos_label,
    words_in,
)


class TestOpening:
    def test_opens_and_reports_metadata(self, dictionary):
        meta = dictionary.meta()
        assert meta["schema_version"] == "1"
        assert int(meta["entries"]) == dictionary.count_entries()

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(DictionaryNotFoundError):
            Dictionary.open(tmp_path / "absent.sqlite")

    def test_a_file_that_is_not_a_database_raises(self, tmp_path):
        path = tmp_path / "broken.sqlite"
        path.write_text("not a database at all", encoding="utf-8")
        with pytest.raises(DictionaryError):
            Dictionary.open(path)

    def test_unsupported_schema_version_is_refused(self, tmp_path):
        path = tmp_path / "future.sqlite"
        connection = sqlite3.connect(str(path))
        connection.executescript(
            "CREATE TABLE meta (key TEXT, value TEXT);"
            "CREATE TABLE entries (id INTEGER, word TEXT, word_lower TEXT);"
            "INSERT INTO meta VALUES ('schema_version', '99');"
        )
        connection.commit()
        connection.close()
        with pytest.raises(DictionaryError, match="schema version"):
            Dictionary.open(path)

    def test_discovery_uses_the_environment_variable(self, dictionary_path, monkeypatch):
        monkeypatch.setenv("SETU_DICTIONARY", str(dictionary_path))
        assert discover_dictionary() == dictionary_path

    def test_discovery_reports_where_it_looked(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SETU_DICTIONARY", raising=False)
        monkeypatch.setattr("setu.dictionary.app_root", lambda: tmp_path / "app")
        monkeypatch.setattr("setu.dictionary.user_data_dir", lambda: tmp_path / "u")
        with pytest.raises(DictionaryNotFoundError, match="Looked in"):
            discover_dictionary()

    def test_can_be_used_as_a_context_manager(self, dictionary_path):
        with Dictionary.open(dictionary_path) as dictionary:
            assert dictionary.count_entries() > 0

    def test_database_is_opened_read_only(self, dictionary):
        with pytest.raises(sqlite3.OperationalError):
            dictionary._connection.execute("DELETE FROM entries")


class TestLookup:
    def test_finds_a_word(self, dictionary):
        entry = dictionary.lookup("government")
        assert entry is not None
        assert entry.word == "government"

    def test_lookup_is_case_insensitive(self, dictionary):
        assert dictionary.lookup("GOVERNMENT") is not None
        assert dictionary.lookup("Government") is not None

    def test_unknown_word_returns_none(self, dictionary):
        assert dictionary.lookup("zzzznotaword") is None

    def test_empty_query_returns_none(self, dictionary):
        assert dictionary.lookup("") is None
        assert dictionary.lookup("   ") is None

    def test_surrounding_punctuation_is_stripped(self, dictionary):
        assert dictionary.lookup("(government),") is not None

    def test_hindi_meanings_are_returned(self, dictionary):
        entry = dictionary.lookup("government")
        assert "सरकार" in entry.hindi_meanings

    def test_parts_of_speech_are_returned(self, dictionary):
        entry = dictionary.lookup("run")
        assert "verb" in entry.parts_of_speech

    def test_definitions_synonyms_and_examples(self, dictionary):
        entry = dictionary.lookup("happy")
        assert any(sense.definition_en for sense in entry.senses)
        assert entry.synonyms
        assert entry.examples

    def test_antonyms_are_returned(self, dictionary):
        entry = dictionary.lookup("happy")
        assert "unhappy" in [word.lower() for word in entry.antonyms]

    def test_multiword_head_words(self, dictionary):
        assert dictionary.lookup("Joint Secretary") is not None


class TestInflections:
    @pytest.mark.parametrize(
        "form,base",
        [
            ("governments", "government"),
            ("running", "run"),
            ("ran", "run"),
            ("happier", "happy"),
            ("happiest", "happy"),
            ("studies", "study"),
            ("studied", "study"),
            ("mice", "mouse"),
        ],
    )
    def test_inflected_forms_resolve(self, dictionary, form, base):
        entry = dictionary.lookup(form)
        assert entry is not None, form
        assert entry.word == base

    def test_matched_form_is_recorded(self, dictionary):
        entry = dictionary.lookup("governments")
        assert entry.matched_form == "governments"

    def test_exact_match_records_no_inflection(self, dictionary):
        assert dictionary.lookup("government").matched_form == ""

    def test_inflection_following_can_be_disabled(self, dictionary):
        assert dictionary.lookup("governments", follow_inflections=False) is None

    def test_hyphen_and_space_variants(self, dictionary):
        assert dictionary.lookup("joint-secretary") is not None

    def test_base_forms_are_generated_for_unknown_words(self, dictionary):
        assert "walk" in dictionary.base_forms("walking")
        assert "carry" in dictionary.base_forms("carries")


class TestSuggest:
    def test_prefix_suggestions(self, dictionary):
        assert "government" in dictionary.suggest("govern", limit=20)

    def test_suggestions_respect_the_limit(self, dictionary):
        assert len(dictionary.suggest("s", limit=3)) <= 3

    def test_empty_prefix_gives_nothing(self, dictionary):
        assert dictionary.suggest("") == []

    def test_unknown_prefix_gives_nothing(self, dictionary):
        assert dictionary.suggest("zzzzq") == []


class TestReverseLookup:
    def test_hindi_finds_the_english_word(self, dictionary):
        assert "government" in [e.word for e in dictionary.reverse_lookup("सरकार")]

    def test_unknown_hindi_gives_nothing(self, dictionary):
        assert dictionary.reverse_lookup("क्ष्ज्ञत्र") == []

    def test_search_detects_devanagari(self, dictionary):
        results = dictionary.search("सरकार")
        assert results and results[0].word == "government"

    def test_search_handles_english(self, dictionary):
        results = dictionary.search("government")
        assert results and results[0].word == "government"

    def test_search_of_nothing_is_empty(self, dictionary):
        assert dictionary.search("  ") == []


class TestAdministrativeGlossary:
    def test_terms_are_listed(self, dictionary):
        terms = dictionary.administrative_terms()
        assert terms
        assert all(entry.is_administrative for entry in terms)

    def test_categories_are_listed(self, dictionary):
        assert "designation" in dictionary.administrative_categories()

    def test_an_administrative_entry_is_complete(self, dictionary):
        entry = dictionary.lookup("Joint Secretary")
        sense = entry.administrative_senses[0]
        assert sense.hindi == ["संयुक्त सचिव"]
        assert sense.definition_en
        assert sense.definition_hi
        assert sense.examples_en
        assert sense.examples_hi
        assert sense.category == "designation"

    def test_administrative_senses_are_listed_first(self, dictionary):
        entry = dictionary.lookup("sanction")
        assert entry.senses[0].is_administrative

    def test_a_plain_word_is_not_administrative(self, dictionary):
        assert not dictionary.lookup("happy").is_administrative


class TestEntryHelpers:
    def test_hindi_meanings_are_deduplicated(self):
        entry = Entry(word="x", senses=[
            Sense(source="admin", hindi=["सरकार"]),
            Sense(source="freedict", hindi=["सरकार", "शासन"]),
        ])
        assert entry.hindi_meanings == ["सरकार", "शासन"]

    def test_senses_group_by_pos(self):
        entry = Entry(word="x", senses=[
            Sense(source="wordnet", pos="noun"),
            Sense(source="wordnet", pos="verb"),
            Sense(source="wordnet", pos="noun"),
        ])
        grouped = entry.senses_by_pos()
        assert len(grouped["noun"]) == 2
        assert len(grouped["verb"]) == 1

    def test_pos_label_is_bilingual(self):
        assert "संज्ञा" in pos_label("noun")

    def test_pos_label_falls_back(self):
        assert pos_label("") == "other"
        assert pos_label("weird") == "weird"

    def test_words_in_extracts_english_words(self):
        assert words_in("Hello, world! Hello again.") == ["Hello", "world", "again"]

    def test_words_in_ignores_devanagari_and_numbers(self):
        assert words_in("42 नमस्ते test") == ["test"]
