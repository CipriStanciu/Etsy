"""Font registration for the PDF generator.

The PDF generator re-uses the exact same VENDORED free TTFs that the listing
image generator ships (``fragbot/imagesgen/fonts/``), so the recipe card PDF
is typographically identical to the listing images and no network is ever
needed at render time. Every font is free / open source:

- Playfair Display  — SIL OFL 1.1  (Google Fonts)  — display / headings
- Lato              — SIL OFL 1.1  (Google Fonts)  — body text
- Cormorant Garamond — SIL OFL 1.1 (Google Fonts)  — elegant accents

Fonts are registered lazily with ReportLab under ``FB-<name>`` and the
registration is memoised, so importing/rendering many recipes in one process
never double-registers.
"""

from __future__ import annotations

import logging
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

log = logging.getLogger("fragbot.pdfgen")

# Canonical logical names -> vendored TTF file (same names/files as imagesgen).
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

# Public aliases the renderer uses, so call sites read cleanly.
PLAYFAIR_REG = "FB-playfair-regular"
PLAYFAIR_IT = "FB-playfair-italic"
PLAYFAIR_BOLD = "FB-playfair-700"
PLAYFAIR_BLACK = "FB-playfair-900"
LATO_REG = "FB-lato-regular"
LATO_IT = "FB-lato-italic"
LATO_BOLD = "FB-lato-700"
LATO_BLACK = "FB-lato-900"
CORMORANT_REG = "FB-cormorant-regular"
CORMORANT_MED = "FB-cormorant-500"
CORMORANT_SEMI = "FB-cormorant-600"
CORMORANT_BOLD = "FB-cormorant-700"
CORMORANT_IT = "FB-cormorant-italic"

_registered: set = set()


def _font_dir() -> Path:
    # fragbot/pdfgen/fonts.py -> fragbot/imagesgen/fonts/
    return Path(__file__).resolve().parent.parent / "imagesgen" / "fonts"


def register_all() -> None:
    """Register every vendored TTF with ReportLab (idempotent)."""
    missing: list = []
    for name, fname in FONT_FILES.items():
        registered_name = f"FB-{name}"
        if registered_name in _registered:
            continue
        path = _font_dir() / fname
        if not path.is_file():
            missing.append(str(path))
            continue
        pdfmetrics.registerFont(TTFont(registered_name, str(path)))
        _registered.add(registered_name)
    if missing:
        raise FileNotFoundError(
            "PDF generator fonts missing (vendored TTFs must live in "
            f"fragbot/imagesgen/fonts/): {missing}"
        )


def available() -> list:
    """Names of the vendored fonts found on disk (for diagnostics)."""
    return sorted(n for n in FONT_FILES if (_font_dir() / FONT_FILES[n]).is_file())