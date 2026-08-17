"""The hand-built Windows .ico must be a structurally valid icon."""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import make_icon  # noqa: E402

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(scope="module")
def icon_bytes() -> bytes:
    return make_icon.ico()


def _entries(data: bytes):
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0 and kind == 1
    for index in range(count):
        yield struct.unpack("<BBBBHHII", data[6 + 16 * index:22 + 16 * index])


class TestPng:
    def test_signature_and_terminator(self):
        data = make_icon.png(32)
        assert data.startswith(PNG_SIGNATURE)
        assert data[-8:-4] == b"IEND"

    def test_header_declares_the_right_size(self):
        data = make_icon.png(48)
        width, height = struct.unpack(">II", data[16:24])
        assert (width, height) == (48, 48)

    def test_pixel_data_decompresses_to_the_expected_length(self):
        size = 16
        data = make_icon.png(size)
        start = data.index(b"IDAT") + 4
        length = struct.unpack(">I", data[start - 8:start - 4])[0]
        raw = zlib.decompress(data[start:start + length])
        # Each row is one filter byte plus RGBA per pixel.
        assert len(raw) == size * (1 + size * 4)


class TestIco:
    def test_every_declared_size_is_present(self, icon_bytes):
        sizes = {(w or 256) for w, _, _, _, _, _, _, _ in _entries(icon_bytes)}
        assert sizes == set(make_icon.SIZES)

    def test_each_image_is_a_valid_png(self, icon_bytes):
        for width, _, _, _, _, _, size, offset in _entries(icon_bytes):
            blob = icon_bytes[offset:offset + size]
            assert blob.startswith(PNG_SIGNATURE), width
            assert blob[-8:-4] == b"IEND", width

    def test_offsets_do_not_overlap(self, icon_bytes):
        spans = sorted((offset, offset + size)
                       for *_, size, offset in _entries(icon_bytes))
        for (_, end), (start, _) in zip(spans, spans[1:]):
            assert end <= start

    def test_the_declared_bit_depth_is_32(self, icon_bytes):
        for *_, bpp, size, offset in _entries(icon_bytes):
            assert bpp == 32

    def test_256_is_recorded_as_zero(self, icon_bytes):
        """The ICO format stores 256 as 0 in a single byte."""
        widths = [w for w, *_ in _entries(icon_bytes)]
        assert 0 in widths

    def test_writing_the_file(self, tmp_path, monkeypatch):
        destination = tmp_path / "installer" / "anuvad.ico"
        monkeypatch.setattr(make_icon, "__file__",
                            str(tmp_path / "tools" / "make_icon.py"))
        assert make_icon.main() == 0
        assert destination.is_file()
        assert destination.stat().st_size > 1000


class TestRendering:
    def test_corners_are_transparent(self):
        size = 32
        raw = make_icon.render(size)
        stride = 1 + size * 4
        # First pixel of the first row, skipping the filter byte.
        assert raw[1:5] == b"\x00\x00\x00\x00"

    def test_the_centre_is_opaque(self):
        size = 32
        raw = make_icon.render(size)
        stride = 1 + size * 4
        middle = (size // 2) * stride + 1 + (size // 2) * 4
        assert raw[middle + 3] == 0xFF
