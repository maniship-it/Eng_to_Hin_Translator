"""Reading text files saved in the encodings Windows produces."""

from __future__ import annotations

import codecs

import pytest

from entohin import textio

SAMPLE = "Hello there. This is a test.\nSecond line."


class TestDetectEncoding:
    @pytest.mark.parametrize(
        "encoding,expected",
        [
            ("utf-8-sig", "utf-8-sig"),
            ("utf-16", "utf-16"),
            ("utf-16-le", "utf-16-le"),
            ("utf-16-be", "utf-16-be"),
            ("utf-32", "utf-32"),
        ],
    )
    def test_detects_bom_and_utf16_shapes(self, encoding, expected):
        assert textio.detect_encoding(SAMPLE.encode(encoding)) == expected

    def test_plain_ascii_is_utf8(self):
        assert textio.detect_encoding(b"plain ascii") == "utf-8"

    def test_empty_input(self):
        assert textio.detect_encoding(b"") == "utf-8"


class TestDecode:
    @pytest.mark.parametrize(
        "encoding",
        ["utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "utf-32", "cp1252"],
    )
    def test_round_trip(self, encoding):
        assert textio.decode(SAMPLE.encode(encoding)) == SAMPLE

    def test_utf16_is_not_mistaken_for_cp1252(self):
        """The bug this module exists to prevent."""
        decoded = textio.decode(SAMPLE.encode("utf-16"))
        assert decoded == SAMPLE
        assert "\x00" not in decoded

    def test_devanagari_round_trip(self):
        text = "यह एक परीक्षण वाक्य है।"
        for encoding in ("utf-8", "utf-8-sig", "utf-16"):
            assert textio.decode(text.encode(encoding)) == text

    def test_windows_1252_accents(self):
        text = "Café naïve résumé"
        assert textio.decode(text.encode("cp1252")) == text

    def test_bom_is_stripped(self):
        assert not textio.decode(codecs.BOM_UTF8 + b"abc").startswith("﻿")


class TestReadWrite:
    @pytest.mark.parametrize(
        "encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-16-le", "cp1252"]
    )
    def test_read_text_file(self, tmp_path, encoding):
        path = tmp_path / "sample.txt"
        path.write_bytes(SAMPLE.encode(encoding))
        assert textio.read_text_file(path) == SAMPLE

    def test_crlf_is_normalised(self, tmp_path):
        path = tmp_path / "crlf.txt"
        path.write_bytes(b"one\r\ntwo\r\nthree")
        assert textio.read_text_file(path) == "one\ntwo\nthree"

    def test_lone_cr_is_normalised(self, tmp_path):
        path = tmp_path / "cr.txt"
        path.write_bytes(b"one\rtwo")
        assert textio.read_text_file(path) == "one\ntwo"

    def test_missing_file_returns_none(self, tmp_path):
        assert textio.read_text_file(tmp_path / "absent.txt") is None

    def test_directory_returns_none(self, tmp_path):
        assert textio.read_text_file(tmp_path) is None

    def test_write_uses_bom_and_crlf(self, tmp_path):
        path = tmp_path / "out.txt"
        textio.write_text_file(path, "एक\nदो")
        data = path.read_bytes()
        assert data.startswith(codecs.BOM_UTF8)
        assert b"\r\n" in data

    def test_write_then_read_round_trip(self, tmp_path):
        path = tmp_path / "out.txt"
        textio.write_text_file(path, SAMPLE)
        assert textio.read_text_file(path) == SAMPLE
