"""Fragrance Bot — Supabase storage layer (dependency-light, free tier).

Two real backends plus an in-memory stub share one interface:

    upsert_recipe(recipe, status, created_at) -> recipe_id          (seed)
    get_next_draft_recipe() -> recipe row or None                   (cron)
    mark_listed(recipe_id, listing_id, etsy_url)                    (cron)
    record_daily_post(date, recipe_id, status="scheduled")          (cron)
    update_daily_post_metrics(date, views, favorites, sales)        (metrics)

Backends
--------
* ``PostgresStore``  — direct SQL over psycopg 3 (``POSTGRES_URL`` env var;
  use Supabase's pooler connection string). Preferred: simplest, exact, and
  the SQL below is unit-verified against a real Postgres engine.
* ``SupabaseRestStore`` — pure-stdlib client for Supabase's PostgREST API
  (``SUPABASE_URL`` + ``SUPABASE_SERVICE_ROLE_KEY``). Zero extra
  dependencies; slightly less capable (no transactional seed, no atomic
  metric increments — it does a read-modify-write instead).
* ``StubStore`` —— in-memory implementation used for tests / dry runs so
  everything can be verified before a database exists.

``get_store()`` picks the backend from the environment:

    POSTGRES_URL                     -> PostgresStore
    SUPABASE_URL + SERVICE_ROLE_KEY  -> SupabaseRestStore
    otherwise                        -> raises StoreNotConfiguredError

Credentials are ONLY ever read from the environment — never hardcoded.
psycopg is imported lazily so this module (and dry-run verification) works
without it installed.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import uuid as _uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Protocol, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
POSTGRES_URL = os.environ.get("POSTGRES_URL", "").strip()

REQUIRED_ENV = ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "POSTGRES_URL")

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class DbError(RuntimeError):
    """Base error for the storage layer."""


class StoreNotConfiguredError(DbError):
    """Raised when get_store() finds no usable credentials in the environment."""


class StoreError(DbError):
    """Raised when a backend operation fails (connection, constraint, HTTP)."""


# ---------------------------------------------------------------------------
# Column mapping (recipe JSON -> public.recipes columns)
# ---------------------------------------------------------------------------
# Engine field -> column. All engine fields map 1:1 except "yield", which the
# schema stores as yield_text (YIELD is a reserved word in the SQL standard).
_TEXT_COLUMNS = {
    "recipe_name": "recipe_name",
    "full_title": "full_title",
    "slug": "slug",
    "category": "category",
    "difficulty": "difficulty",
    "yield": "yield_text",
    "cost_to_make": "cost_to_make",
    "description_long": "description_long",
    "theme": "theme",
    "holiday": "holiday",
}
_JSON_COLUMNS = {
    "scent_profile": "scent_profile",
    "ingredients": "ingredients",
    "instructions": "instructions",
    "equipment": "equipment",
    "safety_notes": "safety_notes",
    "tags": "tags",
}
# Non-content columns that a seed re-run must NEVER touch (they reflect the
# recipe's real-world progression: queued -> listed -> archived).
_IMMUTABLE_ON_UPSERT = {"status", "listing_id", "etsy_url", "created_at", "listed_at"}
ALL_COLUMNS = list(_TEXT_COLUMNS.values()) + ["price_usd"] + list(_JSON_COLUMNS.values()) + [
    "status", "listing_id", "etsy_url", "created_at", "listed_at",
]

VALID_RECIPE_STATUSES = ("draft", "draft_ready", "listed", "archived")
VALID_POST_STATUSES = ("scheduled", "posted", "skipped", "failed")


def _iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()


def _row(recipe: dict, status: str, created_at: datetime) -> Dict[str, Any]:
    """Flatten a validated engine recipe into a recipes-table row dict."""
    row: Dict[str, Any] = {}
    for engine_key, column in _TEXT_COLUMNS.items():
        row[column] = recipe[engine_key]
    row["price_usd"] = f"{float(recipe['price_usd']):.2f}"
    for engine_key, column in _JSON_COLUMNS.items():
        row[column] = json.dumps(recipe[engine_key], ensure_ascii=False)
    row["status"] = status
    row["listing_id"] = None
    row["etsy_url"] = None
    row["created_at"] = created_at
    row["listed_at"] = None
    return row


# ---------------------------------------------------------------------------
# SQL builders — single source of truth for psycopg execution, literal SQL
# dumps (seed --sql-out) and the pglite verification harness.
# ---------------------------------------------------------------------------
def upsert_recipe_sql(recipe: dict, status: str, created_at: datetime) -> Tuple[str, List[Any]]:
    """Return (parameterized SQL, params) for an idempotent recipes upsert.

    ON CONFLICT (slug) refreshes content fields only — status / listing_id /
    etsy_url / created_at / listed_at are left untouched, so re-running the
    seed never resets a recipe that has already progressed to 'listed'.
    """
    row = _row(recipe, status, created_at)
    cols = list(row.keys())
    placeholders = ", ".join(["%s"] * len(cols))
    setters = ", ".join(
        f"{c} = excluded.{c}" for c in cols if c not in _IMMUTABLE_ON_UPSERT
    )
    sql = (
        f"insert into public.recipes ({', '.join(cols)}) "
        f"values ({placeholders}) "
        f"on conflict (slug) do update set {setters} "
        f"returning id"
    )
    return sql, list(row.values())


def render_upsert_sql(recipe: dict, status: str, created_at: datetime) -> str:
    """Render the upsert as a standalone executable SQL statement (dump mode)."""
    row = _row(recipe, status, created_at)
    cols = list(row.keys())
    def lit(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f"{float(value):.2f}" if isinstance(value, float) else str(value)
        if isinstance(value, datetime):
            return f"'{_iso(value)}'::timestamptz"
        s = str(value)
        return "'" + s.replace("'", "''") + "'"
    values = ", ".join(
        f"{lit(v)}::jsonb" if c in _JSON_COLUMNS.values() else lit(v)
        for c, v in zip(cols, row.values())
    )
    setters = ", ".join(
        f"{c} = excluded.{c}" for c in cols if c not in _IMMUTABLE_ON_UPSERT
    )
    return (
        f"insert into public.recipes ({', '.join(cols)}) "
        f"values ({values}) "
        f"on conflict (slug) do update set {setters}"
    )


SELECT_NEXT_DRAFT_SQL = """
    select * from public.recipes
     where status = 'draft_ready' and listing_id is null
     order by created_at asc, id asc
     limit 1
"""

MARK_LISTED_SQL = """
    update public.recipes
       set status = 'listed', listing_id = %s, etsy_url = %s, listed_at = now()
     where id = %s
"""

RECORD_POST_SQL = """
    insert into public.daily_posts (date, recipe_id, status, posted_at)
    values (%s, %s, %s, %s)
    on conflict (date) do update set
        recipe_id = excluded.recipe_id,
        status = excluded.status,
        posted_at = excluded.posted_at
"""

BUMP_METRICS_SQL = """
    update public.daily_posts
       set views = views + %s,
           favorites = favorites + %s,
           sales = sales + %s
     where date = %s
"""


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------
class Store(Protocol):
    def upsert_recipe(self, recipe: dict, status: str, created_at: datetime) -> str: ...
    def get_next_draft_recipe(self) -> Optional[Dict[str, Any]]: ...
    def mark_listed(self, recipe_id: str, listing_id: str, etsy_url: str) -> None: ...
    def record_daily_post(self, pdate: date, recipe_id: str, status: str = "scheduled") -> None: ...
    def update_daily_post_metrics(self, pdate: date, views: int = 0, favorites: int = 0, sales: int = 0) -> None: ...


# ---------------------------------------------------------------------------
# PostgresStore — psycopg 3 over POSTGRES_URL
# ---------------------------------------------------------------------------
class PostgresStore:
    """Direct-SQL store. Requires psycopg (``pip install 'psycopg[binary]'``)."""

    def __init__(self, postgres_url: Optional[str] = None) -> None:
        self.postgres_url = postgres_url or POSTGRES_URL
        if not self.postgres_url:
            raise StoreNotConfiguredError(
                "PostgresStore needs POSTGRES_URL (or pass postgres_url=...)"
            )
        self._psycopg = None

    def _connect(self):
        if self._psycopg is None:
            try:
                import psycopg  # type: ignore
            except ImportError as exc:  # pragma: no cover - env dependent
                raise StoreError(
                    "psycopg is not installed; run: pip install 'psycopg[binary]'"
                ) from exc
            self._psycopg = psycopg
        return self._psycopg.connect(self.postgres_url, connect_timeout=15)

    def upsert_recipe(self, recipe: dict, status: str, created_at: datetime) -> str:
        sql, params = upsert_recipe_sql(recipe, status, created_at)
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                if row is None:  # pragma: no cover - defensive
                    raise StoreError("upsert returned no id")
                return str(row[0])
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"upsert_recipe failed for slug={recipe.get('slug')!r}: {exc}") from exc

    def get_next_draft_recipe(self) -> Optional[Dict[str, Any]]:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(SELECT_NEXT_DRAFT_SQL)
                row = cur.fetchone()
                if row is None:
                    return None
                cols = [d.name for d in cur.description]
                out = dict(zip(cols, row))
                out["id"] = str(out["id"])
                if out.get("listing_id") is not None:
                    out["listing_id"] = str(out["listing_id"])
                if out.get("listed_at") is not None:
                    out["listed_at"] = out["listed_at"].isoformat()
                if out.get("created_at") is not None:
                    out["created_at"] = out["created_at"].isoformat()
                out["price_usd"] = str(out["price_usd"])
                return out
        except Exception as exc:
            raise StoreError(f"get_next_draft_recipe failed: {exc}") from exc

    def mark_listed(self, recipe_id: str, listing_id: str, etsy_url: str) -> None:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(MARK_LISTED_SQL, (listing_id, etsy_url, recipe_id))
                if cur.rowcount != 1:
                    raise StoreError(
                        f"mark_listed: no recipe with id={recipe_id} (rowcount={cur.rowcount})"
                    )
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"mark_listed failed for recipe {recipe_id}: {exc}") from exc

    def record_daily_post(self, pdate: date, recipe_id: str, status: str = "scheduled") -> None:
        if status not in VALID_POST_STATUSES:
            raise ValueError(f"invalid daily post status: {status!r}")
        posted_at = datetime.now(timezone.utc) if status == "posted" else None
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(RECORD_POST_SQL, (pdate.isoformat(), recipe_id, status, posted_at))
        except Exception as exc:
            raise StoreError(f"record_daily_post failed for {pdate}: {exc}") from exc

    def update_daily_post_metrics(self, pdate: date, views: int = 0, favorites: int = 0, sales: int = 0) -> None:
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(BUMP_METRICS_SQL, (views, favorites, sales, pdate.isoformat()))
                if cur.rowcount != 1:
                    raise StoreError(f"update_daily_post_metrics: no row for {pdate}")
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"update_daily_post_metrics failed for {pdate}: {exc}") from exc


# ---------------------------------------------------------------------------
# SupabaseRestStore — stdlib-only client for PostgREST
# ---------------------------------------------------------------------------
class SupabaseRestStore:
    """PostgREST store over SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY.

    Pure stdlib (urllib) — no third-party dependencies. Handles upserts via
    PostgREST's ``Prefer: resolution=merge-duplicates`` header. Metric
    increments are read-modify-write (PostgREST has no atomic increment in
    the basic API) — fine for a single-writer cron.
    """

    def __init__(self, supabase_url: Optional[str] = None, service_role_key: Optional[str] = None) -> None:
        self.base_url = (supabase_url or SUPABASE_URL).rstrip("/")
        self.key = service_role_key or SUPABASE_SERVICE_ROLE_KEY
        if not self.base_url or not self.key:
            raise StoreNotConfiguredError(
                "SupabaseRestStore needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY "
                "(or pass supabase_url=/service_role_key=)"
            )

    # -- http plumbing -----------------------------------------------------
    def _request(self, method: str, path: str, body: Optional[dict] = None,
                 params: Optional[str] = None, prefer: Optional[str] = None) -> List[Dict[str, Any]]:
        import urllib.error
        import urllib.request
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{params}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("apikey", self.key)
        req.add_header("Authorization", f"Bearer {self.key}")
        req.add_header("Content-Type", "application/json")
        if prefer:
            req.add_header("Prefer", prefer)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else []
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raise StoreError(
                f"PostgREST {method} {path} -> {exc.code}: {detail}"
            ) from exc
        except OSError as exc:
            raise StoreError(f"PostgREST {method} {path} network error: {exc}") from exc

    # -- store interface ---------------------------------------------------
    def upsert_recipe(self, recipe: dict, status: str, created_at: datetime) -> str:
        row = _row(recipe, status, created_at)
        row["created_at"] = _iso(created_at)
        row.pop("listed_at", None)
        out = self._request(
            "POST", "/rest/v1/recipes", body=row,
            prefer="resolution=merge-duplicates",
        )
        if not out or "id" not in out[0]:
            raise StoreError(f"upsert_recipe: no id returned for slug={recipe.get('slug')!r}")
        return str(out[0]["id"])

    def get_next_draft_recipe(self) -> Optional[Dict[str, Any]]:
        params = (
            "select=*&status=eq.draft_ready&listing_id=is.null"
            "&order=created_at.asc&limit=1"
        )
        out = self._request("GET", "/rest/v1/recipes", params=params)
        return out[0] if out else None

    def mark_listed(self, recipe_id: str, listing_id: str, etsy_url: str) -> None:
        body = {
            "status": "listed",
            "listing_id": listing_id,
            "etsy_url": etsy_url,
            "listed_at": _iso(datetime.now(timezone.utc)),
        }
        self._request("PATCH", "/rest/v1/recipes", body=body, params=f"id=eq.{recipe_id}")

    def record_daily_post(self, pdate: date, recipe_id: str, status: str = "scheduled") -> None:
        if status not in VALID_POST_STATUSES:
            raise ValueError(f"invalid daily post status: {status!r}")
        body = {
            "date": pdate.isoformat(),
            "recipe_id": recipe_id,
            "status": status,
            "listing_id": None,
            "views": 0,
            "favorites": 0,
            "sales": 0,
            "posted_at": _iso(datetime.now(timezone.utc)) if status == "posted" else None,
        }
        self._request(
            "POST", "/rest/v1/daily_posts", body=body,
            prefer="resolution=merge-duplicates",
        )

    def update_daily_post_metrics(self, pdate: date, views: int = 0, favorites: int = 0, sales: int = 0) -> None:
        rows = self._request(
            "GET", "/rest/v1/daily_posts",
            params=f"select=views,favorites,sales&date=eq.{pdate.isoformat()}",
        )
        if not rows:
            raise StoreError(f"update_daily_post_metrics: no daily_post row for {pdate}")
        cur = rows[0]
        body = {
            "views": int(cur.get("views") or 0) + views,
            "favorites": int(cur.get("favorites") or 0) + favorites,
            "sales": int(cur.get("sales") or 0) + sales,
        }
        self._request("PATCH", "/rest/v1/daily_posts", body=body, params=f"date=eq.{pdate.isoformat()}")


# ---------------------------------------------------------------------------
# StubStore — in-memory, for tests / dry runs before a database exists
# ---------------------------------------------------------------------------
class StubStore:
    """In-memory store mirroring PostgresStore semantics (deterministic)."""

    def __init__(self) -> None:
        self.recipes: Dict[str, Dict[str, Any]] = {}   # slug -> row
        self.posts: Dict[str, Dict[str, Any]] = {}     # iso date -> row

    def upsert_recipe(self, recipe: dict, status: str, created_at: datetime) -> str:
        assert status in VALID_RECIPE_STATUSES, f"bad recipe status: {status}"
        slug = recipe["slug"]
        if slug in self.recipes:
            row = self.recipes[slug]
            for col in ALL_COLUMNS:
                if col not in _IMMUTABLE_ON_UPSERT:
                    row[col] = _row(recipe, status, created_at)[col]
        else:
            self.recipes[slug] = _row(recipe, status, created_at)
            self.recipes[slug]["id"] = str(_uuid.uuid4())
        return self.recipes[slug]["id"]

    def get_next_draft_recipe(self) -> Optional[Dict[str, Any]]:
        candidates = [
            r for r in self.recipes.values()
            if r["status"] == "draft_ready" and r["listing_id"] is None
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda r: (r["created_at"], r["id"]))

    def mark_listed(self, recipe_id: str, listing_id: str, etsy_url: str) -> None:
        for r in self.recipes.values():
            if r["id"] == recipe_id:
                r["status"] = "listed"
                r["listing_id"] = listing_id
                r["etsy_url"] = etsy_url
                r["listed_at"] = datetime.now(timezone.utc)
                return
        raise StoreError(f"mark_listed: no recipe with id={recipe_id}")

    def record_daily_post(self, pdate: date, recipe_id: str, status: str = "scheduled") -> None:
        assert status in VALID_POST_STATUSES, f"bad post status: {status}"
        key = pdate.isoformat()
        row = self.posts.setdefault(key, {
            "date": pdate, "recipe_id": recipe_id, "listing_id": None,
            "status": status, "views": 0, "favorites": 0, "sales": 0,
            "posted_at": None,
        })
        row["recipe_id"] = recipe_id
        row["status"] = status
        if status == "posted":
            row["posted_at"] = datetime.now(timezone.utc)

    def update_daily_post_metrics(self, pdate: date, views: int = 0, favorites: int = 0, sales: int = 0) -> None:
        key = pdate.isoformat()
        if key not in self.posts:
            raise StoreError(f"update_daily_post_metrics: no daily_post row for {pdate}")
        row = self.posts[key]
        row["views"] += views
        row["favorites"] += favorites
        row["sales"] += sales


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def get_store() -> Store:
    """Pick a backend from the environment (see module docstring)."""
    if POSTGRES_URL:
        logger.info("using PostgresStore (POSTGRES_URL)")
        return PostgresStore()
    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        logger.info("using SupabaseRestStore (SUPABASE_URL + service role key)")
        return SupabaseRestStore()
    raise StoreNotConfiguredError(
        "no Supabase credentials found. Set one of:\n"
        "  POSTGRES_URL                      (recommended for the seed/cron)\n"
        "  SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY\n"
        "Credentials are env-only; never hardcode them."
    )


# ---------------------------------------------------------------------------
# Convenience: deterministic seed timestamps
# ---------------------------------------------------------------------------
def seed_created_at(index: int, total: int, base: Optional[datetime] = None) -> datetime:
    """created_at for seed row ``index`` of ``total`` (oldest first).

    The daily cron picks the OLDEST draft_ready recipe, so the seed staggers
    created_at so that index 0 is the first recipe the cron will post.
    """
    base = base or datetime.now(timezone.utc)
    return base - timedelta(days=(total - index))