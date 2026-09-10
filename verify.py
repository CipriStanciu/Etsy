#!/usr/bin/env python3
"""Self-test / verification script for the Fragrance Bot recipe engine.

Run from the package root:  python3 verify.py

Checks (spec rules 1-10):
  1. 30 consecutive daily recipes generate without error and are unique
     (recipe_name, slug, and full note profile).
  2. Every recipe is schema-valid: all fields present, tags exactly 13 and
     each <= 20 chars, full_title <= 140 chars, ingredients reference real
     DB entries, price within 3.99-9.99 and matching difficulty/weekend/
     holiday pricing rules.
  3. Note balance 30/50/20 top/heart/base within +/- 5 percentage points.
  4. Category rotation matches the day-of-week spec, including the
     solid_perfume variant on every 4th perfume day.
  5. No safety-flagged combos: no skin-restricted oils in skin-contact
     products, at most one phototoxic citrus per skin blend (with a warning
     note), at most one skin-restricted oil in home-fragrance blends (with a
     note), coumarin oils flagged in notes.
  6. Holiday detection windows (Valentine's, Mother's Day, Christmas) and
     weekend premiums are applied to names, themes and prices.
  7. Determinism: same date + same config -> identical recipe JSON.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fragbot import batch_generate, generate_recipe
from fragbot.generator import balance_of
from fragbot.ingredients import CARRIER_PRICES, OILS
from fragbot.pricing import DIFFICULTY_BASE, HOLIDAY_PREMIUM, WEEKEND_PREMIUM
from fragbot.schema import EXPECTED_KEYS, validate

# ---------------------------------------------------------------------------
# Independent re-implementations of the spec rules (not imported from fragbot),
# so the verification is a real check rather than a tautology.
# ---------------------------------------------------------------------------
WEEKDAY_CATEGORY = {0: "perfume", 1: "candle", 2: "perfume", 3: "reed_diffuser",
                    4: "perfume", 5: "room_spray", 6: "cologne"}
EPOCH = date(2025, 1, 1)


def expected_category(d: date) -> str:
    cat = WEEKDAY_CATEGORY[d.weekday()]
    if cat == "perfume":
        perfume_days = sum(
            1 for i in range((d - EPOCH).days + 1)
            if (EPOCH + timedelta(days=i)).weekday() in (0, 2, 4)
        )
        if perfume_days % 4 == 0:
            return "solid_perfume"
    return cat


def expected_holiday(d: date) -> str | None:
    # Valentine's window Feb 7-14
    if date(d.year, 2, 7) <= d <= date(d.year, 2, 14):
        return "Valentine's Day"
    # US Mother's Day: 2nd Sunday of May, window = week before through that day
    first = date(d.year, 5, 1)
    second_sunday = first + timedelta(days=(6 - first.weekday()) + 7)
    if second_sunday - timedelta(days=6) <= d <= second_sunday:
        return "Mother's Day"
    # Christmas window Dec 18-26
    if date(d.year, 12, 18) <= d <= date(d.year, 12, 26):
        return "Christmas"
    return None


def expected_theme(d: date) -> str:
    return ["Monday Mood", "Cozy Tuesday", "Wellness Wednesday", "Date Night",
            "Friday Luxe", "Weekend Project", "Sunday Reset"][d.weekday()]


def expected_price(difficulty: str, d: date, holiday: str | None) -> float:
    price = DIFFICULTY_BASE[difficulty]
    if d.weekday() >= 5:
        price += WEEKEND_PREMIUM
    if holiday:
        price += HOLIDAY_PREMIUM
    return min(round(price, 2), 9.99)


OIL_NAMES = {o["name"] for o in OILS}
CARRIER_NAMES = set(CARRIER_PRICES)
DB_NAMES = OIL_NAMES | CARRIER_NAMES
SKIN_RESTRICTED = {"Clove Bud Essential Oil", "Cinnamon Bark Essential Oil", "Lemongrass Essential Oil"}
PHOTOTOXIC = {"Bergamot Essential Oil", "Lemon Essential Oil", "Grapefruit Essential Oil", "Lime Essential Oil"}
COUMARIN = {"Tonka Bean Absolute"}
SKIN_CATEGORIES = {"perfume", "cologne", "solid_perfume"}

checked = 0
failed = []


def check(cond: bool, label: str, detail: str = "") -> None:
    global checked
    checked += 1
    if not cond:
        failed.append(f"{label} {detail}".strip())


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------
def main() -> int:
    start = date(2026, 1, 5)  # a Monday; 30 days exercises every weekday x4+
    days = [start + timedelta(days=i) for i in range(30)]
    recipes = [generate_recipe(d) for d in days]

    # --- 1. schema validity on every recipe
    names, slugs, profiles, tags_ok, titles_ok, prices_ok = set(), set(), set(), True, True, True
    balance_ok = True
    for r in recipes:
        problems = validate(r)
        check(not problems, f"schema-valid {r['recipe_name']} ({r['category']})", "; ".join(problems))
        names.add(r["recipe_name"])
        slugs.add(r["slug"])
        profiles.add((tuple(sorted(r["scent_profile"]["top_notes"])),
                      tuple(sorted(r["scent_profile"]["heart_notes"])),
                      tuple(sorted(r["scent_profile"]["base_notes"]))))
        if len(r["tags"]) != 13 or any(len(t) > 20 for t in r["tags"]):
            tags_ok = False
        if len(r["full_title"]) > 140:
            titles_ok = False
            print(f"  [debug] title too long: {len(r['full_title'])} {r['full_title']}")
        if not (3.99 <= r["price_usd"] <= 9.99):
            prices_ok = False
        # balance
        counts, shares = balance_of(r)
        if not (abs(shares["top"] - 0.30) <= 0.05 and abs(shares["heart"] - 0.50) <= 0.05
                and abs(shares["base"] - 0.20) <= 0.05):
            balance_ok = False
            print(f"  [debug] balance off for {r['recipe_name']}: {shares} (counts {counts})")
    check(len(recipes) == 30, "30 recipes generated")
    check(len(names) == 30, "unique recipe names", f"(got {len(names)})")
    check(len(slugs) == 30, "unique slugs")
    check(len(profiles) == 30, "unique full note profiles")
    check(tags_ok, "tags exactly 13, each <= 20 chars")
    check(titles_ok, "full_title <= 140 chars")
    check(prices_ok, "price within 3.99-9.99")

    # --- 2. rotation, holiday, theme, pricing
    rotation_ok = theme_ok = holiday_ok = pricing_ok = True
    for d, r in zip(days, recipes):
        if r["category"] != expected_category(d):
            rotation_ok = False
            print(f"  [debug] {d} expected {expected_category(d)} got {r['category']}")
        if r["theme"] != expected_theme(d):
            theme_ok = False
        if r["holiday"] != expected_holiday(d):
            holiday_ok = False
        exp = expected_price(r["difficulty"], d, r["holiday"])
        if abs(r["price_usd"] - exp) > 0.001:
            pricing_ok = False
            print(f"  [debug] {d} {r['recipe_name']} price {r['price_usd']} expected {exp}")
    check(rotation_ok, "category rotation matches day-of-week spec")
    check(theme_ok, "theme matches weekday")
    check(holiday_ok, "holiday field matches windows")
    check(pricing_ok, "price matches difficulty/weekend/holiday rules")
    check(balance_ok, "30/50/20 note balance within +/- 5 pp of total")

    # --- 3. safety rules
    safety_ok = True
    for r in recipes:
        cat = r["category"]
        ing = {i["name"]: i for i in r["ingredients"]}
        # all ingredients are real DB entries
        if not all(n in DB_NAMES for n in ing):
            safety_ok = False
            print(f"  [debug] unknown ingredient in {r['recipe_name']}: {set(ing) - DB_NAMES}")
        names_in = set(ing)
        for oil_name in SKIN_RESTRICTED & names_in:
            if cat in SKIN_CATEGORIES:
                safety_ok = False
                print(f"  [debug] skin-restricted {oil_name} in skin product {r['recipe_name']}")
            elif not any("home fragrance only" in s for s in r["safety_notes"]):
                safety_ok = False
                print(f"  [debug] missing home-fragrance note for {oil_name}")
        photo = PHOTOTOXIC & names_in
        if cat in SKIN_CATEGORIES:
            if len(photo) > 1:
                safety_ok = False
                print(f"  [debug] {len(photo)} phototoxic oils in {r['recipe_name']}")
            if photo and not any("phototoxic" in s.lower() for s in r["safety_notes"]):
                safety_ok = False
                print(f"  [debug] missing phototoxic note in {r['recipe_name']}")
        # never combine two skin-restricted (sensitizer-class) oils
        if len(SKIN_RESTRICTED & names_in) > 1:
            safety_ok = False
            print(f"  [debug] two sensitizer oils combined in {r['recipe_name']}")
        if (COUMARIN & names_in) and not any("coumarin" in s.lower() for s in r["safety_notes"]):
            safety_ok = False
            print(f"  [debug] missing coumarin note in {r['recipe_name']}")
    check(safety_ok, "no unsafe ingredient combinations; warnings present")

    # --- 3b. every product lists its required carrier(s) in ingredients
    REQUIRED_CARRIERS = {
        "perfume": {"Jojoba Oil"},
        "cologne": {"Perfumer's Alcohol (190 proof)"},
        "solid_perfume": {"Shea Butter", "Beeswax"},
        "candle": {"Soy Wax"},
        "reed_diffuser": {"Sweet Almond Oil"},
        "room_spray": {"Distilled Water", "Polysorbate 20"},
    }
    carriers_ok = True
    for r in recipes:
        names = {i["name"] for i in r["ingredients"]}
        missing = REQUIRED_CARRIERS.get(r["category"], set()) - names
        if missing:
            carriers_ok = False
            print(f"  [debug] {r['recipe_name']} missing carriers: {missing}")
    check(carriers_ok, "every recipe lists its required carriers")

    # --- 4. determinism + seq variants
    r1 = generate_recipe(date(2026, 2, 11))
    r2 = generate_recipe(date(2026, 2, 11))
    check(json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True),
          "deterministic: same date twice -> same JSON")
    r3 = generate_recipe(date(2026, 2, 11), seq=1)
    check(r3["recipe_name"] != r1["recipe_name"] and r3["slug"] != r1["slug"],
          "batch sequence number yields a different recipe")

    # --- 5. holiday / weekend premium spot checks
    v = generate_recipe(date(2026, 2, 11))   # in Valentine's window, a Wednesday
    check(v["holiday"] == "Valentine's Day", "Valentine's Day detected on 2026-02-11")
    check(abs(v["price_usd"] - expected_price(v["difficulty"], date(2026, 2, 11), "Valentine's Day")) <= 0.001,
          "Valentine's holiday premium applied")
    m = generate_recipe(date(2026, 5, 10))   # 2nd Sunday of May 2026
    check(m["holiday"] == "Mother's Day", "Mother's Day detected on 2026-05-10")
    c = generate_recipe(date(2026, 12, 20))  # Sunday in Christmas window
    check(c["holiday"] == "Christmas", "Christmas detected on 2026-12-20")
    check(abs(c["price_usd"] - expected_price(c["difficulty"], date(2026, 12, 20), "Christmas")) <= 0.001,
          "weekend + holiday premiums applied on 2026-12-20")
    s = generate_recipe(date(2026, 1, 10))   # a Saturday
    check(abs(s["price_usd"] - expected_price(s["difficulty"], date(2026, 1, 10), None)) <= 0.001,
          "weekend premium applied on Saturday")

    # --- 6. batch / seeding smoke test
    batch = batch_generate(date(2026, 4, 1), 7)
    check(len(batch) == 7 and all(not validate(r) for r in batch), "batch_generate(7) valid")

    # --- 7. taxonomy coverage
    cats_seen = {r["category"] for r in recipes}
    check(cats_seen == {expected_category(d) for d in days}, "all rotation categories covered")
    diffs_seen = {r["difficulty"] for r in recipes}
    check(diffs_seen <= {"beginner", "intermediate", "advanced"} and len(diffs_seen) >= 2,
          "difficulty varies", f"(got {sorted(diffs_seen)})")

    # -----------------------------------------------------------------------
    print("=" * 78)
    print("FragBot recipe engine — verification report")
    print(f"window: {days[0].isoformat()} .. {days[-1].isoformat()} (30 days)")
    print("=" * 78)
    print(f"{'date':<12}{'category':<14}{'name':<22}{'diff':<13}{'price':<7}{'theme':<20}{'holiday'}")
    for d, r in zip(days, recipes):
        hol = r["holiday"] or ""
        print(f"{d.isoformat():<12}{r['category']:<14}{r['recipe_name']:<22}{r['difficulty']:<13}"
              f"${r['price_usd']:<6.2f}{r['theme']:<20}{hol}")
    print("-" * 78)
    for d, r in zip(days, recipes):
        _, shares = balance_of(r)
        line = (f"  {d.isoformat()} {r['recipe_name']:<20} "
                f"top {shares['top']*100:4.1f}%  heart {shares['heart']*100:4.1f}%  base {shares['base']*100:4.1f}%")
        print(line)
    print("-" * 78)
    checks_pass = len(failed) == 0
    print(f"checks run : {checked}")
    print(f"passed     : {checked - len(failed)}")
    print(f"failed     : {len(failed)}")
    for f in failed:
        print(f"  FAIL: {f}")
    print("RESULT:", "PASS" if checks_pass else "FAIL")
    return 0 if checks_pass else 1


if __name__ == "__main__":
    sys.exit(main())