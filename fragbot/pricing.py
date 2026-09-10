"""Pricing module: difficulty assignment, price rules, cost estimates."""

from __future__ import annotations

from typing import List, Optional, Tuple

from . import ingredients as ig

DIFFICULTY_BASE = {"beginner": 3.99, "intermediate": 5.99, "advanced": 7.99}
WEEKEND_PREMIUM = 1.00
HOLIDAY_PREMIUM = 2.00

# Difficulty weight profiles keyed by (theme, category-shape, holiday) buckets.
_DIFFICULTY_WEIGHTS: List[Tuple[str, dict]] = [
    # (bucket, weights)
    ("friday_luxe", {"advanced": 0.55, "intermediate": 0.35, "beginner": 0.10}),
    ("holiday", {"intermediate": 0.60, "advanced": 0.30, "beginner": 0.10}),
    ("weekend_project", {"beginner": 0.55, "intermediate": 0.45}),
    ("home_craft", {"intermediate": 0.65, "beginner": 0.35}),   # candle / diffuser
    ("default", {"beginner": 0.45, "intermediate": 0.40, "advanced": 0.15}),
]


def _weighted_choice(rng, weights: dict) -> str:
    items = list(weights.items())
    items.sort(key=lambda kv: kv[0])
    keys = [k for k, _ in items]
    cum = []
    total = 0.0
    for _, w in items:
        total += w
        cum.append(total)
    r = rng.random() * total
    for key, c in zip(keys, cum):
        if r <= c:
            return key
    return keys[-1]


def pick_difficulty(rng, theme: str, category: str, holiday: Optional[str]) -> str:
    if theme == "Friday Luxe":
        bucket = "friday_luxe"
    elif holiday:
        bucket = "holiday"
    elif theme == "Weekend Project":
        bucket = "weekend_project"
    elif category in ("candle", "reed_diffuser"):
        bucket = "home_craft"
    else:
        bucket = "default"
    weights = dict(_DIFFICULTY_WEIGHTS)[bucket]
    return _weighted_choice(rng, weights)


def is_weekend(d) -> bool:
    return d.weekday() >= 5


def price_for(difficulty: str, is_weekend_day: bool, holiday: Optional[str]) -> float:
    price = DIFFICULTY_BASE[difficulty]
    if is_weekend_day:
        price += WEEKEND_PREMIUM
    if holiday:
        price += HOLIDAY_PREMIUM
    # Cap at the owner's stated $3.99-$9.99 range (advanced + weekend + holiday
    # would otherwise compute to $10.99).
    return round(min(price, 9.99), 2)


def expected_price(difficulty: str, d, holiday: Optional[str]) -> float:
    return price_for(difficulty, is_weekend(d), holiday)


# ---------------------------------------------------------------------------
# Cost estimate. Parts -> ml via category config; drops -> ml via the oil's
# drops_per_ml. Carriers and packaging are priced from the category config.
# ---------------------------------------------------------------------------
def estimate_cost(category: str, blends: List[Tuple[dict, int]]) -> float:
    cfg = ig.CATEGORIES[category]
    cost = 0.0

    for oil, parts in blends:
        if cfg["unit"] == "drops":
            ml = parts / oil.get("drops_per_ml", 25)
        else:
            ml = parts * cfg["part_ml"]
        cost += ml * oil["price_per_ml"]

    # carrier cost
    rule = cfg.get("carrier_rule")
    if rule:
        name, kind = rule
        rate = ig.CARRIER_PRICES[name]
        if kind == "fill":
            blend_ml = _blend_ml(category, blends)
            cost += (cfg["bottle_ml"] - blend_ml) * rate
        elif kind == "beeswax-combo":
            cost += 6.0 * ig.CARRIER_PRICES["Shea Butter"]
            cost += 3.0 * ig.CARRIER_PRICES["Beeswax"]
    for carrier_name, amount_str in ig._CARRIER_AMOUNTS.get(category, []):
        amount = float(amount_str.replace("ml", "").replace("g", ""))
        cost += amount * ig.CARRIER_PRICES[carrier_name]

    cost += cfg["packaging_cost"]
    return round(cost * 1.10, 2)  # 10% buffer for waste / price drift


def _blend_ml(category: str, blends: List[Tuple[dict, int]]) -> float:
    cfg = ig.CATEGORIES[category]
    if cfg["unit"] == "drops":
        return sum(p / (o.get("drops_per_ml", 25)) for o, p in blends)
    return sum(p * cfg["part_ml"] for o, p in blends)


def format_cost(cost: float) -> str:
    return f"~${cost:.2f}"