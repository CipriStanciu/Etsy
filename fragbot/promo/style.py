"""Promo-engine constants: canvas sizes, fixed copy, brand placeholders.

Everything here mirrors the listing-image design system
(``fragbot/imagesgen/style.py``) — the palette and fonts are reused as-is so
the social assets feel like the same brand. Only the canvas sizes and the
social-specific call-to-action copy belong to the promo engine.
"""

from __future__ import annotations

# --- canvas sizes (owner spec) ---------------------------------------------
PIN_SIZE = (1000, 1500)          # Pinterest pin, 2:3
STORY_SIZE = (1080, 1920)        # Instagram story, 9:16

# --- fixed copy (owner spec) ------------------------------------------------
PIN_SAVE_COPY = "SAVE THIS SCENT RECIPE"
STORY_CTA = "SWIPE UP FOR RECIPE"
TIKTOK_CTA = "link in bio"
BRAND = "Fragrance Bot"
BRAND_HANDLE = "@FragranceBot"   # placeholder handle for the story footer
BRAND_TAGLINE = "DIY SCENT STUDIO"

# --- promo output file names (owner spec) -----------------------------------
OUTPUT_FILES = ["pin.jpg", "story.jpg", "tiktok.txt", "email.txt"]
JPEG_QUALITY = 90                # within the owner spec band 88-92 (save_jpeg)
MAX_BYTES = 5 * 1024 * 1024      # < 5 MB per image (owner spec)