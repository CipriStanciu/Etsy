"""HTTP transport for the Etsy Open API v3 (stdlib ``urllib`` only).

Responsibilities
----------------
* OAuth 2.0 bearer auth with **auto-refresh**: the first authorized call of
  a session refreshes the access token (``grant_type=refresh_token``), then
  transparently refreshes again when Etsy answers 401 (token expiry between
  calls). Refresh **rotates** the refresh token — the new one is stored via
  the injected ``token_store`` so the *next* daily run keeps working.
* **Rate limiting**: every request passes through a ``RateLimiter``
  (>= 150 ms spacing, <= 10 req/s token bucket).
* **Retries**: exponential backoff + jitter on HTTP 429 and 5xx; honors the
  ``Retry-After`` header when Etsy sends one; raises a typed error after the
  retry budget is exhausted.
* **Multipart/form-data** uploads built with pure stdlib (images, digital
  files), and ``application/x-www-form-urlencoded`` bodies exactly as the
  OpenAPI spec declares them.

No credentials are hardcoded: everything comes from environment variables
(``ETSY_KEYSTRING``, ``ETSY_REFRESH_TOKEN``, optional ``ETSY_SHARED_SECRET``)
or constructor arguments — the daily-post script wires those up.
"""
from __future__ import annotations

import email.utils
import json
import logging
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .errors import (
    EtsyApiError,
    EtsyAuthError,
    EtsyConfigError,
    EtsyRateLimitError,
    EtsyTransportError,
)
from .ratelimit import RateLimiter
from .token_store import TokenStore, get_token_store

log = logging.getLogger("fragbot.etsy.transport")

# Overridden in tests to point at the local mock; production never sets these.
DEFAULT_BASE_URL = "https://openapi.etsy.com"
DEFAULT_TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"


def env_or(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


class OAuthSession:
    """Owns the Etsy access token + its refresh-token rotation.

    ``refresh_token`` resolution order (per the team's decision):
      1. the token store (a rotated token persisted by a previous run), else
      2. the ``ETSY_REFRESH_TOKEN`` env var (the bootstrap / owner-forced
         rotation).
    Every successful refresh saves the *new* refresh token to the store.
    """

    def __init__(
        self,
        keystring: str,
        refresh_token: Optional[str] = None,
        token_url: str = DEFAULT_TOKEN_URL,
        token_store: Optional[TokenStore] = None,
        timeout: float = 30.0,
    ) -> None:
        if not keystring:
            raise EtsyConfigError("ETSY_KEYSTRING is required (Etsy App API key keystring)")
        self.keystring = keystring
        self.token_url = token_url
        self.timeout = timeout
        self.token_store = token_store or get_token_store()

        # Priority: persisted rotated token first, env var as bootstrap.
        self.refresh_token = refresh_token or self.token_store.load() or env_or(
            "ETSY_REFRESH_TOKEN"
        )
        if not self.refresh_token:
            raise EtsyConfigError(
                "no Etsy refresh token found. Set ETSY_REFRESH_TOKEN (or run "
                "scripts/etsy_oauth.py once and persist the token it prints)."
            )
        self.access_token: Optional[str] = None
        self.access_expires_at: float = 0.0  # monotonic() deadline
        self.refresh_count = 0

    # -- token lifecycle ----------------------------------------------------
    def ensure_access_token(self) -> str:
        """Return a valid access token, refreshing when needed."""
        if self.access_token and time.monotonic() < self.access_expires_at - 30:
            return self.access_token
        return self._refresh()

    def _refresh(self) -> str:
        """POST grant_type=refresh_token; store the ROTATED refresh token."""
        form = {
            "grant_type": "refresh_token",
            "client_id": self.keystring,
            "refresh_token": self.refresh_token,
        }
        data = urllib.parse.urlencode(form).encode("utf-8")
        req = urllib.request.Request(self.token_url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            raise EtsyAuthError(
                f"OAuth token refresh failed with HTTP {exc.code}: {body}",
                status=exc.code,
                body=body,
                code=_error_code(body),
            ) from exc
        except OSError as exc:
            raise EtsyTransportError(
                f"OAuth token refresh network error: {exc}"
            ) from exc

        self.access_token = payload.get("access_token")
        if not self.access_token:
            raise EtsyAuthError(
                f"OAuth token refresh returned no access_token: {str(payload)[:300]}"
            )
        self.refresh_count += 1
        # Etsy ROTATES the refresh token on every grant; persist the new one.
        new_refresh = payload.get("refresh_token")
        if new_refresh and new_refresh != self.refresh_token:
            log.info("Etsy rotated the refresh token; persisting the new one")
            self.refresh_token = new_refresh
            try:
                self.token_store.save(new_refresh)
            except Exception as exc:  # pragma: no cover - never fatal  # noqa: BLE001
                log.warning("could not persist rotated refresh token: %s", exc)

        try:
            expires_in = int(payload.get("expires_in", 3600))
        except (TypeError, ValueError):
            expires_in = 3600
        self.access_expires_at = time.monotonic() + expires_in
        log.debug("access token refreshed (expires_in=%ss)", expires_in)
        return self.access_token


def _error_code(body: str) -> Optional[str]:
    """Best-effort extraction of Etsy's machine `error` code from a body."""
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            err = parsed.get("error")
            return str(err) if err else None
    except (ValueError, TypeError):
        pass
    return None


class EtsyTransport:
    """Low-level HTTP for the Etsy API with auth, throttling and retries."""

    def __init__(
        self,
        session: OAuthSession,
        base_url: str = DEFAULT_BASE_URL,
        shared_secret: str = "",
        rate_limiter: Optional[RateLimiter] = None,
        max_retries: int = 4,
        backoff_base: float = 0.6,
        timeout: float = 30.0,
    ) -> None:
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.shared_secret = shared_secret
        self.rate_limiter = rate_limiter or RateLimiter()
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.timeout = timeout

    # -- public -------------------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        form: Optional[Dict[str, Any]] = None,
        files: Optional[List[Tuple[str, str, bytes, str]]] = None,
        headers: Optional[Dict[str, str]] = None,
        auth: bool = True,
    ) -> Tuple[int, Dict[str, Any]]:
        """Send one API call; return (status, parsed JSON body).

        ``files`` is a list of (field_name, filename, bytes, content_type).
        Raises a typed EtsyError after the retry budget is exhausted.
        """
        url = self.base_url + path
        if params:
            url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"

        attempt = 0
        while True:
            self.rate_limiter.wait()
            try:
                status, body, resp_headers = self._send(
                    method, url, form=form, files=files, headers=headers, auth=auth
                )
            except EtsyAuthError as exc:
                # Access token expired between calls; refresh once and retry.
                if auth and not getattr(exc, "_retried_auth", False):
                    self.session.ensure_access_token()
                    exc._retried_auth = True  # type: ignore[attr-defined]
                    continue
                raise

            if status < 400:
                return status, body

            retryable = status in (429,) or 500 <= status <= 599
            if retryable and attempt < self.max_retries:
                delay = self._backoff(
                    attempt,
                    retry_after=(
                        resp_headers.get("Retry-After")
                        if resp_headers is not None else None
                    ),
                )
                log.warning(
                    "Etsy %s %s -> HTTP %s; retrying in %.1fs (attempt %d/%d)",
                    method, path, status, delay, attempt + 1, self.max_retries,
                )
                time.sleep(delay)
                attempt += 1
                continue

            if status == 429:
                raise EtsyRateLimitError(
                    f"Etsy rate limit (429) persisted after {self.max_retries + 1} attempts",
                    status=status, body=json.dumps(body)[:500],
                )
            if 500 <= status <= 599:
                raise EtsyTransportError(
                    f"Etsy HTTP {status} persisted after {self.max_retries + 1} attempts",
                    status=status, body=json.dumps(body)[:500],
                )
            raise EtsyApiError(
                f"Etsy API error HTTP {status}: {json.dumps(body)[:400]}",
                status=status, body=json.dumps(body)[:500], code=_error_code(
                    json.dumps(body)
                ),
            )

    # -- internals ----------------------------------------------------------
    def _backoff(self, attempt: int, retry_after: Any = None) -> float:
        """Sleep budget for a retry: Retry-After wins, else exp+jitter."""
        wa = _parse_retry_after(retry_after)
        if wa is not None:
            return max(0.0, min(wa, 120.0))
        base = self.backoff_base * (2 ** attempt)
        jitter = random.uniform(0.0, base * 0.35)
        return min(base + jitter, 60.0)

    def _headers(self, auth: bool) -> Dict[str, str]:
        hdrs = {
            "Accept": "application/json",
            "User-Agent": "FragranceBot/0.1 (daily Etsy listing pipeline)",
        }
        # x-api-key is required on every v3 request: keystring alone, or
        # "keystring:shared_secret" when the owner supplies the secret.
        hdr = self.session.keystring
        if self.shared_secret:
            hdr = f"{hdr}:{self.shared_secret}"
        hdrs["x-api-key"] = hdr
        if auth:
            hdrs["Authorization"] = f"Bearer {self.session.ensure_access_token()}"
        return hdrs

    def _send(
        self,
        method: str,
        url: str,
        *,
        form: Optional[Dict[str, Any]],
        files: Optional[List[Tuple[str, str, bytes, str]]],
        headers: Optional[Dict[str, str]],
        auth: bool,
    ) -> Tuple[int, Dict[str, Any], Any]:
        hdrs = self._headers(auth)
        if headers:
            hdrs.update(headers)

        body_bytes: Optional[bytes] = None
        if files:
            data, boundary = _multipart_body(form or {}, files)
            hdrs["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            body_bytes = data
        elif form is not None:
            # Lists (tags) are sent as comma-separated strings; Etsy's
            # application/x-www-form-urlencoded schema accepts CSV arrays.
            encoded = {}
            for k, v in form.items():
                if isinstance(v, (list, tuple)):
                    encoded[k] = ",".join(str(x) for x in v)
                elif isinstance(v, bool):
                    encoded[k] = "true" if v else "false"
                else:
                    encoded[k] = v
            body_bytes = urllib.parse.urlencode(encoded).encode("utf-8")
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(url, data=body_bytes, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return (
                    resp.status,
                    (json.loads(raw) if raw else {}),
                    resp.headers,
                )
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            parsed: Dict[str, Any] = {}
            try:
                parsed = json.loads(raw) if raw else {}
            except ValueError:
                parsed = {"raw": raw[:300]}
            if exc.code in (401, 403):
                raise EtsyAuthError(
                    f"Etsy auth error HTTP {exc.code}: {raw[:300]}",
                    status=exc.code, body=raw[:500], code=_error_code(raw),
                ) from exc
            return exc.code, parsed, exc.headers
        except OSError as exc:
            raise EtsyTransportError(f"network error talking to Etsy ({url}): {exc}") from exc


def _parse_retry_after(value: Any) -> Optional[float]:
    """Retry-After may be delta-seconds or an HTTP-date."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if s.isdigit():
        return float(s)
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (dt - datetime.now(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return None


def _multipart_body(
    fields: Dict[str, Any], files: List[Tuple[str, str, bytes, str]]
) -> Tuple[bytes, str]:
    """Build a multipart/form-data body (stdlib only)."""
    boundary = f"----fragbot{uuid.uuid4().hex}"
    chunks: List[bytes] = []
    for k, v in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
        )
        chunks.append(str(v).encode("utf-8") + b"\r\n")
    for field_name, filename, data, ctype in files:
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{filename}"\r\n'
            ).encode()
        )
        chunks.append(f"Content-Type: {ctype}\r\n\r\n".encode())
        chunks.append(data + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary