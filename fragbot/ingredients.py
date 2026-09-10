"""Ingredient database loader and per-category product configuration.

All data comes from ``fragbot/data/ingredients.json`` (curated, safety-vetted).
Edit that file to curate the database; see README.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

DATA_FILE = Path(__file__).resolve().parent / "data" / "ingredients.json"

# ---------------------------------------------------------------------------
# Category configuration. "unit" is either "drops" (perfume-style products) or
# "parts" (candle / reed diffuser, expressed in ml via "part_ml").
# The 30/50/20 top/heart/base balance is always expressed in these units, so
# the ratio holds in drop counts AND in ml of fragrance oil.
# ---------------------------------------------------------------------------
CATEGORIES: Dict[str, dict] = {
    "perfume": {
        "label": "Perfume",
        "slug": "perfume",
        "skin": True,
        "weekdays": (0, 2, 4),            # Mon / Wed / Fri
        "total_parts": 16,                # ~6% dilution in a 10ml roller
        "unit": "drops",
        "yield": "1 x 10ml roll-on bottle",
        "bottle_ml": 10.0,
        "carrier_rule": ("Jojoba Oil", "fill"),
        "packaging_cost": 1.25,           # glass roller bottle
        "equipment": [
            "10ml glass roller bottle",
            "Glass dropper",
            "Small funnel",
            "Permanent marker or label",
        ],
    },
    "cologne": {
        "label": "Cologne",
        "slug": "cologne",
        "skin": True,
        "weekdays": (6,),                 # Sun
        "total_parts": 14,                # ~5% dilution, light & fresh
        "unit": "drops",
        "yield": "1 x 10ml spray bottle",
        "bottle_ml": 10.0,
        "carrier_rule": ("Perfumer's Alcohol (190 proof)", "fill"),
        "packaging_cost": 1.50,           # glass spray bottle
        "equipment": [
            "10ml glass spray bottle",
            "Glass dropper",
            "Small funnel",
            "Permanent marker or label",
        ],
    },
    "solid_perfume": {
        "label": "Solid Perfume",
        "slug": "solid-perfume",
        "skin": True,
        "weekdays": (),                   # variant of perfume days (see generator)
        "total_parts": 24,                # ~10% in 10g balm base
        "unit": "drops",
        "yield": "1 x 10g solid perfume tin",
        "bottle_ml": 10.0,
        "carrier_rule": ("Shea Butter", "beeswax-combo"),  # 6g shea + 3g beeswax
        "packaging_cost": 0.75,           # tin
        "equipment": [
            "10g solid perfume tin",
            "Small glass bowl",
            "Small saucepan (double boiler)",
            "Wooden stirrer",
        ],
    },
    "candle": {
        "label": "Candle",
        "slug": "candle",
        "skin": False,
        "weekdays": (1,),                 # Tue
        "total_parts": 20,                # 10ml fragrance for 110g wax ~ 8% load
        "unit": "parts",
        "part_ml": 0.5,
        "yield": "1 x 120g soy candle (approx. 30-hour burn)",
        "packaging_cost": 1.90,           # tin/jar + cotton wick
        "equipment": [
            "120g candle tin or glass jar",
            "Cotton wick with wick tab",
            "Melt pot or double boiler",
            "Candy thermometer",
            "Wooden stirrer",
        ],
    },
    "reed_diffuser": {
        "label": "Reed Diffuser",
        "slug": "reed-diffuser",
        "skin": False,
        "weekdays": (3,),                 # Thu
        "total_parts": 50,                # 25ml oil / 75ml carrier = 25% ratio
        "unit": "parts",
        "part_ml": 0.5,
        "yield": "1 x 100ml reed diffuser",
        "packaging_cost": 4.00,           # bottle + 6 rattan reeds
        "equipment": [
            "100ml glass diffuser bottle",
            "6 rattan reed sticks",
            "Small funnel",
        ],
    },
    "room_spray": {
        "label": "Room Spray",
        "slug": "room-spray",
        "skin": False,
        "weekdays": (5,),                 # Sat
        "total_parts": 40,                # 40 drops + polysorbate 20 in water
        "unit": "drops",
        "yield": "1 x 120ml room spray",
        "packaging_cost": 1.50,           # glass spray bottle
        "equipment": [
            "120ml glass spray bottle",
            "Measuring cup",
            "Small funnel",
            "Glass stirrer",
        ],
    },
}

_WEEKDAY_TO_CATEGORY = {wd: cat for cat, cfg in CATEGORIES.items() for wd in cfg["weekdays"]}

# Fixed carrier quantities (ml or g) per category, keyed by carrier name.
_CARRIER_AMOUNTS: Dict[str, List[tuple]] = {
    "solid_perfume": [("Shea Butter", "6g"), ("Beeswax", "3g")],
    "room_spray": [("Distilled Water", "115ml"), ("Polysorbate 20", "3ml")],
    "reed_diffuser": [("Sweet Almond Oil", "75ml")],
    "candle": [("Soy Wax", "110g")],
}
_CARRIER_PRICE_RULES = {  # per-category setup cost of carriers (USD)
    "perfume": ("Jojoba Oil", "fill"),
    "cologne": ("Perfumer's Alcohol (190 proof)", "fill"),
    "solid_perfume": None,
    "candle": None,
    "reed_diffuser": None,
    "room_spray": None,
}


class _Db:
    def __init__(self) -> None:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        self.version: int = raw["version"]
        self.oils: List[dict] = raw["oils"]
        self.carriers: Dict[str, float] = {c["name"]: c["price_per_ml"] for c in raw["carriers"]}
        self.groups: Dict[str, List[dict]] = {}
        for oil in self.oils:
            self.groups.setdefault(oil["family"], []).append(oil)


_db = _Db()

OILS: List[dict] = _db.oils
CARRIER_PRICES: Dict[str, float] = _db.carriers
OIL_GROUPS: Dict[str, List[dict]] = _db.groups
DB_VERSION: int = _db.version


def oils_in_families(families: List[str]) -> List[dict]:
    """All oils whose family is in ``families``, preserving family order."""
    out: List[dict] = []
    for family in families:
        out.extend(OIL_GROUPS.get(family, []))
    return out


def category_for_weekday(weekday: int) -> str:
    return _WEEKDAY_TO_CATEGORY[weekday]


def is_skin_category(category: str) -> bool:
    return bool(CATEGORIES[category]["skin"])


def flag_of(oil: dict, flag_prefix: str) -> bool:
    for f in oil.get("flags", []):
        if f == flag_prefix or f.startswith(flag_prefix + ":"):
            return True
    return False


def flag_value(oil: dict, flag_prefix: str) -> int:
    for f in oil.get("flags", []):
        if f.startswith(flag_prefix + ":"):
            try:
                return int(f.split(":", 1)[1])
            except ValueError:
                return 0
    return 0


def is_phototoxic(oil: dict) -> bool:
    return flag_of(oil, "phototoxic")


def is_skin_restricted(oil: dict) -> bool:
    return flag_of(oil, "skin_restricted")


def max_parts(oil: dict) -> int:
    v = flag_value(oil, "max_parts")
    return v if v else 10**6