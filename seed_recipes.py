#!/usr/bin/env python3
"""Seed the Fragrance Bot recipe library (deterministic, idempotent).

Generates ``--count`` recipes with the engine's batch mode (deterministic:
same start date -> same recipes on every run), marks the first ``--ready`` as
status='draft_ready' (the daily posting queue) and the rest as 'draft'
(library-only, not queued), then upserts them into public.recipes.

Idempotency contract
--------------------
* Re-running the seed never duplicates rows: upserts key on recipes.slug
  (ON CONFLICT (slug) DO UPDATE).
* A re-run refreshes CONTENT fields only. It never resets status /
  listing_id / etsy_url / created_at / listed_at, so recipes that already
  progressed to 'listed' are left alone.

Modes
-----
* live:     python3 seed_recipes.py
            Uses get_store() -> POSTGRES_URL, else SUPABASE_URL +
            SUPABASE_SERVICE_ROLE_KEY (see fragbot/db.py).
* dry-run:  python3 seed_recipes.py --dry-run
            Logs the SQL that would run; nothing touches a database.
* sql-out:  python3 seed_recipes.py --dry-run --sql-out seed_library.sql
            Writes the full runnable script (BEGIN/COMMIT wrapped).
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fragbot.db import (
    Store,
    get_store,
    render_upsert_sql,
    seed_created_at,
    upsert_recipe_sql,
)
from fragbot.generator import batch_generate
from fragbot.schema import validate

logger = logging.getLogger("seed_recipes")

DEFAULT_START = date(2026, 1, 1)
DEFAULT_COUNT = 60
DEFAULT_READY = 30


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="seed_recipes.py",
        description="Generate and upsert the deterministic starter recipe library.",
    )
    p.add_argument("--count", type=int, default=DEFAULT_COUNT,
                   help=f"number of recipes to generate (default {DEFAULT_COUNT})")
    p.add_argument("--ready", type=int, default=DEFAULT_READY,
                   help=f"how many of the first recipes get status 'draft_ready' "
                        f"(default {DEFAULT_READY}; the rest become 'draft')")
    p.add_argument("--start", default=DEFAULT_START.isoformat(),
                   help=f"first recipe date, YYYY-MM-DD (default {DEFAULT_START})")
    p.add_argument("--dry-run", action="store_true",
                   help="do not touch any database: log the SQL statements instead")
    p.add_argument("--sql-out", metavar="FILE",
                   help="also write the runnable SQL script (BEGIN/COMMIT) to FILE")
    p.add_argument("--postgres-url", metavar="URL",
                   help="override POSTGRES_URL for this run (overrides env)")
    return p.parse_args(argv)


def _generate(count: int, start: date) -> List[dict]:
    recipes = batch_generate(start, count)
    slugs = [r["slug"] for r in recipes]
    if len(set(slugs)) != len(slugs):
        raise RuntimeError("engine produced duplicate slugs — cannot seed")
    for r in recipes:
        problems = validate(r)
        if problems:
            raise RuntimeError(
                f"recipe {r.get('slug')!r} failed schema validation: {problems}"
            )
    return recipes


def seed(store: Store, count: int, ready: int, start: date) -> int:
    """Upsert the library through a store; returns number of upserted rows."""
    recipes = _generate(count, start)
    base = datetime.now(timezone.utc)
    for i, recipe in enumerate(recipes):
        status = "draft_ready" if i < ready else "draft"
        created_at = seed_created_at(i, count, base)
        recipe_id = store.upsert_recipe(recipe, status, created_at)
        logger.info("upserted %s (%s, %s) -> %s", recipe["slug"], status, recipe["category"], recipe_id)
    return len(recipes)


def _render_sql_script(count: int, ready: int, start: date) -> str:
    recipes = _generate(count, start)
    base = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)  # deterministic placeholder
    lines = [
        "-- Fragrance Bot seed script (generated; run with the schema applied):",
        f"-- python3 seed_recipes.py --count {count} --ready {ready} --start {start.isoformat()}",
        "",
        "begin;",
    ]
    for i, recipe in enumerate(recipes):
        status = "draft_ready" if i < ready else "draft"
        created_at = seed_created_at(i, count, base)
        lines.append(render_upsert_sql(recipe, status, created_at) + ";")
    lines += ["", "commit;"]
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.count < 1:
        raise SystemExit("error: --count must be >= 1")
    if not (0 <= args.ready <= args.count):
        raise SystemExit("error: --ready must be between 0 and --count")
    try:
        start = date.fromisoformat(args.start)
    except ValueError:
        raise SystemExit(f"error: invalid --start date {args.start!r} (expected YYYY-MM-DD)")

    sql_script = _render_sql_script(args.count, args.ready, start)
    if args.sql_out:
        Path(args.sql_out).write_text(sql_script, encoding="utf-8")
        logger.info("wrote SQL script to %s", args.sql_out)

    if args.dry_run:
        if not args.sql_out:
            print(sql_script, end="")
        logger.info(
            "dry run: %d recipes generated (%d draft_ready / %d draft); "
            "no database was touched",
            args.count, args.ready, args.count - args.ready,
        )
        return 0

    try:
        store = get_store()
    except Exception as exc:  # StoreNotConfiguredError or import errors
        raise SystemExit(
            f"error: {exc}\n"
            "Hint: run with --dry-run to preview SQL, or set POSTGRES_URL "
            "(or SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)."
        )
    total = seed(store, args.count, args.ready, start)
    logger.info(
        "seeded %d recipes (%d draft_ready / %d draft) — idempotent, safe to re-run",
        total, args.ready, args.count - args.ready,
    )
    print(f"OK: {total} recipes upserted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())