"""The app icon's renderer writes valid PNGs of the ComplianceWatch Control mark, a white shield
with a blue tick on the brand's blue-to-teal squircle, legible at 16 px, transparent around it, at
every iconset size; and the window's icon.svg, the sidebar's mark and the shell's pages draw the
same shield."""

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


HERE = Path(__file__).resolve().parents[1]
SHIELD_PATH = "M32 10.5 48.5 16.2V31c0 10.6-6.9 18.5-16.5 22.3"
TICK_PATH = "m24.2 31.6 5.9 5.9 10-11.8"


def is_white(pixel: tuple[int, int, int, int]) -> bool:
    return pixel[3] == 255 and min(pixel[:3]) > 215


def is_tick(pixel: tuple[int, int, int, int]) -> bool:
    r, g, b, a = pixel
    return a == 255 and r < 90 and g < 120 and b > 170


@pytest.mark.parametrize("size", [16, 32, 64, 128])
def test_each_size_is_the_mark_on_a_transparent_canvas(size: int) -> None:
    width, height, rows = decode(app_icon.png(size, app_icon.render(size)))
    assert (width, height) == (size, size)
    for x, y in ((0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)):
        assert rows[y][x][3] == 0, (x, y)  # the rounded corners are see-through
    shape = app_icon.geometry(size)
    edge = int(shape["inset"] + shape["side"] * 0.12)
    for x, y in ((edge, size // 2), (size - 1 - edge, size // 2)):
        r, _, b, a = rows[y][x]
        assert a == 255
        assert b > r + 40, (x, y, rows[y][x])  # the blue-to-teal squircle beside the shield
    shield = sum(1 for row in rows for pixel in row if is_white(pixel))
    assert shield >= size * size * 0.12  # the white shield
    tick = sum(1 for row in rows for pixel in row if is_tick(pixel))
    assert tick >= max(size * size * 0.015, 5)  # the blue tick inside it
    top = rows[int(shape["inset"] + shape["side"] * 0.2)][size // 2]
    assert is_white(top) or min(top[:3]) > 180  # the shield reaches up to the middle of the top


def test_the_tick_stays_bold_at_16_and_32_px() -> None:
    assert app_icon.geometry(16)["tick"] >= 1.9
    assert app_icon.geometry(32)["tick"] >= 2.6
    assert app_icon.geometry(16)["inset"] == 1.0
    big = app_icon.geometry(1024)
    assert big["side"] == 824
    assert big["shadow"] > 0
    _, _, rows = decode(app_icon.png(16, app_icon.render(16)))
    tick = [(x, y) for y, row in enumerate(rows) for x, p in enumerate(row) if is_tick(p)]
    assert len({x for x, _ in tick}) >= 4  # the tick spans the shield
    assert len({y for _, y in tick}) >= 3


def test_large_sizes_have_a_soft_shadow_below() -> None:
    size = 256
    shape = app_icon.geometry(size)
    _, _, rows = decode(app_icon.png(size, app_icon.render(size)))
    below = rows[int(size - shape["inset"] + shape["shadow_dy"])][size // 2]
    assert 0 < below[3] < 128  # a shadow, not the square
    above = rows[int(shape["inset"] - shape["shadow_dy"])][size // 2]
    assert above[3] < below[3]


def test_the_shield_s_outline_is_closed_and_sharp_at_its_point() -> None:
    assert app_icon.shield_distance(32, 32) < -10  # inside
    assert app_icon.shield_distance(32, 10.5) == pytest.approx(0, abs=0.01)  # the top point
    assert app_icon.shield_distance(48.5, 24) == pytest.approx(0, abs=0.01)  # a side
    assert app_icon.shield_distance(32, 53.3) == pytest.approx(0, abs=0.05)  # the bottom point
    assert app_icon.shield_distance(32, 56) > 2.5  # below it
    assert app_icon.shield_distance(10, 30) == pytest.approx(5.5, abs=0.01)


def test_the_window_and_the_shell_draw_the_same_mark() -> None:
    for path in (
        HERE / "ui" / "icon.svg",
        HERE / "ui" / "icons.js",
        HERE / "shell" / "ControlApp.swift",
    ):
        text = path.read_text()
        assert SHIELD_PATH in text, path
        assert TICK_PATH in text, path
        for colour in ("#2563eb", "#0f766e", "#1d4ed8"):
            assert colour in text, (path, colour)


@pytest.mark.parametrize("style", sorted(app_icon.STYLES))
def test_the_alternates_draw_too(style: str) -> None:
    width, _, rows = decode(app_icon.png(64, app_icon.render(64, style)))
    assert width == 64
    assert rows[0][0][3] == 0
    assert rows[32][32][3] == 255


def test_the_iconset_has_every_file_at_its_size(tmp_path: Path) -> None:
    folder = tmp_path / "AppIcon.iconset"
    written = app_icon.write_iconset(folder)
    assert [path.name for path in written] == [name for name, _ in app_icon.ICONSET]
    for name, size in app_icon.ICONSET:
        width, height, _ = decode((folder / name).read_bytes())
        assert (width, height) == (size, size), name
    assert (folder / "icon_16x16@2x.png").read_bytes() == (folder / "icon_32x32.png").read_bytes()


def test_it_wants_an_iconset_folder_or_a_preview(tmp_path: Path) -> None:
    assert app_icon.main([str(tmp_path / "icons")]) == 2
    assert app_icon.main([]) == 2
    assert app_icon.main([str(tmp_path / "AppIcon.iconset")]) == 0
    assert app_icon.main(["--preview", str(tmp_path / "preview")]) == 0
    assert sorted(path.name for path in (tmp_path / "preview").iterdir()) == [
        "alternate-night-512.png",
        "alternate-outline-512.png",
        "mark-16.png",
        "mark-32.png",
        "mark-512.png",
    ]
