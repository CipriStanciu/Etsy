"""The five Etsy listing images — rendered with Pillow primitives only.

Every renderer takes the recipe JSON dict (validated against
``fragbot.schema``) plus the brand name and returns a 2000x2000 RGB image.
Output naming is fixed so downstream automation (Etsy upload) can rely on it:

    hero.jpg          — elegant dark hero card
    ingredients.jpg   — ingredient breakdown with measurements
    pyramid.jpg       — visual scent pyramid (top / heart / base)
    included.jpg      — checklist of what's in the download
    lifestyle.jpg     — category product shot + headline, brand watermark

All five are saved as JPEG, quality 88-92, 300 DPI, sRGB (ICC embedded when
the platform provides one; skipped cleanly otherwise). Rendering is fully
deterministic: same recipe JSON + same brand -> identical pixels.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

from ..schema import assert_valid
from .draw import (
    botanical_flourish,
    composite_glow,
    dashed_line,
    diamond,
    draw_check_mark,
    draw_circle_icon,
    draw_droplet,
    draw_heart,
    draw_lines_center,
    draw_product_motif,
    draw_tracked_at,
    fit_font,
    fit_wrapped_font,
    new_canvas,
    pill_box,
    radial_glow_mask,
    save_jpeg,
    text_w,
    vertical_gradient,
    wrap_text,
)
from .fonts import font as load_font
from .style import (
    CATEGORY_LABEL,
    CREAM,
    DARK,
    DIFFICULTY_LABEL,
    GOLD,
    GOLD_DARK,
    GOLD_LIGHT,
    GOLD_LINE,
    INK,
    INK_SOFT,
    PURPOSE_META,
    PYRAMID_BASE_EDGE,
    PYRAMID_BASE_FILL,
    PYRAMID_HEART_EDGE,
    PYRAMID_HEART_FILL,
    PYRAMID_TOP_EDGE,
    PYRAMID_TOP_FILL,
    accent_for_theme,
)

log = logging.getLogger("fragbot.imagesgen")

OUTPUT_FILES = ["hero.jpg", "ingredients.jpg", "pyramid.jpg", "included.jpg", "lifestyle.jpg"]
CANVAS_SIZE = (2000, 2000)

# product motif body colour by category (lifestyle image)
MOTIF_BODY = {
    "perfume": (43, 38, 33),
    "cologne": (43, 38, 33),
    "candle": (245, 238, 222),
    "reed_diffuser": (43, 38, 33),
    "room_spray": (43, 38, 33),
    "solid_perfume": (232, 222, 200),
}


def _D(img: Image.Image) -> ImageDraw.ImageDraw:
    """ImageDraw in RGBA mode so alpha-blended colours merge properly."""
    return ImageDraw.Draw(img, "RGBA")


# ===========================================================================
# shared bits
# ===========================================================================
def _eyebrow(d: ImageDraw.ImageDraw, cx: float, y: float, text: str,
             size: int = 34, fill=GOLD_DARK, tracking: float = 10) -> None:
    f = load_font("lato-700", size)
    draw_tracked_at(d, cx, y, text.upper(), f, fill=fill, tracking=tracking, anchor_vert="a")


def _rule_with_diamond(
    d: ImageDraw.ImageDraw, cx: float, y: float,
    half: float = 210, color=GOLD, width: int = 4, diamond_r: int = 8,
) -> None:
    d.line((cx - half, y, cx - diamond_r * 2 - 6, y), fill=color, width=width)
    d.line((cx + half, y, cx + diamond_r * 2 + 6, y), fill=color, width=width)
    diamond(d, cx, y, diamond_r, color)


def _corner_lines(d: ImageDraw.ImageDraw, color=GOLD, width: int = 4) -> None:
    """Thin gold corner accents used on the hero canvas."""
    m, L = 64, 150
    W, H = CANVAS_SIZE
    for x0, y0, sx, sy in ((m, m, 1, 1), (W - m - L, m, -1, 1),
                           (m, H - m - L, 1, -1), (W - m - L, H - m - L, -1, -1)):
        d.line((x0, y0, x0 + L * sx, y0), fill=color, width=width)
        d.line((x0, y0, x0, y0 + L * sy), fill=color, width=width)
        diamond(d, x0 + L * sx, y0 + L * sy, 7, color)


def _brand_footer(d: ImageDraw.ImageDraw, brand: str, y: int = 1895,
                  color=INK_SOFT, size: int = 26) -> None:
    f = load_font("lato-700", size)
    draw_tracked_at(d, CANVAS_SIZE[0] / 2, y, f"{brand.upper()} \u00b7 DIY SCENT STUDIO",
                    f, fill=color, tracking=8, anchor_vert="a")


def _pill_text(d: ImageDraw.ImageDraw, cx: float, cy: float, text: str,
               font: ImageFont.FreeTypeFont, text_fill, outline, outline_w: int = 3,
               fill=None, pad_x: float = 46, pad_y: float = 24) -> None:
    tw = text_w(font, text)
    asc, desc = font.getmetrics()
    w = tw + pad_x * 2
    h = asc + desc + pad_y * 2
    pill_box(d, cx, cy, w, h, outline=outline, fill=fill, width=outline_w)
    d.text((cx, cy), text, font=font, fill=text_fill, anchor="mm")


# ===========================================================================
# 1. hero.jpg — elegant dark hero card
# ===========================================================================
def render_hero(recipe: dict, brand: str = "Fragrance Bot") -> Image.Image:
    name = recipe["recipe_name"]
    category = recipe["category"]
    accent = accent_for_theme(recipe.get("theme"))
    holiday = recipe.get("holiday")

    img = vertical_gradient(CANVAS_SIZE, DARK, (36, 36, 36))
    img = composite_glow(img, radial_glow_mask(CANVAS_SIZE, (1000, 850), 950, 0.07), accent)
    d = _D(img)

    _corner_lines(d, color=accent, width=4)

    # --- top-left badge
    _pill_text(d, 300, 118, "DIY FRAGRANCE RECIPE", load_font("lato-700", 30),
               text_fill=GOLD_LIGHT, outline=accent, outline_w=3)

    # --- top-right: holiday badge or theme tag
    if holiday:
        f_hol = load_font("lato-700", 30)
        htxt = f"{holiday.upper()} EDITION"
        pill_cx = CANVAS_SIZE[0] - 320
        hw = text_w(f_hol, htxt) + 140
        pill_box(d, pill_cx, 118, hw, 66, outline=accent, width=3, fill=(48, 40, 30))
        draw_heart(d, pill_cx - hw / 2 + 56, 118, 28, accent)
        d.text((pill_cx + 26, 118), htxt, font=f_hol, fill=GOLD_LIGHT, anchor="mm")
    else:
        theme = recipe.get("theme")
        if theme:
            f_th = load_font("lato-700", 26)
            draw_tracked_at(d, CANVAS_SIZE[0] - 260, 118, theme.upper(), f_th,
                            fill=accent, tracking=8, anchor_vert="a")

    # --- center block
    _eyebrow(d, 1000, 430, f"{CATEGORY_LABEL[category].upper()} RECIPE",
             size=38, fill=GOLD_LIGHT, tracking=16)

    f_name = fit_wrapped_font("playfair-900", name, 1780, 500, start=230, min_size=60)
    asc, desc = f_name.getmetrics()
    name_lines = wrap_text(name, f_name, 1780)
    name_block_h = len(name_lines) * (asc + desc + 25)
    draw_lines_center(d, 1000, 515, name_lines, f_name, fill=(247, 243, 234), line_gap=25)

    divider_y = 515 + name_block_h + 40
    _rule_with_diamond(d, 1000, divider_y, half=250, color=accent, diamond_r=9)

    notes_y = divider_y + 88
    sp = recipe["scent_profile"]
    note_lines = [f"Top: {', '.join(sp['top_notes'])}",
                  f"Heart: {', '.join(sp['heart_notes'])}",
                  f"Base: {', '.join(sp['base_notes'])}"]
    for line in note_lines:
        f_line = fit_font("cormorant-italic", line, 1750, 130, start=58, min_size=24)
        draw_lines_center(d, 1000, notes_y, [line], f_line, fill=(235, 224, 196))
        notes_y += 96
    notes_y += 12

    # price pill
    price_txt = f"${recipe['price_usd']:.2f}"
    f_price = load_font("playfair-900", 112)
    pw = text_w(f_price, price_txt)
    price_cy = notes_y + 36
    pill_box(d, 1000, price_cy, pw + 190, 190, outline=accent, width=5, fill=(43, 40, 33))
    d.text((1000, price_cy), price_txt, font=f_price, fill=GOLD_LIGHT, anchor="mm")

    # difficulty / yield / cost line
    sub = (f"{DIFFICULTY_LABEL[recipe['difficulty']]} \u00b7 "
           f"{recipe['yield']} \u00b7 {recipe['cost_to_make']} to make")
    f_sub = fit_font("lato-regular", sub, 1720, 110, start=36, min_size=18)
    draw_lines_center(d, 1000, price_cy + 158, [sub], f_sub, fill=(196, 186, 162))

    # botanical flourishes
    botanical_flourish(img, "bl", accent, scale=1.0, alpha=80)
    botanical_flourish(img, "br", accent, scale=1.0, alpha=80)

    # watermarks
    draw_tracked_at(d, 1000, 1900, "DIGITAL DOWNLOAD", load_font("lato-900", 30),
                    fill=(255, 255, 255, 72), tracking=18, anchor_vert="a")
    d.text((1000, 1948), brand, font=load_font("cormorant-600", 34),
           fill=(*GOLD_LIGHT, 130), anchor="ma")
    return img


# ===========================================================================
# 2. ingredients.jpg — clean minimal ingredient breakdown
# ===========================================================================
def render_ingredients(recipe: dict, brand: str = "Fragrance Bot") -> Image.Image:
    name = recipe["recipe_name"]
    category = recipe["category"]
    accent = accent_for_theme(recipe.get("theme"))
    ings = recipe["ingredients"]

    img = new_canvas(fill=CREAM)
    d = _D(img)

    _rule_with_diamond(d, 1000, 150, half=90, color=GOLD, width=5, diamond_r=9)
    _eyebrow(d, 1000, 218, f"INGREDIENTS \u00b7 {CATEGORY_LABEL[category].upper()}",
             size=34, fill=GOLD_DARK, tracking=12)
    f_name = fit_font("playfair-700", name, 1600, 150, start=110, min_size=40)
    draw_lines_center(d, 1000, 290, [name], f_name, fill=INK)
    draw_lines_center(d, 1000, 420, ["Everything you need, measured exactly"],
                      load_font("cormorant-italic", 46), fill=INK_SOFT)

    # ingredient rows
    top, bottom = 540, 1620
    n = len(ings)
    row_h = min(172, (bottom - top) / n)
    f_purpose = load_font("lato-700", 24)
    for i, ing in enumerate(ings):
        y0 = top + row_h * i
        cy = y0 + row_h / 2
        # icon
        if ing["purpose"] == "carrier":
            draw_circle_icon(d, 250, cy, 46, fill=accent)
            d.ellipse((250 - 46, cy - 46, 250 + 46, cy + 46), outline=GOLD_DARK, width=5)
        else:
            draw_droplet(d, 250, cy, 52, fill=accent)
        # name
        f_name_row = fit_font("lato-700", ing["name"], 1050, row_h * 0.9,
                              start=52, min_size=24)
        d.text((380, cy - 16), ing["name"], font=f_name_row, fill=INK, anchor="lm")
        # purpose tag (bottom-anchored so it never collides with next row)
        purpose_label, purpose_color = PURPOSE_META[ing["purpose"]]
        draw_tracked_at(d, 392, y0 + row_h - 36, purpose_label.upper(), f_purpose,
                        fill=purpose_color, tracking=3, anchor_vert="d")
        # amount, right aligned
        f_amount = fit_font("lato-900", ing["amount"], 420, row_h * 0.55,
                            start=52, min_size=24)
        d.text((1748, cy - 16), ing["amount"], font=f_amount, fill=GOLD_DARK, anchor="rm")
        # hairline divider
        if i < n - 1:
            d.line((360, y0 + row_h, 1740, y0 + row_h), fill=(232, 226, 212), width=3)

    # Makes callout
    callout_cy = 1758
    yield_text = f"Makes {recipe['yield']}"
    f_yield = fit_font("playfair-700", yield_text, 1380, 120, start=52, min_size=22)
    d.rounded_rectangle((250, callout_cy - 92, 1750, callout_cy + 92),
                        radius=26, outline=GOLD, width=4, fill=(246, 241, 229))
    d.text((1000, callout_cy - 24), yield_text, font=f_yield, fill=INK, anchor="mm")
    d.text((1000, callout_cy + 42), f"Cost to make: {recipe['cost_to_make']}",
           font=load_font("cormorant-italic", 40), fill=GOLD_DARK, anchor="mm")

    _brand_footer(d, brand)
    return img


# ===========================================================================
# 3. pyramid.jpg — visual scent pyramid
# ===========================================================================
def render_pyramid(recipe: dict, brand: str = "Fragrance Bot") -> Image.Image:
    name = recipe["recipe_name"]
    category = recipe["category"]
    accent = accent_for_theme(recipe.get("theme"))
    sp = recipe["scent_profile"]
    holiday = recipe.get("holiday")

    img = new_canvas(fill=CREAM)
    d = _D(img)

    _rule_with_diamond(d, 1000, 150, half=90, color=GOLD, width=5, diamond_r=9)
    _eyebrow(d, 1000, 218, f"SCENT PYRAMID \u00b7 {CATEGORY_LABEL[category].upper()}",
             size=34, fill=GOLD_DARK, tracking=12)
    f_name = fit_font("playfair-700", name, 1600, 150, start=104, min_size=40)
    draw_lines_center(d, 1000, 290, [name], f_name, fill=INK)
    draw_lines_center(d, 1000, 410,
                      ["How the blend unfolds \u2014 30% top \u00b7 50% heart \u00b7 20% base"],
                      load_font("cormorant-italic", 44), fill=INK_SOFT)

    # --- pyramid geometry (centered on x=1000)
    cx = 1000
    base_w = 1500
    level_h = 340
    block_tops = [560, 928, 1296]
    fracs = [0.34, 0.62, 1.00]
    blocks = [
        (0, PYRAMID_TOP_FILL, PYRAMID_TOP_EDGE, (74, 58, 40), "TOP NOTES",
         ", ".join(sp["top_notes"]), "FIRST IMPRESSION", "30%"),
        (1, PYRAMID_HEART_FILL, PYRAMID_HEART_EDGE, (255, 250, 240), "HEART NOTES",
         ", ".join(sp["heart_notes"]), "THE SOUL OF THE SCENT", "50%"),
        (2, PYRAMID_BASE_FILL, PYRAMID_BASE_EDGE, (247, 241, 230), "BASE NOTES",
         ", ".join(sp["base_notes"]), "THE FOUNDATION", "20%"),
    ]

    for idx, fill, edge, tcol, label, notes, side, pct in blocks:
        y_top = block_tops[idx]
        w = base_w * fracs[idx]
        x0, x1 = cx - w / 2, cx + w / 2
        d.rectangle((x0, y_top, x1, y_top + level_h), fill=fill)
        for ln in ((x0, y_top, x1, y_top), (x0, y_top + level_h, x1, y_top + level_h),
                   (x0, y_top, x0, y_top + level_h), (x1, y_top, x1, y_top + level_h)):
            d.line(ln, fill=edge, width=6)
        # side description (left, outside pyramid)
        draw_tracked_at(d, 148, y_top + 26, side, load_font("lato-700", 26),
                        fill=INK_SOFT, tracking=4, anchor_vert="a")
        # percentage (right, outside pyramid)
        d.text((1852, y_top + level_h / 2), pct, font=load_font("playfair-700", 56),
               fill=GOLD_DARK, anchor="mm")
        # level label + wrapped notes
        draw_tracked_at(d, cx, y_top + 52, label, load_font("playfair-700", 44),
                        fill=tcol, tracking=10, anchor_vert="a")
        inner_w = w - 70
        f_notes = fit_wrapped_font("cormorant-600", notes, inner_w,
                                   level_h - 130, start=56, min_size=16)
        nlines = wrap_text(notes, f_notes, inner_w)
        draw_lines_center(d, cx, y_top + 146, nlines, f_notes, fill=tcol, line_gap=12)

    # connecting blend lines in the gaps
    for i in range(2):
        w0, w1 = base_w * fracs[i], base_w * fracs[i + 1]
        y_up, y_low = block_tops[i] + level_h, block_tops[i + 1]
        xl0, xr0 = cx - w0 / 2, cx + w0 / 2
        xl1, xr1 = cx - w1 / 2, cx + w1 / 2
        dashed_line(d, (xl0 + 40, y_up, xl1 + 60, y_low), dash=14, gap=10,
                    fill=(*accent[:3], 190), width=3)
        dashed_line(d, (xr0 - 40, y_up, xr1 - 60, y_low), dash=14, gap=10,
                    fill=(*accent[:3], 190), width=3)
        diamond(d, xl1 + 60, y_low, 7, accent)
        diamond(d, xr1 - 60, y_low, 7, accent)

    # category chip + holiday badge
    chip_y = 1742
    f_chip = load_font("lato-700", 32)
    _pill_text(d, cx, chip_y, CATEGORY_LABEL[category].upper(), f_chip,
               text_fill=GOLD_DARK, outline=GOLD, outline_w=3, pad_x=42, pad_y=20)
    if holiday:
        _pill_text(d, cx + 340, chip_y, f"{holiday.upper()} EDITION", f_chip,
                   text_fill=GOLD_DARK, outline=accent, outline_w=3, pad_x=42, pad_y=20)
    _brand_footer(d, brand)
    return img


# ===========================================================================
# 4. included.jpg — what's included checklist
# ===========================================================================
INCLUDED_ITEMS = [
    ("PDF Recipe Card", "Beautifully formatted \u2014 print it or follow on any device"),
    ("Step-by-Step Instructions", "Clear, beginner-friendly steps from start to finish"),
    ("Safety Guidelines", "IFRA-sensible usage, storage and essential-oil safety notes"),
    ("Ingredient Sourcing Tips", "Where to find quality oils and supplies"),
]


def render_included(recipe: dict, brand: str = "Fragrance Bot") -> Image.Image:
    name = recipe["recipe_name"]
    accent = accent_for_theme(recipe.get("theme"))

    img = new_canvas(fill=CREAM)
    d = _D(img)

    _rule_with_diamond(d, 1000, 150, half=90, color=GOLD, width=5, diamond_r=9)
    _eyebrow(d, 1000, 218, "WHAT'S INCLUDED", size=34, fill=GOLD_DARK, tracking=14)
    f_name = fit_font("playfair-700", name, 1600, 140, start=96, min_size=36)
    draw_lines_center(d, 1000, 290, [name], f_name, fill=INK)
    draw_lines_center(d, 1000, 408, ["Your instant digital download"],
                      load_font("cormorant-italic", 44), fill=INK_SOFT)

    # checklist rows
    row_top, row_h = 520, 235
    f_item = fit_font("lato-700", max(t for t, _ in INCLUDED_ITEMS), 1250, 120,
                      start=56, min_size=24)
    f_detail = load_font("cormorant-italic", 38)
    for i, (title, detail) in enumerate(INCLUDED_ITEMS):
        cy = row_top + row_h * i + row_h / 2
        d.ellipse((330 - 52, cy - 76, 330 + 52, cy + 76), fill=accent)
        draw_check_mark(d, 330 - 26, cy - 44, 330 + 26, cy + 44, fill=(255, 252, 245),
                        width=10)
        d.text((492, cy - 34), title, font=f_item, fill=INK, anchor="lm")
        d.text((492, cy + 44), detail, font=f_detail, fill=INK_SOFT, anchor="la")

    # price / difficulty / instant download tiles
    tile_cy = 1670
    tiles = [
        (f"${recipe['price_usd']:.2f}", "PRICE", "playfair-900", 82, GOLD_DARK),
        (DIFFICULTY_LABEL[recipe["difficulty"]], "SKILL LEVEL", "lato-700", 48, INK),
        ("INSTANT DOWNLOAD", "DELIVERY", "lato-900", 34, GOLD_DARK),
    ]
    for (tval, tlab, tfont, tsize, tcol), x in zip(tiles, (620, 1000, 1400)):
        d.rounded_rectangle((x - 255, tile_cy - 96, x + 255, tile_cy + 96),
                            radius=24, outline=GOLD, width=4, fill=(246, 241, 229))
        draw_tracked_at(d, x, tile_cy - 56, tlab, load_font("lato-700", 26),
                        fill=INK_SOFT, tracking=6, anchor_vert="a")
        f_val = fit_font(tfont, tval, 430, 90, start=tsize, min_size=18)
        d.text((x, tile_cy + 34), tval, font=f_val, fill=tcol, anchor="mm")

    draw_lines_center(d, 1000, 1830,
                      ["Digital item \u2014 nothing ships, no waiting, no shipping fees."],
                      load_font("cormorant-italic", 40), fill=INK_SOFT)
    _brand_footer(d, brand)
    return img


# ===========================================================================
# 5. lifestyle.jpg — signature-scent lifestyle card
# ===========================================================================
def render_lifestyle(recipe: dict, brand: str = "Fragrance Bot") -> Image.Image:
    name = recipe["recipe_name"]
    category = recipe["category"]
    accent = accent_for_theme(recipe.get("theme"))
    sp = recipe["scent_profile"]

    img = vertical_gradient(CANVAS_SIZE, (253, 248, 240), (236, 210, 186))
    img = composite_glow(img, radial_glow_mask(CANVAS_SIZE, (1000, 1250), 800, 0.20), accent)
    d = _D(img)

    # faint diagonal brand watermark
    wm_layer = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    wd = ImageDraw.Draw(wm_layer)
    wd.text((1000, 1000), brand, font=load_font("playfair-italic", 320),
            fill=(*INK, 16), anchor="mm")
    wm_layer = wm_layer.rotate(-24, resample=Image.Resampling.BICUBIC)
    img.paste(wm_layer, (0, 0), wm_layer)

    # badges top corners
    _pill_text(d, 290, 118, "DIY FRAGRANCE RECIPE", load_font("lato-700", 28),
               text_fill=GOLD_DARK, outline=GOLD, outline_w=3)
    _pill_text(d, CANVAS_SIZE[0] - 300, 118, f"{CATEGORY_LABEL[category].upper()} RECIPE",
               load_font("lato-700", 28), text_fill=GOLD_DARK, outline=accent, outline_w=3)

    # headline (wrapped) + sub line
    headline = "Create Your Signature Scent at Home"
    f_h = fit_wrapped_font("playfair-700", headline, 1780, 300, start=118, min_size=40)
    asc, desc = f_h.getmetrics()
    hlines = wrap_text(headline, f_h, 1780)
    draw_lines_center(d, 1000, 300, hlines, f_h, fill=INK, line_gap=18)
    sub_y = 300 + len(hlines) * (asc + desc + 18) + 48
    theme = recipe.get("theme") or "Made at Home"
    draw_lines_center(d, 1000, sub_y, [f"DIY {CATEGORY_LABEL[category]} \u00b7 {theme}"],
                      load_font("cormorant-italic", 52), fill=INK_SOFT)

    # floating note pills FIRST so the product motif covers the line ends
    notes_pos = [(sp["top_notes"][0], 590, 1330),
                 (sp["heart_notes"][0], 1430, 1200),
                 (sp["base_notes"][0], 1330, 800)]
    f_pill = load_font("cormorant-600", 36)
    for note, nx, ny in notes_pos:
        dashed_line(d, (nx, ny + 66, 1000, 1400), dash=10, gap=8,
                    fill=(*accent[:3], 130), width=3)
        _pill_text(d, nx, ny, note, f_pill, text_fill=INK, outline=accent,
                   outline_w=3, pad_x=40, pad_y=18)

    # product motif
    label_text = name if len(name) <= 18 else ""
    draw_product_motif(img, category, 1000, 1560, 560, MOTIF_BODY.get(category, INK),
                       accent, label_text)

    # brand watermark
    d.text((1000, 1790), brand, font=load_font("playfair-700", 74), fill=INK, anchor="mm")
    draw_tracked_at(d, 1000, 1862, "DIY SCENT STUDIO", load_font("lato-700", 26),
                    fill=INK_SOFT, tracking=12, anchor_vert="a")
    return img


# ===========================================================================
# public API
# ===========================================================================
RENDERERS = {
    "hero": render_hero,
    "ingredients": render_ingredients,
    "pyramid": render_pyramid,
    "included": render_included,
    "lifestyle": render_lifestyle,
}


def render_one(recipe: dict, kind: str, brand: str = "Fragrance Bot") -> Image.Image:
    """Render a single image kind ('hero', 'ingredients', ...) for a recipe."""
    if kind not in RENDERERS:
        raise ValueError(f"unknown image kind {kind!r}; known: {sorted(RENDERERS)}")
    return RENDERERS[kind](recipe, brand)


def render_recipe(
    recipe: dict,
    out_dir: str | Path,
    brand: str = "Fragrance Bot",
    quality: int = 90,
    kinds: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Render all five listing images for a recipe into ``out_dir``.

    Returns ``{kind: absolute_path}`` for the generated JPEGs. Validates the
    recipe against the engine schema first; raises ValueError on invalid input.
    """
    assert_valid(recipe)
    kinds = kinds or list(RENDERERS)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    results: Dict[str, str] = {}
    for kind in kinds:
        img = render_one(recipe, kind, brand=brand)
        path = out / f"{kind}.jpg"
        save_jpeg(img, str(path), quality=quality)
        results[kind] = str(path)
    return results