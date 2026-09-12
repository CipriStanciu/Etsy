"""Fragrance Bot promo engine.

Auto-generated social promotion content for each recipe — all Pillow /
stdlib, no network, matching the listing-image brand:

    pin.jpg       — 1000x1500 Pinterest pin (dark hero + gold accents)
    story.jpg     — 1080x1920 Instagram story (scent-pyramid visual)
    tiktok.txt    — 15-second voiceover script + 3-shot shot list
    email.txt     — 2-sentence newsletter teaser + subject line

    from fragbot.promo import generate_all
    paths = generate_all(recipe, "promo-out/", brand="Fragrance Bot")

CLI:  python3 -m fragbot.promo --help
"""

from __future__ import annotations

__version__ = "0.1.0"

from .render import OUTPUT_FILES, generate_all
from .email import email_teaser
from .pin import render_pin
from .story import render_story
from .tiktok import tiktok_script

__all__ = [
    "OUTPUT_FILES",
    "generate_all",
    "render_pin",
    "render_story",
    "tiktok_script",
    "email_teaser",
    "__version__",
]