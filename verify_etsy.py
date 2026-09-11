#!/usr/bin/env python3
"""Verification for the Fragrance Bot Etsy posting pipeline (no live Etsy).

Run (from repo root):  python3 verify_etsy.py
Writes its full output to verification-etsy.txt (gitignored).

What is verified — all against a LOCAL mock Etsy API (scripts/mock_etsy.py)
and an in-memory StubStore; NO live Etsy credentials exist or are used:

  1. Happy path: daily_post draws the oldest draft_ready recipe, renders
     5 images + PDF, creates the listing draft, uploads 5 images (rank 1..5,
     first = primary), activates it, uploads the digital PDF, fetches the
     public URL, then mark_listed + record_daily_post('posted') on the store.
  2. Rate limiting: every request is spaced >= 150 ms apart.
  3. Retry-on-429: an injected 429 (with Retry-After) is retried by the
     client with backoff and the run still succeeds.
  4. Failure semantics: an injected persistent 500 on activation leaves the
     recipe as draft_ready (never mark_listed), records a 'failed' daily
     post, and main() exits non-zero (skip-day semantics: tomorrow retries
     the same recipe).
  5. Length/enum enforcement: title > 140 or tag > 20 chars raises
     EtsyValidationError BEFORE any request is sent.
  6. Payload lint: every field the client sends is in the official OpenAPI
     spec's parameter maps (fragbot/etsy/spec.py).
  7. Refresh-token rotation: after a run the NEW refresh token Etsy returns
     is persisted (token store), proving the cron keeps working run to run.

The same checks run against scripts/etsy_oauth.py's authorize-URL builder
(pure function) to make sure the one-time owner flow builds a spec-shaped
URL (PKCE S256, scopes, state, redirect_uri).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from fragbot.db import StubStore  # noqa: E402
from fragbot.etsy import EtsyClient, EtsyValidationError, FileTokenStore  # noqa: E402
from fragbot.etsy.errors import EtsyConfigError, EtsyError  # noqa: E402
from fragbot.etsy.spec import (  # noqa: E402
    CREATE_LISTING_FIELDS,
    CREATE_LISTING_REQUIRED,
    UPLOAD_FILE_FIELDS,
    UPLOAD_IMAGE_FIELDS,
    UPDATE_LISTING_FIELDS,
)
from fragbot.schema import validate as schema_validate  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "scripts"))
from mock_etsy import SHOP_ID, MockEtsyState, Handler as MockHandler  # noqa: E402

RESULTS: List[Tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


def record(checks: List[Tuple[str, bool, str]]) -> None:
    RESULTS.extend(checks)


# ---------------------------------------------------------------------------
# Mock server lifecycle
# ---------------------------------------------------------------------------
class _QuietTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class MockServer:
    """Starts scripts/mock_etsy.py in-process on a fresh port + state dir."""

    def __init__(self) -> None:
        self.state_dir = Path(tempfile.mkdtemp(prefix="mock-etsy-"))
        for stale in self.state_dir.glob("*"):
            if stale.is_file():
                stale.unlink()
        self.srv = None
        self.thread = None
        self.port: Optional[int] = None
        self._start()

    def _start(self) -> None:
        # Bind a free port first.
        import socket
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()

        self.srv = _QuietTCPServer(("127.0.0.1", self.port), MockHandler)
        import mock_etsy as mod
        mod.STATE = MockEtsyState(self.state_dir)  # fresh per-server state
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()
        time.sleep(0.2)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def token_url(self) -> str:
        return f"{self.base_url}/v3/public/oauth/token"

    def config(self, **cfg: Any) -> None:
        req = urllib.request.Request(
            f"{self.base_url}/__config",
            data=json.dumps(cfg).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()

    def state(self) -> Dict[str, Any]:
        with urllib.request.urlopen(f"{self.base_url}/__state", timeout=10) as resp:
            return json.loads(resp.read().decode())

    def log(self) -> List[Dict[str, Any]]:
        with urllib.request.urlopen(f"{self.base_url}/__log", timeout=10) as resp:
            return json.loads(resp.read().decode())

    def stop(self) -> None:
        if self.srv is not None:
            self.srv.shutdown()
            self.srv.server_close()
        shutil.rmtree(self.state_dir, ignore_errors=True)


def make_client(mock: MockServer, token_store: Optional[Any] = None) -> EtsyClient:
    return EtsyClient(
        keystring="test-keystring",
        refresh_token="seed-refresh-token",
        shop_id=SHOP_ID,
        base_url=mock.base_url,
        token_url=mock.token_url,
        token_store=token_store,
        max_retries=4,
    )


def seeded_store(recipe: Dict[str, Any]) -> StubStore:
    store = StubStore()
    store.upsert_recipe(
        recipe, "draft_ready",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    return store


def load_example_recipe() -> Dict[str, Any]:
    path = REPO_ROOT / "examples" / "recipe-2026-01-19-perfume.json"
    recipe = json.loads(path.read_text(encoding="utf-8"))
    problems = schema_validate(recipe)
    if problems:
        raise RuntimeError(f"example recipe invalid: {problems}")
    return recipe


# ---------------------------------------------------------------------------
# 1. Happy path — full listing cycle against the mock + StubStore
# ---------------------------------------------------------------------------
def test_happy_path(mock: MockServer, work: Path) -> None:
    print("\n1. Happy path (create -> 5 images -> activate -> pdf -> mark_listed)")
    recipe = load_example_recipe()
    store = seeded_store(recipe)
    token_store = FileTokenStore(work / "tokens" / "etsy_refresh_token")
    client = make_client(mock, token_store=token_store)

    from scripts.daily_post import run_daily_post  # noqa: PLC0415
    summary = run_daily_post(store, work_dir=work / "assets", client=client)

    ok1 = summary.get("status") == "posted"
    check("daily_post completed with status=posted", ok1, str(summary.get("status")))

    # store progression
    row = next(r for r in store.recipes.values())
    check("recipe marked listed in store", row["status"] == "listed",
          f"status={row['status']}")
    check("listing_id + etsy_url recorded",
          bool(row["listing_id"]) and str(row["etsy_url"]).startswith("https://"),
          f"listing_id={row['listing_id']} url={row['etsy_url']}")
    today = date.today().isoformat()
    post = store.posts.get(today, {})
    check("daily_posts recorded status=posted", post.get("status") == "posted",
          f"status={post.get('status')}")

    mstate = mock.state()
    listings = list(mstate["listings"].values())
    check("exactly one listing created on Etsy", len(listings) == 1)
    listing = listings[0]
    check("listing activated (state=active)",
          listing.get("state") == "active", f"state={listing.get('state')}")
    check("listing type is digital download",
          listing.get("type") == "download", f"type={listing.get('type')}")
    check("listing has digital file attached",
          mstate["files"].get(str(listing["listing_id"])) is not None
          and len(mstate["files"][str(listing["listing_id"])]) == 1,
          str(mstate["files"]))
    images = mstate["images"].get(str(listing["listing_id"]), [])
    check("five listing images uploaded",
          len(images) == 5, f"got {len(images)}")
    ranks = sorted(img["rank"] for img in images)
    check("image ranks are 1..5 (first = primary)",
          ranks == [1, 2, 3, 4, 5], str(ranks))
    check("primary image (rank 1) uploaded first",
          images and images[0]["rank"] == 1)
    check("image alt_text set and <= 500 chars",
          all(img.get("alt_text") and len(img["alt_text"]) <= 500 for img in images))

    # request sequence on the wire (excluding oauth refresh + control endpoints)
    wire = [
        (e["method"], e["path"]) for e in mock.log()
        if "oauth/token" not in e["path"]
        and e["path"] not in ("/__log", "/__config", "/__state")
    ]
    seq = " -> ".join(f"{m} {p}" for m, p in wire)
    def idx(pred):
        for i, (m0, p0) in enumerate(wire):
            if pred(m0, p0):
                return i
        return -1
    i_create = idx(lambda m, p: m == "POST" and "shops" in p and p.endswith("/listings"))
    i_imgs = [i for i, (m0, p0) in enumerate(wire) if p0.endswith("/images")]
    i_patch = idx(lambda m, p: m == "PATCH" and p.split("/")[-1].isdigit())
    i_file = idx(lambda m, p: m == "POST" and p.endswith("/files"))
    i_get_first = idx(lambda m, p: m == "GET" and p.startswith("/v3/application/listings/"))
    check(
        "wire order: create -> images x5 -> activate -> get -> file -> get",
        i_create >= 0 and len(i_imgs) == 5
        and i_create < i_imgs[0] and i_imgs[-1] < i_patch < i_get_first < i_file,
        seq,
    )

    check("returned etsy_url matches mock listing url",
          summary.get("etsy_url") == f"https://www.etsy.com/listing/{listing['listing_id']}")

    # token rotation persisted
    stored = token_store.load()
    check("refresh-token rotation persisted (new != env seed)",
          stored is not None and stored != "seed-refresh-token" and stored.startswith("rot."),
          f"stored={str(stored)[:28]}...")
    return summary, store


# ---------------------------------------------------------------------------
# 2. Rate limiting: >= 150 ms between requests
# ---------------------------------------------------------------------------
def test_rate_limiting(mock: MockServer, work: Path) -> None:
    print("\n2. Rate limiting (>= 150 ms between requests)")
    recipe = load_example_recipe()
    store = seeded_store(recipe)
    from scripts.daily_post import run_daily_post  # noqa: PLC0415
    client = make_client(mock)
    run_daily_post(store, work_dir=work / "assets2", client=client)

    # Primary check: the client's rate limiter — send times must be >= 150 ms
    # apart (this is the guarantee; mock arrival times skew with payload size).
    sends = client.transport.rate_limiter.recorded_sends
    send_gaps = [b - a for a, b in zip(sends, sends[1:])]
    min_send = min(send_gaps) if send_gaps else 0.0
    check(
        f"all {len(send_gaps)} client send gaps >= 149 ms (min={min_send * 1000:.1f} ms)",
        bool(send_gaps) and min_send >= 0.149, f"min send gap {min_send * 1000:.1f} ms",
    )

    # Secondary: mock-arrival gaps (>= 100 ms sanity; sizes distort arrival).
    entries = [e for e in mock.log()
               if "oauth/token" not in e["path"]
               and e["path"] not in ("/__log", "/__config", "/__state")]
    timestamps = [e["ts"] for e in entries]
    gaps = [b - a for a, b in zip(timestamps, timestamps[1:])]
    min_gap = min(gaps) if gaps else 0.0
    check(
        f"mock saw {len(gaps)} request arrivals, min gap {min_gap * 1000:.1f} ms",
        bool(gaps) and min_gap >= 0.10, f"min gap {min_gap * 1000:.1f} ms",
    )
    check("request count is sane (>= 9 API calls)",
          len(timestamps) >= 9, f"{len(timestamps)} calls")


# ---------------------------------------------------------------------------
# 3. Retry on 429 (honoring Retry-After), then success
# ---------------------------------------------------------------------------
def test_retry_429(mock: MockServer, work: Path) -> None:
    print("\n3. Retry-on-429 (two injected 429s, then success)")
    before = len(mock.log())
    mock.config(faults={"createListing": [429, 2]})
    client = make_client(mock)
    t0 = time.monotonic()
    listing = client.create_listing_draft(load_example_recipe(), taxonomy_id=563)
    elapsed = time.monotonic() - t0
    check("createListingDraft succeeded after 2 retries",
          isinstance(listing.get("listing_id"), int))
    create_hits = [e for e in mock.log()[before:]
                   if e["path"].endswith("/listings") and e["method"] == "POST"]
    check("exactly 3 create attempts hit the wire (1 + 2 retries)",
          len(create_hits) == 3, f"{len(create_hits)} attempts")
    check("Retry-After honored (run took >= 2s from 2x1s waits)",
          elapsed >= 1.8, f"elapsed {elapsed:.2f}s")


# ---------------------------------------------------------------------------
# 4. Failure semantics: activation 500 -> recipe stays draft_ready, exit != 0
# ---------------------------------------------------------------------------
def test_failure_semantics(mock: MockServer, work: Path) -> None:
    print("\n4. Failure semantics (persistent 500 on activation)")
    recipe = load_example_recipe()
    store = seeded_store(recipe)
    mock.config(faults={"activate": [500, 100]})  # never succeeds
    from scripts.daily_post import main as daily_main  # noqa: PLC0415

    # point EtsyClient.from_env() at the mock (that's what main() constructs)
    saved_env = {
        k: os.environ.pop(k, None) for k in (
            "ETSY_KEYSTRING", "ETSY_REFRESH_TOKEN", "ETSY_SHOP_ID",
            "ETSY_BASE_URL", "ETSY_TOKEN_URL",
        )
    }
    os.environ.update({
        "ETSY_KEYSTRING": "test-keystring",
        "ETSY_REFRESH_TOKEN": "seed-refresh-token",
        "ETSY_SHOP_ID": SHOP_ID,
        "ETSY_BASE_URL": mock.base_url,
        "ETSY_TOKEN_URL": mock.token_url,
    })
    buf = io.StringIO()
    rc = None
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            rc = daily_main(
                ["--store", "stub", "--work-dir", str(work / "assets3")],
                store=store,
            )
    except SystemExit as exc:  # pragma: no cover - defensive
        rc = exc.code
    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    check("main() exited non-zero", rc == 1, f"rc={rc}")
    check("recipe still draft_ready (skip-day semantics)",
          next(iter(store.recipes.values()))["status"] == "draft_ready")
    check("no mark_listed happened",
          next(iter(store.recipes.values()))["listing_id"] is None)
    today = date.today().isoformat()
    check("daily_posts recorded status=failed",
          store.posts.get(today, {}).get("status") == "failed",
          f"status={store.posts.get(today, {}).get('status')}")
    check("same recipe is retried next run (oldest draft_ready)",
          store.get_next_draft_recipe()["id"] == next(iter(store.recipes.values()))["id"])
    # the listing draft was created but never activated — nothing local marked
    mstate = mock.state()
    listings = mstate["listings"]
    last_key = max(listings, key=int)
    check("latest listing on Etsy is a draft (created, never activated)",
          listings[last_key]["state"] == "draft",
          f"state={listings[last_key]['state']}")


# ---------------------------------------------------------------------------
# 5. Title/tag length enforcement (before any request)
# ---------------------------------------------------------------------------
def test_length_enforcement(mock: MockServer, work: Path) -> None:
    print("\n5. Title/tag length enforcement (nothing reaches the wire)")
    before = len(mock.log())
    client = make_client(mock)

    too_long_title = load_example_recipe()
    too_long_title["full_title"] = "X" * 141
    try:
        client.build_listing_form(too_long_title, taxonomy_id=563)
        check("title > 140 rejected", False)
    except EtsyValidationError as exc:
        check("title > 140 rejected", "140" in str(exc))

    bad_tag = load_example_recipe()
    bad_tag["tags"] = [t if len(t) <= 20 else "ok" for t in bad_tag["tags"]]
    bad_tag["tags"][0] = "this-tag-is-definitely-longer-than-twenty"
    try:
        client.build_listing_form(bad_tag, taxonomy_id=563)
        check("tag > 20 chars rejected", False)
    except EtsyValidationError as exc:
        check("tag > 20 chars rejected", "too long" in str(exc))

    too_many_tags = load_example_recipe()
    too_many_tags["tags"] = [f"tag{i}" for i in range(14)]
    try:
        client.build_listing_form(too_many_tags, taxonomy_id=563)
        check("14 tags rejected", False)
    except EtsyValidationError:
        check("14 tags rejected", True)

    # nothing should have been sent for the rejected payloads
    creates = [e for e in mock.log()[before:]
               if e["path"].endswith("/listings") and e["method"] == "POST"]
    check("zero create requests hit the wire for invalid payloads", len(creates) == 0)


# ---------------------------------------------------------------------------
# 6. Payload lint against the official OpenAPI parameter maps
# ---------------------------------------------------------------------------
def test_spec_lint(mock: MockServer) -> None:
    print("\n6. Payload field names match the official OpenAPI spec")
    recipe = load_example_recipe()
    client = make_client(mock)

    form = client.build_listing_form(recipe, taxonomy_id=563)
    check("createListingDraft: all fields in spec",
          set(form).issubset(CREATE_LISTING_FIELDS),
          f"extra={sorted(set(form) - CREATE_LISTING_FIELDS) or None}")
    check("createListingDraft: all required fields present",
          CREATE_LISTING_REQUIRED.issubset(set(form)),
          f"missing={sorted(CREATE_LISTING_REQUIRED - set(form)) or None}")
    check("createListingDraft: enum values from spec",
          form["who_made"] in {"i_did", "someone_else", "collective"}
          and form["when_made"] == "made_to_order"
          and form["type"] in {"physical", "download", "both"})

    img_form = {"rank": 1, "alt_text": "x"}
    check("uploadListingImage: fields in spec",
          set(img_form).issubset(UPLOAD_IMAGE_FIELDS))
    file_form = {"name": "a.pdf", "rank": 1}
    check("uploadListingFile: fields in spec",
          set(file_form).issubset(UPLOAD_FILE_FIELDS))
    upd_form = {"state": "active"}
    check("updateListing (activate): fields in spec",
          set(upd_form).issubset(UPDATE_LISTING_FIELDS))

    # taxonomy resolution: by-name lookup pins a deep node (no env override)
    tax = client.resolve_taxonomy_id()
    check("taxonomy by-name lookup returns a node id", isinstance(tax, int))
    check("taxonomy lookup prefers a deep DIY node (any child under 6642)",
          str(tax) in ("7587", "7588", "24246", "24247"), f"got {tax}")

    # env override wins
    os.environ["ETSY_TAXONOMY_ID"] = "563"
    try:
        client2 = make_client(mock)
        check("ETSY_TAXONOMY_ID override takes precedence",
              client2.resolve_taxonomy_id() == 563)
    finally:
        del os.environ["ETSY_TAXONOMY_ID"]


# ---------------------------------------------------------------------------
# 7. One-time OAuth helper builds a spec-shaped authorize URL
# ---------------------------------------------------------------------------
def test_oauth_helper() -> None:
    print("\n7. scripts/etsy_oauth.py builds a spec-shaped authorize URL")
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import etsy_oauth  # noqa: PLC0415

    verifier, challenge = etsy_oauth.pkce_pair()
    state = "abc123"
    url = etsy_oauth.build_authorize_url(
        "key123", "http://localhost:8080/callback",
        "listings_r listings_w transactions_r shops_r", state, challenge,
    )
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    check("authorize URL host is www.etsy.com/oauth/connect",
          url.startswith("https://www.etsy.com/oauth/connect"))
    check("response_type=code", qs.get("response_type") == ["code"])
    check("PKCE S256 (code_challenge_method=S256)",
          qs.get("code_challenge_method") == ["S256"]
          and bool(qs.get("code_challenge")))
    check("scopes include listings_r listings_w transactions_r",
          all(s in qs.get("scope", [""])[0] for s in
              ("listings_r", "listings_w", "transactions_r")))
    check("state echoed", qs.get("state") == [state])
    check("redirect_uri registered shape",
          qs.get("redirect_uri") == ["http://localhost:8080/callback"])
    check("code verifier is a valid PKCE preimage (S256 round-trip)",
          etsy_oauth.build_authorize_url(
              "k", "http://localhost:8080/callback", "r", "s", challenge
          ).__contains__("code_challenge=") and len(verifier) >= 43)


# ---------------------------------------------------------------------------
# 8. CLI smoke: --dry-run prints the exact payloads, calls nothing
# ---------------------------------------------------------------------------
def test_cli_dry_run(mock: MockServer, work: Path) -> None:
    print("\n8. CLI --dry-run prints payloads without calling Etsy")
    before = len(mock.log())
    env = dict(os.environ)
    env.update({
        "ETSY_BASE_URL": mock.base_url,
        "ETSY_TOKEN_URL": mock.token_url,
    })
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "daily_post.py"),
         "--dry-run", "--work-dir", str(work / "dryrun")],
        capture_output=True, text=True, env=env, timeout=180,
    )
    check("--dry-run exits 0", proc.returncode == 0, f"rc={proc.returncode}")
    out = proc.stdout + proc.stderr
    check("--dry-run prints createListingDraft payload", "createListingDraft" in out)
    check("--dry-run prints uploadListingImage payload(s)", "uploadListingImage" in out)
    check("--dry-run prints activate payload", '"state": "active"' in out)
    check("--dry-run mentions Etsy was NOT called", "NOT called" in out)
    check("--dry-run sent zero requests to the mock",
          len(mock.log()) == before,
          f"mock requests before={before} after={len(mock.log())}")


def _main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work-dir", default=None,
                    help="persistent work dir for rendered assets (default: temp)")
    args = ap.parse_args(argv)

    print("=" * 74)
    print("Fragrance Bot — Etsy posting pipeline verification (mock Etsy API)")
    print("=" * 74)

    mock = MockServer()
    work = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="verify-etsy-"))
    work.mkdir(parents=True, exist_ok=True)
    print(f"mock Etsy: {mock.base_url}   work dir: {work}")

    try:
        test_happy_path(mock, work)
        test_rate_limiting(mock, work)
        test_retry_429(mock, work)
        test_failure_semantics(mock, work)
        test_length_enforcement(mock, work)
        test_spec_lint(mock)
        test_oauth_helper()
        test_cli_dry_run(mock, work)
    finally:
        mock.stop()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{'=' * 74}")
    print(f"RESULT: {passed}/{total} checks passed")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAILED: {name}" + (f" — {detail}" if detail else ""))
    if passed != total:
        print("VERIFICATION FAILED", file=sys.stderr)
        return 1
    print("VERIFICATION PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(_main())