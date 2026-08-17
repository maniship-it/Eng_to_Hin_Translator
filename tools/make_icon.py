"""Generate the application icon without needing an image library.

Writes a multi-resolution Windows .ico built from PNGs encoded here by hand,
so the build has no extra dependency. The mark is a marigold double arrow --
the two directions Anuvad Plus translates -- on the deep indigo of the app.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import List, Tuple

SIZES = (16, 24, 32, 48, 64, 128, 256)

INDIGO = (0x2F, 0x4B, 0x8C)
INDIGO_DEEP = (0x1B, 0x2C, 0x52)
MARIGOLD = (0xE0, 0xAB, 0x5B)
WHITE = (0xFF, 0xFF, 0xFF)


def _rounded(x: float, y: float, size: float, radius: float) -> bool:
    """True if (x, y) is inside a rounded square filling ``size``."""
    left, top, right, bottom = radius, radius, size - radius, size - radius
    cx = min(max(x, left), right)
    cy = min(max(y, top), bottom)
    return (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2


def _arrow_band(x: float, y: float, size: float, centre: float,
                pointing_right: bool) -> bool:
    """A chevron-tipped horizontal bar, drawn in normalised coordinates."""
    thickness = size * 0.085
    half = thickness / 2.0
    shaft_left, shaft_right = size * 0.26, size * 0.74

    if abs(y - centre) <= half and shaft_left <= x <= shaft_right:
        return True

    # The head: a chevron opening away from the direction of travel.
    tip = shaft_right if pointing_right else shaft_left
    depth = size * 0.13
    along = (tip - x) if pointing_right else (x - tip)
    if 0 <= along <= depth:
        spread = along * 1.05
        return abs(abs(y - centre) - spread) <= half * 1.25
    return False


def render(size: int) -> bytes:
    """Render one square icon as raw RGBA rows."""
    rows: List[bytes] = []
    radius = size * 0.22
    top_centre = size * 0.38
    bottom_centre = size * 0.62

    for py in range(size):
        row = bytearray()
        for px in range(size):
            x, y = px + 0.5, py + 0.5
            if not _rounded(x, y, size, radius):
                row += bytes((0, 0, 0, 0))
                continue

            # A soft vertical gradient across the tile.
            blend = y / size
            background = tuple(
                int(INDIGO[i] + (INDIGO_DEEP[i] - INDIGO[i]) * blend)
                for i in range(3)
            )

            if _arrow_band(x, y, size, top_centre, True):
                colour = MARIGOLD
            elif _arrow_band(x, y, size, bottom_centre, False):
                colour = WHITE
            else:
                colour = background
            row += bytes(colour) + b"\xff"
        rows.append(bytes(row))
    return b"".join(b"\x00" + row for row in rows)


def png(size: int) -> bytes:
    """Wrap rendered pixels in a minimal PNG."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(render(size), 9))
            + chunk(b"IEND", b""))


def ico(sizes=SIZES) -> bytes:
    """Assemble the PNGs into a Windows .ico."""
    images: List[Tuple[int, bytes]] = [(size, png(size)) for size in sizes]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size, 0 if size >= 256 else size,
            0, 0, 1, 32, len(data), offset,
        )
        blobs += data
        offset += len(data)
    return out + entries + blobs


def main() -> int:
    destination = Path(__file__).resolve().parents[1] / "installer" / "anuvad.ico"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(ico())
    print("Wrote %s (%.1f KB)" % (destination, destination.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
