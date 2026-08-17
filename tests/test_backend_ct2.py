"""Integration tests against a real CTranslate2 model.

The model is built locally with random weights, so its output is meaningless.
These tests check the wiring -- that tokenising, decoding, batching and the
safety fallbacks all work against the real library -- not translation quality.
"""

from __future__ import annotations

import pytest

from entohin.translator import CTranslate2Backend, Options, Translator

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def backend(ct2_model_dir):
    instance = CTranslate2Backend.from_dir(ct2_model_dir, Options(beam_size=2))
    yield instance
    instance.close()


class TestBackend:
    def test_loads_and_reports_its_compute_type(self, backend):
        assert backend.compute_type

    def test_translates_a_batch_and_returns_one_string_each(self, backend):
        outputs = backend.translate(
            ["Hello there.", "This is a test.", "Third sentence."], Options()
        )
        assert len(outputs) == 3
        assert all(isinstance(text, str) for text in outputs)

    def test_empty_batch(self, backend):
        assert backend.translate([], Options()) == []

    def test_greedy_mode_runs(self, backend):
        assert len(backend.translate(["Hello there."], Options(), greedy=True)) == 1

    def test_long_input_does_not_hang_or_crash(self, backend):
        sentence = "This is a fairly long sentence with plenty of words in it."
        outputs = backend.translate([sentence * 3], Options())
        assert len(outputs) == 1


class TestEndToEnd:
    """With random weights every output is junk, so the engine must reject it."""

    def test_document_structure_survives(self, ct2_model_dir):
        translator = Translator(
            CTranslate2Backend.from_dir(ct2_model_dir), Options(beam_size=2)
        )
        text = (
            "Hello there. This is a test.\n"
            "Visit https://example.com/a_b for details.\n"
            "\n"
            "  - Read the file C:\\Users\\me\\notes.txt today.\n"
            "1. Numbers like 3.14 and Mr. Smith should not split.\n"
            "42\n"
        )
        result = translator.translate_text(text)
        translator.close()

        lines = result.text.split("\n")
        assert len(lines) == len(text.split("\n"))
        assert lines[2] == ""
        assert lines[3].startswith("  - ")
        assert lines[4].startswith("1. ")
        assert lines[5] == "42"

    def test_junk_output_is_never_shown(self, ct2_model_dir):
        """A model producing nonsense must leave the English in place."""
        translator = Translator(
            CTranslate2Backend.from_dir(ct2_model_dir), Options(beam_size=2)
        )
        source = "The meeting will start at nine o'clock tomorrow morning."
        result = translator.translate_text(source)
        translator.close()

        # Random weights cannot produce Devanagari, so the guard must fire.
        assert result.text == source
        assert result.report.failed == 1
        assert result.report.warnings

    def test_urls_are_never_corrupted(self, ct2_model_dir):
        translator = Translator(
            CTranslate2Backend.from_dir(ct2_model_dir), Options(beam_size=2)
        )
        result = translator.translate_text(
            "Please download it from https://example.com/path?a=1&b=2 today."
        )
        translator.close()
        assert "https://example.com/path?a=1&b=2" in result.text

    def test_progress_callback_is_driven_to_completion(self, ct2_model_dir):
        translator = Translator(
            CTranslate2Backend.from_dir(ct2_model_dir), Options(beam_size=1)
        )
        seen = []
        translator.translate_text(
            "\n".join("Sentence number %d here." % i for i in range(12)),
            progress=lambda done, total: seen.append((done, total)),
        )
        translator.close()
        assert seen[-1][0] == seen[-1][1] > 0
