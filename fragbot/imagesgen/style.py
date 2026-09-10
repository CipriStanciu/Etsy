"""Palette, category and theme definitions for the listing images.

The design system is deliberately narrow so all five images of a listing feel
like one brand: a dark "hero" canvas with gold accents, cream/white canvases
for the informational images, and a soft gradient for the lifestyle shot.

``theme`` (recipe JSON extension) nudges the hero's gold accent colour
slightly, per the owner spec ("theme can drive the hero's accent color choice
slightly") — all accents stay in the gold family so the brand stays coherent.
"""

from __future__ import annotations

# --- core palette -----------------------------------------------------------
DARK = (26, 26, 26)             # #1a1a1a hero background
DARK_RAISED = (37, 37, 37)      # slightly lighter panels on dark
GOLD = (212, 175, 55)           # #d4af37 default gold
GOLD_LIGHT = (232, 205, 122)    # brighter gold for text on dark
GOLD_DARK = (168, 133, 38)      # darker gold for text on light backgrounds
GOLD_LINE = (170, 140, 60)      # muted gold for accent lines
CREAM = (250, 247, 240)         # #faf7f0 light canvas
CREAM_DEEP = (240, 234, 220)
INK = (43, 38, 33)              # near-black warm brown for text on light
INK_SOFT = (110, 100, 88)       # secondary text on light
WHITE = (255, 255, 255)

# --- per-theme hero accents (gold family, slight variation) -----------------
THEME_ACCENTS = {
    "Monday Mood": (235, 190, 84),        # bright citrus gold
    "Cozy Tuesday": (214, 142, 58),       # warm amber gold
    "Wellness Wednesday": (196, 182, 110),# soft sage gold
    "Date Night": (208, 148, 124),        # rose gold
    "Friday Luxe": (233, 203, 112),       # champagne gold
    "Weekend Project": (216, 170, 70),    # honey gold
    "Sunday Reset": (206, 196, 152),      # pale clean gold
}
DEFAULT_ACCENT = GOLD

# --- category vocabulary ----------------------------------------------------
CATEGORY_LABEL = {
    "perfume": "Perfume",
    "cologne": "Cologne",
    "candle": "Candle",
    "reed_diffuser": "Reed Diffuser",
    "room_spray": "Room Spray",
    "solid_perfume": "Solid Perfume",
}
CATEGORY_TAGLINE = {
    "perfume": "Roll-On Perfume",
    "cologne": "Eau de Cologne",
    "candle": "Soy Candle",
    "reed_diffuser": "Reed Diffuser",
    "room_spray": "Room Spray",
    "solid_perfume": "Solid Perfume Tin",
}

DIFFICULTY_LABEL = {
    "beginner": "Beginner",
    "intermediate": "Intermediate",
    "advanced": "Advanced",
}

# --- scent pyramid palette --------------------------------------------------
PYRAMID_TOP_FILL = (242, 231, 205)        # soft champagne pastel
PYRAMID_TOP_EDGE = (214, 194, 152)
PYRAMID_HEART_FILL = (217, 160, 91)       # warm amber
PYRAMID_HEART_EDGE = (188, 132, 62)
PYRAMID_BASE_FILL = (110, 78, 46)         # deep espresso
PYRAMID_BASE_EDGE = (86, 58, 31)

PYRAMID_LEVEL_META = [
    # (key, label, fill, edge, text_color, side_text)
    ("top", "TOP", PYRAMID_TOP_FILL, PYRAMID_TOP_EDGE, (74, 58, 40), "FIRST IMPRESSION"),
    ("heart", "HEART", PYRAMID_HEART_FILL, PYRAMID_HEART_EDGE, (250, 245, 236), "THE SOUL OF THE SCENT"),
    ("base", "BASE", PYRAMID_BASE_FILL, PYRAMID_BASE_EDGE, (246, 240, 230), "THE FOUNDATION"),
]

# purpose tag colors for the ingredient list (light background)
PURPOSE_META = {
    "carrier": ("Carrier", (160, 150, 132)),
    "top": ("Top Note", (200, 150, 60)),
    "heart": ("Heart Note", (190, 100, 60)),
    "base": ("Base Note", (110, 78, 46)),
}


def accent_for_theme(theme: str | None) -> tuple:
    """Gold accent for a recipe's 7-day theme (fall back to default gold)."""
    if theme and theme in THEME_ACCENTS:
        return THEME_ACCENTS[theme]
    return DEFAULT_ACCENT


def hex_to_rgb(hexcolor: str) -> tuple:
    h = hexcolor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))