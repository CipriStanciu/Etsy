#!/usr/bin/env python3
"""Regenerate the dashboard's bundled sample snapshot (dashboard/data/stub.json).

The dashboard works without any credentials by falling back to this file. It is
NOT live data — every recipe here is produced by the real engine (so the stub
is structurally identical to what Supabase serves), but statuses, Etsy URLs,
listing ids and metrics are fabricated sample values so the UI demos every
feature (including the low-inventory alert) with no network.

Snapshot contract (matches lib/types.ts + what the live API route returns):
    {
      "meta": {...},
      "recipes":     [ ...flat rows exactly like public.recipes... ],
      "daily_posts": [ ...rows exactly like public.daily_posts... ],
    }

Regenerate:  python3 dashboard/scripts/generate_stub.py
"""
from __future__ import annotations

import json
import random
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from fragbot.generator import batch_generate  # noqa: E402
from fragbot.schema import validate  # noqa: E402

RECIPE_START = date(2026, 1, 1)
RECIPE_COUNT = 43          # 35 used by the 35-day calendar window + 8 extra queued
QUEUED_EXTRA = 8           # draft_ready pool -> 8 < 10 -> the inventory alert fires
CALENDAR_PAST = 5          # posted days before today (so metrics have history)
CALENDAR_AHEAD = 29        # scheduled days after today (today + this = 30-day calendar)
OUT = REPO_ROOT / "dashboard" / "data" / "stub.json"


def recipe_row(recipe: dict, idx: int, status: str) -> dict:
    """Flatten an engine recipe into a public.recipes-shaped row (see schema.sql)."""
    row = dict(recipe)
    row["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"fragbot-stub:{recipe['slug']}"))
    row["yield_text"] = row.pop("yield")   # YIELD is reserved in SQL; stored as yield_text
    row["price_usd"] = float(row["price_usd"])
    row["status"] = status
    row["listing_id"] = None
    row["etsy_url"] = None
    row["created_at"] = (datetime.combine(RECIPE_START, datetime.min.time(), tzinfo=timezone.utc)
                         + timedelta(days=idx)).isoformat()
    row["listed_at"] = None
    return row


def main() -> None:
    recipes_raw = batch_generate(RECIPE_START, RECIPE_COUNT, 0)
    assert len(recipes_raw) == RECIPE_COUNT, "engine returned the wrong count"
    for r in recipes_raw:                      # engine output must stay schema-valid
        errs = validate(r)
        assert not errs, f"engine emitted invalid recipe: {errs}"

    today = date.today()
    window = [today + timedelta(days=d) for d in range(-CALENDAR_PAST, CALENDAR_AHEAD + 1)]
    assert len(window) == RECIPE_COUNT - QUEUED_EXTRA, "window must map 1:1 onto recipes"

    # status per recipe index: calendar-used recipes are 'listed' (past+today) or
    # 'draft' (future plan); the QUEUED_EXTRA extras are 'draft_ready' (the queue).
    used_idx = {(d - RECIPE_START).days % RECIPE_COUNT for d in window}
    status_of: dict[int, str] = {}
    for idx in range(RECIPE_COUNT):
        if idx in used_idx:
            status_of[idx] = "draft"
        else:
            status_of[idx] = "draft_ready"
    for d in window[:-CALENDAR_AHEAD]:         # past + today -> listed
        status_of[(d - RECIPE_START).days % RECIPE_COUNT] = "listed"

    rng = random.Random("fragbot-stub-metrics")
    recipes: list[dict] = []
    for idx, r in enumerate(recipes_raw):
        recipes.append(recipe_row(r, idx, status_of[idx]))

    # attach listing details to listed recipes (sample Etsy ids/URLs — clearly stub)
    listing_counter = 900000
    listed_by_id = {}
    for idx in [i for i, s in status_of.items() if s == "listed"]:
        listed_at = next(d for d in window if (d - RECIPE_START).days % RECIPE_COUNT == idx
                         and d <= today)
        rec = recipes[idx]
        rec["listing_id"] = str(listing_counter + idx)
        rec["etsy_url"] = f"https://www.etsy.com/listing/{rec['listing_id']}/{rec['slug']}"
        rec["listed_at"] = datetime.combine(listed_at, datetime.min.time(),
                                            tzinfo=timezone.utc).isoformat()
        listed_by_id[rec["id"]] = rec

    daily_posts = []
    for d in window:
        idx = (d - RECIPE_START).days % RECIPE_COUNT
        rec = recipes[idx]
        if d > today:
            status, posted_at = "scheduled", None
            views = favorites = sales = 0
        elif d == today:
            status, posted_at = "posted", datetime.now(timezone.utc).isoformat()
            views, favorites, sales = rng.randint(0, 14), rng.randint(0, 4), rng.randint(0, 2)
        else:
            status, posted_at = "posted", datetime.combine(d, datetime.min.time(),
                                                           tzinfo=timezone.utc).isoformat()
            views, favorites, sales = (rng.randint(9, 170), rng.randint(0, 26),
                                       rng.randint(0, 7))
        daily_posts.append({
            "date": d.isoformat(),
            "recipe_id": rec["id"],
            "listing_id": rec["listing_id"] if status == "posted" else None,
            "status": status,
            "views": views,
            "favorites": favorites,
            "sales": sales,
            "posted_at": posted_at,
        })

    payload = {
        "meta": {
            "recipe_start": RECIPE_START.isoformat(),
            "recipe_count": RECIPE_COUNT,
            "calendar_window": [window[0].isoformat(), window[-1].isoformat()],
            "queue_size_draft_ready": sum(1 for s in status_of.values() if s == "draft_ready"),
            "note": "sample snapshot generated by dashboard/scripts/generate_stub.py",
        },
        "recipes": recipes,
        "daily_posts": daily_posts,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(recipes)} recipes, {len(daily_posts)} daily posts)")


if __name__ == "__main__":
    main()