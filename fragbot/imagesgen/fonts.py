"""Font loading for the image generator.

All fonts are VENDORED inside this package (``fragbot/imagesgen/fonts/``) so
rendering needs no network at runtime or CI time. Every font is free / open
source:

- Playfair Display  — SIL OFL 1.1  (Google Fonts)
- Lato              — SIL OFL 1.1  (Google Fonts, tyPoland)
- Cormorant Garamond — SIL OFL 1.1 (Google Fonts, Catharsis Fonts)

OFL licence files are vendored next to the TTFs.

Fallback chain (belt-and-braces — should never trigger because fonts ship in
the package): vendored path -> a handful of common system free-font paths
(DejaVu / Liberation, both free) -> error surface. We never silently fall back
to a paid font.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from PIL import ImageFont

log = logging.getLogger("fragbot.imagesgen")

FONT_DIR = Path(__file__).resolve().parent / "fonts"

# Canonical names -> vendored file names.
FONT_FILES = {
    "playfair-regular": "playfair-display-regular.ttf",
    "playfair-italic": "playfair-display-italic.ttf",
    "playfair-700": "playfair-display-700.ttf",
    "playfair-900": "playfair-display-900.ttf",
    "lato-regular": "lato-regular.ttf",
    "lato-italic": "lato-italic.ttf",
    "lato-700": "lato-700.ttf",
    "lato-900": "lato-900.ttf",
    "cormorant-regular": "cormorant-regular.ttf",
    "cormorant-500": "cormorant-500.ttf",
    "cormorant-600": "cormorant-600.ttf",
    "cormorant-700": "cormorant-700.ttf",
    "cormorant-italic": "cormorant-italic.ttf",
}

# Free system fonts used as an emergency fallback if the vendored files are
# ever missing from the checkout.
_SYSTEM_FALLBACKS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    "/Library/Fonts/Arial.ttf",  # macOS — free OS font, emergency only
    "C:\\Windows\\Fonts\\arial.ttf",  # Windows — free OS font, emergency only
]

_lock = threading.Lock()
_cache: dict = {}


def available_fonts() -> list:
    """Return the list of vendored font names that exist on disk."""
    return sorted(n for n in FONT_FILES if (FONT_DIR / FONT_FILES[n]).is_file())


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a font by canonical name and size (cached per (name, size))."""
    key = (name, int(size))
    with _lock:
        if key in _cache:
            return _cache[key]
        f = _load(name, size)
        _cache[key] = f
        return f


def _load(name: str, size: int) -> ImageFont.FreeTypeFont:
    if name not in FONT_FILES:
        raise ValueError(f"unknown font name {name!r}; known: {sorted(FONT_FILES)}")

    path = FONT_DIR / FONT_FILES[name]
    if path.is_file():
        return ImageFont.truetype(str(path), size)

    # Emergency fallback: an equally free system font, with a loud warning.
    for sys_path in _SYSTEM_FALLBACKS:
        if os.path.isfile(sys_path):
            log.warning(
                "vendored font %s missing (%s); falling back to free system font %s",
                name, path, sys_path,
            )
            return ImageFont.truetype(sys_path, size)

    raise FileNotFoundError(
        f"font {name!r} is neither vendored ({path}) nor available as a "
        f"free system font; refusing to substitute a non-free font"
    )