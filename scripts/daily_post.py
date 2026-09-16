#!/usr/bin/env python3
"""Daily Etsy posting pipeline for Fragrance Bot.

Draws the oldest ``draft_ready`` recipe from the Supabase-backed store,
renders its 5 listing images and the recipe-card PDF, creates a digital
download listing on Etsy, uploads everything, activates it and records the
post — then (only if RESEND_API_KEY is set) emails the owner the listing URL.

Order of operations (researched against Etsy's official OpenAPI v3 spec —
see fraggbot/etsy/spec.py for the parameter-level notes):

    1. load store → get_next_draft_recipe()       (oldest draft_ready)
    2. render 5 images   (fragbot.imagesgen.render_recipe)
    3. render PDF        (fragbot.pdfgen.generate_pdf)
    4. verify shop       (GET /v3/application/shops/{id})
    5. resolve taxonomy  (GET /v3/application/seller-taxonomy/nodes)
    6. createListingDraft (POST .../shops/{id}/listings, type=download)
    7. uploadListingImage × 5 (rank 1..5, first = primary)
    8. publish: activate (PATCH state=active) → upload digital PDF
       (uploadListingFile) — with an automatic fallback that uploads the
       file first if Etsy demands a digital file before activation
    9. getListing for the public URL
   10. mark_listed(recipe_id, listing_id, etsy_url)
       + record_daily_post(today, recipe_id, status='posted')
   11. optional Resend email (only when RESEND_API_KEY set; otherwise just
       log the listing URL).

Failure semantics (owner spec): on ANY Etsy API error → log the error, leave
the recipe as ``draft_ready`` (never mark listed), record the day as
``failed`` in daily_posts, and exit non-zero — so the next run retries the
same recipe. Idempotent by construction: get_next_draft_recipe() only
returns recipes that are still ``draft_ready`` with no listing_id.

Dry-run (--dry-run) does everything except touch Etsy (and the store): it
prints the exact payloads that would be sent.

Posting cadence (config-driven, NOT hardcoded): the GitHub Actions workflow
still triggers *daily* at 08:00 UTC, but the script only posts on "posting
days" — those where (today - 2026-01-01).days % interval == 0, with
``interval`` read from FRAGBOT_POST_INTERVAL_DAYS (default 3 → one listing
every 3 days; set 1 for every day, 2 for every 2 days, etc.). On a non-posting
day the script logs ``not a posting day (interval N) — nothing to do`` and
exits 0 — green workflow, and CRUCIALLY it touches nothing: no recipe is
consumed, no ``daily_posts`` row is created, no Etsy listing is attempted, so
the queue and store are byte-identical. The existing skip-day retry semantics
are unchanged: on a real Etsy error the run exits non-zero and the recipe
stays ``draft_ready`` to be retried on the next posting day.

Usage
-----
    # live (add --promo to also render the 4 social promo assets)
    python3 scripts/daily_post.py [--promo] [--log-file logs/daily.log]

    # dry run against an example recipe (no credentials needed)
    python3 scripts/daily_post.py --dry-run

    # simulate a specific date for the posting-day decision (test hook)
    python3 scripts/daily_post.py --dry-run --date 2026-01-01   # posting day
    python3 scripts/daily_post.py --dry-run --date 2026-01-02   # non-posting

    # against the local mock + in-memory store (verification)
    python3 scripts/daily_post.py --store stub
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fragbot.db import StoreNotConfiguredError, get_store  # noqa: E402
from fragbot.etsy import EtsyClient  # noqa: E402
from fragbot.etsy.errors import EtsyError, EtsyValidationError  # noqa: E402
from fragbot.imagesgen import render_recipe  # noqa: E402
from fragbot.pdfgen import generate_pdf  # noqa: E402
from fragbot.schema import assert_valid  # noqa: E402

log = logging.getLogger("fragbot.daily_post")

IMAGE_KINDS = ["hero", "ingredients", "pyramid", "included", "lifestyle"]
BRAND = "Fragrance Bot"

RESEND_URL = "https://api.resend.com/emails"

# ---------------------------------------------------------------------------
# Posting cadence (config-driven, default every 3 days)
# ---------------------------------------------------------------------------
# Day index is measured from a FIXED anchor (the seed start date) so the
# cadence is deterministic and independent of the cron's day-of-month: today
# is a posting day iff (today - anchor).days % interval == 0.
POSTING_ANCHOR = date(2026, 1, 1)
POSTING_INTERVAL_ENV = "FRAGBOT_POST_INTERVAL_DAYS"
DEFAULT_POST_INTERVAL_DAYS = 3


def posting_interval_days() -> int:
    """Posting cadence from FRAGBOT_POST_INTERVAL_DAYS (default 3).

    Validated: must be a positive integer. A bad value is a hard config
    error (raises ValueError) — it must never silently post daily or skip
    forever.
    """
    raw = os.environ.get(POSTING_INTERVAL_ENV, "").strip()
    if not raw:
        return DEFAULT_POST_INTERVAL_DAYS
    try:
        n = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"{POSTING_INTERVAL_ENV} must be a positive integer, got {raw!r}"
        ) from exc
    if n < 1:
        raise ValueError(f"{POSTING_INTERVAL_ENV} must be >= 1, got {n}")
    return n


def is_posting_day(today: Optional[date] = None,
                   interval: Optional[int] = None,
                   anchor: date = POSTING_ANCHOR) -> bool:
    """True when *today* is a posting day for the given interval.

    Pure rule: day_index = (today - anchor).days; posting day iff
    day_index % interval == 0. When *interval* is None the env-configured
    value is used (see posting_interval_days). The anchor is fixed at
    2026-01-01 so the cadence is stable across restarts and never drifts
    with the cron day-of-month.
    """
    today = today or date.today()
    if interval is None:
        interval = posting_interval_days()
    return (today - anchor).days % interval == 0


# ---------------------------------------------------------------------------
# Recipe row -> engine recipe dict
# ---------------------------------------------------------------------------
_JSON_FIELDS = ("scent_profile", "ingredients", "equipment", "instructions",
                "safety_notes", "tags")


def row_to_recipe(row: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a recipes-table row (from any store backend) into an engine
    recipe dict that schema.validate() accepts.

    Handles both JSON-string columns (Postgres/Stub) and already-parsed
    dicts/lists (Supabase REST returns parsed JSON).
    """
    recipe: Dict[str, Any] = {
        "recipe_name": row["recipe_name"],
        "full_title": row["full_title"],
        "slug": row["slug"],
        "category": row["category"],
        "difficulty": row["difficulty"],
        "yield": row["yield_text"],
        "cost_to_make": row["cost_to_make"],
        "description_long": row["description_long"],
        "price_usd": float(row["price_usd"]),
        "theme": row.get("theme"),
        "holiday": row.get("holiday"),
    }
    for key in _JSON_FIELDS:
        val = row[key]
        if isinstance(val, str):
            val = json.loads(val)
        recipe[key] = val
    assert_valid(recipe)
    return recipe


def recipe_id(row: Dict[str, Any]) -> str:
    return str(row["id"])


# ---------------------------------------------------------------------------
# Optional Resend notification (STDLIB only; only when RESEND_API_KEY is set)
# ---------------------------------------------------------------------------
def notify_resend(subject: str, text: str, log_when_missing: bool = False) -> bool:
    """Send the owner a notification via Resend. Returns True when e-mailed.

    Deliberately conservative: unless BOTH RESEND_API_KEY and ETSY_NOTIFY_TO
    are set, nothing is sent — the caller logs the listing URL instead.
    Never claims an email was sent when it wasn't.
    """
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    to = os.environ.get("ETSY_NOTIFY_TO", "").strip()
    if not api_key or not to:
        if log_when_missing:
            log.info(
                "Resend notification skipped: set RESEND_API_KEY + ETSY_NOTIFY_TO "
                "to enable (nothing was sent)."
            )
        return False
    sender = os.environ.get("ETSY_NOTIFY_FROM", "Fragrance Bot <onboarding@resend.dev>")
    body = json.dumps(
        {"from": sender, "to": [to], "subject": subject, "text": text}
    ).encode("utf-8")
    req = urllib.request.Request(RESEND_URL, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
        if resp.status == 200:
            log.info("notification email sent to %s", to)
            return True
        log.warning("Resend returned HTTP %s; email NOT sent", resp.status)
        return False
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        log.warning("Resend email failed (HTTP %s): %s — email NOT sent", exc.code, detail)
        return False
    except OSError as exc:
        log.warning("Resend email network error: %s — email NOT sent", exc)
        return False


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------
def run_daily_post(
    store,
    dry_run: bool = False,
    work_dir: Optional[Path] = None,
    client: Optional[EtsyClient] = None,
    promo: bool = False,
    interval: Optional[int] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Run one daily posting cycle. Returns a summary dict.

    Posting-cadence guard: when *today* is not a posting day (see
    is_posting_day) the cycle returns immediately with a ``skip`` summary —
    BEFORE touching the store, the filesystem or Etsy — so a workflow run on
    a non-posting day is green (exit 0) and writes nothing anywhere.

    Raises EtsyError on failure (caller decides exit code); the store is
    only mutated on full success (mark_listed) — except a best-effort
    daily_posts 'failed' record.
    """
    today = today or date.today()
    if interval is None:
        interval = posting_interval_days()
    summary: Dict[str, Any] = {
        "date": today.isoformat(),
        "dry_run": dry_run,
        "interval_days": interval,
    }

    if not is_posting_day(today, interval):
        # Not a posting day: nothing to do, and NOTHING may be touched —
        # no recipe consumed, no daily_posts row, no listing, no assets.
        msg = f"not a posting day (interval {interval}) — nothing to do"
        if dry_run:
            print(f"would skip: {msg}")
            summary["status"] = "dry_run_skip"
        else:
            log.info(msg)
            summary["status"] = "skip"
        return summary
    if dry_run:
        print(f"posting day (interval {interval}) — would post")

    row = store.get_next_draft_recipe()
    if row is None:
        if dry_run:
            # dry-run must show payloads even without a seeded database
            example = _load_example_recipe()
            from fragbot.db import StubStore
            seed_store = store if isinstance(store, StubStore) else StubStore()
            seed_store.upsert_recipe(
                example, "draft_ready",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
            row = seed_store.get_next_draft_recipe()
            if row is None:
                raise RuntimeError("could not prepare a recipe for dry run")
        else:
            msg = "no draft_ready recipe in the queue — nothing to do"
            log.info(msg)
            summary["status"] = "noop"
            return summary
    recipe = row_to_recipe(row)
    rid = recipe_id(row)
    summary["recipe_slug"] = recipe["slug"]
    log.info("posting recipe %s (id=%s)", recipe["slug"], rid)

    work = Path(work_dir or tempfile.mkdtemp(prefix="fragbot-post-"))
    images = render_recipe(recipe, str(work / "images"), brand=BRAND)
    pdf_path = generate_pdf(recipe, str(work / "pdf"), brand=BRAND)
    summary["images"] = {k: images[k] for k in IMAGE_KINDS}
    summary["pdf"] = str(pdf_path)
    log.info("rendered 5 listing images + PDF at %s", work)
    if promo:
        # Optional social-promo byproduct (flag off by default): the four
        # promo assets are NOT needed by Etsy posting, they are produced
        # alongside so social content exists for the same recipe.
        from fragbot.promo import generate_all as render_promo
        summary["promo"] = render_promo(recipe, str(work / "promo"), brand=BRAND)
        log.info("rendered 4 social promo assets at %s", work / "promo")

    if dry_run:
        # Payload builder only: no network, no real credentials required.
        from fragbot.etsy import DEFAULT_TAXONOMY_ID as FALLBACK_TAXONOMY_ID

        dummy = EtsyClient(
            keystring="dry-run", refresh_token="dry-run", shop_id="0",
            taxonomy_id=FALLBACK_TAXONOMY_ID,
        )
        payload = dummy.build_listing_form(recipe, taxonomy_id=FALLBACK_TAXONOMY_ID)
        summary["status"] = "dry_run"
        summary["payloads"] = {
            "createListingDraft": payload,
            "uploadListingImage": [
                {
                    "image": images[k],
                    "rank": rank,
                    "alt_text": image_alt(recipe, k),
                }
                for rank, k in enumerate(IMAGE_KINDS, start=1)
            ],
            "uploadListingFile": {"file": str(pdf_path), "name": pdf_path.name},
            "updateListing": {"state": "active"},
            "getListing": {"listing_id": "<from-create-response>"},
        }
        print("=" * 70)
        print("DRY RUN — Etsy was NOT called. Exact payloads that would be sent:")
        print("=" * 70)
        print(json.dumps(summary["payloads"], indent=2, ensure_ascii=False))
        # remind about env-only credentials
        print("\n(production would call Etsy with env credentials ETSY_KEYSTRING,"
              " ETSY_REFRESH_TOKEN, ETSY_SHOP_ID.)")
        return summary

    # ---------------- live path ----------------
    if client is None:
        client = EtsyClient.from_env()
    assert client is not None

    shop = client.verify_shop()
    taxonomy_id = client.resolve_taxonomy_id()
    summary["shop_id"] = client.shop_id
    summary["taxonomy_id"] = taxonomy_id

    listing = client.create_listing_draft(recipe, taxonomy_id=taxonomy_id)
    listing_id = str(listing["listing_id"])
    summary["listing_id"] = listing_id
    log.info("created draft listing %s for %s", listing_id, recipe["slug"])

    image_ids = []
    for rank, kind in enumerate(IMAGE_KINDS, start=1):
        img = client.upload_listing_image(
            listing_id, images[kind], rank=rank, alt_text=image_alt(recipe, kind)
        )
        image_ids.append(img.get("listing_image_id"))
    summary["image_ids"] = image_ids

    try:
        listing_final = client.publish_digital_listing(listing_id, str(pdf_path))
    except EtsyError:
        # Anything failing after draft creation leaves an orphaned DRAFT on
        # Etsy; the recipe stays draft_ready locally (retry re-posts). Logging
        # the listing id makes manual cleanup possible.
        log.error(
            "POSTING FAILED after creating Etsy listing %s (draft left on Etsy "
            "for manual cleanup); recipe %s stays draft_ready and will be "
            "retried on the next posting day.", listing_id, recipe["slug"],
        )
        raise

    etsy_url = listing_final.get("url") or f"https://www.etsy.com/listing/{listing_id}"
    summary["etsy_url"] = etsy_url

    # ---------------- persist success ----------------
    store.mark_listed(rid, listing_id, etsy_url)
    store.record_daily_post(today, rid, status="posted")
    summary["status"] = "posted"
    log.info("posted %s -> listing %s (%s)", recipe["slug"], listing_id, etsy_url)

    # optional email — ONLY when RESEND_API_KEY is set; otherwise log the URL
    emailed = notify_resend(
        f"Fragrance Bot posted: {recipe['full_title'][:80]}",
        (
            f"A new Fragrance Bot recipe went live on Etsy:\n\n"
            f"  {recipe['full_title']}\n"
            f"  {etsy_url}\n\n"
            f"Recipe: {recipe['recipe_name']} (${float(recipe['price_usd']):.2f})\n"
        ),
        log_when_missing=True,
    )
    summary["email_sent"] = emailed
    if not emailed:
        log.info("listing URL: %s", etsy_url)
    return summary


def _load_example_recipe() -> Dict[str, Any]:
    """Deterministic sample recipe for --dry-run with an empty store."""
    examples = REPO_ROOT / "examples"
    candidates = sorted(examples.glob("recipe-*.json"))
    if not candidates:
        raise RuntimeError("no example recipes found for --dry-run (examples/ is empty)")
    recipe = json.loads(candidates[0].read_text(encoding="utf-8"))
    assert_valid(recipe)
    return recipe


def image_alt(recipe: Dict[str, Any], kind: str) -> str:
    """Short alt text (<=500 chars per Etsy spec) for each listing image."""
    base = f"{recipe['recipe_name']} — DIY {recipe['category'].replace('_', ' ')} recipe"
    labels = {
        "hero": "digital download cover card",
        "ingredients": "ingredient list with measurements",
        "pyramid": "scent pyramid top heart base notes",
        "included": "what's included in the download",
        "lifestyle": "finished product look",
    }
    return f"{base} ({labels.get(kind, kind)}) by Fragrance Bot"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="render everything and print the exact payloads "
                         "without calling Etsy or the store")
    ap.add_argument("--store", choices=("auto", "stub"), default="auto",
                    help="auto = env-driven backend (production); stub = "
                         "in-memory store (tests / verification)")
    ap.add_argument("--log-file", default=None,
                    help="also append logs to this file (stdout is always used)")
    ap.add_argument("--work-dir", default=None,
                    help="directory for rendered images/PDF (default: temp)")
    ap.add_argument("--promo", action="store_true",
                    help="also render the 4 social promo assets (pin.jpg, "
                         "story.jpg, tiktok.txt, email.txt) into "
                         "<work-dir>/promo as a byproduct of the post")
    ap.add_argument("--date", default=None,
                    help="simulate this calendar date (YYYY-MM-DD) for the "
                         "posting-day decision and summary; default: today. "
                         "Testing hook — the real cron never passes it.")
    return ap


def main(argv: Optional[list] = None, store=None) -> int:
    args = build_parser().parse_args(argv)

    # logging: stdout always + optional file
    handlers = [logging.StreamHandler(sys.stdout)]
    if args.log_file:
        Path(args.log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )

    # posting cadence + optional simulated date (validate BEFORE any work:
    # a bad interval must fail loudly, never silently post/skip forever)
    try:
        interval = posting_interval_days()
    except ValueError as exc:
        log.error("bad posting interval: %s", exc)
        return 2
    sim_today = None
    if args.date:
        try:
            sim_today = date.fromisoformat(args.date)
        except ValueError:
            log.error("--date must be YYYY-MM-DD, got %r", args.date)
            return 2
        log.info("simulating date %s (posting-day decision only)",
                 sim_today.isoformat())

    # store selection (an injected store wins — used by the verify harness)
    if store is None:
        if args.store == "stub" or (args.dry_run and not _store_env_configured()):
            from fragbot.db import StubStore
            store = StubStore()
            if args.store == "auto" and args.dry_run:
                log.info("dry run without Supabase credentials: using in-memory StubStore")
        else:
            try:
                store = get_store()
            except (StoreNotConfiguredError, ImportError) as exc:
                log.error("could not configure the store: %s", exc)
                return 2

    try:
        run_daily_post(store, dry_run=args.dry_run, work_dir=(
            Path(args.work_dir) if args.work_dir else None),
            promo=args.promo, interval=interval, today=sim_today)
    except EtsyError as exc:
        # Owner spec: log, leave the recipe draft_ready, exit non-zero.
        log.error("daily post failed: %s", exc)
        try:
            row = store.get_next_draft_recipe()
            if row is not None:
                store.record_daily_post(date.today(), recipe_id(row), status="failed")
        except Exception:  # noqa: BLE001 - failure recording must not mask the error
            pass
        return 1
    except Exception as exc:  # noqa: BLE001 - unexpected failure = non-zero exit
        log.error("unexpected failure: %s", exc, exc_info=True)
        return 1
    return 0


def _store_env_configured() -> bool:
    return bool(
        os.environ.get("POSTGRES_URL", "").strip()
        or (
            os.environ.get("SUPABASE_URL", "").strip()
            and os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        )
    )


if __name__ == "__main__":
    sys.exit(main())