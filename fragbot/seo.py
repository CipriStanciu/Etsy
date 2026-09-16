"""SEO copy module: slug, full title, 13 tags, long description, image alt text.

Listing metadata is *adaptive* rather than static-per-category (gap-analysis
upgrade, see /home/team/shared/seo/keyword-gap-analysis.md):

  * tags = 9 core (per category) + 4 rotating slots that are pure functions
    of the already-computed per-date fields (``themes.holiday_for(d)``, the
    month-derived season, ``themes.DAY_THEMES[d.weekday()]``) and the blend's
    actual note names. The note / holiday / season slots only emit tags whose
    content really matches the recipe (a note tag is only used when that note
    is in the blend; holiday gift tags only inside the holiday window; season
    tags only in-season).
  * title = front-loaded "<category> making/recipe + heart&base note pair +
    benefit/recipient" per the analyst's [REC] patterns. The invented brand
    name is intentionally NOT in the title (zero search volume; the schema
    does not require it — the analyst's [REC] titles omit it). The note
    segment is never dropped: the trim cascade removes the lower-value tail
    segments first, never the searchable notes.
  * description = six spec sections with beginner / recipient / season
    keywords added (the hook now opens with "Make your own <label> at home",
    the highest-volume phrasing, plus a season term).
  * image alt text = category + note pair + "digital download" (Etsy's 500
    char budget is no longer wasted on the invented name).

Claim guardrail (analyst §5, owner has NOT signed off): product-claim tags
("long lasting", "non toxic", "cruelty free", "stress relief", "sleep spray")
are NOT shipped by default. They only replace the benefit slot when
``FRAGBOT_ALLOW_CLAIMS`` is truthy. Soft truthful phrasing ("calming",
"natural", "beginner friendly") ships unconditionally. Solid-perfume never
tags "vegan" (it uses beeswax).
"""

from __future__ import annotations

import os
import re
from datetime import date
from typing import Dict, List, Optional

from . import ingredients as ig
from . import themes

# ---------------------------------------------------------------------------
# Tag pools (gap-analysis §3.1-3.6 [REC] sets; char-count-verified <= 20).
# ---------------------------------------------------------------------------
# 9 core tags per category — static, high-volume category/form/format terms.
CATEGORY_CORE_TAGS: Dict[str, List[str]] = {
    "perfume": [
        "diy perfume making",
        "perfume recipe",
        "essential oil blend",
        "natural perfume",
        "roll on perfume",
        "perfume making kit",
        "homemade perfume",
        "essential oil recipe",
        "digital download",
    ],
    "cologne": [
        "diy cologne",
        "cologne recipe",
        "mens cologne recipe",
        "fragrance for men",
        "homemade cologne",
        "eau de cologne",
        "essential oil blend",
        "perfume making",
        "essential oil recipe",
    ],
    "candle": [
        "candle making",
        "soy candle recipe",
        "candle making kit",
        "diy candle making",
        "homemade candle",
        "essential oil blend",
        "fragrance recipe",
        "home fragrance",
        "digital download",
    ],
    "reed_diffuser": [
        "diy reed diffuser",
        "reed diffuser",
        "diffuser recipe",
        "reed diffuser oil",
        "reed diffuser refill",
        "homemade diffuser",
        "home fragrance",
        "essential oil blend",
        "digital download",
    ],
    "room_spray": [
        "room spray diy",
        "room spray recipe",
        "linen spray diy",
        "homemade spray",
        "home fragrance",
        "essential oil blend",
        "fabric spray",
        "pillow mist",
        "digital download",
    ],
    "solid_perfume": [
        "solid perfume",
        "solid perfume diy",
        "perfume balm",
        "natural perfume",
        "homemade perfume",
        "essential oil blend",
        "natural beauty",
        "clean beauty",
        "digital download",
    ],
}

# Note-tag suffix per category -> "<note> <suffix>" (e.g. "lavender perfume").
# Analysts: perfume/cologne/candle rotate "<note> perfume/cologne/candle",
# solid_perfume uses "<note> balm" ("lavender perfume balm" would be 21 chars).
NOTE_TAG_SUFFIX: Dict[str, str] = {
    "perfume": "perfume",
    "cologne": "cologne",
    "candle": "candle",
    "reed_diffuser": "diffuser",
    "room_spray": "spray",
    "solid_perfume": "balm",
}

# Holiday gift tags, keyed by the engine's holiday names (thematic slot).
HOLIDAY_GIFT_TAGS: Dict[str, str] = {
    "Valentine's Day": "valentines gift",
    "Christmas": "christmas gift",
    "Mother's Day": "mothers day gift",
}

# Non-holiday recipient tag per category.
RECIPIENT_TAG: Dict[str, str] = {
    "perfume": "gift for her",
    "cologne": "gift for him",
    "candle": "hostess gift",
    "reed_diffuser": "hostess gift",   # -> "housewarming gift" in spring
    "room_spray": "self care gift",
    "solid_perfume": "gift for her",
}

# Season tag per category + month (pure function of the date). The analyst's
# rotation pools say candles get product-specific season terms ("christmas
# candle", "fall candle") while the rest use generic scent terms ("cozy
# scent", "summer scent"). December keeps "christmas candle" for the whole
# month (the shopping window), Jan-Feb falls back to "cozy candle".
_CANDLE_SEASON_TAGS: Dict[int, str] = {
    12: "christmas candle", 1: "cozy candle", 2: "cozy candle",
    3: "spring candle", 4: "spring candle", 5: "spring candle",
    6: "summer candle", 7: "summer candle", 8: "summer candle",
    9: "fall candle", 10: "fall candle", 11: "fall candle",
}
_GENERIC_SEASON_TAGS: Dict[int, str] = {
    12: "cozy scent", 1: "cozy scent", 2: "cozy scent",
    3: "spring scent", 4: "spring scent", 5: "spring scent",
    6: "summer scent", 7: "summer scent", 8: "summer scent",
    9: "fall scent", 10: "fall scent", 11: "fall scent",
}

# Benefit slot (4th rotating tag): shipped default per category, with a
# theme-driven override for perfume (Wellness Wednesday => calming blend).
BENEFIT_TAG: Dict[str, str] = {
    "perfume": "beginner friendly",
    "cologne": "beginner friendly",
    "candle": "easy candle making",
    "reed_diffuser": "calming blend",
    "room_spray": "calming blend",
    "solid_perfume": "zero waste gift",
}
THEME_BENEFIT_OVERRIDE: Dict[str, Dict[str, str]] = {
    "perfume": {"Wellness Wednesday": "calming blend"},
}

# Claim-gated alternates — only used when FRAGBOT_ALLOW_CLAIMS is truthy
# (owner sign-off required; NOT shipped by default).
CLAIM_TAG: Dict[str, str] = {
    "perfume": "long lasting",
    "cologne": "long lasting",
    "candle": "long lasting",
    "reed_diffuser": "stress relief",
    "room_spray": "non toxic",
    "solid_perfume": "long lasting",
}
CLAIMS_ENV = "FRAGBOT_ALLOW_CLAIMS"


def _claims_allowed() -> bool:
    return os.environ.get(CLAIMS_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


def make_slug(recipe_name: str, category: str) -> str:
    cat_slug = ig.CATEGORIES[category]["slug"]
    return f"{slugify(recipe_name)}-diy-{cat_slug}-recipe"


def key_note_pair(scent_profile: dict) -> str:
    """Heart + base note pair like ``Lavender & Frankincense``.

    Single source of truth for the note pair used in titles and alt text, so
    the two can never disagree. Falls back to heart[1]/top[0] when the base
    note equals the heart note (the generator may pick the same oil in both
    levels, e.g. Vanilla Absolute).
    """
    heart = scent_profile.get("heart_notes") or []
    base = scent_profile.get("base_notes") or []
    top = scent_profile.get("top_notes") or []
    a = heart[0]
    b = base[0] if base else (heart[1] if len(heart) > 1 else None)
    if b and b != a:
        return f"{a} & {b}"
    return " & ".join([a, top[0]][:2]) if top else a


# ---------------------------------------------------------------------------
# Title (gap-analysis §4.2): front-loaded category phrase + note pair +
# benefit/recipient, brand name dropped.
# ---------------------------------------------------------------------------
TITLE_HEAD: Dict[str, str] = {
    "perfume": "DIY Perfume Making Kit Recipe",
    "cologne": "DIY Cologne Recipe for Men",
    "candle": "DIY Candle Making Recipe",
    "reed_diffuser": "DIY Reed Diffuser Refill Recipe",
    "room_spray": "DIY Room Spray Recipe",
    "solid_perfume": "DIY Solid Perfume Recipe",
}
TITLE_NOTE_FORM: Dict[str, str] = {
    "perfume": "Roll-On",
    "cologne": "",
    "candle": "Soy Candle",
    "reed_diffuser": "Home Fragrance",
    "room_spray": "Pillow Mist",
    "solid_perfume": "Perfume Balm",
}
TITLE_BENEFIT: Dict[str, str] = {  # non-holiday tail
    "perfume": "Natural Gift for Her",
    "cologne": "Date Night Cologne Gift",
    "candle": "Hostess Gift",
    "reed_diffuser": "Calming Gift",
    "room_spray": "Natural Linen Spray for Home",
    "solid_perfume": "Natural Pocket Gift",
}
TITLE_BENEFIT_HOLIDAY: Dict[str, str] = {
    "Valentine's Day": "Valentine's Day Gift",
    "Christmas": "Christmas Gift",
    "Mother's Day": "Mother's Day Gift",
}
_CANDLE_CHRISTMAS_BENEFIT = "Cozy Holiday Gift"  # analyst's [REC] candle title


def make_title(category: str, scent_profile: dict, d) -> str:
    """Front-loaded, note-first Etsy title (<= 140 chars, enforced).

    Pattern: ``DIY <Category-heading> Recipe | <Heart> & <Base> <Form> |
    <Benefit/Recipient> | Digital Download``.

    The invented recipe name is intentionally absent (zero search volume; the
    schema does not require it). The heart+base note pair is the last segment
    ever trimmed: if the assembled title is over 140 chars the benefit tail is
    dropped first, then the format tail — the notes always survive.
    """
    holiday = themes.holiday_for(d)

    # Head: candles get a seasonal head (Christmas/fall); everything else is
    # category-stable (the [REC] patterns are already high-volume phrases).
    if category == "candle":
        if holiday == "Christmas" or d.month == 12:
            head = "DIY Christmas Candle Making Recipe"
        elif d.month in (9, 10, 11):
            head = "DIY Fall Candle Making Recipe"
        else:
            head = TITLE_HEAD[category]
    else:
        head = TITLE_HEAD[category]

    # Notes: heart + base pair + product form — never trimmed.
    notes = f"{key_note_pair(scent_profile)} {TITLE_NOTE_FORM[category]}".strip()

    # Benefit / recipient / occasion tail (searchable; gap-analysis §4.3/4.4:
    # "Holiday Cozy" -> "Christmas Gift" etc.).
    if holiday:
        if category == "candle" and holiday == "Christmas":
            benefit = _CANDLE_CHRISTMAS_BENEFIT
        else:
            benefit = TITLE_BENEFIT_HOLIDAY[holiday]
    else:
        benefit = TITLE_BENEFIT[category]

    format_tail = "Digital Download"
    title = " | ".join([head, notes, benefit, format_tail])
    if len(title) <= 140:
        return title
    # Trim cascade: drop benefit, then format — never the head or the notes.
    title = " | ".join([head, notes, format_tail])
    if len(title) <= 140:
        return title
    title = f"{head} | {notes}"
    if len(title) <= 140:
        return title
    return f"{head} | {notes}"[:137].rstrip() + "..."


# ---------------------------------------------------------------------------
# Tags (gap-analysis §4.1): 9 core + 4 rotating slots, all pure functions of
# (date, category, blend).
# ---------------------------------------------------------------------------
def _note_tag_for(category: str, scent_profile: dict) -> str:
    """Best note-based tag whose note is actually in the blend (<= 20 chars).

    Deterministic priority: heart, then base, then top — the same order as the
    title pair — skipping notes that make an over-long tag (e.g. "roman
    chamomile perfume" = 22 chars is skipped in favour of the next note).
    """
    suffix = NOTE_TAG_SUFFIX[category]
    seen = set()
    for level in ("heart_notes", "base_notes", "top_notes"):
        for note in scent_profile.get(level, []):
            key = note.lower()
            if key in seen:
                continue
            seen.add(key)
            tag = f"{key} {suffix}"
            if len(tag) <= 20:
                return tag
    # Defensive: blends carry 6-9 distinct notes, virtually all fit; this
    # keeps make_tags' 13/<=20 invariant safe regardless.
    return "homemade scent"


def _rotating_tags(category: str, d: date, scent_profile: dict) -> List[str]:
    """The 4 rotating tag slots for a date+category+blend (order matters:
    note, holiday/recipient, season, benefit)."""
    tags: List[str] = []

    # 1. Note tag — always reflects an actual note in the blend.
    tags.append(_note_tag_for(category, scent_profile))

    # 2. Holiday gift tag at holiday time, else the category recipient tag
    #    (reed diffusers get "housewarming gift" in spring — moving season).
    holiday = themes.holiday_for(d)
    if holiday:
        tags.append(HOLIDAY_GIFT_TAGS[holiday])
    elif category == "reed_diffuser" and d.month in (3, 4, 5):
        tags.append("housewarming gift")
    else:
        tags.append(RECIPIENT_TAG[category])

    # 3. Season tag — only in-season (candles get product-specific terms).
    tags.append(
        _CANDLE_SEASON_TAGS[d.month]
        if category == "candle"
        else _GENERIC_SEASON_TAGS[d.month]
    )

    # 4. Benefit slot: theme override for perfume; claim-gated alternates.
    theme = themes.DAY_THEMES[d.weekday()]
    benefit = THEME_BENEFIT_OVERRIDE.get(category, {}).get(theme, BENEFIT_TAG[category])
    if _claims_allowed():
        benefit = CLAIM_TAG[category]
    tags.append(benefit)
    return tags


def make_tags(category: str, d: date, scent_profile: dict) -> List[str]:
    """Exactly 13 unique tags, each <= 20 chars: 9 core + 4 rotating.

    All rotation inputs are pure functions of (date, category, blend), so the
    tags are fully deterministic per date.
    """
    tags: List[str] = []
    seen = set()
    for t in CATEGORY_CORE_TAGS[category] + _rotating_tags(category, d, scent_profile):
        if t not in seen:
            seen.add(t)
            tags.append(t)
    assert len(tags) == 13, f"{category} on {d.isoformat()} produced {len(tags)} tags"
    for t in tags:
        assert len(t) <= 20, f"tag too long: {t!r}"
    return tags


# ---------------------------------------------------------------------------
# Description (six spec sections + beginner / recipient / season keywords)
# ---------------------------------------------------------------------------
def season_word(d: date) -> str:
    """Full season name for copy: winter / spring / summer / fall (pure)."""
    m = d.month
    if m in (12, 1, 2):
        return "winter"
    if m in (3, 4, 5):
        return "spring"
    if m in (6, 7, 8):
        return "summer"
    return "fall"


_GIFT_LINE: Dict[str, str] = {
    "perfume": "a thoughtful handmade gift for her — birthdays, bridesmaids, holidays",
    "cologne": "a thoughtful handmade gift for him — date nights, holidays, Father's Day",
    "candle": "a thoughtful handmade gift for her — hostess gifts, teacher gifts, holidays",
    "reed_diffuser": "a thoughtful handmade gift for housewarmings and hosts",
    "room_spray": "a thoughtful handmade gift for friends, family, and hosts",
    "solid_perfume": "a thoughtful handmade gift for her — pocket-size and travel-friendly",
}


def make_description(
    category: str,
    scent_profile: dict,
    theme: str,
    holiday,
    season: Optional[str],
    difficulty: str,
    yield_str: str,
    cost: str,
    safety_notes: List[str],
) -> str:
    cat = ig.CATEGORIES[category]
    label = cat["label"]
    label_word = label.lower()
    vibe = themes.THEME_VIBE.get(theme, "")
    top = ", ".join(scent_profile["top_notes"])
    heart = ", ".join(scent_profile["heart_notes"])
    base = ", ".join(scent_profile["base_notes"])
    holiday_line = f" A special {holiday} edition." if holiday else ""
    season_word_copy = season or ""
    # "an energizing / a calming" — the vibe adjective drives the article.
    article = "an" if vibe[:1].lower() in "aeiou" else "a"

    hook = (
        "About This Recipe\n"
        f"Make your own {label_word} at home with this beginner-friendly DIY "
        f"{label_word} recipe — {article} {vibe} {season_word_copy} scent built around "
        f"{heart} with {top} on top and {base} at the base."
        f"{holiday_line} This digital recipe card turns essential oil blending "
        "into a simple 20-minute project you can make at home."
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
        f"Skill level: {difficulty} — perfect for DIY {label_word} beginners and "
        f"{_GIFT_LINE[category]}."
    )

    safety_section = "Safety & Tips\n" + "\n".join(f"- {s}" for s in safety_notes[:6])

    instant = (
        "Instant Download\n"
        "This listing is a DIGITAL DOWNLOAD. After checkout you will receive a beautifully "
        "formatted PDF recipe card you can print, save, or follow on any device. No physical "
        "product will be shipped. Since this is a digital item, all sales are final."
    )

    return "\n\n".join([hook, what_you_get, scent_profile_section, how_it_works, safety_section, instant])


# ---------------------------------------------------------------------------
# Image alt text (gap-analysis §4.7): category + note pair + digital download.
# ---------------------------------------------------------------------------
ALT_FORM: Dict[str, str] = {
    "perfume": "roll-on perfume",
    "cologne": "cologne spray",
    "candle": "soy candle",
    "reed_diffuser": "reed diffuser",
    "room_spray": "room spray",
    "solid_perfume": "perfume balm",
}
ALT_KIND_LABEL: Dict[str, str] = {
    "hero": "cover card",
    "ingredients": "ingredient list",
    "pyramid": "scent pyramid",
    "included": "what's included",
    "lifestyle": "finished product",
}


def make_image_alt(category: str, scent_profile: dict, kind: str = "hero") -> str:
    """Keyword-rich alt text: category + note pair + "digital download".

    Well under Etsy's 500-char budget; the invented name is dropped (it added
    no search value and ate the budget).
    """
    pair = key_note_pair(scent_profile).lower()
    label = ig.CATEGORIES[category]["label"]
    form = ALT_FORM[category]
    kind_label = ALT_KIND_LABEL.get(kind, kind)
    return (
        f"DIY {label} recipe — {pair} {form} — digital download PDF recipe "
        f"card ({kind_label})"
    )