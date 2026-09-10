"""Theme, season and holiday logic.

Implements:
  * the 7-day content themes (spec rule 5),
  * holiday windows: Valentine's Day, Christmas, Mother's Day (spec rule 6),
  * seasonal flavour bias: June-Aug fresh/citrus, Dec-Feb warm/woody/spicy,
  * the family pools that drive note selection for each theme/holiday/season.

Holiday pools take precedence, then season pools, then the daily theme pools:
this is the "overrides or blends" behaviour from the spec.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# 7-day content themes
# ---------------------------------------------------------------------------
DAY_THEMES: Dict[int, str] = {
    0: "Monday Mood",        # energizing citrus / fresh
    1: "Cozy Tuesday",       # warm / spicy
    2: "Wellness Wednesday", # calming / lavender / chamomile
    3: "Date Night",         # seductive / oud / vanilla
    4: "Friday Luxe",        # premium / complex
    5: "Weekend Project",    # home scent project
    6: "Sunday Reset",       # clean / minimal
}

THEME_VIBE: Dict[str, str] = {
    "Monday Mood": "energizing",
    "Cozy Tuesday": "cozy",
    "Wellness Wednesday": "calming",
    "Date Night": "seductive",
    "Friday Luxe": "luxurious",
    "Weekend Project": "homey",
    "Sunday Reset": "clean",
}

THEME_OCCASION: Dict[str, str] = {
    "Monday Mood": "Monday Morning Energy",
    "Cozy Tuesday": "Cozy Night In",
    "Wellness Wednesday": "Wellness Reset",
    "Date Night": "Date Night Elegance",
    "Friday Luxe": "Everyday Luxury",
    "Weekend Project": "Weekend Home Refresh",
    "Sunday Reset": "Sunday Reset",
}

# Family pools per theme level. Oils are grouped by family in ingredients.json.
THEME_FAMILIES: Dict[str, Dict[str, List[str]]] = {
    "Monday Mood": {
        "top": ["citrus", "fresh", "herbal"],
        "heart": ["floral", "herbal"],
        "base": ["woody", "musk"],
    },
    "Cozy Tuesday": {
        "top": ["citrus", "spicy"],
        "heart": ["spicy", "sweet", "floral"],
        "base": ["woody", "resin", "sweet"],
    },
    "Wellness Wednesday": {
        "top": ["herbal", "citrus"],
        "heart": ["floral", "herbal"],
        "base": ["woody", "resin"],
    },
    "Date Night": {
        "top": ["spicy", "citrus"],
        "heart": ["floral", "sweet"],
        "base": ["woody", "musk", "tobacco"],
    },
    "Friday Luxe": {
        "top": ["citrus", "spicy"],
        "heart": ["floral", "herbal"],
        "base": ["resin", "woody", "sweet"],
    },
    "Weekend Project": {
        "top": ["citrus", "fresh", "herbal"],
        "heart": ["floral", "sweet"],
        "base": ["woody", "resin", "musk"],
    },
    "Sunday Reset": {
        "top": ["citrus", "herbal"],
        "heart": ["floral"],
        "base": ["musk", "woody"],
    },
}

# ---------------------------------------------------------------------------
# Holiday windows (US-centric, Etsy shop audience)
# ---------------------------------------------------------------------------
_SEASON_SUMMER = ((6, 1), (8, 31))   # Jun 1 - Aug 31: fresh/citrus/coastal
_SEASON_WINTER = ((12, 1), (2, 28))  # Dec 1 - Feb 28: warm/woody/spicy


def _valentine_window(year: int):
    return date(year, 2, 7), date(year, 2, 14)


def _mothers_day_window(year: int):
    # US Mother's Day = 2nd Sunday of May; window is the week before through that day.
    first = date(year, 5, 1)
    second_sunday = first + timedelta(days=(6 - first.weekday()) + 7)
    return second_sunday - timedelta(days=6), second_sunday


def _christmas_window(year: int):
    return date(year, 12, 18), date(year, 12, 26)


def holiday_for(d: date) -> Optional[str]:
    """Return the holiday name whose window contains ``d``, else None."""
    if _valentine_window(d.year)[0] <= d <= _valentine_window(d.year)[1]:
        return "Valentine's Day"
    if _mothers_day_window(d.year)[0] <= d <= _mothers_day_window(d.year)[1]:
        return "Mother's Day"
    if _christmas_window(d.year)[0] <= d <= _christmas_window(d.year)[1]:
        return "Christmas"
    return None


def season_for(d: date) -> Optional[str]:
    m = d.month
    if m in (6, 7, 8):
        return "summer"
    if m in (12, 1, 2):
        return "winter"
    return None


HOLIDAY_FAMILIES: Dict[str, Dict[str, List[str]]] = {
    "Valentine's Day": {
        "top": ["spicy", "citrus"],
        "heart": ["floral"],                 # romantic rose/jasmine/ylang
        "base": ["sweet", "woody", "musk"],
    },
    "Christmas": {
        "top": ["citrus", "conifer", "spicy"],
        "heart": ["spicy", "sweet", "floral"],
        "base": ["resin", "woody", "sweet"],
    },
    "Mother's Day": {
        "top": ["citrus", "spicy"],
        "heart": ["floral"],
        "base": ["woody", "resin", "musk", "sweet"],
    },
}

SEASON_FAMILIES: Dict[str, Dict[str, List[str]]] = {
    "summer": {
        "top": ["citrus"],
        "heart": ["floral", "herbal"],
        "base": ["musk", "woody"],
    },
    "winter": {
        "top": ["citrus", "spicy"],
        "heart": ["sweet", "spicy", "floral"],
        "base": ["resin", "woody", "sweet"],
    },
}

HOLIDAY_OCCASION: Dict[str, str] = {
    "Valentine's Day": "Valentine's Day Gift",
    "Christmas": "Holiday Cozy",
    "Mother's Day": "Mother's Day Elegance",
}


def effective_families(d: date) -> Dict[str, List[str]]:
    """Merged family pools for a date: holiday > season > daily theme."""
    theme = DAY_THEMES[d.weekday()]
    pools: Dict[str, List[str]] = {"top": [], "heart": [], "base": []}
    sources: List[Dict[str, List[str]]] = []
    holiday = holiday_for(d)
    if holiday:
        sources.append(HOLIDAY_FAMILIES[holiday])
    season = season_for(d)
    if season:
        sources.append(SEASON_FAMILIES[season])
    sources.append(THEME_FAMILIES[theme])
    for src in sources:
        for level in ("top", "heart", "base"):
            for family in src[level]:
                if family not in pools[level]:
                    pools[level].append(family)
    return pools


def holiday_prefix_families(d: date) -> Dict[str, List[str]]:
    """Family pools coming *only* from the named holiday (empty if no holiday).

    The generator biases its sampling offset into this prefix on holiday dates
    so the holiday's character (romantic floral, cozy spice...) actually shows
    up in the blend while the daily theme still rounds it out.
    """
    holiday = holiday_for(d)
    if not holiday:
        return {"top": [], "heart": [], "base": []}
    return HOLIDAY_FAMILIES[holiday]


def occasion_phrase(d: date) -> str:
    holiday = holiday_for(d)
    if holiday:
        return HOLIDAY_OCCASION[holiday]
    return THEME_OCCASION[DAY_THEMES[d.weekday()]]