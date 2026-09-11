"""Refresh-token rotation persistence for Etsy OAuth.

Etsy **rotates** refresh tokens: every token refresh invalidates the
previous refresh token and returns a new one. Left alone, a GitHub Actions
cron (which reads ``ETSY_REFRESH_TOKEN`` from Secrets) would break on its
second run, because the Secret still holds the now-dead token.

This module provides small, dependency-light stores that persist the *new*
refresh token somewhere durable so the next daily run can load it:

1. ``FileTokenStore`` — a gitignored local file (works for on-server crons
   and for local runs).
2. ``SupabaseTokenStore`` — persists into a tiny ``etsy_tokens`` key/value
   table (created lazily with ``CREATE TABLE IF NOT EXISTS``) via either
   psycopg (``POSTGRES_URL``) or the stdlib PostgREST client
   (``SUPABASE_URL`` + ``SUPABASE_SERVICE_ROLE_KEY``). This is what the
   GitHub Actions cron uses so rotation survives between runs.
3. ``ChainTokenStore`` — tries several stores in order (Supabase first,
   file second), so a run always has a durable copy even if one backend is
   down. Failures to persist are **logged, never fatal**: a failed save must
   not take down a successful posting run.

``get_token_store()`` picks the chain for the current environment. The
daily-post script consults ``store.load()`` *before* ``ETSY_REFRESH_TOKEN``:
the env var is the bootstrap value (or an owner-forced rotation), while a
persisted rotated token takes priority once it exists.

The ``etsy_tokens`` table is intentionally NOT part of ``supabase/schema.sql``:
it is created lazily so adding the Etsy layer never requires re-running the
main schema migration — and it stays out of the main schema's blast radius.
Run this SQL once anywhere to create it up front::

    create table if not exists public.etsy_tokens (
        k          text primary key,
        v          text not null,
        updated_at timestamptz not null default now()
    );
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import List, Optional

log = logging.getLogger("fragbot.etsy.token_store")

KEY = "etsy_refresh_token"
TABLE_DDL = (
    "create table if not exists public.etsy_tokens ("
    " k text primary key, v text not null, updated_at timestamptz not null default now())"
)


class TokenStore:
    """Minimal interface: load() -> Optional[str], save(token) -> None."""

    def load(self) -> Optional[str]:
        raise NotImplementedError

    def save(self, token: str) -> None:
        raise NotImplementedError


class FileTokenStore(TokenStore):
    """Persist the rotated refresh token in a gitignored local file."""

    DEFAULT_PATH = Path("secrets/etsy_refresh_token")

    def __init__(self, path=None) -> None:
        self.path = Path(path or self.DEFAULT_PATH)

    def load(self) -> Optional[str]:
        try:
            if self.path.exists():
                val = self.path.read_text(encoding="utf-8").strip()
                return val or None
        except OSError as exc:  # pragma: no cover - defensive
            log.warning("could not read token file %s: %s", self.path, exc)
        return None

    def save(self, token: str) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(token.strip(), encoding="utf-8")
            log.info("rotated refresh token persisted to %s", self.path)
        except OSError as exc:  # pragma: no cover - defensive
            log.warning("could not persist rotated token to %s: %s", self.path, exc)


class SupabaseTokenStore(TokenStore):
    """Persist the rotated refresh token in the ``etsy_tokens`` table.

    Backends (mirroring fragbot.db): psycopg over POSTGRES_URL, or the
    stdlib-only PostgREST client over SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY.
    """

    def __init__(
        self,
        postgres_url: Optional[str] = None,
        supabase_url: Optional[str] = None,
        service_role_key: Optional[str] = None,
    ) -> None:
        self.postgres_url = postgres_url or os.environ.get("POSTGRES_URL", "").strip()
        self.supabase_url = (
            supabase_url or os.environ.get("SUPABASE_URL", "").strip()
        ).rstrip("/")
        self.service_role_key = service_role_key or os.environ.get(
            "SUPABASE_SERVICE_ROLE_KEY", ""
        ).strip()

    def _ensure_table_pg(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute(TABLE_DDL)
        conn.commit()

    def load(self) -> Optional[str]:
        try:
            if self.postgres_url:
                import psycopg  # type: ignore

                with psycopg.connect(self.postgres_url, connect_timeout=15) as conn:
                    self._ensure_table_pg(conn)
                    with conn.cursor() as cur:
                        cur.execute(
                            "select v from public.etsy_tokens where k = %s", (KEY,)
                        )
                        row = cur.fetchone()
                        return str(row[0]) if row else None
            if self.supabase_url and self.service_role_key:
                rows = self._rest_get()
                return str(rows[0]["v"]) if rows else None
        except Exception as exc:  # noqa: BLE001 - never fatal
            log.warning("SupabaseTokenStore.load failed: %s", exc)
        return None

    def save(self, token: str) -> None:
        try:
            if self.postgres_url:
                import psycopg  # type: ignore

                with psycopg.connect(self.postgres_url, connect_timeout=15) as conn:
                    self._ensure_table_pg(conn)
                    with conn.cursor() as cur:
                        cur.execute(
                            "insert into public.etsy_tokens (k, v, updated_at)"
                            " values (%s, %s, now())"
                            " on conflict (k) do update set v = excluded.v,"
                            " updated_at = now()",
                            (KEY, token.strip()),
                        )
                    conn.commit()
                log.info("rotated refresh token persisted to etsy_tokens (Postgres)")
                return
            if self.supabase_url and self.service_role_key:
                self._rest_upsert(token)
                log.info("rotated refresh token persisted to etsy_tokens (REST)")
                return
            log.warning(
                "SupabaseTokenStore.save: no POSTGRES_URL or SUPABASE_URL+KEY set"
            )
        except Exception as exc:  # noqa: BLE001 - never fatal
            log.warning("SupabaseTokenStore.save failed: %s", exc)

    # -- PostgREST plumbing (stdlib only) ------------------------------------
    def _rest_get(self) -> list:
        import urllib.request

        url = f"{self.supabase_url}/rest/v1/etsy_tokens?k=eq.{KEY}&select=v"
        req = urllib.request.Request(url, method="GET")
        req.add_header("apikey", self.service_role_key)
        req.add_header("Authorization", f"Bearer {self.service_role_key}")
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else []

    def _rest_upsert(self, token: str) -> None:
        import urllib.request

        url = f"{self.supabase_url}/rest/v1/etsy_tokens"
        body = json.dumps(
            {"k": KEY, "v": token.strip(), "updated_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            )}
        ).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("apikey", self.service_role_key)
        req.add_header("Authorization", f"Bearer {self.service_role_key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Prefer", "resolution=merge-duplicates")
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()


class ChainTokenStore(TokenStore):
    """Try each store in order for load; save to all of them (best-effort)."""

    def __init__(self, stores: List[TokenStore]) -> None:
        self.stores = stores

    def load(self) -> Optional[str]:
        for store in self.stores:
            val = store.load()
            if val:
                return val
        return None

    def save(self, token: str) -> None:
        for store in self.stores:
            try:
                store.save(token)
            except Exception as exc:  # noqa: BLE001
                log.warning("token store %s failed to save: %s", type(store).__name__, exc)


def get_token_store() -> TokenStore:
    """Pick the best token store chain for the current environment."""
    stores: List[TokenStore] = []
    supabase = SupabaseTokenStore()
    if supabase.postgres_url or (supabase.supabase_url and supabase.service_role_key):
        stores.append(supabase)
    stores.append(FileTokenStore())
    return ChainTokenStore(stores)