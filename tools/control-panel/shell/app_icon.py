"""The app icon of ComplianceWatch Control, drawn in pure Python.

The mark: a white shield with a blue tick, on a squircle in the brand's blue-to-teal gradient
(packages/ui/src/styles/tokens.css: --focus #2563eb into --accent #0f766e, the tick --primary
#1d4ed8), with a soft highlight at the top, a soft inner shadow at the bottom and a drop shadow on
the macOS icon grid. ``ui/icon.svg`` is the same mark.

Each size is drawn at its own pixel size, not scaled down from a big one: at 16 and 32 px the
squircle fills more of the canvas, the shield is a little larger and the tick at least 1.9 px
wide, and the highlight and shadows that would only blur them are left out.

    python3 app_icon.py AppIcon.iconset             # the ten PNGs iconutil turns into AppIcon.icns
    python3 app_icon.py --preview <folder>          # the mark at 512 and 32 px, and two alternates

Standard library only (``zlib`` for the PNG), and Python 3.9 or later, so the installer can run
it with any Python on the Mac.
"""

from __future__ import annotations

import math
import struct
import sys
import zlib
from bisect import bisect_left
from dataclasses import dataclass
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

Colour = tuple[float, float, float]


@dataclass(frozen=True)
class Style:
    top_left: Colour
    bottom_right: Colour
    shield_top: Colour
    shield_bottom: Colour
    tick: Colour
    gloss: float
    outline: bool = False


STYLES: dict[str, Style] = {
    "shield": Style(
        top_left=(0x25, 0x63, 0xEB),
        bottom_right=(0x0F, 0x76, 0x6E),
        shield_top=(0xFF, 0xFF, 0xFF),
        shield_bottom=(0xE6, 0xEE, 0xFC),
        tick=(0x1D, 0x4E, 0xD8),
        gloss=0.20,
    ),
    "night": Style(
        top_left=(0x1E, 0x29, 0x3B),
        bottom_right=(0x0B, 0x12, 0x20),
        shield_top=(0x8A, 0xB4, 0xFF),
        shield_bottom=(0x2D, 0xD4, 0xBF),
        tick=(0x0B, 0x12, 0x20),
        gloss=0.10,
    ),
    "outline": Style(
        top_left=(0x25, 0x63, 0xEB),
        bottom_right=(0x0F, 0x76, 0x6E),
        shield_top=(0xFF, 0xFF, 0xFF),
        shield_bottom=(0xFF, 0xFF, 0xFF),
        tick=(0xFF, 0xFF, 0xFF),
        gloss=0.20,
        outline=True,
    ),
}
"""The mark (``shield``) and the two alternates the preview draws beside it."""

# The shield and the tick in the squircle's 64-unit box (the path of ui/icon.svg).
APEX = (32.0, 10.5)
CORNER = (48.5, 16.2)
SIDE_END = 31.0
CURVE = ((48.5, 31.0), (48.5, 41.6), (41.6, 49.5), (32.0, 53.3))
"""The right half of the shield's bottom, a cubic from the side down to the point."""
TICK = ((24.2, 31.6), (30.1, 37.5), (40.1, 25.7))
TICK_WIDTH = 4.8
OUTLINE_WIDTH = 3.4


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def _smooth(edge0: float, edge1: float, value: float) -> float:
    t = _clamp((value - edge0) / (edge1 - edge0))
    return t * t * (3 - 2 * t)


def _mix(a: Colour, b: Colour, t: float) -> Colour:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


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


def _bottom_table(steps: int = 2048) -> tuple[list[float], list[float]]:
    """The shield's half width along its bottom curve, by height in the box: (heights, widths)."""
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = CURVE
    heights, widths = [], []
    for i in range(steps + 1):
        t = i / steps
        s = 1 - t
        x = s * s * s * x0 + 3 * s * s * t * x1 + 3 * s * t * t * x2 + t * t * t * x3
        y = s * s * s * y0 + 3 * s * s * t * y1 + 3 * s * t * t * y2 + t * t * t * y3
        heights.append(y)
        widths.append(x - 32.0)
    return heights, widths


_HEIGHTS, _WIDTHS = _bottom_table()
_TIP = CURVE[-1][1]
_TOP_SLOPE = (CORNER[1] - APEX[1], -(CORNER[0] - APEX[0]))  # the top edge's outward normal
_TOP_NORM = math.hypot(*_TOP_SLOPE)


def _bottom_half_width(v: float) -> tuple[float, float]:
    """The half width of the shield's bottom at height ``v`` and its slope dw/dv; below the
    point, the curve's last direction carried on (so the point is sharp, not rounded)."""
    i = min(max(bisect_left(_HEIGHTS, v), 1), len(_HEIGHTS) - 1)
    v0, v1 = _HEIGHTS[i - 1], _HEIGHTS[i]
    w0, w1 = _WIDTHS[i - 1], _WIDTHS[i]
    slope = 0.0 if v1 == v0 else (w1 - w0) / (v1 - v0)
    return w0 + slope * (v - v0), slope


def shield_distance(u: float, v: float) -> float:
    """Signed distance in box units from (u, v) to the shield's outline: negative inside. Each
    edge's own distance, the farthest counting (the shield is convex)."""
    dx = abs(u - 32.0)
    top = ((dx - 0.0) * _TOP_SLOPE[0] + (v - APEX[1]) * _TOP_SLOPE[1]) / _TOP_NORM
    side = dx - (CORNER[0] - 32.0)
    distance = max(top, side)
    if v > SIDE_END:
        width, slope = _bottom_half_width(v)
        distance = max(distance, (dx - width) / math.sqrt(1.0 + slope * slope))
    return distance


def geometry(size: int) -> dict[str, float]:
    """The icon's shapes at ``size`` pixels: the squircle, the mark's scale, the tick and the
    shadows.

    From 128 px up it follows the macOS grid (an 824/1024 squircle); the small sizes fill more of
    the canvas, draw the shield a little larger and the tick at least 1.9 px wide at 16 px and
    2.6 px at 32 px."""
    if size >= 128:
        inset = size * 100 / 1024
    elif size >= 64:
        inset = size * 0.07
    else:
        inset = size / 16
    side = size - 2 * inset
    small = size <= 32
    tiny = size <= 16
    unit = side / 64
    scale = 1.2 if tiny else 1.1 if small else 1.0
    return {
        "size": float(size),
        "inset": inset,
        "side": side,
        "half": side / 2,
        "centre": size / 2,
        "radius": side * (0.21 if small else 0.2237),
        "unit": unit,
        "scale": scale,
        "tick": max(TICK_WIDTH * unit * scale, 1.9 if tiny else 2.6 if small else 0.0),
        "outline": max(OUTLINE_WIDTH * unit * scale, 1.2),
        "effects": 0.0 if size < 32 else 0.6 if small else 1.0,
        "shadow": 0.0 if size < 64 else size * 0.028,
        "shadow_dy": 0.0 if size < 64 else size * 0.012,
        "shield_shadow": 0.0 if size < 64 else 2.2,
    }


def render(size: int, style: str = "shield") -> bytes:
    """The icon as straight-alpha RGBA rows, ``size`` x ``size``."""
    paint = STYLES[style]
    shape = geometry(size)
    inset, side, half, centre = shape["inset"], shape["side"], shape["half"], shape["centre"]
    radius, unit, scale = shape["radius"], shape["unit"], shape["scale"]
    blur, dy, effects = shape["shadow"], shape["shadow_dy"], shape["effects"]
    lift = shape["shield_shadow"]
    top_left, bottom_right = paint.top_left, paint.bottom_right
    shield_top, shield_bottom, tick = paint.shield_top, paint.shield_bottom, paint.tick
    gloss = paint.gloss * effects
    outlined = paint.outline
    stroke, outline = shape["tick"], shape["outline"]
    to_box = 64.0 / side / scale  # pixels to box units, through the mark's scale
    to_px = 1.0 / to_box
    a, b, c = TICK
    inner = side * 0.06
    out = bytearray(size * size * 4)
    for y in range(size):
        py = y + 0.5
        down = _clamp((py - inset) / side)
        v = (py - inset) / side * 64.0
        v = 32.0 + (v - 32.0) / scale
        row = y * size * 4
        for x in range(size):
            px = x + 0.5
            d = _round_rect(px, py, half, centre, radius)
            body = _clamp(0.5 - d)
            shadow = 0.0
            if blur > 0.0:
                ds = _round_rect(px, py - dy, half, centre, radius)
                if ds < blur:
                    shadow = 0.30 * (1.0 - _smooth(-blur, blur, ds))
            if body <= 0.0 and shadow <= 0.0:
                continue
            across = _clamp((px - inset) / side)
            colour = _mix(top_left, bottom_right, (across + down) / 2)
            if gloss > 0.0:  # a soft highlight on the top half
                colour = _mix(
                    colour, (255.0, 255.0, 255.0), gloss * (1.0 - _smooth(0.0, 0.55, down))
                )
            if effects > 0.0 and d > -inner:  # a soft inner shadow, darker towards the bottom
                depth = (1.0 - _smooth(-inner, 0.0, -d)) * (0.3 + 0.7 * down) * 0.30 * effects
                colour = _mix(colour, (0x0B, 0x12, 0x20), depth)
            u = (px - inset) / side * 64.0
            u = 32.0 + (u - 32.0) / scale
            edge = shield_distance(u, v) * to_px
            if lift > 0.0:  # the shield's own soft shadow
                lifted = shield_distance(u, v - lift * 0.55) * to_px
                spread = lift * unit
                if lifted < spread:
                    fall = 0.22 * (1.0 - _smooth(-spread, spread, lifted))
                    colour = _mix(colour, (0x0B, 0x12, 0x20), fall * _clamp(0.5 + edge))
            if outlined:
                ring = _clamp(0.5 - (abs(edge) - outline / 2))
                inside = _clamp(0.5 - edge)
                colour = _mix(colour, (255.0, 255.0, 255.0), 0.12 * inside)
                colour = _mix(colour, shield_top, ring)
            else:
                cover = _clamp(0.5 - edge)
                if cover > 0.0:
                    fill = _mix(shield_top, shield_bottom, _clamp((v - APEX[1]) / (_TIP - APEX[1])))
                    colour = _mix(colour, fill, cover)
            if edge < 0.0:
                ink = min(_segment(u, v, a, b), _segment(u, v, b, c)) * to_px - stroke / 2
                mark = _clamp(0.5 - ink)
                if mark > 0.0:
                    colour = _mix(colour, tick, mark)
            alpha = body + shadow * (1.0 - body)
            k = body / alpha  # the squircle over its shadow, which is black: only its alpha counts
            i = row + x * 4
            out[i] = round(colour[0] * k)
            out[i + 1] = round(colour[1] * k)
            out[i + 2] = round(colour[2] * k)
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


def write_preview(folder: Path) -> list[Path]:
    """The mark at 512 and 32 px, and the two alternates at 512 px, to choose from."""
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, size, style in (
        ("mark-512.png", 512, "shield"),
        ("mark-32.png", 32, "shield"),
        ("mark-16.png", 16, "shield"),
        ("alternate-night-512.png", 512, "night"),
        ("alternate-outline-512.png", 512, "outline"),
    ):
        path = folder / name
        path.write_bytes(png(size, render(size, style)))
        written.append(path)
    return written


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--preview":
        write_preview(Path(argv[1]))
        return 0
    if len(argv) != 1 or not argv[0].endswith(".iconset"):
        sys.stderr.write("usage: app_icon.py <folder>.iconset | --preview <folder>\n")
        return 2
    write_iconset(Path(argv[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
