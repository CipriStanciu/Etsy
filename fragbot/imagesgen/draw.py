"""Shared PIL drawing helpers for the listing image renderers.

Everything is drawn with Pillow primitives only (shapes, gradients, text) —
no image assets, no network, no paid tools. All coordinates are for the
2000x2000 canvas the renderers use.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageCms, ImageDraw, ImageFilter, ImageFont, ImageOps

from .fonts import font as load_font
from .style import GOLD, INK, WHITE

log = logging.getLogger("fragbot.imagesgen")

CANVAS = 2000  # 2000 x 2000 px per the owner spec
JPEG_QUALITY_DEFAULT = 90  # spec: 88-92

# ---------------------------------------------------------------------------
# ICC profile (sRGB) — embed if available, skip cleanly otherwise.
# ---------------------------------------------------------------------------
_srgb_cache: Optional[bytes] = None
_SRGB_VENDORED = Path(__file__).resolve().parent / "data" / "srgb.icc"


def sRGB_profile_bytes() -> Optional[bytes]:
    """sRGB ICC profile bytes, or None if none is available.

    Prefers the vendored profile (``data/srgb.icc`` — fixed bytes, so output
    files are byte-identical across runs); falls back to Pillow's LittleCMS
    ``createProfile("sRGB")``; on any failure returns None and callers embed
    nothing (spec: "embed or skip cleanly, never error").
    """
    global _srgb_cache
    if _srgb_cache is not None:
        return _srgb_cache or None
    try:
        if _SRGB_VENDORED.is_file():
            _srgb_cache = _SRGB_VENDORED.read_bytes()
        else:
            profile = ImageCms.createProfile("sRGB")
            _srgb_cache = ImageCms.ImageCmsProfile(profile).tobytes()
    except Exception as exc:  # pragma: no cover - environment dependent
        log.warning("sRGB ICC profile unavailable (%s); saving without it", exc)
        _srgb_cache = b""
    return _srgb_cache or None


def save_jpeg(img: Image.Image, path: str, quality: int = JPEG_QUALITY_DEFAULT) -> str:
    """Save an RGB image as a high-quality sRGB JPEG with 300 DPI metadata.

    Quality must be in the 88-92 band per the owner spec (validated in
    verify.py); the ICC profile is embedded when the platform can provide one
    and skipped cleanly otherwise.
    """
    if not (88 <= quality <= 92):
        raise ValueError(f"JPEG quality {quality} outside the spec band 88-92")
    if img.mode != "RGB":
        img = img.convert("RGB")
    kwargs = {"quality": quality, "dpi": (300, 300), "subsampling": 0}
    icc = sRGB_profile_bytes()
    if icc:
        kwargs["icc_profile"] = icc
    img.save(path, "JPEG", **kwargs)
    return path


# ---------------------------------------------------------------------------
# Canvas / gradients
# ---------------------------------------------------------------------------
def new_canvas(fill=WHITE, size: Tuple[int, int] = (CANVAS, CANVAS)) -> Image.Image:
    return Image.new("RGB", size, fill)


def vertical_gradient(size: Tuple[int, int], top: Tuple, bottom: Tuple) -> Image.Image:
    """Vertical linear gradient from ``top`` colour to ``bottom`` colour."""
    w, h = size
    base = Image.linear_gradient("L").resize((w, h))
    return ImageOps.colorize(base, black=top, white=bottom)


def radial_glow_mask(
    size: Tuple[int, int],
    center: Tuple[float, float],
    radius: float,
    strength: float = 1.0,
) -> Image.Image:
    """L-mode mask: white at ``center`` fading to black at ``radius``.

    Use with Image.composite(glow_layer, img, mask) for a soft halo.
    """
    w, h = size
    mask = Image.new("L", (w, h), 0)
    d = int(radius * 2)
    if d <= 0:
        return mask
    g = Image.radial_gradient("L").resize((d, d), Image.Resampling.BILINEAR)
    g = g.point(lambda v: int(v * strength))
    x0 = int(center[0] - radius)
    y0 = int(center[1] - radius)
    mask.paste(g, (x0, y0), g)
    return mask


def composite_glow(img: Image.Image, mask: Image.Image, color: Tuple) -> Image.Image:
    """Blend a soft coloured glow over ``img`` using a precomputed mask."""
    overlay = Image.new("RGB", img.size, color)
    return Image.composite(overlay, img, mask)


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------
def text_w(font: ImageFont.FreeTypeFont, text: str) -> float:
    return font.getlength(text)


def tracked_width(font: ImageFont.FreeTypeFont, text: str, tracking: float = 0) -> float:
    if not text:
        return 0.0
    return sum(font.getlength(c) for c in text) + tracking * (len(text) - 1)


def fit_font(
    name: str,
    text: str,
    max_width: float,
    max_height: float,
    start: int = 220,
    min_size: int = 18,
) -> ImageFont.FreeTypeFont:
    """Largest font size so ``text`` (may contain newlines) fits the box."""
    lo, hi = min_size, start
    best = load_font(name, min_size)
    while lo <= hi:
        mid = (lo + hi) // 2
        f = load_font(name, mid)
        ascent, descent = f.getmetrics()
        line_h = ascent + descent
        lines = text.split("\n")
        w = max(text_w(f, ln) for ln in lines)
        h_ = line_h * len(lines)
        if w <= max_width and h_ <= max_height:
            best = f
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> List[str]:
    """Greedy word-wrap to fit ``max_width``."""
    words = text.split()
    if not words:
        return []
    lines: List[str] = []
    cur = words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        if text_w(font, trial) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def fit_wrapped_font(
    name: str,
    text: str,
    max_width: float,
    max_height: float,
    start: int = 64,
    min_size: int = 16,
    line_gap: float = 0,
) -> ImageFont.FreeTypeFont:
    """Largest font size so ``text`` fits as wrapped lines inside the box."""
    lo, hi = min_size, start
    best = load_font(name, min_size)
    while lo <= hi:
        mid = (lo + hi) // 2
        f = load_font(name, mid)
        lines = wrap_text(text, f, max_width)
        a, d = f.getmetrics()
        h = len(lines) * (a + d) + line_gap * (len(lines) - 1)
        if h <= max_height and all(text_w(f, ln) <= max_width for ln in lines):
            best = f
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def draw_lines_center(
    draw: ImageDraw.ImageDraw,
    cx: float,
    y_top: float,
    lines: Sequence[str],
    font: ImageFont.FreeTypeFont,
    fill: Tuple,
    line_gap: float = 0,
    tracking: float = 0,
) -> float:
    """Draw centered lines; ``y_top`` is the ascender line of the first line.

    Returns the bottom of the last line's box (ascender line + n*line_height).
    Pillow's 'a' vertical anchor positions y on the font's ascender line, so
    glyph ink begins a little below ``y_top`` — that headroom keeps text inside
    the caller's allocated band by design.
    """
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    y = y_top
    for ln in lines:
        if tracking:
            draw_tracked_at(draw, cx, y, ln, font, fill, tracking, anchor_vert="a")
        else:
            draw.text((cx, y), ln, font=font, fill=fill, anchor="ma")
        y += line_h + line_gap
    return y - line_h


def draw_tracked_at(
    draw: ImageDraw.ImageDraw,
    center_x: float,
    y: float,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: Tuple,
    tracking: float,
    anchor_vert: str = "a",
) -> None:
    """Letter-spaced text centered horizontally at ``center_x`` (anchor 'm')."""
    total = tracked_width(font, text, tracking)
    x = center_x - total / 2.0
    for c in text:
        draw.text((x, y), c, font=font, fill=fill, anchor=f"l{anchor_vert}")
        x += font.getlength(c) + tracking


def shadow_text(
    img: Image.Image,
    xy: Tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: Tuple,
    anchor: str = "mm",
    shadow: Tuple = (0, 0, 0),
    blur: int = 6,
    offset: Tuple[int, int] = (0, 4),
    alpha: int = 140,
) -> None:
    """Text with a soft drop shadow drawn on ``img`` directly."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.text(xy, text, font=font, fill=(255, 255, 255, alpha), anchor=anchor)
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    mask = layer.getchannel("A")
    img.paste(Image.new("RGB", img.size, shadow), (int(xy[0] + offset[0]), int(xy[1] + offset[1])), mask)
    ImageDraw.Draw(img).text(xy, text, font=font, fill=fill, anchor=anchor)


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------
def pill_box(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    w: float,
    h: float,
    outline: Tuple = GOLD,
    fill: Optional[Tuple] = None,
    width: int = 3,
) -> None:
    draw.rounded_rectangle(
        (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2),
        radius=h / 2,
        outline=outline,
        width=width,
        fill=fill,
    )


def diamond(
    draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill: Tuple
) -> None:
    draw.polygon(
        [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=fill
    )


def draw_heart(
    draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, fill: Tuple
) -> None:
    r = size / 2
    draw.ellipse((cx - r, cy - r * 0.55, cx, cy + r * 0.45), fill=fill)
    draw.ellipse((cx, cy - r * 0.55, cx + r, cy + r * 0.45), fill=fill)
    draw.polygon(
        [
            (cx - r * 1.04, cy - r * 0.05),
            (cx + r * 1.04, cy - r * 0.05),
            (cx, cy + r * 1.05),
        ],
        fill=fill,
    )


def draw_check_mark(draw: ImageDraw.ImageDraw, x0, y0, x1, y1, fill, width=8) -> None:
    """A checkmark inside the bbox (x0,y0)-(x1,y1)."""
    draw.line((x0, y0 + (y1 - y0) * 0.35, x0 + (x1 - x0) * 0.36, y0 + (y1 - y0) * 0.92), fill=fill, width=width)
    draw.line((x0 + (x1 - x0) * 0.36, y0 + (y1 - y0) * 0.92, x1, y0 + (y1 - y0) * 0.12), fill=fill, width=width)


def draw_droplet(
    draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill: Tuple
) -> None:
    """A small teardrop/droplet icon (circle bottom + pointed top)."""
    body_r = r * 0.62
    cy_body = cy + r * 0.32
    draw.ellipse((cx - body_r, cy_body - body_r, cx + body_r, cy_body + body_r), fill=fill)
    draw.polygon(
        [
            (cx, cy - r * 1.05),
            (cx - body_r * 0.95, cy_body - body_r * 0.85),
            (cx + body_r * 0.95, cy_body - body_r * 0.85),
        ],
        fill=fill,
    )


def draw_circle_icon(
    draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill: Tuple
) -> None:
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)


def dashed_line(
    draw: ImageDraw.ImageDraw, xy: Tuple, dash: float = 16, gap: float = 12,
    fill: Tuple = GOLD, width: int = 3,
) -> None:
    x0, y0, x1, y1 = xy
    length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    if length <= 0:
        return
    dx, dy = (x1 - x0) / length, (y1 - y0) / length
    pos = 0.0
    while pos < length:
        end = min(pos + dash, length)
        draw.line(
            (x0 + dx * pos, y0 + dy * pos, x0 + dx * end, y0 + dy * end),
            fill=fill, width=width,
        )
        pos = end + gap


def paste_rotated(
    img: Image.Image, layer: Image.Image, angle: float, center: Tuple[int, int]
) -> None:
    """Paste ``layer`` (RGBA, transparent bg) rotated by ``angle`` at ``center``."""
    rot = layer.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    cx, cy = center
    img.paste(rot, (int(cx - rot.width / 2), int(cy - rot.height / 2)), rot)


def leaf(
    img: Image.Image, cx: int, cy: int, length: int, angle: float, color: Tuple
) -> None:
    """A single botanical leaf drawn as an elongated ellipse + tip, rotated."""
    w, h = length, max(6, int(length * 0.42))
    layer = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.ellipse((w / 2, 0, w * 1.5, h), fill=(*color, 255))
    ld.polygon([(w * 1.5, h / 2), (w * 1.95, h / 2), (w * 1.5, h * 0.1)], fill=(*color, 255))
    ld.polygon([(w / 2, h / 2), (w * 0.05, h / 2), (w / 2, h * 0.1)], fill=(*color, 255))
    paste_rotated(img, layer, angle, (cx, cy))


def botanical_flourish(
    img: Image.Image,
    corner: str,
    color: Tuple,
    scale: float = 1.0,
    alpha: int = 90,
) -> None:
    """Subtle gold botanical line art in a corner using PIL primitives only.

    ``corner``: 'bl' (bottom-left) or 'br' (bottom-right).
    """
    from PIL import ImageDraw as _ID

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = _ID.Draw(layer)
    s = 200 * scale
    accent = (*color, alpha)
    if corner == "bl":
        base = (170, 1850)
        arc_xy = (40, 1650, 640, 1980)
        sign = 1
    else:
        base = (1830, 1850)
        arc_xy = (1360, 1650, 1960, 1980)
        sign = -1
    # main stem curve
    ld.arc(arc_xy, start=0 if sign == 1 else 90, end=90 if sign == 1 else 180, fill=accent, width=5)
    ld.line((base[0], base[1], base[0] + sign * 60, base[1] + 20), fill=accent, width=5)
    # leaves along the stem (fully opaque leaves, stem stays alpha-blended)
    leaf(img, base[0] + sign * 130, base[1] - 60, 90, sign * -28, color)
    leaf(img, base[0] + sign * 260, base[1] - 130, 110, sign * -42, color)
    leaf(img, base[0] + sign * 160, base[1] - 30, 70, sign * 35, color)
    img.paste(layer, (0, 0), layer)
    # small berries / dots
    d = _ID.Draw(img)
    for dx, dy, r in ((-300, 1680, 8), (-350, 1720, 6), (-130, 1780, 7)):
        cx = base[0] + sign * dx
        cy = base[1] - dy
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*color, 235))


# ---------------------------------------------------------------------------
# Product motifs (for the lifestyle image) — all pure PIL primitives
# ---------------------------------------------------------------------------
def _soft_ellipse(draw, cx, cy, w, h, fill, alpha=110):
    layer = Image.new("RGBA", draw._image.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), fill=(*fill, alpha))
    draw._image.paste(layer, (0, 0), layer)


def draw_bottle(
    img: Image.Image,
    cx: float,
    bottom: float,
    width: float,
    body_color: Tuple,
    accent: Tuple,
    label_text: str = "",
) -> None:
    """Elegant perfume-bottle silhouette (rounded body, shoulders, gold cap)."""
    d = ImageDraw.Draw(img, "RGBA")
    total_h = 830
    body_w = width
    body_h = total_h * 0.62
    cap_w = width * 0.5
    neck_w = width * 0.26
    body_top = bottom - body_h
    # subtle ground shadow
    _soft_ellipse(d, cx, bottom + 30, width * 1.7, 60, (0, 0, 0), 70)
    # body
    d.rounded_rectangle(
        (cx - body_w / 2, body_top, cx + body_w / 2, bottom), radius=36, fill=(*body_color, 255)
    )
    # shoulders
    neck_bottom = body_top
    neck_top = neck_bottom - total_h * 0.10
    d.polygon(
        [
            (cx - body_w / 2, neck_bottom),
            (cx + body_w / 2, neck_bottom),
            (cx + neck_w / 2, neck_top),
            (cx - neck_w / 2, neck_top),
        ],
        fill=(*body_color, 255),
    )
    # neck
    d.rectangle((cx - neck_w / 2, neck_top - total_h * 0.05, cx + neck_w / 2, neck_top), fill=(*accent, 255))
    # cap
    d.rounded_rectangle(
        (cx - cap_w / 2, neck_top - total_h * 0.20, cx + cap_w / 2, neck_top - total_h * 0.04),
        radius=cap_w * 0.18, fill=(*accent, 255),
    )
    # label
    label_w = body_w * 0.62
    label_h = body_h * 0.42
    label_cy = body_top + body_h * 0.55
    d.rounded_rectangle(
        (cx - label_w / 2, label_cy - label_h / 2, cx + label_w / 2, label_cy + label_h / 2),
        radius=14, fill=(255, 252, 245),
    )
    d.rounded_rectangle(
        (cx - label_w / 2, label_cy - label_h / 2, cx + label_w / 2, label_cy + label_h / 2),
        radius=14, outline=(*accent, 220), width=4,
    )
    draw_droplet(d, cx, label_cy - label_h * 0.22, 26, accent)
    if label_text:
        f = load_font("cormorant-600", 34)
        d.text((cx, label_cy + label_h * 0.18), label_text, font=f, fill=(90, 80, 66), anchor="ma")
    # glass shine
    d.rounded_rectangle(
        (cx - body_w / 2 + body_w * 0.16, body_top + body_h * 0.16,
         cx - body_w / 2 + body_w * 0.24, bottom - body_h * 0.18),
        radius=10, fill=(255, 255, 255, 70),
    )


def draw_candle(
    img: Image.Image,
    cx: float,
    bottom: float,
    width: float,
    body_color: Tuple,
    accent: Tuple,
    label_text: str = "",
) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    jar_w = width
    jar_h = 560
    top = bottom - jar_h
    _soft_ellipse(d, cx, bottom + 26, jar_w * 1.5, 50, (0, 0, 0), 70)
    # jar
    d.rounded_rectangle((cx - jar_w / 2, top, cx + jar_w / 2, bottom), radius=30, fill=(*body_color, 255))
    # wax
    wax_cy = top + 34
    d.ellipse((cx - jar_w / 2 + 14, wax_cy - 26, cx + jar_w / 2 - 14, wax_cy + 26), fill=(246, 240, 226))
    # rim
    d.rectangle((cx - jar_w / 2 - 8, top - 6, cx + jar_w / 2 + 8, top + 12), fill=(*accent, 255))
    # label band
    d.rounded_rectangle((cx - jar_w * 0.44, top + jar_h * 0.34, cx + jar_w * 0.44, top + jar_h * 0.58), radius=12, fill=(255, 252, 245))
    d.rounded_rectangle((cx - jar_w * 0.44, top + jar_h * 0.34, cx + jar_w * 0.44, top + jar_h * 0.58), radius=12, outline=(*accent, 220), width=4)
    if label_text:
        f = load_font("cormorant-600", 32)
        d.text((cx, top + jar_h * 0.46), label_text, font=f, fill=(90, 80, 66), anchor="mm")
    # wick + flame
    wick_top = wax_cy - 26
    d.line((cx, wax_cy, cx, wick_top - 16), fill=(60, 52, 44), width=6)
    d.polygon(
        [(cx, wick_top - 88), (cx - 26, wick_top - 22), (cx + 26, wick_top - 22)],
        fill=(*accent, 255),
    )
    d.ellipse((cx - 24, wick_top - 66, cx + 24, wick_top - 18), fill=(255, 214, 120, 255))
    _soft_ellipse(d, cx, wick_top - 60, 150, 130, accent, 60)


def draw_spray_bottle(
    img: Image.Image,
    cx: float,
    bottom: float,
    width: float,
    body_color: Tuple,
    accent: Tuple,
    label_text: str = "",
) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    body_w = width
    body_h = 640
    body_top = bottom - body_h
    _soft_ellipse(d, cx, bottom + 26, body_w * 1.6, 50, (0, 0, 0), 70)
    # body (tall, slightly tapered)
    d.rounded_rectangle((cx - body_w / 2, body_top, cx + body_w / 2, bottom), radius=46, fill=(*body_color, 255))
    # neck + trigger head
    d.rectangle((cx - body_w * 0.16, body_top - 70, cx + body_w * 0.16, body_top + 8), fill=(*accent, 255))
    d.rounded_rectangle((cx - body_w * 0.42, body_top - 110, cx + body_w * 0.42, body_top - 52), radius=18, fill=(*accent, 255))
    # nozzle
    d.rectangle((cx + body_w * 0.30, body_top - 92, cx + body_w * 0.72, body_top - 66), fill=(60, 54, 46))
    d.line((cx + body_w * 0.72, body_top - 79, cx + body_w * 0.86, body_top - 92), fill=(60, 54, 46), width=8)
    # label band
    d.rounded_rectangle((cx - body_w * 0.42, bottom - body_h * 0.52, cx + body_w * 0.42, bottom - body_h * 0.30), radius=12, fill=(255, 252, 245))
    d.rounded_rectangle((cx - body_w * 0.42, bottom - body_h * 0.52, cx + body_w * 0.42, bottom - body_h * 0.30), radius=12, outline=(*accent, 220), width=4)
    if label_text:
        f = load_font("cormorant-600", 32)
        d.text((cx, bottom - body_h * 0.41), label_text, font=f, fill=(90, 80, 66), anchor="mm")
    # mist dots
    for dx, dy, r in ((body_w * 0.95, -118, 8), (body_w * 1.12, -138, 6), (body_w * 1.25, -112, 5)):
        d.ellipse((cx + dx - r, bottom - body_h + dy - r, cx + dx + r, bottom - body_h + dy + r), fill=(*accent, 200))


def draw_diffuser(
    img: Image.Image,
    cx: float,
    bottom: float,
    width: float,
    body_color: Tuple,
    accent: Tuple,
    label_text: str = "",
) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    bottle_w = width * 0.9
    bottle_h = 620
    top = bottom - bottle_h
    _soft_ellipse(d, cx, bottom + 26, bottle_w * 2.2, 50, (0, 0, 0), 70)
    # reeds fanning out of the neck
    neck_cx, neck_cy = cx, top + 30
    for ang in (-52, -34, -16, 0, 16, 34, 52):
        import math

        rad = math.radians(ang)
        x2 = neck_cx + math.sin(rad) * 420
        y2 = neck_cy - math.cos(rad) * 420
        d.line((neck_cx, neck_cy, x2, y2), fill=(198, 178, 138), width=7)
    # bottle
    d.rounded_rectangle((cx - bottle_w / 2, top, cx + bottle_w / 2, bottom), radius=26, fill=(*body_color, 255))
    d.rounded_rectangle((cx - bottle_w * 0.20, top - 40, cx + bottle_w * 0.20, top + 30), radius=10, fill=(*accent, 255))
    d.rounded_rectangle((cx - bottle_w * 0.44, bottom - bottle_h * 0.34, cx + bottle_w * 0.44, bottom - bottle_h * 0.14), radius=12, fill=(255, 252, 245))
    d.rounded_rectangle((cx - bottle_w * 0.44, bottom - bottle_h * 0.34, cx + bottle_w * 0.44, bottom - bottle_h * 0.14), radius=12, outline=(*accent, 220), width=4)
    if label_text:
        f = load_font("cormorant-600", 32)
        d.text((cx, bottom - bottle_h * 0.24), label_text, font=f, fill=(90, 80, 66), anchor="mm")
    # reed tips dots
    for ang in (-52, -16, 16, 52):
        import math

        rad = math.radians(ang)
        x2 = neck_cx + math.sin(rad) * 420
        y2 = neck_cy - math.cos(rad) * 420
        d.ellipse((x2 - 7, y2 - 7, x2 + 7, y2 + 7), fill=(*accent, 230))


def draw_tin(
    img: Image.Image,
    cx: float,
    bottom: float,
    width: float,
    body_color: Tuple,
    accent: Tuple,
    label_text: str = "",
) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    w, h = width * 1.15, 400
    top = bottom - h
    _soft_ellipse(d, cx, bottom + 24, w * 1.5, 46, (0, 0, 0), 70)
    # lid (slightly wider ellipse on top)
    d.ellipse((cx - w * 0.56, top - 16, cx + w * 0.56, top + 34), fill=(*accent, 255))
    d.rectangle((cx - w * 0.52, top + 18, cx + w * 0.52, top + 40), fill=(*accent, 255))
    # tin body
    d.rounded_rectangle((cx - w / 2, top + 34, cx + w / 2, bottom), radius=18, fill=(*body_color, 255))
    # label
    d.rounded_rectangle((cx - w * 0.42, top + 80, cx + w * 0.42, top + 160), radius=12, fill=(255, 252, 245))
    d.rounded_rectangle((cx - w * 0.42, top + 80, cx + w * 0.42, top + 160), radius=12, outline=(*accent, 220), width=4)
    if label_text:
        f = load_font("cormorant-600", 30)
        d.text((cx, top + 120), label_text, font=f, fill=(90, 80, 66), anchor="mm")
    # scent sparkle above lid
    for dx, dy, r in ((-60, -40, 8), (10, -66, 6), (74, -30, 7)):
        d.ellipse((cx + dx - r, top - 20 + dy - r, cx + dx + r, top - 20 + dy + r), fill=(*accent, 220))


def draw_product_motif(
    img: Image.Image,
    category: str,
    cx: float,
    bottom: float,
    width: float,
    body_color: Tuple,
    accent: Tuple,
    label_text: str,
) -> None:
    """Category-aware hero product for the lifestyle image."""
    if category == "candle":
        draw_candle(img, cx, bottom, width, body_color, accent, label_text)
    elif category == "room_spray":
        draw_spray_bottle(img, cx, bottom, width, body_color, accent, label_text)
    elif category == "reed_diffuser":
        draw_diffuser(img, cx, bottom, width, body_color, accent, label_text)
    elif category == "solid_perfume":
        draw_tin(img, cx, bottom, width, body_color, accent, label_text)
    else:  # perfume, cologne
        draw_bottle(img, cx, bottom, width, body_color, accent, label_text)