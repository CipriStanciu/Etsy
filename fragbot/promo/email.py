"""Newsletter email teaser generator (text).

A two-sentence teaser derived from the recipe (name, top/heart/base notes,
price) with a deterministic subject line. Pure text; no rendering, no
network, no templating engine.
"""

from __future__ import annotations

from ..imagesgen.style import CATEGORY_LABEL, DIFFICULTY_LABEL
from .style import BRAND


def _price(recipe: dict) -> str:
    return f"${float(recipe['price_usd']):.2f}"


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def email_teaser(recipe: dict, brand: str = BRAND) -> str:
    """Return the newsletter teaser (subject + exactly two sentences)."""
    name = recipe["recipe_name"]
    category_label = CATEGORY_LABEL[recipe["category"]]
    difficulty = DIFFICULTY_LABEL[recipe["difficulty"]]
    sp = recipe["scent_profile"]
    holiday = recipe.get("holiday")

    if holiday:
        subject = f"{name} \u2014 a {holiday} scent recipe"
    else:
        subject = f"{name} \u2014 a new DIY scent recipe"

    diff = difficulty.lower()
    sentence_1 = (
        f"{name} is {_article(diff)} {diff} {category_label.lower()} recipe "
        f"that opens with {', '.join(sp['top_notes'])}, blooms with "
        f"{', '.join(sp['heart_notes'])}, and settles on "
        f"{', '.join(sp['base_notes'])} at the base."
    )
    sentence_2 = (
        f"The complete recipe card with exact measurements is available now "
        f"for {_price(recipe)} in the shop."
    )

    return (
        f"Subject: {subject}\n"
        f"\n"
        f"{sentence_1}\n"
        f"{sentence_2}\n"
        f"\n"
        f"\u2014 {brand}\n"
    )