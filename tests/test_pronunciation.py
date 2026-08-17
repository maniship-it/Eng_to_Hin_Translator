"""Turning ARPAbet into IPA and readable respellings."""

from __future__ import annotations

import pytest

from anuvad import pronunciation as p


class TestPhoneParsing:
    @pytest.mark.parametrize(
        "phone,base,stress",
        [("AH1", "AH", 1), ("AH0", "AH", 0), ("OW2", "OW", 2),
         ("T", "T", 0), ("NG", "NG", 0)],
    )
    def test_base_and_stress(self, phone, base, stress):
        assert p.base_phone(phone) == base
        assert p.stress_of(phone) == stress


class TestSyllabify:
    def test_no_phone_is_ever_lost(self):
        """The bug this guards against silently dropped coda consonants."""
        for arpabet in [
            "S AE1 NG K SH AH0 N",          # sanction
            "K AH0 M P Y UW1 T ER0",        # computer
            "T R AE0 N Z L EY1 T",          # translate
            "S T R EH1 NG K TH",            # strength
            "G AH1 V ER0 M AH0 N T",        # government
        ]:
            phones = arpabet.split()
            rebuilt = [ph for s in p.syllabify(phones) for ph in s.phones]
            assert rebuilt == phones, arpabet

    @pytest.mark.parametrize(
        "arpabet,count",
        [
            ("R AH1 N", 1),
            ("HH AE1 P IY0", 2),
            ("G AH1 V ER0 M AH0 N T", 3),
            ("N OW2 T AH0 F AH0 K EY1 SH AH0 N", 5),
        ],
    )
    def test_syllable_counts(self, arpabet, count):
        assert len(p.syllabify(arpabet.split())) == count

    def test_a_legal_cluster_opens_the_next_syllable(self):
        # computer: the P Y cluster starts the stressed syllable.
        syllables = p.syllabify("K AH0 M P Y UW1 T ER0".split())
        assert [s.phones for s in syllables] == [
            ["K", "AH0", "M"], ["P", "Y", "UW1"], ["T", "ER0"],
        ]

    def test_an_illegal_cluster_closes_the_previous_syllable(self):
        # sanction: NG K cannot open a syllable, so they close the first one.
        syllables = p.syllabify("S AE1 NG K SH AH0 N".split())
        assert [s.phones for s in syllables] == [
            ["S", "AE1", "NG", "K"], ["SH", "AH0", "N"],
        ]

    def test_a_word_with_no_vowel(self):
        assert len(p.syllabify(["M"])) == 1

    def test_empty_input(self):
        assert p.syllabify([]) == []


class TestRendering:
    @pytest.mark.parametrize(
        "arpabet,ipa,respelling",
        [
            ("G AH1 V ER0 M AH0 N T", "ˈɡʌ.vɚ.mənt", "GUH-vur-muhnt"),
            ("S AE1 NG K SH AH0 N", "ˈsæŋk.ʃən", "SANGK-shuhn"),
            ("HH AH0 L OW1", "hə.ˈloʊ", "huh-LOH"),
            ("W AO1 T ER0", "ˈwɔ.tɚ", "WAW-tur"),
        ],
    )
    def test_known_words(self, arpabet, ipa, respelling):
        result = p.analyse(arpabet)
        assert result.ipa == ipa
        assert result.respelling == respelling

    def test_unstressed_ah_becomes_schwa(self):
        assert "ə" in p.to_ipa("K AH0 M P Y UW1 T ER0".split())

    def test_stressed_ah_stays_open(self):
        assert "ʌ" in p.to_ipa("R AH1 N".split())

    def test_primary_and_secondary_stress_marks(self):
        ipa = p.to_ipa("N OW2 T AH0 F AH0 K EY1 SH AH0 N".split())
        assert "ˌ" in ipa and "ˈ" in ipa

    def test_a_single_syllable_is_not_shouted(self):
        assert p.to_respelling("R AH1 N".split()) == "ruhn"

    def test_the_stressed_syllable_is_capitalised(self):
        respelling = p.to_respelling("HH AE1 P IY0".split())
        assert respelling.split("-")[0].isupper()

    def test_empty_input_renders_as_nothing(self):
        assert p.analyse("").is_empty
        assert p.analyse("").ipa == ""


class TestCmudictParsing:
    SAMPLE = [
        ";;; a comment line",
        "government G AH1 V ER0 M AH0 N T",
        "record R EH1 K ER0 D",
        "record(2) R IH0 K AO1 R D",
        "hello HH AH0 L OW1  # greeting",
        "",
    ]

    def test_entries_are_read(self):
        table = p.parse_cmudict(self.SAMPLE)
        assert table["government"] == "G AH1 V ER0 M AH0 N T"

    def test_comments_are_skipped(self):
        assert ";;;" not in "".join(p.parse_cmudict(self.SAMPLE))

    def test_alternative_pronunciations_are_skipped(self):
        table = p.parse_cmudict(self.SAMPLE)
        assert "record(2)" not in table
        assert table["record"] == "R EH1 K ER0 D"

    def test_trailing_comments_are_stripped(self):
        assert p.parse_cmudict(self.SAMPLE)["hello"] == "HH AH0 L OW1"

    def test_lookup_finds_variants(self):
        table = {"post office": "P OW1 S T AO1 F IH0 S"}
        found = p.lookup("post-office", table)
        assert found is not None
        assert found[0] == "post office"

    def test_lookup_misses_cleanly(self):
        assert p.lookup("zzzznotaword", {}) is None
