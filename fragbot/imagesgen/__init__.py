"""Fragrance Bot listing image generator.

Renders the five Etsy listing images (hero, ingredient breakdown, scent
pyramid, what's included, lifestyle) for a recipe JSON produced by the
recipe engine — Pillow only, no network at render time, free vendored fonts.

    from fragbot.imagesgen import render_recipe
    paths = render_recipe(recipe, "out/", brand="Fragrance Bot")

CLI:  python -m fragbot.imagesgen --help
"""

from __future__ import annotations

__version__ = "0.1.0"

from .render import RENDERERS, OUTPUT_FILES, render_one, render_recipe

__all__ = ["RENDERERS", "OUTPUT_FILES", "render_recipe", "render_one", "__version__"]