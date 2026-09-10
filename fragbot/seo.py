"""SEO copy module: slug, full title, 13 tags, long description."""

from __future__ import annotations

import re
from typing import List

from . import ingredients as ig
from . import themes

# Exactly 9 generic tags; each category adds 4 more -> exactly 13 total.
GENERIC_TAGS = [
    "diy perfume",
    "fragrance recipe",
    "essential oil blend",
    "homemade scent",
    "digital download",
    "diy gift",
    "aromatherapy",
    "scent recipe",
    "handmade gift",
]

CATEGORY_TAGS = {
    "perfume": ["perfume making", "natural perfume", "roll on perfume", "perfume making kit"],
    "cologne": ["diy cologne", "cologne recipe", "mens cologne recipe", "fragrance for men"],
    "candle": ["candle making", "soy candle recipe", "candle crafting", "candle making kit"],
    "reed_diffuser": ["diy reed diffuser", "diffuser recipe", "home fragrance", "reed diffuser oil"],
    "room_spray": ["room spray diy", "homemade spray", "home fragrance", "linen spray diy"],
    "solid_perfume": ["solid perfume", "perfume balm", "natural perfume", "diy beauty"],
}


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


def make_slug(recipe_name: str, category: str) -> str:
    cat_slug = ig.CATEGORIES[category]["slug"]
    return f"{slugify(recipe_name)}-diy-{cat_slug}-recipe"


def _key_notes(recipe_name: str, scent_profile: dict) -> str:
    heart = scent_profile["heart_notes"]
    base = scent_profile["base_notes"]
    top = scent_profile["top_notes"]
    # Prefer a heart+base pairing like "Dark Vanilla & Smoked Oud".
    a = heart[0]
    b = base[0] if base else (heart[1] if len(heart) > 1 else None)
    if b and b != a:
        return f"{a} & {b}"
    return " & ".join([a, top[0]][:2])


def make_title(recipe_name: str, category: str, scent_profile: dict, d) -> str:
    base = f"DIY {recipe_name} {ig.CATEGORIES[category]['label']} Recipe | {_key_notes(recipe_name, scent_profile)} | {themes.occasion_phrase(d)} | Digital Download"
    if len(base) <= 140:
        return base
    # Trim the key-notes segment if needed.
    title = f"DIY {recipe_name} {ig.CATEGORIES[category]['label']} Recipe | {themes.occasion_phrase(d)} | Digital Download"
    if len(title) <= 140:
        return title
    return title[:137].rstrip() + "..." if len(title) > 140 else title


def make_tags(category: str) -> List[str]:
    tags: List[str] = []
    seen = set()
    for t in GENERIC_TAGS + CATEGORY_TAGS[category]:
        if t not in seen:
            seen.add(t)
            tags.append(t)
    assert len(tags) == 13, f"{category} produced {len(tags)} tags"
    for t in tags:
        assert len(t) <= 20, f"tag too long: {t!r}"
    return tags


def make_description(
    recipe_name: str,
    category: str,
    scent_profile: dict,
    theme: str,
    holiday,
    difficulty: str,
    yield_str: str,
    cost: str,
    safety_notes: List[str],
) -> str:
    cat = ig.CATEGORIES[category]
    label = cat["label"]
    vibe = themes.THEME_VIBE.get(theme, "")
    top = ", ".join(scent_profile["top_notes"])
    heart = ", ".join(scent_profile["heart_notes"])
    base = ", ".join(scent_profile["base_notes"])
    holiday_line = f" A special {holiday} edition." if holiday else ""

    hook = (
        f"About This Recipe\n"
        f"Create your own {recipe_name.lower()} — a {vibe} DIY {label.lower()} recipe "
        f"built around {heart} with {top} on top and {base} at the base. This digital recipe card "
        f"turns essential oil blending into a simple 20-minute project you can make at home "
        f"anytime.{holiday_line}"
    )

    what_you_get = (
        "What You Get\n"
        f"- Complete recipe card with exact measurements for a {yield_str} batch\n"
        "- Ready-to-use essential oil blend with a balanced 30% top / 50% heart / 20% base structure\n"
        "- Ingredient list with safe, IFRA-sensible usage amounts\n"
        "- Step-by-step instructions written for beginners\n"
        "- Safety notes and pro tips for the best results\n"
        "- Instant digital download — no physical items are shipped\n"
    )

    scent_profile_section = (
        "Scent Profile\n"
        f"Top: {top}\n"
        f"Heart: {heart}\n"
        f"Base: {base}\n"
        "The blend unfolds in layers — the top notes greet you first, the heart notes linger, "
        "and the base notes anchor the scent for hours."
    )

    how_it_works = (
        "How It Works\n"
        "Gather your ingredients, measure, blend, and let the recipe rest. Hands-on time is about "
        f"15\u201320 minutes. This recipe makes {yield_str}. Estimated cost to make: {cost}. "
        f"Skill level: {difficulty} — perfect for DIY {label.lower()} beginners and a thoughtful, "
        "handmade gift for friends and family."
    )

    safety_section = "Safety & Tips\n" + "\n".join(f"- {s}" for s in safety_notes[:6])

    instant = (
        "Instant Download\n"
        "This listing is a DIGITAL DOWNLOAD. After checkout you will receive a beautifully "
        "formatted PDF recipe card you can print, save, or follow on any device. No physical "
        "product will be shipped. Since this is a digital item, all sales are final."
    )

    return "\n\n".join([hook, what_you_get, scent_profile_section, how_it_works, safety_section, instant])