"""Sentence splitting and layout preservation."""

from __future__ import annotations

import pytest

from entohin import segmenter


class TestSplitSentences:
    def test_simple_sentences(self):
        assert segmenter.split_sentences("One. Two. Three.") == [
            "One. ", "Two. ", "Three.",
        ]

    def test_question_and_exclamation(self):
        assert segmenter.split_sentences("Really? Yes! Fine.") == [
            "Really? ", "Yes! ", "Fine.",
        ]

    @pytest.mark.parametrize(
        "text",
        [
            "Mr. Smith arrived late.",
            "Dr. Rao and Prof. Iyer met.",
            "The value is 3.14 exactly.",
            "Ship it to the U.S.A. office.",
            "Costs 10.50 per unit.",
            "See Fig. 2 for details.",
            "J. R. R. Tolkien wrote it.",
        ],
    )
    def test_does_not_split(self, text):
        assert segmenter.split_sentences(text) == [text]

    def test_lower_case_continuation_is_not_a_boundary(self):
        assert segmenter.split_sentences("Apples, oranges etc. are fruit.") == [
            "Apples, oranges etc. are fruit."
        ]

    def test_quotes_and_brackets_close_the_sentence(self):
        assert segmenter.split_sentences('He said "stop." Then he left.') == [
            'He said "stop." ', "Then he left.",
        ]

    def test_danda_is_a_boundary(self):
        assert segmenter.split_sentences("पहला वाक्य। दूसरा वाक्य।") == [
            "पहला वाक्य। ", "दूसरा वाक्य।",
        ]

    @pytest.mark.parametrize(
        "text",
        [
            "One. Two. Three.",
            "Mr. Smith arrived late. He was tired.",
            "No terminator here",
            "Really?! Wow... okay then.",
            "   leading and trailing   ",
            "",
        ],
    )
    def test_pieces_rejoin_exactly(self, text):
        assert "".join(segmenter.split_sentences(text)) == text


class TestSplitLine:
    @pytest.mark.parametrize(
        "line,prefix,body",
        [
            ("    indented text", "    ", "indented text"),
            ("- a bullet", "- ", "a bullet"),
            ("* another bullet", "* ", "another bullet"),
            ("1. numbered item", "1. ", "numbered item"),
            ("2) other numbering", "2) ", "other numbering"),
            ("  • unicode bullet", "  • ", "unicode bullet"),
            ("## Heading", "## ", "Heading"),
            ("no marker", "", "no marker"),
        ],
    )
    def test_marker_is_kept_out_of_the_body(self, line, prefix, body):
        result = segmenter.split_line(line)
        assert result.prefix == prefix
        assert result.body == body

    def test_trailing_whitespace_preserved(self):
        result = segmenter.split_line("text   ")
        assert result.trailing == "   "
        assert result.prefix + result.body + result.trailing == "text   "

    @pytest.mark.parametrize(
        "line",
        ["", "   ", "42", "-----", "1234.56", "!!!", "\t"],
    )
    def test_lines_without_letters_are_not_translatable(self, line):
        assert not segmenter.split_line(line).translatable


class TestParse:
    def test_blank_lines_produce_no_segments(self):
        doc = segmenter.parse("Hello.\n\n\nWorld.")
        assert len(doc.segments) == 2
        assert [s.text for s in doc.segments] == ["Hello.", "World."]

    def test_render_without_translation_returns_the_original(self):
        text = "  - First item.\n\n2. Second item is longer. It has two.\n42\n"
        doc = segmenter.parse(text)
        for segment in doc.segments:
            segment.translated = segment.text
        assert doc.render() == text

    def test_render_substitutes_translations_in_place(self):
        doc = segmenter.parse("- Hello. World.")
        for index, segment in enumerate(doc.segments):
            segment.translated = "T%d" % index
        assert doc.render() == "- T0T1"

    def test_numeric_lines_are_passed_through(self):
        doc = segmenter.parse("Total\n42\n3.14")
        assert [s.text for s in doc.segments] == ["Total"]


class TestIterBatches:
    def test_chunks(self):
        assert list(segmenter.iter_batches([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]

    def test_zero_size_yields_everything(self):
        assert list(segmenter.iter_batches([1, 2, 3], 0)) == [[1, 2, 3]]

    def test_empty(self):
        assert list(segmenter.iter_batches([], 4)) == []
