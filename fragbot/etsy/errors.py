"""Typed errors for the Etsy API layer (fragbot.etsy).

Hierarchy
---------
``EtsyError`` is the base for everything this package raises; callers that
only want "did the Etsy step fail?" catch ``EtsyError``. Finer subtypes let
the daily-post pipeline and the verifier react differently to auth problems,
transient failures and rejected payloads.
"""
from __future__ import annotations

from typing import Optional


class EtsyError(RuntimeError):
    """Base class for all errors raised by the Fragrance Bot Etsy layer."""

    def __init__(self, message: str, *, cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.cause = cause


class EtsyConfigError(EtsyError):
    """Missing/invalid configuration (env vars, over-long tags, ...)."""


class EtsyValidationError(EtsyConfigError):
    """A payload violates an Etsy API constraint (title > 140, tag > 20, ...).

    Raised *before* any bytes hit the network — the API client refuses to
    send payloads that Etsy's OpenAPI spec would reject.
    """


class EtsyTransportError(EtsyError):
    """Network-level failure after retries were exhausted."""


class EtsyRateLimitError(EtsyTransportError):
    """Etsy kept answering 429 past our retry budget."""


class EtsyApiError(EtsyError):
    """Etsy answered with a non-2xx status (after retries for 429/5xx).

    Carries the HTTP status and a short snippet of the response body so
    callers and logs can reason about it.
    """

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        body: Optional[str] = None,
        code: Optional[str] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.status = status
        self.body = body
        # Etsy error responses carry an `error` (machine code) + `error_description`:
        # {"error": "bad_request", "error_description": "..."}
        self.code = code

    @property
    def is_missing_digital_file(self) -> bool:
        """True if Etsy rejected the call because a digital file is required.

        Etsy rejects activating a digital listing that has no uploaded file;
        when that happens the pipeline uploads the file first and retries.
        Detection is intentionally substring-based on the message Etsy sends.
        """
        hay = f"{self.message} {self.body or ''} {self.code or ''}".lower()
        return ("file" in hay and ("digital" in hay or "activ" in hay)) or (
            "digital" in hay and "file" in hay
        )


class EtsyAuthError(EtsyApiError):
    """401/403 — the access token is invalid/expired or the grant was revoked."""

    @property
    def refresh_token_rejected(self) -> bool:
        """True when Etsy rejected the *refresh* token itself (invalid_grant)."""
        return "invalid_grant" in self.body or "refresh_token" in (self.body or "")