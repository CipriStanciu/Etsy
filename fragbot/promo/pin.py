"""Pinterest pin renderer (1000 x 1500, 2:3).

Uses the hero-card design language from the listing images — dark #1a1a1a
gradient, gold accents, Playfair Display for the recipe name — with the
promo overlay copy "Save this scent recipe" plus a price/difficulty badge
and the brand watermark. Pillow only; reuses the vendored fonts and the
shared palette/style helpers.

The layout is fully deterministic and text-fit is guarded at render time:
every text block is sized with the fit_font/fit_wrapped_font helpers and
then re-asserted against its box, so an unexpectedly long recipe name or
note list raises instead of silently overflowing the canvas.
"""

from __future__ import annotations

import logging

from PIL import Image, ImageDraw

from ..imagesgen.draw import (
    composite_glow,
    diamond,
    draw_lines_center,
    draw_heart,
    draw_tracked_at,
    fit_font,
    fit_wrapped_font,
    new_canvas,
    radial_glow_mask,
    save_jpeg,
    text_w,
    vertical_gradient,
    wrap_text,
)
from ..imagesgen.fonts import font as load_font
from ..imagesgen.style import (
    DARK,
    DIFFICULTY_LABEL,
    GOLD_LIGHT,
    accent_for_theme,
)
from .style import BRAND, BRAND_TAGLINE, PIN_SAVE_COPY, PIN_SIZE

log = logging.getLogger("fragbot.promo")

W, H = PIN_SIZE
CX = W / 2
_MARGIN = 58


def _D(img: Image.Image) -> ImageDraw.ImageDraw:
    return ImageDraw.Draw(img, "RGBA")


def _assert_fit(text: str, font, max_w: float, where: str) -> None:
    """Render-time overflow guard: raise if any line exceeds ``max_w``."""
    for ln in (text.split("\n") if "\n" in text else wrap_text(text, font, max_w)):
        w = text_w(font, ln)
        if w > max_w:
            raise ValueError(
                f"pin text overflow at {where}: {ln!r} is {w:.0f}px > {max_w:.0f}px"
            )


def _frame(img: Image.Image, accent) -> None:
    """Thin gold inner frame + corner brackets (subtle, brand-consistent)."""
    d = _D(img)
    m, L, t = 34, 110, 4
    for x0, y0, sx, sy in ((m, m, 1, 1), (W - m - L, m, -1, 1),
                           (m, H - m - L, 1, -1), (W - m - L, H - m - L, -1, -1)):
        d.line((x0, y0, x0 + L * sx, y0), fill=(*accent, 200), width=t)
        d.line((x0, y0, x0, y0 + L * sy), fill=(*accent, 200), width=t)
        diamond(d, x0 + L * sx, y0 + L * sy, 6, (*accent, 230))
    outline_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(outline_layer).rounded_rectangle(
        (m, m, W - m, H - m), radius=26, outline=(*accent, 90), width=2
    )
    img.paste(outline_layer, (0, 0), outline_layer)


def render_pin(recipe: dict, brand: str = BRAND, quality: int = 90) -> Image.Image:
    """Render the 1000x1500 Pinterest pin for a recipe (RGB image)."""
    name = recipe["recipe_name"]
    category = recipe["category"]
    difficulty = DIFFICULTY_LABEL[recipe["difficulty"]]
    accent = accent_for_theme(recipe.get("theme"))
    holiday = recipe.get("holiday")
    sp = recipe["scent_profile"]

    img = vertical_gradient(PIN_SIZE, DARK, (37, 37, 37))
    img = composite_glow(img, radial_glow_mask(PIN_SIZE, (CX, 660), 760, 0.09), accent)
    d = _D(img)
    _frame(img, accent)

    # --- top: brand eyebrow ------------------------------------------------
    f_brand = load_font("lato-700", 22)
    draw_tracked_at(d, CX, 74, f"{brand.upper()} \u00b7 {BRAND_TAGLINE}",
                    f_brand, fill=(*GOLD_LIGHT, 235), tracking=7, anchor_vert="a")

    # --- holiday pill (or theme tag) ----------------------------------------
    if holiday:
        f_hol = fit_font("lato-700", f"{holiday.upper()} EDITION", 520, 60,
                         start=30, min_size=16)
        htxt = f"{holiday.upper()} EDITION"
        hw = text_w(f_hol, htxt) + 46 + 76  # heart icon + padding
        hy = 132
        d.rounded_rectangle((CX - hw / 2, hy - 26, CX + hw / 2, hy + 26),
                            radius=26, outline=(*accent, 220), width=3,
                            fill=(48, 40, 30))
        draw_heart(d, CX - hw / 2 + 42, hy, 20, accent)
        d.text((CX + 12, hy), htxt, font=f_hol, fill=(*GOLD_LIGHT, 255), anchor="mm")
    elif recipe.get("theme"):
        f_th = fit_font("lato-700", recipe["theme"].upper(), 560, 56,
                        start=26, min_size=14)
        draw_tracked_at(d, CX, 132, recipe["theme"].upper(), f_th,
                        fill=(*accent, 230), tracking=6, anchor_vert="a")

    # --- headline: "SAVE THIS SCENT RECIPE" ---------------------------------
    f_head = load_font("lato-900", 40)
    draw_tracked_at(d, CX, 254, PIN_SAVE_COPY, f_head, fill=GOLD_LIGHT,
                    tracking=8, anchor_vert="a")
    for dx in (-402, 402):
        diamond(d, CX + dx, 254, 7, (*accent, 230))

    # --- recipe name (Playfair, fit-wrapped) --------------------------------
    name_top = 346
    f_name = fit_wrapped_font("playfair-900", name, W - 2 * _MARGIN, 430,
                              start=102, min_size=40, line_gap=20)
    name_lines = wrap_text(name, f_name, W - 2 * _MARGIN)
    asc, desc = f_name.getmetrics()
    block_h = len(name_lines) * (asc + desc) + 20 * (len(name_lines) - 1)
    draw_lines_center(d, CX, name_top, name_lines, f_name, fill=(247, 243, 234),
                      line_gap=20)
    _assert_fit(name, f_name, W - 2 * _MARGIN, "recipe_name")
    name_bottom = name_top + block_h

    # --- rule with diamond ---------------------------------------------------
    rule_y = name_bottom + 34
    d.line((CX - 250, rule_y, CX - 30, rule_y), fill=(*accent, 220), width=3)
    d.line((CX + 30, rule_y, CX + 250, rule_y), fill=(*accent, 220), width=3)
    diamond(d, CX, rule_y, 8, accent)

    # --- note lines -----------------------------------------------------------
    note_y = rule_y + 62
    note_lines = [f"Top \u00b7 {', '.join(sp['top_notes'])}",
                  f"Heart \u00b7 {', '.join(sp['heart_notes'])}",
                  f"Base \u00b7 {', '.join(sp['base_notes'])}"]
    for line in note_lines:
        f_line = fit_font("cormorant-italic", line, W - 2 * _MARGIN - 40, 76,
                          start=48, min_size=22)
        _assert_fit(line, f_line, W - 2 * _MARGIN - 40, "note line")
        draw_lines_center(d, CX, note_y, [line], f_line, fill=(235, 224, 196))
        asc, desc = f_line.getmetrics()
        note_y += asc + desc + 12
    note_y += 10

    # --- blend / yield / cost line -------------------------------------------
    info = (f"30% top \u00b7 50% heart \u00b7 20% base   \u2022   {recipe['yield']}"
            f"   \u2022   {recipe['cost_to_make']}")
    f_info = fit_font("cormorant-italic", info, W - 2 * _MARGIN, 66,
                      start=40, min_size=18)
    _assert_fit(info, f_info, W - 2 * _MARGIN, "yield/cost line")
    draw_lines_center(d, CX, note_y, [info], f_info, fill=(196, 186, 162))

    # --- price / difficulty badge --------------------------------------------
    badge_txt = f"${float(recipe['price_usd']):.2f}  \u00b7  {difficulty.upper()}"
    f_badge = fit_font("playfair-700", badge_txt, 580, 88, start=54, min_size=24)
    _assert_fit(badge_txt, f_badge, 580, "price badge")
    bw = text_w(f_badge, badge_txt)
    badge_cy = 1192
    d.rounded_rectangle((CX - bw / 2 - 58, badge_cy - 50, CX + bw / 2 + 58,
                         badge_cy + 50), radius=50, outline=(*accent, 255),
                        width=4, fill=(43, 40, 33))
    d.text((CX, badge_cy), badge_txt, font=f_badge, fill=(*GOLD_LIGHT, 255),
           anchor="mm")

    draw_tracked_at(d, CX, 1262, "DIGITAL DOWNLOAD", load_font("lato-900", 22),
                    fill=(255, 255, 255, 90), tracking=16, anchor_vert="a")

    # --- brand watermark ------------------------------------------------------
    d.line((_MARGIN + 30, 1340, CX - 90, 1340), fill=(*accent, 90), width=2)
    d.line((CX + 90, 1340, W - _MARGIN - 30, 1340), fill=(*accent, 90), width=2)
    diamond(d, CX, 1340, 6, (*accent, 150))
    d.text((CX, 1406), brand, font=load_font("cormorant-600", 44),
           fill=(*GOLD_LIGHT, 165), anchor="mm")
    return img