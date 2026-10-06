"""The app icon's renderer writes valid PNGs of the ComplianceWatch mark: a dark rounded square
with a white tick that stays legible at 16 px, transparent around it, at every iconset size."""

import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shell"))
import app_icon

Pixels = list[list[tuple[int, int, int, int]]]


def decode(data: bytes) -> tuple[int, int, Pixels]:
    """A PNG of 8-bit RGBA rows with filter 0, as this renderer writes it, checked chunk by
    chunk."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, width, height = 8, b"", 0, 0
    kinds = []
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])
        assert crc == zlib.crc32(kind + body) & 0xFFFFFFFF, kind
        kinds.append(kind)
        if kind == b"IHDR":
            width, height, depth, colour, _, _, _ = struct.unpack(">IIBBBBB", body)
            assert (depth, colour) == (8, 6)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    assert kinds[0] == b"IHDR"
    assert kinds[-1] == b"IEND"
    raw = zlib.decompress(idat)
    stride = width * 4 + 1
    assert len(raw) == height * stride
    rows: Pixels = []
    for y in range(height):
        row = raw[y * stride : (y + 1) * stride]
        assert row[0] == 0
        rows.append([tuple(row[1 + x * 4 : 5 + x * 4]) for x in range(width)])  # type: ignore[misc]
    return width, height, rows


@pytest.mark.parametrize("size", [16, 32, 64, 128])
def test_each_size_is_the_mark_on_a_transparent_canvas(size: int) -> None:
    width, height, rows = decode(app_icon.png(size, app_icon.render(size)))
    assert (width, height) == (size, size)
    for x, y in ((0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)):
        assert rows[y][x][3] == 0, (x, y)  # the rounded corners are see-through
    below_tick = rows[int(size * 0.84)][size // 2]
    assert below_tick[3] == 255
    assert max(below_tick[:3]) < 70  # the dark square
    white = sum(1 for row in rows for r, g, b, a in row if a == 255 and min(r, g, b) > 200)
    assert white >= size * size * 0.04  # the tick
    top_row = rows[int(size * 0.3)]
    assert all(min(pixel[:3]) < 200 for pixel in top_row[: size // 4])  # no tick at the left top


def test_the_tick_stays_two_pixels_wide_at_16_px() -> None:
    shape = app_icon.geometry(16)
    assert shape["stroke"] >= 1.8
    assert shape["inset"] == 1.0
    big = app_icon.geometry(1024)
    assert big["side"] == 824
    assert big["shadow"] > 0
    _, _, rows = decode(app_icon.png(16, app_icon.render(16)))
    bright = [(x, y) for y, row in enumerate(rows) for x, p in enumerate(row) if min(p[:3]) > 180]
    columns = {x for x, _ in bright}
    assert len(columns) >= 7  # the tick spans most of the square


def test_large_sizes_have_a_soft_shadow_below() -> None:
    size = 256
    shape = app_icon.geometry(size)
    _, _, rows = decode(app_icon.png(size, app_icon.render(size)))
    below = rows[int(size - shape["inset"] + shape["shadow_dy"])][size // 2]
    assert 0 < below[3] < 128  # a shadow, not the square
    above = rows[int(shape["inset"] - shape["shadow_dy"])][size // 2]
    assert above[3] < below[3]


def test_the_iconset_has_every_file_at_its_size(tmp_path: Path) -> None:
    folder = tmp_path / "AppIcon.iconset"
    written = app_icon.write_iconset(folder)
    assert [path.name for path in written] == [name for name, _ in app_icon.ICONSET]
    for name, size in app_icon.ICONSET:
        width, height, _ = decode((folder / name).read_bytes())
        assert (width, height) == (size, size), name
    assert (folder / "icon_16x16@2x.png").read_bytes() == (folder / "icon_32x32.png").read_bytes()


def test_it_wants_an_iconset_folder(tmp_path: Path) -> None:
    assert app_icon.main([str(tmp_path / "icons")]) == 2
    assert app_icon.main([]) == 2
    assert app_icon.main([str(tmp_path / "AppIcon.iconset")]) == 0
