"""Engine behaviour: structure, batching, caching and the safety fallbacks."""

from __future__ import annotations

import threading

import pytest

from entohin.translator import (
    Options,
    TranslationCancelled,
    Translator,
    is_degenerate,
    looks_untranslated,
)


class TestStructurePreservation:
    def test_line_count_is_preserved(self, translator):
        text = "One.\n\nTwo.\n   \nThree."
        result = translator.translate_text(text)
        assert result.text.count("\n") == text.count("\n")

    def test_blank_lines_stay_blank(self, translator):
        result = translator.translate_text("First.\n\nSecond.")
        assert result.text.split("\n")[1] == ""

    def test_indentation_and_bullets_are_kept(self, translator):
        result = translator.translate_text("  - A sentence here.")
        assert result.text.startswith("  - ")

    def test_numbering_is_kept(self, translator):
        result = translator.translate_text("1. First item.\n2. Second item.")
        lines = result.text.split("\n")
        assert lines[0].startswith("1. ")
        assert lines[1].startswith("2. ")

    def test_lines_without_letters_are_untouched(self, translator):
        result = translator.translate_text("Heading\n=======\n42\n3.14")
        lines = result.text.split("\n")
        assert lines[1] == "======="
        assert lines[2] == "42"
        assert lines[3] == "3.14"

    def test_empty_input_produces_empty_output(self, translator):
        result = translator.translate_text("")
        assert result.text == ""
        assert result.report.segments == 0

    def test_whitespace_only_input_is_returned_unchanged(self, translator):
        result = translator.translate_text("   \n\t\n")
        assert result.text == "   \n\t\n"

    def test_trailing_newline_survives(self, translator):
        result = translator.translate_text("A sentence.\n")
        assert result.text.endswith("\n")

    def test_many_lines(self, translator):
        text = "\n".join("This is line number %d." % i for i in range(500))
        result = translator.translate_text(text)
        assert len(result.text.split("\n")) == 500
        assert result.report.segments == 500


class TestSentenceHandling:
    def test_each_sentence_is_translated_separately(self, fake_backend, translator):
        translator.translate_text("First one. Second one. Third one.")
        assert len(fake_backend.translated_texts) == 3

    def test_sentence_spacing_is_kept(self, translator):
        result = translator.translate_text("One. Two.")
        assert " " in result.text
        assert result.text.count("शब्द") == 2

    def test_abbreviations_do_not_split(self, fake_backend, translator):
        translator.translate_text("Mr. Smith paid 3.14 dollars.")
        assert len(fake_backend.translated_texts) == 1


class TestPlaceholders:
    def test_url_survives_translation(self, translator):
        result = translator.translate_text("Please visit https://example.com/a_b today.")
        assert "https://example.com/a_b" in result.text

    def test_url_only_line_is_not_sent_to_the_model(self, fake_backend, translator):
        result = translator.translate_text("https://example.com/only")
        assert result.text == "https://example.com/only"
        assert fake_backend.translated_texts == []
        assert result.report.passthrough == 1

    def test_dropped_placeholder_triggers_a_retry(self, translator, fake_backend):
        source = "Please visit https://example.com now."
        # The model swallows the placeholder on the first pass.
        fake_backend.overrides = {"Please visit #1# now.": "कृपया अभी जाएँ।"}
        fake_backend.greedy_overrides = {source: "कृपया अभी https://example.com जाएँ।"}
        result = translator.translate_text(source)
        assert fake_backend.greedy_calls == [[source]]
        assert result.report.retried == 1
        assert "https://example.com" in result.text

    def test_retry_that_corrupts_a_url_is_rejected(self, translator, fake_backend):
        source = "Please visit https://example.com/a_b now."
        # First pass drops the placeholder; the retry mangles the real URL.
        fake_backend.overrides = {
            "Please visit #1# now.": "कृपया अभी जाएँ।",
        }
        fake_backend.greedy_overrides = {
            source: "कृपया अभी https://example.com/A-B पर जाएँ।",
        }
        result = translator.translate_text(source)
        # Rather than publish a broken link, the English is kept.
        assert result.text == source
        assert result.report.failed == 1

    def test_protection_can_be_disabled(self, fake_backend):
        translator = Translator(fake_backend, Options(protect_entities=False))
        translator.translate_text("Visit https://example.com now.")
        assert "https://example.com" in fake_backend.translated_texts[0]


class TestCaching:
    def test_repeated_sentences_are_translated_once(self, fake_backend, translator):
        translator.translate_text("Same line.\nSame line.\nSame line.")
        assert len(fake_backend.translated_texts) == 1

    def test_cache_is_reused_across_calls(self, fake_backend, translator):
        translator.translate_text("Hello there.")
        translator.translate_text("Hello there.")
        assert len(fake_backend.translated_texts) == 1

    def test_clearing_the_cache_forces_a_retranslation(self, fake_backend, translator):
        translator.translate_text("Hello there.")
        translator.clear_cache()
        translator.translate_text("Hello there.")
        assert len(fake_backend.translated_texts) == 2

    def test_cache_is_bounded(self, fake_backend):
        translator = Translator(fake_backend, Options(cache_size=4))
        translator.translate_text("\n".join("Line %d here." % i for i in range(20)))
        assert len(translator._cache) == 4


class TestBatching:
    def test_batches_respect_the_configured_size(self, fake_backend):
        translator = Translator(fake_backend, Options(max_batch_size=3))
        translator.translate_text("\n".join("Line %d here." % i for i in range(7)))
        assert [len(batch) for batch in fake_backend.calls] == [3, 3, 1]

    def test_progress_reaches_the_total(self, translator):
        seen = []
        translator.translate_text(
            "\n".join("Line %d here." % i for i in range(5)),
            progress=lambda done, total: seen.append((done, total)),
        )
        assert seen[0][0] == 0
        assert seen[-1] == (5, 5)


class TestFallbacks:
    def test_degenerate_output_keeps_the_english(self, fake_backend):
        source = "This is a normal sentence."
        loop = "शब्द " * 40
        fake_backend.overrides = {source: loop}
        fake_backend.greedy_overrides = {source: loop}
        translator = Translator(fake_backend)
        result = translator.translate_text(source)
        assert result.text == source
        assert result.report.failed == 1
        assert result.report.warnings

    def test_english_echo_is_rejected(self, fake_backend):
        source = "This is a normal sentence."
        fake_backend.overrides = {source: source}
        fake_backend.greedy_overrides = {source: source}
        translator = Translator(fake_backend)
        result = translator.translate_text(source)
        assert result.text == source
        assert result.report.failed == 1

    def test_retry_result_is_used_when_it_is_good(self, fake_backend):
        source = "This is a normal sentence."
        fake_backend.overrides = {source: "शब्द " * 40}
        fake_backend.greedy_overrides = {source: "एक सामान्य वाक्य।"}
        translator = Translator(fake_backend)
        result = translator.translate_text(source)
        assert result.text == "एक सामान्य वाक्य।"
        assert result.report.retried == 1
        assert result.report.failed == 0

    def test_empty_model_output_keeps_the_english(self, fake_backend):
        source = "This is a normal sentence."
        fake_backend.overrides = {source: ""}
        fake_backend.greedy_overrides = {source: ""}
        translator = Translator(fake_backend)
        result = translator.translate_text(source)
        assert result.text == source

    def test_short_input_may_stay_in_latin(self, fake_backend):
        # "OK" is too short to demand Devanagari.
        fake_backend.overrides = {"OK": "OK"}
        fake_backend.greedy_overrides = {"OK": "OK"}
        translator = Translator(fake_backend)
        result = translator.translate_text("OK")
        assert result.text == "OK"
        assert result.report.failed == 0

    def test_devanagari_check_can_be_disabled(self, fake_backend):
        source = "This is a normal sentence."
        fake_backend.overrides = {source: "yeh ek vaakya hai"}
        translator = Translator(fake_backend, Options(expect_devanagari=False))
        result = translator.translate_text(source)
        assert result.text == "yeh ek vaakya hai"


class TestCancellation:
    def test_cancel_before_the_first_batch(self, translator):
        event = threading.Event()
        event.set()
        with pytest.raises(TranslationCancelled):
            translator.translate_text("A sentence here.", cancel=event)


class TestHeuristics:
    @pytest.mark.parametrize(
        "output",
        [
            "",
            "   ",
            "शब्द शब्द शब्द शब्द शब्द शब्द",
            "एक दो एक दो एक दो एक दो",
            "क " * 30,
        ],
    )
    def test_detects_degenerate_output(self, output):
        assert is_degenerate("A short source sentence.", output)

    @pytest.mark.parametrize(
        "output",
        [
            "यह एक सामान्य वाक्य है।",
            "नमस्ते",
            "मैंने कल बाज़ार से दो किताबें खरीदीं।",
        ],
    )
    def test_accepts_normal_output(self, output):
        assert not is_degenerate("A short source sentence.", output)

    def test_untranslated_detection(self):
        assert looks_untranslated("Hello world", "Hello world")
        assert not looks_untranslated("Hello world", "नमस्ते दुनिया")
        # Too short to judge.
        assert not looks_untranslated("OK", "OK")
