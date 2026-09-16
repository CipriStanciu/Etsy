"""Recipe generator: deterministic per date, perfumery-safe, spec-compliant."""

from __future__ import annotations

import logging
import random
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from . import ingredients as ig
from . import pricing, seo, themes
from .ingredients import CATEGORIES, max_parts
from .schema import assert_valid

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Name bank: 80 adjectives x 80 nouns = 6400 unique two-word luxury names.
# A date ordinal walks the grid via a coprime stride, so names never repeat
# within a 6400-recipe cycle (~17.5 years of daily posting) and are fully
# deterministic per date. "seq" offsets the walk for repeat variants.
# ---------------------------------------------------------------------------
ADJECTIVES = [
    "Velvet", "Midnight", "Golden", "Ambery", "Smoked", "Coastal", "Silk", "Lunar",
    "Moonlit", "Honeyed", "Gilded", "Dusty", "Mystic", "Pearl", "Ivory", "Cinder",
    "Wild", "Quiet", "Salted", "Frost", "Azure", "Crimson", "Noir", "Pale",
    "Oaken", "Marble", "Blooming", "Royal", "Scarlet", "Cedar", "Opal", "Amber",
    "Burnished", "Moonstone", "Porcelain", "Willow", "Botanic", "Lush", "Sunlit",
    "Dappled", "Drifting", "Distant", "Hidden", "Secret", "Twilight", "Aurora",
    "Ember", "Glimmer", "Radiant", "Sterling", "Antique", "Vintage", "Timeless",
    "Sunny", "Breezy", "Misty", "Dewy", "Meadow", "Spiced", "Woodsy", "Creamy",
    "Velvety", "Silken", "Cashmere", "Linen", "Sienna", "Umber", "Indigo",
    "Saffron", "Coraline", "Opaline", "Celadon", "Citrine", "Garnet", "Obsidian",
    "Vermillion", "Copper", "Bronze", "Steel", "Slate",
]
NOUNS = [
    "Garden", "Hour", "Drift", "Sillage", "Haze", "Bloom", "Reverie", "Tide",
    "Dune", "Myth", "Aria", "Muse", "Haven", "Mirage", "Solace", "Cove",
    "Glow", "Veil", "Shadow", "Petal", "Lune", "Kiss", "Spell", "Echo",
    "Grove", "Oak", "Oasis", "Nectar", "Orchard", "Flame", "Ash", "Ember",
    "Sable", "Breeze", "Mist", "Dew", "Harbor", "Horizon", "Sunset", "Dawn",
    "Dusk", "Moon", "Star", "Comet", "Orbit", "Current", "Wave", "Surf",
    "Shore", "Coast", "Isle", "Atoll", "Reef", "Lagoon", "Creek", "Brook",
    "River", "Falls", "Spring", "Rain", "Storm", "Thunder", "Forest", "Pine",
    "Fern", "Moss", "Vine", "Petrichor", "Bourbon", "Cognac", "Fig", "Plum",
    "Cherry", "Almond", "Honey", "Caramel", "Toffee", "Musk", "Wood",
]

_NAME_GRID = len(ADJECTIVES) * len(NOUNS)
_NAME_STRIDE = 3747          # coprime with _NAME_GRID (2^8 * 5^2)
_NAME_SEQ_STRIDE = 571       # coprime with _NAME_GRID, separates repeat variants

# Solid perfume appears on every 4th perfume day (spec rule 3).
SOLID_EVERY_NTH_PERFUME_DAY = 4
_EPOCH = date(2025, 1, 1)


def _name_for(d: date, seq: int) -> str:
    idx = (d.toordinal() * _NAME_STRIDE + seq * _NAME_SEQ_STRIDE) % _NAME_GRID
    return f"{ADJECTIVES[idx // len(NOUNS)]} {NOUNS[idx % len(NOUNS)]}"


def perfume_day_index(d: date) -> int:
    """1-based count of Mon/Wed/Fri perfume days from the epoch through ``d``."""
    if d < _EPOCH:
        return 0
    days = (d - _EPOCH).days
    return sum(
        1
        for i in range(days + 1)
        if (_EPOCH + timedelta(days=i)).weekday() in (0, 2, 4)
    )


def _category_for(d: date) -> str:
    cat = ig.category_for_weekday(d.weekday())
    if cat == "perfume" and perfume_day_index(d) % SOLID_EVERY_NTH_PERFUME_DAY == 0:
        return "solid_perfume"
    return cat


# ---------------------------------------------------------------------------
# Blending
# ---------------------------------------------------------------------------
def _level_parts(total_parts: int) -> Tuple[int, int, int]:
    top = int(round(total_parts * 0.30))
    heart = int(round(total_parts * 0.50))
    base = total_parts - top - heart
    return top, heart, base


def _pick_oils(oils: List[dict], count: int, category: str, offset: int,
               blend_state: dict) -> List[dict]:
    """Pick ``count`` oils. ``blend_state`` carries cross-level safety state:
    at most one skin-restricted (sensitizer-class) oil per entire blend."""
    skin = ig.is_skin_category(category)
    chosen: List[dict] = []
    phototoxic_seen = False
    cursor = offset
    guard = 0
    pool_len = len(oils)
    while len(chosen) < count and guard < pool_len * 4 + 8:
        oil = oils[cursor % pool_len]
        cursor += 1
        guard += 1
        if oil in chosen:
            continue
        if skin:
            if ig.is_skin_restricted(oil):
                continue
            if ig.is_phototoxic(oil):
                if phototoxic_seen:
                    continue
                phototoxic_seen = True
        else:
            if ig.is_skin_restricted(oil):
                if blend_state.get("restricted", 0) >= 1:
                    continue
                blend_state["restricted"] = blend_state.get("restricted", 0) + 1
        chosen.append(oil)
    if not chosen:  # theoretical safety net
        chosen = [o for o in oils[:count]] or oils[:1]
    return chosen


def _allocate_parts(chosen: List[dict], parts: int, rng: random.Random) -> List[Tuple[dict, int]]:
    n = len(chosen)
    if n == 0:
        return []
    by_name = {o["name"]: o for o in chosen}
    alloc = {o["name"]: 1 for o in chosen}
    remaining = parts - n
    order = [o["name"] for o in chosen]
    rng.shuffle(order)
    i = 0
    guard = 0
    while remaining > 0:
        progressed = False
        for _ in range(n):
            name = order[i % n]
            i += 1
            if alloc[name] < max_parts(by_name[name]):
                alloc[name] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
        guard += 1
        if not progressed or guard > parts:
            break  # all oils at their cap; nothing left to distribute
    return [(o, alloc[o["name"]]) for o in chosen]


def _amount_string(oil: dict, parts: int, cfg: dict) -> str:
    if cfg["unit"] == "drops":
        unit = "drop" if parts == 1 else "drops"
        return f"{parts} {unit}"
    ml = round(parts * cfg["part_ml"], 1)
    return f"{ml:g}ml"


def _phrases(blends: List[Tuple[dict, int]], cfg: dict) -> List[str]:
    return [f"{_amount_string(o, p, cfg)} {o['name']}" for o, p in blends]


# ---------------------------------------------------------------------------
# Category templates
# ---------------------------------------------------------------------------
def _instructions(category: str, blends_top, blends_heart, blends_base) -> List[str]:
    cfg = CATEGORIES[category]
    top = ", ".join(_phrases(blends_top, cfg))
    heart = ", ".join(_phrases(blends_heart, cfg))
    base = ", ".join(_phrases(blends_base, cfg))

    if category in ("perfume", "cologne", "solid_perfume"):
        if category == "perfume":
            return [
                "Pour 9.4ml jojoba oil into the 10ml roller bottle using the small funnel, leaving a little headroom.",
                f"Add the essential oil blend in this order: {top} (top notes), then {heart} (heart notes), then {base} (base notes).",
                "Cap the bottle tightly and roll it between your palms 20 times to blend everything evenly.",
                "Label the bottle with the recipe name and date, then let the perfume rest for 48 hours before first use.",
            ]
        if category == "cologne":
            return [
                "Pour 9.4ml perfumer's alcohol into the 10ml spray bottle using the small funnel.",
                f"Add the essential oil blend in this order: {top} (top notes), then {heart} (heart notes), then {base} (base notes).",
                "Cap the bottle and shake gently for 30 seconds to combine.",
                "Label the bottle and let it macerate for 48 hours, shaking once a day, before first use.",
            ]
        return [
            "Melt 6g shea butter and 3g beeswax in a small glass bowl over a saucepan of simmering water until fully liquid.",
            "Remove from heat and stir in the essential oil blend: " + f"{top}, {heart}, and {base}.",
            "Pour the melted blend into the 10g tin and let it set for 30 minutes at room temperature.",
            "Label the tin, then test with a fingertip — the balm should be firm but melt on contact with skin.",
        ]
    if category == "candle":
        return [
            "Melt 110g soy wax in a melt pot over medium-low heat until it reaches about 175°F (80°C).",
            f"Remove from heat and let the wax cool to about 140°F (60°C), then stir in the fragrance blend: {top}, {heart}, and {base}.",
            "Stir gently for 2 full minutes so the fragrance is completely incorporated.",
            "Secure the wick in the candle tin, pour in the wax, and let the candle cure for 24–48 hours.",
            "Trim the wick to 1/4 inch before the first burn.",
        ]
    if category == "reed_diffuser":
        return [
            "Pour 75ml sweet almond oil into the 100ml diffuser bottle.",
            f"Add the fragrance blend: {top}, {heart}, and {base}.",
            "Insert the 6 rattan reed sticks and let them soak for 24 hours before the first flip.",
            "Flip the reeds once a week to refresh the scent, and label the bottle with the recipe name.",
        ]
    # room_spray
    return [
        f"Combine the essential oil blend — {top}, {heart}, and {base} — with 3ml polysorbate 20 in a small bowl and stir to combine.",
        "Add 115ml distilled water and stir until the mixture looks cloudy and evenly dispersed.",
        "Funnel everything into the 120ml spray bottle and label it.",
        "Shake well before every use.",
    ]


def _safety_notes(category: str, blends: List[Tuple[dict, int]]) -> List[str]:
    cfg = CATEGORIES[category]
    notes: List[str] = ["Keep essential oils and the finished fragrance out of reach of children and pets."]

    if cfg["skin"]:
        notes += [
            "Patch test on a small area of skin before regular use.",
            "Do not apply to broken or irritated skin.",
            "Keep away from eyes and mucous membranes.",
            "Store in a cool, dark place away from direct sunlight.",
            "If pregnant, nursing, or under medical care, ask a healthcare provider before use.",
        ]
        phototoxic = [o["note"] for o, _ in blends if ig.is_phototoxic(o)]
        if phototoxic:
            names = " and ".join(phototoxic)
            notes.append(
                f"Contains phototoxic citrus oil ({names}) — avoid sun/UV exposure on treated skin for 12+ hours after application."
            )
    tonka = [o["note"] for o, _ in blends if ig.flag_of(o, "coumarin")]
    if tonka:
        notes.append("Contains tonka bean absolute (coumarin) — do not exceed the amount stated in the recipe.")
    if not cfg["skin"]:
        restricted = [o["note"] for o, _ in blends if ig.is_skin_restricted(o)]
        if restricted:
            notes.append(
                "Contains " + " and ".join(restricted) + " — for home fragrance only; do not apply to skin."
            )

    if category == "candle":
        notes += [
            "Never leave a burning candle unattended.",
            "Burn within sight and away from drafts, children, and pets.",
            "Trim the wick to 1/4 inch before every burn.",
            "Stop burning when 1/4 inch of wax remains.",
            "Do not touch the melted wax or move a lit candle.",
        ]
    elif category == "reed_diffuser":
        notes += [
            "Place away from direct sunlight, heat sources, and open flames.",
            "Do not ingest. The carrier oil is not for skin application.",
            "Flip the reeds weekly and refresh the oil when the scent fades.",
        ]
    elif category == "room_spray":
        notes += [
            "Shake well before every use.",
            "Spray away from the face; avoid inhaling the mist directly.",
            "Test on an inconspicuous surface before spraying fabrics.",
            "Store out of direct sunlight.",
        ]
    return notes


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------
class RecipeGenerator:
    """Deterministic per-date recipe generator."""

    def __init__(self, d: date, seq: int = 0):
        self.d = d
        self.seq = seq
        self.rng = random.Random(f"{d.isoformat()}|{seq}")
        self.category = _category_for(d)
        self.theme = themes.DAY_THEMES[d.weekday()]
        self.holiday = themes.holiday_for(d)
        self.recipe_name = _name_for(d, seq)
        self.difficulty = pricing.pick_difficulty(
            self.rng, self.theme, self.category, self.holiday
        )
        self.price = pricing.expected_price(self.difficulty, d, self.holiday)
        self.scent_profile: Dict[str, List[str]] = {}

    # -- blending ----------------------------------------------------------
    def build_blend(self) -> Dict[str, List[Tuple[dict, int]]]:
        cfg = CATEGORIES[self.category]
        pools = themes.effective_families(self.d)
        top_parts, heart_parts, base_parts = _level_parts(cfg["total_parts"])
        ordinal = self.d.toordinal()
        levels = {
            "top": (top_parts, 0),
            "heart": (heart_parts, 3),
            "base": (base_parts, 7),
        }
        result: Dict[str, List[Tuple[dict, int]]] = {}
        blend_state: Dict[str, int] = {}
        holiday_prefix = themes.holiday_prefix_families(self.d)
        for level, (parts, salt) in levels.items():
            oils = ig.oils_in_families(pools[level])
            # On holiday dates, bias the sampling window into the holiday family
            # prefix so the holiday character drives the blend (spec rule 6).
            prefix_len = len(ig.oils_in_families(holiday_prefix[level]))
            if prefix_len > 0:
                window = min(prefix_len, len(oils))
            else:
                window = len(oils)
            count = self.rng.randint(2, min(3, parts))
            offset = (ordinal * 7 + salt) % max(window, 1)
            chosen = _pick_oils(oils, count, self.category, offset, blend_state)
            result[level] = _allocate_parts(chosen, parts, self.rng)
        return result

    def build_safety_and_instructions(self, blend) -> Tuple[List[str], List[str]]:
        all_blends = blend["top"] + blend["heart"] + blend["base"]
        safety = _safety_notes(self.category, all_blends)
        instructions = _instructions(self.category, blend["top"], blend["heart"], blend["base"])
        return safety, instructions

    # -- assembly ----------------------------------------------------------
    def generate(self) -> dict:
        blend = self.build_blend()
        safety, instructions = self.build_safety_and_instructions(blend)
        cfg = CATEGORIES[self.category]

        self.scent_profile = {
            "top_notes": [o["note"] for o, _ in blend["top"]],
            "heart_notes": [o["note"] for o, _ in blend["heart"]],
            "base_notes": [o["note"] for o, _ in blend["base"]],
        }

        # ingredients: carriers first, then top/heart/base oils
        ingredients: List[dict] = []
        carry = self._carrier_ingredients(blend)
        ingredients.extend(carry)
        for level in ("top", "heart", "base"):
            for oil, parts in blend[level]:
                ingredients.append(
                    {
                        "name": oil["name"],
                        "amount": _amount_string(oil, parts, cfg),
                        "purpose": level,
                    }
                )

        cost = pricing.estimate_cost(self.category, blend["top"] + blend["heart"] + blend["base"])
        cost_str = pricing.format_cost(cost)
        slug = seo.make_slug(self.recipe_name, self.category)
        full_title = seo.make_title(self.category, self.scent_profile, self.d)
        tags = seo.make_tags(self.category, self.d, self.scent_profile)
        description = seo.make_description(
            self.category,
            self.scent_profile,
            self.theme,
            self.holiday,
            seo.season_word(self.d),
            self.difficulty,
            cfg["yield"],
            cost_str,
            safety,
        )

        recipe = {
            "recipe_name": self.recipe_name,
            "full_title": full_title,
            "slug": slug,
            "category": self.category,
            "difficulty": self.difficulty,
            "scent_profile": self.scent_profile,
            "ingredients": ingredients,
            "equipment": list(cfg["equipment"]),
            "instructions": instructions,
            "safety_notes": safety,
            "yield": cfg["yield"],
            "cost_to_make": cost_str,
            "description_long": description,
            "tags": tags,
            "price_usd": self.price,
            "theme": self.theme,
            "holiday": self.holiday,
        }
        assert_valid(recipe)
        return recipe

    def _carrier_ingredients(self, blend: Dict[str, List[Tuple[dict, int]]]) -> List[dict]:
        cfg = CATEGORIES[self.category]
        out: List[dict] = []
        if cfg["unit"] == "drops":
            blend_ml = sum(p / (o.get("drops_per_ml", 25)) for o, p in
                           (blend["top"] + blend["heart"] + blend["base"]))
        else:
            blend_ml = sum(p * cfg["part_ml"] for o, p in
                           (blend["top"] + blend["heart"] + blend["base"]))

        rule = cfg.get("carrier_rule")
        if rule:
            name, kind = rule
            if kind == "fill":
                amount = round(cfg["bottle_ml"] - blend_ml, 1)
                out.append({"name": name, "amount": f"{amount:g}ml", "purpose": "carrier"})
            elif kind == "beeswax-combo":
                out.append({"name": "Shea Butter", "amount": "6g", "purpose": "carrier"})
                out.append({"name": "Beeswax", "amount": "3g", "purpose": "carrier"})
        # fixed-quantity carriers (soy wax, diffuser oil, water + solubol, ...)
        for carrier_name, amount in ig._CARRIER_AMOUNTS.get(self.category, []):
            if carrier_name not in {c["name"] for c in out}:
                out.append({"name": carrier_name, "amount": amount, "purpose": "carrier"})
        return out


def generate_recipe(d: date, seq: int = 0) -> dict:
    return RecipeGenerator(d, seq).generate()


def batch_generate(start: date, count: int, seq: int = 0) -> List[dict]:
    return [generate_recipe(start + timedelta(days=i), seq) for i in range(count)]


def balance_of(recipe: dict) -> Tuple[dict, dict]:
    """Recompute the top/heart/base balance from a recipe's ingredient amounts.

    Returns (part counts per level, fractional shares). Works for both drop-based
    and ml-based (candle / reed diffuser) products.
    """
    cfg = CATEGORIES[recipe["category"]]
    counts = {"top": 0, "heart": 0, "base": 0}
    for ing in recipe["ingredients"]:
        purpose = ing["purpose"]
        if purpose not in counts:
            continue
        amount = ing["amount"]
        if amount.endswith("drops") or amount.endswith("drop"):
            parts = int(amount.split()[0])
        elif amount.endswith("ml") and cfg["unit"] == "parts":
            parts = round(float(amount[:-2]) / cfg["part_ml"])
        else:
            continue
        counts[purpose] += parts
    total = sum(counts.values())
    shares = {k: (v / total if total else 0.0) for k, v in counts.items()}
    return counts, shares