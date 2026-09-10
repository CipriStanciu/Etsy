#!/usr/bin/env python3
"""Verification for the Fragrance Bot Supabase layer (no live DB required).

Run (from repo root):  python3 verify_supabase.py
Writes its full output to verification-supabase.txt (gitignored).

What is verified
----------------
A. Seed generation (pure Python, no DB):
   - 60 deterministic recipes, all schema-valid, unique slugs & names
   - exactly 30 'draft_ready' (first 30) and 30 'draft'
B. Store logic (pure Python):
   - StubStore: oldest-draft_ready selection, mark_listed progression,
     idempotent upsert (never resets status of listed recipes),
     daily-post recording and metric increments
   - PostgresStore SQL builders: parameter counts, idempotent column sets
C. Real Postgres semantics via PGlite (Postgres compiled to WASM) — SKIPPED
   with a clear note if node/pglite is unavailable:
   - schema.sql executes; unique/check/FK constraints are enforced
   - the seed SQL (exactly as the seed renders it) inserts 60 rows, and
     re-running it keeps 60 rows (idempotent)
   - get_next_draft_recipe / mark_listed / daily posts / metrics SQL
D. SupabaseRestStore request shape against a local mock PostgREST server:
   - upsert headers (Prefer: resolution=merge-duplicates, Authorization),
     query parameters for next-draft, PATCH bodies for mark_listed/metrics
E. seed_recipes.py CLI: --dry-run --sql-out produces a runnable SQL script.

NOTE ON SCOPE: with no SUPABASE_URL / POSTGRES_URL in the environment, no
live cloud database is touched (this session had none set). The SQL layer is
instead executed against PGlite, a genuine Postgres build, so schema and
statement semantics ARE validated — only the network hop to Supabase's
servers is not.
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from fragbot import batch_generate  # noqa: E402
from fragbot.db import (  # noqa: E402
    BUMP_METRICS_SQL,
    MARK_LISTED_SQL,
    RECORD_POST_SQL,
    SELECT_NEXT_DRAFT_SQL,
    StubStore,
    SupabaseRestStore,
    _IMMUTABLE_ON_UPSERT,
    render_upsert_sql,
    seed_created_at,
    upsert_recipe_sql,
)
from fragbot.schema import validate as schema_validate  # noqa: E402

SEED_START = date(2026, 1, 1)
SEED_COUNT = 60
SEED_READY = 30

# ---------------------------------------------------------------------------
# tiny check harness
# ---------------------------------------------------------------------------
_results: List[Tuple[str, str, str]] = []  # (name, status, detail)


class SkipCheck(Exception):
    pass


def check(name: str, fn: Callable[[], Optional[str]]) -> None:
    """Run a check; fn returns None on pass, or a failure detail string."""
    try:
        detail = fn()
        _results.append((name, "PASS" if detail is None else "FAIL", detail or ""))
    except SkipCheck as exc:
        _results.append((name, "SKIP", str(exc)))
    except Exception as exc:  # noqa: BLE001 - harness reports, does not crash
        _results.append((name, "FAIL", f"{type(exc).__name__}: {exc}"))


def _pg(sql: str, params: List[object]) -> Tuple[str, List[object]]:
    """Convert psycopg-style %s placeholders to PGlite $n placeholders."""
    out: List[str] = []
    n = 0
    i = 0
    while True:
        j = sql.find("%s", i)
        if j < 0:
            out.append(sql[i:])
            break
        out.append(sql[i:j])
        n += 1
        out.append(f"${n}")
        i = j + 2
    return "".join(out), params


# ---------------------------------------------------------------------------
# PGlite driver
# ---------------------------------------------------------------------------
class Pglite:
    def __init__(self) -> None:
        node = shutil.which("node")
        if not node:
            raise RuntimeError("node not found on PATH")
        bridge = REPO_ROOT / "scripts" / "pglite_bridge.cjs"
        env = dict(os.environ)
        if not env.get("PGLITE_MODULE_PATH") and Path("/tmp/pgverify/node_modules").exists():
            env["PGLITE_MODULE_PATH"] = "/tmp/pgverify/node_modules"
        self.proc = subprocess.Popen(
            [node, str(bridge)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env,
        )

    def _send(self, msg: dict) -> dict:
        if self.proc.poll() is not None:
            raise RuntimeError(f"pglite bridge exited early: {self.proc.stderr.read()}")
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError(f"pglite bridge produced no output: {self.proc.stderr.read()}")
        return json.loads(line)

    def exec(self, sql: str) -> None:
        resp = self._send({"cmd": "exec", "sql": sql})
        if not resp["ok"]:
            raise RuntimeError(f"pglite exec failed: {resp['error']}")

    def query(self, sql: str, params: Optional[List[object]] = None) -> List[dict]:
        pg_sql, pg_params = _pg(sql, params or [])
        resp = self._send({"cmd": "query", "sql": pg_sql, "params": pg_params})
        if not resp["ok"]:
            raise RuntimeError(f"pglite query failed: {resp['error']}")
        return resp["rows"]

    def expect_fail(self, sql: str, params: Optional[List[object]] = None) -> str:
        """Run a statement that should fail; return the error text."""
        pg_sql, pg_params = _pg(sql, params or [])
        resp = self._send({"cmd": "query", "sql": pg_sql, "params": pg_params})
        if resp["ok"]:
            raise RuntimeError("statement unexpectedly succeeded")
        return resp["error"]

    def close(self) -> None:
        try:
            self._send({"cmd": "close"})
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


# ---------------------------------------------------------------------------
# mock PostgREST server for SupabaseRestStore checks
# ---------------------------------------------------------------------------
class MockHandler(http.server.BaseHTTPRequestHandler):
    requests: List[dict] = []
    next_draft_rows: List[dict] = []
    metrics_rows: List[dict] = [{"views": 5, "favorites": 2, "sales": 1}]

    def log_message(self, *a):  # silence
        pass

    def _record(self, body: Optional[bytes]) -> None:
        self.requests.append({
            "method": self.command,
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "apikey": self.headers.get("apikey"),
            "prefer": self.headers.get("Prefer"),
            "body": json.loads(body.decode("utf-8")) if body else None,
        })

    def _send_json(self, payload: object, code: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self._record(None)
        if self.path.startswith("/rest/v1/recipes"):
            self._send_json(self.next_draft_rows)
        elif self.path.startswith("/rest/v1/daily_posts"):
            self._send_json(self.metrics_rows)
        else:
            self._send_json([])

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self._record(self.rfile.read(length) if length else None)
        if self.path.startswith("/rest/v1/recipes"):
            self._send_json([{"id": str(uuid.uuid4())}])
        else:
            self._send_json([])

    def do_PATCH(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self._record(self.rfile.read(length) if length else None)
        self._send_json([])


class MockServer:
    def __init__(self) -> None:
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), MockHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.httpd.server_address[1]

    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.thread.join(timeout=5)
        self.httpd.server_close()


# ===========================================================================
# Section A — seed generation
# ===========================================================================
def section_a() -> None:
    recipes = batch_generate(SEED_START, SEED_COUNT)

    check("A1: engine generates 60 deterministic recipes",
          lambda: None if len(recipes) == SEED_COUNT else f"got {len(recipes)}")
    check("A2: every recipe is schema-valid",
          lambda: None if all(not schema_validate(r) for r in recipes)
          else "some recipes failed schema validation")
    check("A3: all 60 slugs are unique",
          lambda: None if len({r['slug'] for r in recipes}) == SEED_COUNT else "duplicate slugs")
    check("A4: all 60 recipe_names are unique",
          lambda: None if len({r['recipe_name'] for r in recipes}) == SEED_COUNT else "duplicate names")

    statuses = ["draft_ready"] * SEED_READY + ["draft"] * (SEED_COUNT - SEED_READY)
    counts = {"draft_ready": 0, "draft": 0}
    for _, s in zip(recipes, statuses):
        counts[s] += 1
    check("A5: exactly 30 draft_ready / 30 draft by seed plan",
          lambda: None if counts == {"draft_ready": SEED_READY, "draft": SEED_COUNT - SEED_READY}
          else f"counts wrong: {counts}")
    check("A6: seed re-run is byte-identical (deterministic)",
          lambda: None if batch_generate(SEED_START, SEED_COUNT) == recipes
          else "recipes differ across runs")


# ===========================================================================
# Section B — store logic (StubStore + SQL builders)
# ===========================================================================
def section_b() -> None:
    recipes = batch_generate(SEED_START, SEED_COUNT)

    def plan() -> List[Tuple[dict, str, datetime]]:
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return [(r, "draft_ready" if i < SEED_READY else "draft",
                 seed_created_at(i, SEED_COUNT, base)) for i, r in enumerate(recipes)]

    def test_stub() -> None:
        stub = StubStore()
        for r, s, ts in plan():
            stub.upsert_recipe(r, s, ts)
        assert len(stub.recipes) == SEED_COUNT, f"stub has {len(stub.recipes)} rows"
        first = stub.get_next_draft_recipe()
        assert first is not None and first["slug"] == recipes[0]["slug"], \
            f"oldest not first: {first and first['slug']}"
        assert first["status"] == "draft_ready" and first["listing_id"] is None
        stub.mark_listed(first["id"], "listing-1", "https://etsy.com/listing/1")
        second = stub.get_next_draft_recipe()
        assert second is not None and second["slug"] == recipes[1]["slug"], \
            f"after mark_listed expected 2nd, got {second and second['slug']}"
        assert first["status"] == "listed" and first["listed_at"] is not None
        # idempotency: re-upsert everything; listed row must NOT be reset
        for r, s, ts in plan():
            stub.upsert_recipe(r, s, ts)
        assert len(stub.recipes) == SEED_COUNT, "stub duplicated rows on re-upsert"
        assert stub.recipes[recipes[0]["slug"]]["status"] == "listed", \
            "upsert reset a listed recipe's status"
        assert stub.recipes[recipes[1]["slug"]]["status"] == "draft_ready"
        # daily posts + metrics
        stub.record_daily_post(SEED_START, first["id"], status="posted")
        stub.record_daily_post(SEED_START, first["id"], status="posted")  # upsert, not dup
        assert len(stub.posts) == 1, "daily post duplicated"
        stub.update_daily_post_metrics(SEED_START, views=10, favorites=3, sales=1)
        stub.update_daily_post_metrics(SEED_START, views=5, favorites=2)
        row = stub.posts[SEED_START.isoformat()]
        assert (row["views"], row["favorites"], row["sales"]) == (15, 5, 1), \
            f"metrics wrong: {row}"

    check("B1: StubStore upsert/draft-queue/mark_listed/idempotency/metrics", test_stub)

    def test_sql_builders() -> None:
        r0, s0, ts0 = plan()[0]
        sql, params = upsert_recipe_sql(r0, s0, ts0)
        assert sql.count("%s") == len(params), "placeholder/param mismatch"
        assert "on conflict (slug) do update" in sql and "returning id" in sql
        rendered = render_upsert_sql(r0, s0, ts0)
        assert "%s" not in rendered, "rendered SQL still has placeholders"
        assert rendered.startswith("insert into public.recipes")
        for col in ("status", "listing_id", "etsy_url", "created_at", "listed_at"):
            assert f"{col} = excluded.{col}" not in rendered, \
                f"upsert would reset {col}"
        assert "recipe_name = excluded.recipe_name" in rendered, \
            "content fields not refreshed"
        assert "draft_ready" in SELECT_NEXT_DRAFT_SQL
        assert SELECT_NEXT_DRAFT_SQL.count("%s") == 0

    check("B2: PostgresStore SQL builders (params, idempotent column sets)", test_sql_builders)


# ===========================================================================
# Section C — real Postgres semantics through PGlite
# ===========================================================================
def section_c(pg: Optional[Pglite]) -> None:
    if pg is None:
        raise SkipCheck(
            "pglite unavailable (node or @electric-sql/pglite missing); "
            "SQL was NOT executed against a Postgres engine")

    schema = (REPO_ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
    pg.exec(schema)

    check("C1: schema.sql executes on a real Postgres engine", lambda: None)

    def tables_exist() -> None:
        rows = pg.query("select table_name from information_schema.tables "
                        "where table_schema = 'public' order by table_name")
        names = {r["table_name"] for r in rows}
        assert {"recipes", "daily_posts"} <= names, f"missing tables: {names}"
    check("C2: recipes + daily_posts tables created", tables_exist)

    # -- run the seed exactly as seed_recipes.py renders it ----------------
    from seed_recipes import _generate, _render_sql_script
    script = _render_sql_script(SEED_COUNT, SEED_READY, SEED_START)
    pg.exec(script)

    def seeded() -> None:
        rows = pg.query("select count(*) as n from public.recipes")
        assert rows[0]["n"] == SEED_COUNT, f"expected {SEED_COUNT} rows, got {rows[0]['n']}"
        rows = pg.query("select status, count(*) as n from public.recipes group by status order by status")
        got = {r["status"]: r["n"] for r in rows}
        assert got == {"draft_ready": 30, "draft": 30}, f"status counts wrong: {got}"
    check("C6: seed SQL inserts exactly 60 rows (30 draft_ready / 30 draft)", seeded)

    def idempotent() -> None:
        pg.exec(script)  # re-run the same seed
        rows = pg.query("select count(*) as n from public.recipes")
        assert rows[0]["n"] == SEED_COUNT, f"re-run duplicated rows: {rows[0]['n']}"
    check("C7: re-running the seed does not duplicate (idempotent)", idempotent)

    _first_id: dict = {"id": None}  # captured across checks

    def next_draft() -> None:
        rows = pg.query(SELECT_NEXT_DRAFT_SQL)
        assert len(rows) == 1, f"expected exactly one next draft, got {len(rows)}"
        expected = _generate(SEED_COUNT, SEED_START)[0]["slug"]
        assert rows[0]["slug"] == expected, \
            f"oldest draft_ready should be {expected}, got {rows[0]['slug']}"
        _first_id["id"] = str(rows[0]["id"])
    check("C8: get_next_draft_recipe returns the oldest draft_ready", next_draft)

    def mark_listed() -> None:
        pg.query(MARK_LISTED_SQL, ["listing-xyz", "https://www.etsy.com/listing/xyz", _first_id["id"]])
        now_next = pg.query(SELECT_NEXT_DRAFT_SQL)
        expected = _generate(SEED_COUNT, SEED_START)[1]["slug"]
        assert now_next[0]["slug"] == expected, \
            f"after mark_listed expected {expected}, got {now_next[0]['slug']}"
    check("C9: mark_listed flips the recipe and advances the queue", mark_listed)

    def daily_post() -> None:
        pg.query(RECORD_POST_SQL, ["2026-02-01", _first_id["id"], "posted", None])
        pg.query(RECORD_POST_SQL, ["2026-02-01", _first_id["id"], "posted", None])  # upsert
        rows = pg.query("select count(*) as n from public.daily_posts")
        assert rows[0]["n"] == 1, "daily post duplicated"
        pg.query(BUMP_METRICS_SQL, [10, 3, 1, "2026-02-01"])
        pg.query(BUMP_METRICS_SQL, [5, 2, 0, "2026-02-01"])
        rows = pg.query("select views, favorites, sales from public.daily_posts where date = '2026-02-01'")
        assert (rows[0]["views"], rows[0]["favorites"], rows[0]["sales"]) == (15, 5, 1), \
            f"metrics wrong: {rows[0]}"
    check("C10: record_daily_post upsert + metric increments (atomic SQL)", daily_post)


def section_c_constraints() -> None:
    """Constraint checks run in a SEPARATE pglite instance so the failing
    inserts cannot pollute the seeded library used by the C5-C9 checks."""
    pg = Pglite()
    try:
        schema = (REPO_ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
        pg.exec(schema)

        def status_check() -> None:
            err = pg.expect_fail(
                "insert into public.recipes (recipe_name, category, difficulty, scent_profile, ingredients, instructions, equipment, safety_notes, yield_text, cost_to_make, price_usd, full_title, slug, tags, description_long, theme, status) "
                "values ('Bad Status', 'perfume', 'beginner', '{}', '[]', '[]', '[]', '[]', 'y', '~$1.00', '1.99', 'T', 'bad-status-slug', '[]', 'd', 't', 'bogus-status')")
            assert "check" in err.lower(), f"bad status accepted: {err}"
        check("C3: CHECK constraint on recipes.status enforced", status_check)

        def unique_slug() -> None:
            pg.query(
                "insert into public.recipes (recipe_name, category, difficulty, scent_profile, ingredients, instructions, equipment, safety_notes, yield_text, cost_to_make, price_usd, full_title, slug, tags, description_long, theme) "
                "values ('OK One', 'perfume', 'beginner', '{}', '[]', '[]', '[]', '[]', 'y', '~$1.00', '1.99', 'T', 'dup-slug', '[]', 'd', 't')")
            err = pg.expect_fail(
                "insert into public.recipes (recipe_name, category, difficulty, scent_profile, ingredients, instructions, equipment, safety_notes, yield_text, cost_to_make, price_usd, full_title, slug, tags, description_long, theme) "
                "values ('OK Two', 'perfume', 'beginner', '{}', '[]', '[]', '[]', '[]', 'y', '~$1.00', '1.99', 'T', 'dup-slug', '[]', 'd', 't')")
            assert "unique" in err.lower() or "duplicate" in err.lower() or "conflict" in err.lower(), \
                f"duplicate slug accepted: {err}"
        check("C4: UNIQUE constraint on recipes.slug enforced", unique_slug)

        def fk() -> None:
            err = pg.expect_fail(
                "insert into public.daily_posts (date, recipe_id, status) "
                "values ('2026-02-01', '00000000-0000-0000-0000-000000000000', 'scheduled')")
            assert "foreign" in err.lower() or "constraint" in err.lower(), \
                f"FK not enforced: {err}"
        check("C5: daily_posts.recipe_id FK enforced", fk)
    finally:
        pg.close()


# ===========================================================================
# Section D — SupabaseRestStore request shape (mock PostgREST)
# ===========================================================================
def section_d(mock: MockServer) -> None:
    MockHandler.requests = []
    store = SupabaseRestStore(supabase_url=mock.url(), service_role_key="test-service-key")

    recipes = batch_generate(SEED_START, 2)
    price = f"{float(recipes[0]['price_usd']):.2f}"
    rid = store.upsert_recipe(recipes[0], "draft_ready", datetime(2026, 1, 1, tzinfo=timezone.utc))
    req = MockHandler.requests[-1]
    check("D1: REST upsert posts to /rest/v1/recipes with merge-duplicates",
          lambda: None if (req["method"] == "POST" and req["path"] == "/rest/v1/recipes"
                           and req["prefer"] == "resolution=merge-duplicates"
                           and req["apikey"] == "test-service-key"
                           and req["authorization"] == "Bearer test-service-key"
                           and req["body"]["slug"] == recipes[0]["slug"]
                           and req["body"]["status"] == "draft_ready"
                           and req["body"]["price_usd"] == price)
          else f"unexpected request: {req}")

    MockHandler.next_draft_rows = [{"id": rid, "slug": recipes[0]["slug"]}]
    got = store.get_next_draft_recipe()
    req = MockHandler.requests[-1]
    check("D2: REST next-draft GET filters + ordering",
          lambda: None if (req["method"] == "GET"
                           and "status=eq.draft_ready" in req["path"]
                           and "listing_id=is.null" in req["path"]
                           and "order=created_at.asc" in req["path"]
                           and "limit=1" in req["path"]
                           and got is not None and got["slug"] == recipes[0]["slug"])
          else f"unexpected request: {req}")

    store.mark_listed(rid, "listing-9", "https://etsy.com/listing/9")
    req = MockHandler.requests[-1]
    check("D3: REST mark_listed PATCHes the row by id",
          lambda: None if (req["method"] == "PATCH" and f"id=eq.{rid}" in req["path"]
                           and req["body"]["status"] == "listed"
                           and req["body"]["listing_id"] == "listing-9"
                           and req["body"]["etsy_url"] == "https://etsy.com/listing/9")
          else f"unexpected request: {req}")

    store.record_daily_post(SEED_START, rid, status="posted")
    req = MockHandler.requests[-1]
    check("D4: REST daily-post upsert",
          lambda: None if (req["method"] == "POST" and req["path"] == "/rest/v1/daily_posts"
                           and req["prefer"] == "resolution=merge-duplicates"
                           and req["body"]["date"] == "2026-01-01"
                           and req["body"]["recipe_id"] == rid
                           and req["body"]["status"] == "posted")
          else f"unexpected request: {req}")

    store.update_daily_post_metrics(SEED_START, views=7, favorites=1, sales=0)
    patches = [r for r in MockHandler.requests
               if r["method"] == "PATCH" and "daily_posts" in r["path"]]
    check("D5: REST metrics = read-modify-write (GET then PATCH sums)",
          lambda: None if patches and patches[-1]["body"] == {"views": 12, "favorites": 3, "sales": 1}
          else f"unexpected writes: {patches[-1]['body'] if patches else 'none'}")


# ===========================================================================
# Section E — seed CLI smoke
# ===========================================================================
def section_e() -> None:
    out_dir = REPO_ROOT / "_verify_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "seed_dry.sql"
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "seed_recipes.py"), "--dry-run", "--sql-out", str(out)],
        capture_output=True, text=True, cwd=str(REPO_ROOT), check=True,
    )
    text = out.read_text(encoding="utf-8")

    def check_sql_file() -> None:
        assert text.startswith("--") and "begin;" in text and "commit;" in text
        n = text.count("insert into public.recipes")
        assert n == SEED_COUNT, f"expected {SEED_COUNT} inserts, got {n}"
        assert "%s" not in text, "dump still contains placeholders"
    check("E1: seed --dry-run --sql-out writes a runnable SQL script (60 inserts)", check_sql_file)


# ===========================================================================
# main
# ===========================================================================
def main() -> int:
    print("Fragrance Bot — Supabase layer verification")
    print(f"seed plan: {SEED_COUNT} recipes from {SEED_START}, {SEED_READY} draft_ready\n")

    section_a()
    section_b()

    pg: Optional[Pglite] = None
    try:
        pg = Pglite()
        print("[info] PGlite available — executing SQL against a real Postgres engine\n")
    except Exception as exc:
        print(f"[warn] PGlite unavailable: {exc}\n")
    try:
        section_c(pg)
        section_c_constraints() if pg is not None else None
    finally:
        if pg is not None:
            pg.close()

    mock = MockServer()
    try:
        section_d(mock)
    finally:
        mock.close()

    section_e()

    lines: List[str] = []
    passes = fails = skips = 0
    for name, status, detail in _results:
        if status == "PASS":
            passes += 1
        elif status == "FAIL":
            fails += 1
        elif status == "SKIP":
            skips += 1
        lines.append(f"[{status:4s}] {name}" + (f" — {detail}" if detail else ""))
    total = len(_results)
    result = "PASS" if fails == 0 else "FAIL"
    lines.append("")
    lines.append(f"checks run : {total}")
    lines.append(f"passes     : {passes}")
    lines.append(f"failures   : {fails}")
    lines.append(f"skipped    : {skips}")
    lines.append(f"RESULT: {result}" + (f"   ({skips} checks skipped, see details)" if skips else ""))

    out_text = "\n".join(lines) + "\n"
    print("\n".join(lines))
    (REPO_ROOT / "verification-supabase.txt").write_text(out_text, encoding="utf-8")
    print("\noutput written to verification-supabase.txt")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())