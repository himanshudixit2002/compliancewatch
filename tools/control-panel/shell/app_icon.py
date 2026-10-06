"""The app icon of ComplianceWatch Control, drawn in pure Python.

The ComplianceWatch mark (the web app's ``icon.svg``: a dark rounded square with a white tick) on
the macOS icon grid, with a soft shadow at the larger sizes. Each size is drawn at its own pixel
size, not scaled down from a big one, so the tick stays a clear two pixels wide at 16 px.

    python3 app_icon.py AppIcon.iconset     # the ten PNGs iconutil turns into AppIcon.icns

Standard library only (``zlib`` for the PNG), and Python 3.9 or later, so the installer can run
it with any Python on the Mac.
"""

from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path

ICONSET = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)
"""The files of an ``.iconset`` folder and their pixel sizes."""

TOP = (0x2C, 0x2C, 0x31)
BOTTOM = (0x10, 0x10, 0x12)
"""The square's fill, top to bottom: the brand's #171717, lit from above."""

TICK = (9.0, 17.0), (14.0, 22.0), (23.0, 11.0)
"""The tick of the brand mark, in its 32-unit box: M9 17 l5 5 9-11."""


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def _round_rect(px: float, py: float, half: float, centre: float, radius: float) -> float:
    """Signed distance from a point to a square of half side ``half`` around (centre, centre)
    with corners of ``radius``: negative inside."""
    qx = abs(px - centre) - (half - radius)
    qy = abs(py - centre) - (half - radius)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    return outside + min(max(qx, qy), 0.0) - radius


def _segment(px: float, py: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    h = _clamp(((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy))
    return math.hypot(px - ax - dx * h, py - ay - dy * h)


def geometry(size: int) -> dict[str, float]:
    """The icon's shapes at ``size`` pixels: the square, its corners, the tick and the shadow.

    From 128 px up it follows the macOS grid (an 824/1024 square); the small sizes fill more of
    the canvas and draw the tick a little larger and at least 1.8 px wide, to stay legible."""
    if size >= 128:
        inset = size * 100 / 1024
    elif size >= 64:
        inset = size * 0.07
    else:
        inset = size / 16
    side = size - 2 * inset
    small = size <= 32
    stroke = max(side * 3 / 32, 1.8 if small else 0.0)
    return {
        "size": float(size),
        "half": side / 2,
        "centre": size / 2,
        "radius": side * (0.2237 if not small else 0.2),
        "inset": inset,
        "side": side,
        "stroke": stroke,
        "tick_scale": 1.1 if small else 1.0,
        "shadow": 0.0 if size < 64 else size * 0.028,
        "shadow_dy": 0.0 if size < 64 else size * 0.012,
    }


def tick_points(shape: dict[str, float]) -> list[tuple[float, float]]:
    """The tick's three points in pixels, centred on the square."""
    inset, side, scale = shape["inset"], shape["side"], shape["tick_scale"]
    points = []
    for vx, vy in TICK:
        x = 16 + (vx - 16) * scale
        y = 16.5 + (vy - 16.5) * scale
        points.append((inset + x / 32 * side, inset + y / 32 * side))
    return points


def render(size: int) -> bytes:
    """The icon as straight-alpha RGBA rows, ``size`` x ``size``."""
    shape = geometry(size)
    half, centre, radius = shape["half"], shape["centre"], shape["radius"]
    stroke, blur, dy = shape["stroke"], shape["shadow"], shape["shadow_dy"]
    a, b, c = tick_points(shape)
    left = min(a[0], b[0], c[0]) - stroke
    right = max(a[0], b[0], c[0]) + stroke
    top = min(a[1], b[1], c[1]) - stroke
    bottom = max(a[1], b[1], c[1]) + stroke
    out = bytearray(size * size * 4)
    for y in range(size):
        py = y + 0.5
        shade = _clamp((py - (centre - half)) / (2 * half))
        fill = [TOP[i] + (BOTTOM[i] - TOP[i]) * shade for i in range(3)]
        in_tick_rows = top <= py <= bottom
        row = y * size * 4
        for x in range(size):
            px = x + 0.5
            d = _round_rect(px, py, half, centre, radius)
            body = _clamp(0.5 - d)
            shadow = 0.0
            if blur > 0.0:
                ds = _round_rect(px, py - dy, half, centre, radius)
                if ds < blur:
                    t = _clamp((ds + blur) / (2 * blur))
                    shadow = 0.32 * (1.0 - t * t * (3 - 2 * t))
            if body <= 0.0 and shadow <= 0.0:
                continue
            r, g, bl = fill
            if body > 0.0 and blur > 0.0 and -1.6 * size / 512 < d < 0.0 and py < centre:
                lift = 0.10 * (1.0 - (py - (centre - half)) / half)  # a faint top rim of light
                r, g, bl = r + (255 - r) * lift, g + (255 - g) * lift, bl + (255 - bl) * lift
            if in_tick_rows and left <= px <= right and body > 0.0:
                dt = min(_segment(px, py, a, b), _segment(px, py, b, c)) - stroke / 2
                mark = _clamp(0.5 - dt)
                if mark > 0.0:
                    r, g, bl = r + (255 - r) * mark, g + (255 - g) * mark, bl + (255 - bl) * mark
            # the square over its shadow (the shadow is black, so only its alpha counts)
            alpha = body + shadow * (1.0 - body)
            if alpha <= 0.0:
                continue
            k = body / alpha
            i = row + x * 4
            out[i] = round(r * k)
            out[i + 1] = round(g * k)
            out[i + 2] = round(bl * k)
            out[i + 3] = round(alpha * 255)
    return bytes(out)


def png(size: int, rgba: bytes) -> bytes:
    """A PNG file of straight-alpha RGBA rows."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    stride = size * 4
    raw = b"".join(b"\x00" + rgba[y * stride : (y + 1) * stride] for y in range(size))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def write_iconset(folder: Path) -> list[Path]:
    """Writes the ten PNGs of an ``.iconset`` folder; each size is drawn once."""
    folder.mkdir(parents=True, exist_ok=True)
    drawn: dict[int, bytes] = {}
    written = []
    for name, size in ICONSET:
        if size not in drawn:
            drawn[size] = png(size, render(size))
        path = folder / name
        path.write_bytes(drawn[size])
        written.append(path)
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not argv[0].endswith(".iconset"):
        sys.stderr.write("usage: app_icon.py <folder>.iconset\n")
        return 2
    write_iconset(Path(argv[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
