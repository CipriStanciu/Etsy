"""Promo engine orchestration: generate all four social assets per recipe.

Public API mirrors ``fragbot.imagesgen.render``:

    from fragbot.promo import generate_all
    paths = generate_all(recipe, "promo-out/", brand="Fragrance Bot")

writes four files (owner spec):
    pin.jpg       — 1000x1500  Pinterest pin (dark hero card language)
    story.jpg     — 1080x1920  Instagram story (scent-pyramid visual)
    tiktok.txt    — 15-second voiceover script + 3-shot shot list
    email.txt     — 2-sentence newsletter teaser + subject line

Deterministic: same recipe JSON + same brand -> byte-identical files.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

from ..imagesgen.draw import save_jpeg
from ..schema import assert_valid
from .email import email_teaser
from .pin import render_pin
from .story import render_story
from .style import BRAND, JPEG_QUALITY, OUTPUT_FILES
from .tiktok import tiktok_script

log = logging.getLogger("fragbot.promo")


def generate_all(
    recipe: dict,
    out_dir: str | Path,
    brand: str = BRAND,
    quality: int = JPEG_QUALITY,
) -> Dict[str, str]:
    """Generate the four promo assets for a recipe into ``out_dir``.

    Returns ``{kind: absolute_path}`` for pin.jpg, story.jpg, tiktok.txt
    and email.txt. Validates the recipe against the engine schema first;
    raises ValueError on invalid input.
    """
    assert_valid(recipe)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    img = render_pin(recipe, brand=brand, quality=quality)
    pin_path = out / "pin.jpg"
    save_jpeg(img, str(pin_path), quality=quality)

    img = render_story(recipe, brand=brand, quality=quality)
    story_path = out / "story.jpg"
    save_jpeg(img, str(story_path), quality=quality)

    tiktok_path = out / "tiktok.txt"
    tiktok_path.write_text(tiktok_script(recipe, brand=brand),
                           encoding="utf-8")

    email_path = out / "email.txt"
    email_path.write_text(email_teaser(recipe, brand=brand), encoding="utf-8")

    return {
        "pin": str(pin_path),
        "story": str(story_path),
        "tiktok": str(tiktok_path),
        "email": str(email_path),
    }


__all__ = ["generate_all", "OUTPUT_FILES"]