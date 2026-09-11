"""Fragrance Bot Etsy API layer.

    from fragbot.etsy import EtsyClient
    client = EtsyClient.from_env()

Standard-library only (urllib) — no paid services, no extra dependencies.
Endpoint shapes are verified against Etsy's official OpenAPI v3 spec
(see ``fragbot.etsy.spec`` for the extracted parameter maps).

CLI / docs: see scripts/etsy_oauth.py (one-time owner authorization) and
scripts/daily_post.py (the daily posting pipeline).
"""
from __future__ import annotations

__version__ = "0.1.0"

from .client import DEFAULT_TAXONOMY_ID, EtsyClient, _find_taxonomy_by_name
from .errors import (
    EtsyApiError,
    EtsyAuthError,
    EtsyConfigError,
    EtsyError,
    EtsyRateLimitError,
    EtsyTransportError,
    EtsyValidationError,
)
from .ratelimit import RateLimiter
from .token_store import (
    ChainTokenStore,
    FileTokenStore,
    SupabaseTokenStore,
    TokenStore,
    get_token_store,
)
from .transport import OAuthSession

__all__ = [
    "DEFAULT_TAXONOMY_ID",
    "EtsyClient",
    "EtsyError",
    "EtsyConfigError",
    "EtsyValidationError",
    "EtsyTransportError",
    "EtsyRateLimitError",
    "EtsyApiError",
    "EtsyAuthError",
    "RateLimiter",
    "TokenStore",
    "FileTokenStore",
    "SupabaseTokenStore",
    "ChainTokenStore",
    "get_token_store",
    "OAuthSession",
    "__version__",
]