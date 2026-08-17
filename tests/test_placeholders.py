"""Protecting and restoring non-translatable spans."""

from __future__ import annotations

import pytest

from entohin import placeholders


class TestProtect:
    @pytest.mark.parametrize(
        "text,value",
        [
            ("Go to https://example.com/a_b now", "https://example.com/a_b"),
            ("Mail me at a.b+c@example.co.in today", "a.b+c@example.co.in"),
            ("Open C:\\Users\\me\\file.txt please", "C:\\Users\\me\\file.txt"),
            ("Share \\\\server\\folder with us", "\\\\server\\folder"),
            ("Run `pip install foo` first", "`pip install foo`"),
            ("Visit www.example.org/page today", "www.example.org/page"),
            ("Use {user_name} in the template", "{user_name}"),
            ("Wrap it in <b> tags", "<b>"),
        ],
    )
    def test_extracts_the_span(self, text, value):
        result = placeholders.protect(text)
        assert result.values == [value]
        assert "#1#" in result.text
        assert value not in result.text

    def test_multiple_spans_are_numbered_in_order(self):
        result = placeholders.protect("See https://a.com and mail b@c.com now")
        assert result.values == ["https://a.com", "b@c.com"]
        assert "#1#" in result.text and "#2#" in result.text

    def test_plain_text_is_untouched(self):
        result = placeholders.protect("Just ordinary words here")
        assert result.values == []
        assert result.text == "Just ordinary words here"

    def test_overlapping_matches_do_not_double_protect(self):
        result = placeholders.protect("Read https://example.com/a@b.com/x now")
        assert len(result.values) == 1
        assert result.values[0].startswith("https://")

    @pytest.mark.parametrize(
        "text",
        ["https://example.com", "a@b.com", "  `code`  ", "C:\\temp\\x.txt"],
    )
    def test_placeholder_only_text_is_detected(self, text):
        assert placeholders.protect(text).is_placeholder_only

    def test_text_with_words_is_not_placeholder_only(self):
        assert not placeholders.protect("Visit https://example.com now").is_placeholder_only


class TestRestore:
    def test_round_trip(self):
        original = "Go to https://example.com/a_b now"
        protected = placeholders.protect(original)
        restored, ok = placeholders.restore(protected.text, protected.values)
        assert ok
        assert "https://example.com/a_b" in restored

    def test_tolerates_spaces_the_model_inserts(self):
        restored, ok = placeholders.restore("देखें # 1 # पर", ["https://a.com"])
        assert ok
        assert "https://a.com" in restored

    def test_missing_placeholder_is_reported(self):
        _, ok = placeholders.restore("मॉडल ने इसे गिरा दिया", ["https://a.com"])
        assert not ok

    def test_duplicated_placeholder_is_reported(self):
        _, ok = placeholders.restore("#1# और #1#", ["https://a.com"])
        assert not ok

    def test_out_of_range_placeholder_is_reported(self):
        _, ok = placeholders.restore("#1# और #9#", ["https://a.com"])
        assert not ok

    def test_no_values_means_nothing_to_check(self):
        restored, ok = placeholders.restore("सामान्य पाठ", [])
        assert ok
        assert restored == "सामान्य पाठ"

    def test_spacing_before_punctuation_is_tidied(self):
        restored, ok = placeholders.restore("देखें #1# ।", ["https://a.com"])
        assert ok
        assert restored.endswith("।")
        assert " ।" not in restored
