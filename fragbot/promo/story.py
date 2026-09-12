"""Instagram story renderer (1080 x 1920, 9:16).

A vertical scent-pyramid visual reusing the listing image's pyramid palette
(pastel top / amber heart / espresso base) on the cream canvas, with the
recipe name, a "Swipe up for recipe" CTA area at the bottom and a brand
handle placeholder. Pillow only; vendored fonts; deterministic with
render-time overflow guards (mirrors fragbot/promo/pin.py).
"""

from __future__ import annotations

import logging

from PIL import Image, ImageDraw

from ..imagesgen.draw import (
    dashed_line,
    diamond,
    draw_lines_center,
    draw_tracked_at,
    fit_font,
    fit_wrapped_font,
    new_canvas,
    pill_box,
    save_jpeg,
    text_w,
    wrap_text,
)
from ..imagesgen.fonts import font as load_font
from ..imagesgen.style import (
    CATEGORY_LABEL,
    CREAM,
    GOLD,
    GOLD_DARK,
    GOLD_LIGHT,
    INK,
    INK_SOFT,
    PYRAMID_BASE_EDGE,
    PYRAMID_BASE_FILL,
    PYRAMID_HEART_EDGE,
    PYRAMID_HEART_FILL,
    PYRAMID_TOP_EDGE,
    PYRAMID_TOP_FILL,
    accent_for_theme,
)
from .style import BRAND_HANDLE, STORY_CTA, STORY_SIZE

log = logging.getLogger("fragbot.promo")

W, H = STORY_SIZE
CX = W / 2
PAL = [  # (label, fill, edge, text_colour)
    ("TOP", PYRAMID_TOP_FILL, PYRAMID_TOP_EDGE, (74, 58, 40)),
    ("HEART", PYRAMID_HEART_FILL, PYRAMID_HEART_EDGE, (255, 250, 240)),
    ("BASE", PYRAMID_BASE_FILL, PYRAMID_BASE_EDGE, (247, 241, 230)),
]


def _D(img: Image.Image) -> ImageDraw.ImageDraw:
    return ImageDraw.Draw(img, "RGBA")


def _assert_fit(text: str, font, max_w: float, where: str) -> None:
    for ln in wrap_text(text, font, max_w):
        if text_w(font, ln) > max_w:
            raise ValueError(
                f"story text overflow at {where}: {ln!r} too wide for {max_w:.0f}px"
            )


def _pyramid_block(d: ImageDraw.ImageDraw, cx: float, x0: float, y_top: float,
                   block_h: float, label: str, notes: str, pct: str,
                   fill, edge, tcol, accent) -> None:
    """One pyramid level: label left, wrapped notes centre, % right."""
    x1 = x0 + (cx - x0) * 2
    d.rectangle((x0, y_top, x1, y_top + block_h), fill=fill)
    for ln in ((x0, y_top, x1, y_top), (x0, y_top + block_h, x1, y_top + block_h),
               (x0, y_top, x0, y_top + block_h), (x1, y_top, x1, y_top + block_h)):
        d.line(ln, fill=edge, width=6)
    draw_tracked_at(d, x0 + 46, y_top + 44, label, load_font("playfair-700", 32),
                    fill=tcol, tracking=8, anchor_vert="a")
    inner_w = (x1 - x0) - 300
    f_notes = fit_wrapped_font("cormorant-600", notes, inner_w, block_h - 130,
                               start=56, min_size=18)
    nlines = wrap_text(notes, f_notes, inner_w)
    draw_lines_center(d, cx, y_top + 132, nlines, f_notes, fill=tcol, line_gap=10)
    _assert_fit(notes, f_notes, inner_w, f"pyramid {label} notes")
    d.text((x1 - 62, y_top + block_h / 2), pct, font=load_font("playfair-700", 46),
           fill=tcol, anchor="mm")


def render_story(recipe: dict, brand: str = "Fragrance Bot",
                 quality: int = 90) -> Image.Image:
    """Render the 1080x1920 Instagram story for a recipe (RGB image)."""
    name = recipe["recipe_name"]
    category = recipe["category"]
    accent = accent_for_theme(recipe.get("theme"))
    holiday = recipe.get("holiday")
    sp = recipe["scent_profile"]

    img = new_canvas(fill=CREAM, size=STORY_SIZE)
    d = _D(img)

    # --- header -------------------------------------------------------------
    d.line((CX - 90, 120, CX - 26, 120), fill=GOLD, width=5)
    d.line((CX + 26, 120, CX + 90, 120), fill=GOLD, width=5)
    diamond(d, CX, 120, 9, GOLD)

    eyebrow = (f"SCENT PYRAMID \u00b7 {holiday.upper()} EDITION" if holiday
               else f"SCENT PYRAMID \u00b7 {CATEGORY_LABEL[category].upper()}")
    f_eyebrow = fit_font("lato-700", eyebrow, 900, 64, start=30, min_size=16)
    _assert_fit(eyebrow, f_eyebrow, 900, "eyebrow")
    draw_tracked_at(d, CX, 178, eyebrow, f_eyebrow, fill=GOLD_DARK,
                    tracking=8, anchor_vert="a")

    f_name = fit_wrapped_font("playfair-700", name, 920, 150, start=104,
                              min_size=40, line_gap=12)
    nlines = wrap_text(name, f_name, 920)
    draw_lines_center(d, CX, 252, nlines, f_name, fill=INK, line_gap=12)
    _assert_fit(name, f_name, 920, "recipe_name")

    sub = f"DIY {CATEGORY_LABEL[category]} \u00b7 30% top \u00b7 50% heart \u00b7 20% base"
    f_sub = fit_font("cormorant-italic", sub, 900, 60, start=40, min_size=18)
    _assert_fit(sub, f_sub, 900, "subline")
    draw_lines_center(d, CX, 392, [sub], f_sub, fill=INK_SOFT)

    # --- pyramid (stepped, centered) ----------------------------------------
    block_h = 320
    level_w = [520, 800, 1060]
    block_tops = [560, 900, 1240]
    note_sets = [sp["top_notes"], sp["heart_notes"], sp["base_notes"]]
    pcts = ["30%", "50%", "20%"]
    for i, (label, fill, edge, tcol) in enumerate(PAL):
        x0 = CX - level_w[i] / 2
        _pyramid_block(d, CX, x0, block_tops[i], block_h, label,
                       ", ".join(note_sets[i]), pcts[i], fill, edge, tcol, accent)
        if i < 2:
            # dashed connectors into the next level
            xl0, xr0 = CX - level_w[i] / 2, CX + level_w[i] / 2
            xl1, xr1 = CX - level_w[i + 1] / 2, CX + level_w[i + 1] / 2
            y_up, y_low = block_tops[i] + block_h, block_tops[i + 1]
            dashed_line(d, (xl0 + 30, y_up, xl1 + 40, y_low), dash=12, gap=8,
                        fill=(*accent, 170), width=3)
            dashed_line(d, (xr0 - 30, y_up, xr1 - 40, y_low), dash=12, gap=8,
                        fill=(*accent, 170), width=3)

    # --- CTA area ------------------------------------------------------------
    cta_y = 1690
    f_cta = fit_font("lato-900", STORY_CTA, 700, 90, start=44, min_size=22)
    _assert_fit(STORY_CTA, f_cta, 700, "CTA")
    pill_box(d, CX, cta_y, text_w(f_cta, STORY_CTA) + 190, 108,
             outline=accent, fill=(246, 241, 229), width=4)
    draw_tracked_at(d, CX, cta_y - 6, STORY_CTA, f_cta, fill=INK,
                    tracking=5, anchor_vert="a")
    draw_lines_center(d, CX, cta_y + 78,
                      ["Full recipe + measurements on the product page"],
                      load_font("cormorant-italic", 36), fill=INK_SOFT)

    # --- brand handle placeholder --------------------------------------------
    m = 90
    d.line((m, 1836, CX - 110, 1836), fill=(*GOLD, 200), width=3)
    d.line((CX + 110, 1836, W - m, 1836), fill=(*GOLD, 200), width=3)
    diamond(d, CX, 1836, 7, GOLD)
    f_handle = load_font("lato-700", 36)
    draw_tracked_at(d, CX, 1876, BRAND_HANDLE, f_handle, fill=GOLD_DARK,
                    tracking=4, anchor_vert="a")
    return img