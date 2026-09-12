"""TikTok voiceover script generator (text only — no video rendering).

Derives a deterministic ~15-second voiceover script from a recipe JSON:
hook line, 3-4 spoken sentences covering what you'll make plus the
top/heart/base notes and difficulty/price, a "link in bio" CTA, and a
3-shot shot list for the creator. Pure text, fully deterministic for a
given recipe.
"""

from __future__ import annotations

from ..imagesgen.style import CATEGORY_LABEL, DIFFICULTY_LABEL
from .style import BRAND, TIKTOK_CTA


def _price(recipe: dict) -> str:
    return f"${float(recipe['price_usd']):.2f}"


def tiktok_script(recipe: dict, brand: str = BRAND) -> str:
    """Return the TikTok script text for a recipe (deterministic)."""
    name = recipe["recipe_name"]
    category_label = CATEGORY_LABEL[recipe["category"]]
    difficulty = DIFFICULTY_LABEL[recipe["difficulty"]]
    sp = recipe["scent_profile"]
    ings = recipe["ingredients"]
    n_ing = len(ings)
    top = ", ".join(sp["top_notes"])
    heart = ", ".join(sp["heart_notes"])
    base = ", ".join(sp["base_notes"])
    first_top = sp["top_notes"][0]

    hook = (
        f"{name} \u2014 a {category_label.lower()} you can blend "
        f"at home tonight."
    )
    body = (
        f"You'll need just {n_ing} ingredients, most of which are probably "
        f"already in your cupboard. {top} open the scent, {heart} carry the "
        f"heart, and {base} anchor the base \u2014 a classic 30/50/20 blend. "
        f"It's {difficulty.lower()}-friendly and costs "
        f"{recipe['cost_to_make']} to make."
    )
    cta = (
        f"The full recipe with exact drops and measures is in the "
        f"{TIKTOK_CTA}."
    )

    lines = [
        f"TIKTOK VOICEOVER SCRIPT \u2014 {name} ({category_label})",
        f"Brand: {brand} \u00b7 Runtime: ~15 seconds \u00b7 Deterministic, "
        "auto-generated from the recipe card",
        "=" * 72,
        "",
        f"HOOK (0-2s):",
        f'"{hook}"',
        "",
        "BODY (3-12s):",
        f'"{body}"',
        "",
        f"CTA (13-15s):",
        f'"{cta}"',
        "",
        "SHOT LIST (3 shots, for the creator):",
        f"1. (0-2s)  Close-up of the finished {category_label.lower()} "
        f"\u2014 text overlay: \u201c{name}\u201d.",
        f"2. (3-8s)  Hands measuring drops of {first_top} into the blend "
        f"\u2014 overlay: \u201c{n_ing} ingredients\u201d.",
        f"3. (9-15s) The finished {category_label.lower()} next to its label "
        f"\u2014 overlay: \u201c{_price(recipe)} recipe \u00b7 {TIKTOK_CTA}\u201d.",
        "",
        f"End card: {brand} \u00b7 new scent recipe every day.",
    ]
    return "\n".join(lines) + "\n"