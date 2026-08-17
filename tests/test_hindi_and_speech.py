"""Devanagari folding, and the Windows speech bridge."""

from __future__ import annotations

import pytest

from anuvad import hindi, speech


class TestNormalize:
    def test_nukta_variants_fold_together(self):
        assert hindi.normalize("मंज़ूरी") == hindi.normalize("मंजूरी")

    @pytest.mark.parametrize(
        "with_nukta,without",
        [("क़लम", "कलम"), ("ग़ज़ल", "गजल"), ("फ़ाइल", "फाइल"), ("ज़िला", "जिला")],
    )
    def test_precomposed_nukta_letters(self, with_nukta, without):
        assert hindi.normalize(with_nukta) == hindi.normalize(without)

    def test_combining_nukta_is_dropped(self):
        # क + combining nukta should fold to plain क.
        assert hindi.normalize("क" + "़") == hindi.normalize("क")

    def test_candrabindu_folds_to_anusvara(self):
        assert hindi.normalize("हँसी") == hindi.normalize("हंसी")

    def test_zero_width_characters_are_removed(self):
        assert hindi.normalize("सर‍कार") == hindi.normalize("सरकार")
        assert hindi.normalize("सर‌cकार".replace("c", "")) == \
               hindi.normalize("सरकार")

    def test_punctuation_and_danda_are_removed(self):
        assert hindi.normalize("सरकार।") == hindi.normalize("सरकार")

    def test_whitespace_is_collapsed(self):
        assert hindi.normalize("  छोड़   देना  ") == hindi.normalize("छोड़ देना")

    def test_empty_input(self):
        assert hindi.normalize("") == ""
        assert hindi.normalize(None) == ""

    def test_different_words_stay_different(self):
        assert hindi.normalize("सरकार") != hindi.normalize("अधिकार")


class TestDisplay:
    def test_tilde_becomes_a_space(self):
        assert hindi.display("छोड़~देना") == "छोड़ देना"

    def test_display_keeps_the_nukta(self):
        """Folding is for matching; what is shown stays as written."""
        assert "़" in hindi.display("मंज़ूरी") or hindi.display("मंज़ूरी") == "मंज़ूरी"

    def test_zero_width_is_still_removed(self):
        assert hindi.display("सर‍कार") == "सरकार"


class TestDetection:
    def test_devanagari_is_detected(self):
        assert hindi.has_devanagari("सरकार")
        assert hindi.has_devanagari("word सरकार")

    def test_latin_is_not(self):
        assert not hindi.has_devanagari("government")
        assert not hindi.has_devanagari("")


class TestSplitTerms:
    def test_semicolons_and_commas(self):
        assert hindi.split_terms("मंजूरी; स्वीकृति") == ["मंजूरी", "स्वीकृति"]
        assert hindi.split_terms("एक, दो") == ["एक", "दो"]

    def test_blanks_are_dropped(self):
        assert hindi.split_terms("मंजूरी;;") == ["मंजूरी"]

    def test_empty(self):
        assert hindi.split_terms("") == []


class TestSpeech:
    """The command is built everywhere; only Windows can actually run it."""

    def test_command_speaks_the_text(self):
        command = speech.build_command("government")
        joined = " ".join(command)
        assert "System.Speech" in joined
        assert "government" in joined

    def test_single_quotes_are_escaped(self):
        command = speech.build_command("it's fine")
        assert "it''s fine" in " ".join(command)

    def test_rate_is_clamped(self):
        assert "$s.Rate = 10;" in " ".join(speech.build_command("x", rate=99))
        assert "$s.Rate = -10;" in " ".join(speech.build_command("x", rate=-99))

    def test_a_voice_is_selected_defensively(self):
        joined = " ".join(speech.build_command("x", voice="Microsoft David"))
        assert "SelectVoice" in joined
        assert "try {" in joined  # a missing voice must not abort the command

    def test_no_voice_means_no_selection(self):
        assert "SelectVoice" not in " ".join(speech.build_command("x"))

    def test_powershell_runs_without_a_profile_or_prompt(self):
        command = speech.build_command("x")
        assert "-NoProfile" in command
        assert "-NonInteractive" in command

    def test_empty_text_is_refused_without_touching_the_system(self):
        result = speech.speak("   ")
        assert not result.ok
        assert "nothing to speak" in result.message.lower()

    def test_availability_matches_the_platform(self, monkeypatch):
        monkeypatch.setattr(speech.os, "name", "posix")
        assert not speech.is_available()
        assert "Windows" in speech.unavailable_reason()

    def test_speaking_off_windows_explains_itself(self, monkeypatch):
        monkeypatch.setattr(speech.os, "name", "posix")
        result = speech.speak("hello")
        assert not result.ok
        assert "Windows" in result.message

    def test_missing_powershell_is_reported(self, monkeypatch):
        monkeypatch.setattr(speech.os, "name", "nt")
        monkeypatch.setattr(speech.shutil, "which", lambda name: None)
        assert not speech.is_available()
        assert "PowerShell" in speech.unavailable_reason()

    def test_async_speech_reports_back(self):
        results = []
        thread = speech.speak_async("hello", done=results.append)
        thread.join(timeout=30)
        assert results, "the callback should always run"
        assert isinstance(results[0], speech.SpeechResult)
