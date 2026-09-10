"""Recipe JSON schema definition and validation (stdlib only)."""

from __future__ import annotations

from typing import Any, List, Optional

# Exact top-level keys, in documented order. "theme" and "holiday" are the two
# sanctioned extensions (lead spec: "add a theme and optional holiday field").
EXPECTED_KEYS: List[str] = [
    "recipe_name",
    "full_title",
    "slug",
    "category",
    "difficulty",
    "scent_profile",
    "ingredients",
    "equipment",
    "instructions",
    "safety_notes",
    "yield",
    "cost_to_make",
    "description_long",
    "tags",
    "price_usd",
    "theme",
    "holiday",
]

CATEGORIES = {
    "perfume",
    "cologne",
    "candle",
    "reed_diffuser",
    "room_spray",
    "solid_perfume",
}
DIFFICULTIES = {"beginner", "intermediate", "advanced"}
NOTES_LEVELS = {"top_notes", "heart_notes", "base_notes"}
INGREDIENT_PURPOSES = {"carrier", "top", "heart", "base"}


def validate(recipe: dict) -> List[str]:
    """Validate a recipe dict against the spec.

    Returns a list of human-readable problems; empty list == valid.
    """
    errors: List[str] = []

    if not isinstance(recipe, dict):
        return ["recipe is not a dict"]

    missing = [k for k in EXPECTED_KEYS if k not in recipe]
    if missing:
        errors.append(f"missing keys: {missing}")
        return errors
    extra = [k for k in recipe if k not in EXPECTED_KEYS]
    if extra:
        errors.append(f"unexpected keys: {extra}")

    # --- names / identity
    if not recipe["recipe_name"] or not isinstance(recipe["recipe_name"], str):
        errors.append("recipe_name must be a non-empty string")
    if not isinstance(recipe["slug"], str) or len(recipe["slug"]) > 80:
        errors.append("slug must be a string <= 80 chars")
    if not isinstance(recipe["full_title"], str) or len(recipe["full_title"]) > 140:
        errors.append(f"full_title must be <= 140 chars (got {len(recipe['full_title'])})")

    # --- category / difficulty
    if recipe["category"] not in CATEGORIES:
        errors.append(f"invalid category: {recipe['category']}")
    if recipe["difficulty"] not in DIFFICULTIES:
        errors.append(f"invalid difficulty: {recipe['difficulty']}")

    # --- scent profile
    sp = recipe["scent_profile"]
    if not isinstance(sp, dict) or set(sp.keys()) != NOTES_LEVELS:
        errors.append("scent_profile must have exactly top_notes/heart_notes/base_notes")
    else:
        for level in NOTES_LEVELS:
            notes = sp[level]
            if not isinstance(notes, list) or not notes:
                errors.append(f"scent_profile.{level} must be a non-empty list")
            else:
                for n in notes:
                    if not isinstance(n, str) or not n:
                        errors.append(f"scent_profile.{level} contains an empty note")

    # --- ingredients
    if not isinstance(recipe["ingredients"], list) or not recipe["ingredients"]:
        errors.append("ingredients must be a non-empty list")
    else:
        for ing in recipe["ingredients"]:
            if set(ing.keys()) != {"name", "amount", "purpose"}:
                errors.append(f"ingredient entry has wrong keys: {ing}")
            elif ing["purpose"] not in INGREDIENT_PURPOSES:
                errors.append(f"ingredient purpose invalid: {ing.get('purpose')}")
            elif not isinstance(ing["name"], str) or not isinstance(ing["amount"], str):
                errors.append(f"ingredient name/amount not strings: {ing}")

    # --- lists
    for key in ("equipment", "instructions", "safety_notes"):
        if not isinstance(recipe[key], list) or not recipe[key]:
            errors.append(f"{key} must be a non-empty list")
        elif not all(isinstance(x, str) and x for x in recipe[key]):
            errors.append(f"{key} must contain only non-empty strings")

    # --- tags: exactly 13, each <= 20 chars
    tags = recipe["tags"]
    if not isinstance(tags, list) or len(tags) != 13:
        errors.append(f"tags must be exactly 13 (got {len(tags) if isinstance(tags, list) else 'n/a'})")
    else:
        seen = set()
        for t in tags:
            if not isinstance(t, str) or not t:
                errors.append("tag is not a non-empty string")
            elif len(t) > 20:
                errors.append(f"tag too long ({len(t)} chars): {t!r}")
            if t in seen:
                errors.append(f"duplicate tag: {t!r}")
            seen.add(t)

    # --- strings
    for key in ("yield", "cost_to_make", "description_long"):
        if not isinstance(recipe[key], str) or not recipe[key]:
            errors.append(f"{key} must be a non-empty string")
    if not recipe["cost_to_make"].startswith("~$"):
        errors.append("cost_to_make should look like '~$X.XX'")

    # --- price
    price = recipe["price_usd"]
    if not isinstance(price, (int, float)) or isinstance(price, bool):
        errors.append("price_usd must be a number")
    else:
        price = float(price)
        if not (3.99 <= price <= 9.99):
            errors.append(f"price_usd out of 3.99..9.99 range: {price}")

    # --- extensions
    if "theme" in recipe and not isinstance(recipe["theme"], str):
        errors.append("theme must be a string")
    if "holiday" in recipe and recipe["holiday"] is not None and not isinstance(recipe["holiday"], str):
        errors.append("holiday must be a string or null")

    return errors


def is_valid(recipe: dict) -> bool:
    return not validate(recipe)


def assert_valid(recipe: dict) -> None:
    problems = validate(recipe)
    if problems:
        raise ValueError(f"recipe failed schema validation: {'; '.join(problems)}")