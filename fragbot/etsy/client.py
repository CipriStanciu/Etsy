"""Etsy API client — the high-level surface the daily-post pipeline calls.

Endpoint shapes are taken from Etsy's official OpenAPI v3 spec (see
``fragbot/etsy/spec.py`` for the extracted parameter maps and the note on
where the owner's draft field names (``is_digital``) differ from the real
API).

    from fragbot.etsy import EtsyClient
    client = EtsyClient.from_env()
    shop = client.verify_shop()
    tax  = client.resolve_taxonomy_id()
    listing = client.create_listing_draft(recipe, taxonomy_id=tax)
    client.upload_listing_image(listing["listing_id"], image_path, rank=1)
    ...
    listing = client.activate_listing(listing["listing_id"])
    client.upload_digital_file(listing["listing_id"], pdf_path)
    client.get_listing(listing["listing_id"])["url"]

Constants
---------
* ``DEFAULT_TAXONOMY_ID`` — sensible fallback taxonomy when the live
  seller-taxonomy lookup finds no match (Etsy "Craft Supplies & Tools"
  root, id 563 — the broadest node that accepts DIY/digital-download
  listings). Override with ``ETSY_TAXONOMY_ID``; the runtime lookup by name
  (deepest keyword match first) normally pins a more specific node.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .errors import (
    EtsyConfigError,
    EtsyError,
    EtsyValidationError,
)
from .spec import (
    CREATE_LISTING_REQUIRED,
    ENUM_STATE,
    ENUM_TYPE,
    ENUM_WHEN_MADE,
    ENUM_WHO_MADE,
)
from .transport import (
    DEFAULT_BASE_URL,
    DEFAULT_TOKEN_URL,
    EtsyTransport,
    OAuthSession,
    env_or,
)
from .ratelimit import RateLimiter
from .token_store import TokenStore

log = logging.getLogger("fragbot.etsy.client")

# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------
# "Craft Supplies & Tools" — Etsy seller-taxonomy root id (well-documented
# stable value). Used only when the live taxonomy cannot be fetched or no
# node matches by name.
DEFAULT_TAXONOMY_ID = 563

# Keyword groups used for the by-name lookup; the DEEPEST matching node wins.
TAXONOMY_KEYWORDS = [
    ("craft supplies", 1),
    ("diy", 1),
    ("recipe", 2),
    ("how-to", 2),
    ("how to", 2),
    ("digital", 2),
    ("home & hobby", 1),
]


class EtsyClient:
    """High-level client: shop verification, taxonomy, listings, uploads."""

    def __init__(
        self,
        keystring: str,
        refresh_token: Optional[str] = None,
        shop_id: Optional[str] = None,
        shared_secret: str = "",
        taxonomy_id: Optional[int] = None,
        shipping_profile_id: Optional[int] = None,
        base_url: str = DEFAULT_BASE_URL,
        token_url: str = DEFAULT_TOKEN_URL,
        token_store: Optional[TokenStore] = None,
        rate_limiter: Optional[RateLimiter] = None,
        max_retries: int = 4,
    ) -> None:
        if shop_id is None:
            shop_id = env_or("ETSY_SHOP_ID")
        if shop_id is None or not str(shop_id).strip():
            raise EtsyConfigError(
                "ETSY_SHOP_ID is required (the numeric id of the owner's Etsy shop)"
            )
        self.shop_id = str(shop_id).strip()
        if not self.shop_id.isdigit():
            raise EtsyConfigError(f"ETSY_SHOP_ID must be numeric, got {self.shop_id!r}")

        session = OAuthSession(
            keystring=keystring,
            refresh_token=refresh_token,
            token_url=token_url,
            token_store=token_store,
        )
        self.transport = EtsyTransport(
            session=session,
            base_url=base_url,
            shared_secret=shared_secret,
            rate_limiter=rate_limiter or RateLimiter(),
            max_retries=max_retries,
        )
        self.keystring = keystring
        self.taxonomy_id = (
            int(taxonomy_id) if taxonomy_id is not None else _taxonomy_from_env()
        )
        self.shipping_profile_id = (
            int(shipping_profile_id)
            if shipping_profile_id is not None
            else (int(env_or("ETSY_SHIPPING_PROFILE_ID")) if env_or("ETSY_SHIPPING_PROFILE_ID") else None)
        )
        self._taxonomy_cache: Optional[List[Dict[str, Any]]] = None

    @classmethod
    def from_env(cls, **overrides: Any) -> "EtsyClient":
        """Build a client from environment variables (credentials never hardcoded)."""
        return cls(
            keystring=overrides.pop("keystring", env_or("ETSY_KEYSTRING")),
            refresh_token=overrides.pop("refresh_token", None),
            shop_id=overrides.pop("shop_id", None),
            shared_secret=overrides.pop("shared_secret", env_or("ETSY_SHARED_SECRET")),
            taxonomy_id=overrides.pop("taxonomy_id", None),
            shipping_profile_id=overrides.pop("shipping_profile_id", None),
            base_url=overrides.pop("base_url", env_or("ETSY_BASE_URL", DEFAULT_BASE_URL)),
            token_url=overrides.pop("token_url", env_or("ETSY_TOKEN_URL", DEFAULT_TOKEN_URL)),
            **overrides,
        )

    # ------------------------------------------------------------------
    # Shop + taxonomy
    # ------------------------------------------------------------------
    def verify_shop(self, shop_id: Optional[str] = None) -> Dict[str, Any]:
        """GET /v3/application/shops/{shop_id}; raises if the shop doesn't exist."""
        sid = shop_id or self.shop_id
        status, body = self.transport.request(
            "GET", f"/v3/application/shops/{sid}"
        )
        if not body:
            raise EtsyError(f"verify_shop: empty response for shop {sid}")
        log.info(
            "verified shop id=%s name=%r", sid, body.get("shop_name", body.get("name"))
        )
        return body

    def resolve_taxonomy_id(self, preferred: Optional[int] = None) -> int:
        """Pin the seller-taxonomy id for this product.

        Priority: explicit arg/env override > live by-name lookup > default.
        The live lookup fetches the full seller taxonomy, flattens it and
        picks the deepest node whose path matches the DIY/download keywords.
        """
        if preferred is not None:
            return int(preferred)
        if self.taxonomy_id is not None:
            return self.taxonomy_id
        nodes = self._fetch_taxonomy()
        found = _find_taxonomy_by_name(nodes)
        if found is not None:
            log.info("taxonomy matched by name: %s (id %s)", found["path"], found["id"])
            self.taxonomy_id = found["id"]
            return self.taxonomy_id
        log.warning(
            "no seller-taxonomy node matched the DIY keywords; using default "
            "taxonomy_id %s (override with ETSY_TAXONOMY_ID)", DEFAULT_TAXONOMY_ID,
        )
        return DEFAULT_TAXONOMY_ID

    def _fetch_taxonomy(self) -> List[Dict[str, Any]]:
        if self._taxonomy_cache is not None:
            return self._taxonomy_cache
        status, body = self.transport.request(
            "GET", "/v3/application/seller-taxonomy/nodes"
        )
        nodes = body.get("results") if isinstance(body, dict) else body
        if not isinstance(nodes, list):
            raise EtsyError("seller-taxonomy response has no 'results' list")
        self._taxonomy_cache = nodes
        return nodes

    # ------------------------------------------------------------------
    # Listings
    # ------------------------------------------------------------------
    def build_listing_form(
        self, recipe: Dict[str, Any], taxonomy_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """Build the createListingDraft form payload for a recipe (pure).

        Validates every constraint Etsy enforces (title <= 140, tags <= 13
        of <= 20 chars, price bound, enums) and raises ``EtsyValidationError``
        BEFORE anything is sent. This same function powers ``--dry-run`` so
        the printed payload is byte-for-byte what would be sent.

        ``taxonomy_id`` may be passed explicitly (dry-run / tests) to avoid
        the live seller-taxonomy lookup.
        """
        title = str(recipe["full_title"]).strip()
        if len(title) > 140:
            raise EtsyValidationError(
                f"Etsy title must be <= 140 chars (got {len(title)}); "
                f"recipe slug={recipe.get('slug')!r}"
            )
        tags = list(recipe["tags"])
        if not 1 <= len(tags) <= 13:
            raise EtsyValidationError(
                f"Etsy listings accept 1..13 tags (got {len(tags)})"
            )
        for tag in tags:
            if len(tag) > 20:
                raise EtsyValidationError(f"Etsy tag too long ({len(tag)} chars): {tag!r}")

        price = float(recipe["price_usd"])
        resolved_taxonomy = (
            int(taxonomy_id)
            if taxonomy_id is not None
            else self.resolve_taxonomy_id()
        )
        form: Dict[str, Any] = {
            "quantity": 999,                       # digital download: large stock
            "title": title,
            "description": str(recipe["description_long"]).strip(),
            "price": price,
            "who_made": "i_did",
            "when_made": "made_to_order",
            "taxonomy_id": resolved_taxonomy,
            "tags": [t for t in tags],
            "is_supply": False,
            "should_auto_renew": True,
            "is_taxable": False,
            "type": "download",
        }
        if self.shipping_profile_id is not None:
            form["shipping_profile_id"] = self.shipping_profile_id

        # hard guards against enum/spec drift
        if form["who_made"] not in ENUM_WHO_MADE:
            raise EtsyValidationError(f"who_made not in spec enum: {form['who_made']}")
        if form["when_made"] not in ENUM_WHEN_MADE:
            raise EtsyValidationError(f"when_made not in spec enum: {form['when_made']}")
        if form["type"] not in ENUM_TYPE:
            raise EtsyValidationError(f"type not in spec enum: {form['type']}")
        missing = CREATE_LISTING_REQUIRED - set(form)
        if missing:
            raise EtsyValidationError(f"createListingDraft missing required fields: {sorted(missing)}")
        return form

    def create_listing_draft(
        self, recipe: Dict[str, Any], taxonomy_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """POST /v3/application/shops/{shop_id}/listings (returns the listing)."""
        form = self.build_listing_form(recipe)
        if taxonomy_id is not None:
            form["taxonomy_id"] = int(taxonomy_id)
        status, body = self.transport.request(
            "POST", f"/v3/application/shops/{self.shop_id}/listings", form=form
        )
        lid = body.get("listing_id")
        if not lid:
            raise EtsyError(f"createListingDraft response missing listing_id: {body}")
        log.info("created draft listing id=%s (slug=%s)", lid, recipe.get("slug"))
        return body

    def upload_listing_image(
        self,
        listing_id: str,
        image_path: str,
        rank: int,
        alt_text: str = "",
    ) -> Dict[str, Any]:
        """POST .../listings/{listing_id}/images — one image, one call."""
        import os as _os

        if rank < 1:
            raise EtsyValidationError("image rank must be >= 1 (rank 1 = primary)")
        if not _os.path.isfile(image_path):
            raise EtsyValidationError(f"image file not found: {image_path}")
        with open(image_path, "rb") as fh:
            data = fh.read()
        files: List[Tuple[str, str, bytes, str]] = [
            ("image", _os.path.basename(image_path), data, "image/jpeg")
        ]
        form: Dict[str, Any] = {"rank": rank}
        if alt_text:
            if len(alt_text) > 500:
                raise EtsyValidationError("alt_text exceeds Etsy's 500-char limit")
            form["alt_text"] = alt_text
        status, body = self.transport.request(
            "POST",
            f"/v3/application/shops/{self.shop_id}/listings/{listing_id}/images",
            form=form, files=files,
        )
        img_id = body.get("listing_image_id")
        log.info("uploaded listing image rank=%d -> id=%s", rank, img_id)
        return body

    def upload_digital_file(
        self, listing_id: str, pdf_path: str, rank: int = 1
    ) -> Dict[str, Any]:
        """POST .../listings/{listing_id}/files — the digital download PDF."""
        import os as _os

        if not _os.path.isfile(pdf_path):
            raise EtsyValidationError(f"pdf file not found: {pdf_path}")
        with open(pdf_path, "rb") as fh:
            data = fh.read()
        name = _os.path.basename(pdf_path)
        files: List[Tuple[str, str, bytes, str]] = [
            ("file", name, data, "application/pdf")
        ]
        form: Dict[str, Any] = {"name": name, "rank": rank}
        status, body = self.transport.request(
            "POST",
            f"/v3/application/shops/{self.shop_id}/listings/{listing_id}/files",
            form=form, files=files,
        )
        log.info("uploaded digital file %s -> id=%s", name, body.get("listing_file_id"))
        return body

    def activate_listing(self, listing_id: str) -> Dict[str, Any]:
        """PATCH .../listings/{listing_id} with state=active."""
        form: Dict[str, Any] = {"state": "active"}
        if form["state"] not in ENUM_STATE:
            raise EtsyValidationError(f"state not in spec enum: {form['state']}")
        status, body = self.transport.request(
            "PATCH",
            f"/v3/application/shops/{self.shop_id}/listings/{listing_id}",
            form=form,
        )
        state = body.get("state")
        if state != "active":
            raise EtsyError(
                f"activateListing: expected state=active, got {state!r} ({body})"
            )
        log.info("activated listing id=%s", listing_id)
        return body

    def get_listing(self, listing_id: str) -> Dict[str, Any]:
        """GET /v3/application/listings/{listing_id} (public URL in 'url')."""
        status, body = self.transport.request(
            "GET", f"/v3/application/listings/{listing_id}"
        )
        return body

    # ------------------------------------------------------------------
    # Composite flow: activate (uploading the digital file first if Etsy
    # demands it) and fetch the public URL.
    # ------------------------------------------------------------------
    def publish_digital_listing(
        self, listing_id: str, pdf_path: str
    ) -> Dict[str, Any]:
        """Activate the listing and attach its digital download file.

        Order researched against the official spec: activation only requires
        an *image* (which the pipeline uploads before calling this); the
        file upload's spec does not constrain listing state, so we activate
        first and then attach the file. If Etsy rejects the activation
        because a digital file is missing, we upload the file first and
        retry the activation once.
        """
        try:
            self.activate_listing(listing_id)
        except EtsyError as exc:
            if exc.is_missing_digital_file:
                log.info("activation wants a digital file first; uploading file, then activating")
                self.upload_digital_file(listing_id, pdf_path)
                self.activate_listing(listing_id)
            else:
                raise
        # File may already be attached via the fallback; uploading again is
        # idempotent-ish (Etsy replaces by listing_file_id) but we skip it
        # when the fallback already did it.
        listing = self.get_listing(listing_id)
        if not listing.get("has_digital_download") and not _listing_has_file(listing):
            self.upload_digital_file(listing_id, pdf_path)
        return self.get_listing(listing_id)


def _listing_has_file(listing: Dict[str, Any]) -> bool:
    """Best-effort: does the listing already carry a digital file?

    Note: ``type == "download"`` marks the digital-download product type but
    does NOT mean a file is attached — Etsy only reports
    ``has_digital_download`` once ``uploadListingFile`` stored a file.
    """
    if listing.get("has_digital_download") is True:
        return True
    return bool(listing.get("digital_files") or listing.get("files"))


def _taxonomy_from_env() -> Optional[int]:
    val = env_or("ETSY_TAXONOMY_ID")
    if not val:
        return None
    try:
        return int(val)
    except ValueError as exc:
        raise EtsyConfigError(f"ETSY_TAXONOMY_ID must be an integer, got {val!r}") from exc


def _flatten_taxonomy(
    nodes: List[Dict[str, Any]], parents: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    parents = parents or []
    for node in nodes:
        name = str(node.get("name", ""))
        path = parents + [name]
        out.append(
            {
                "id": node.get("id"),
                "name": name,
                "path": path,
                "level": len(parents),
                "full_path": " > ".join(path),
            }
        )
        children = node.get("children") or []
        if children:
            out.extend(_flatten_taxonomy(children, parents=path))
    return out


def _find_taxonomy_by_name(nodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Deepest node whose full path matches the DIY/download keywords."""
    flat = _flatten_taxonomy(nodes)
    scored: List[Tuple[int, int, Dict[str, Any]]] = []
    for item in flat:
        hay = item["full_path"].lower()
        score = 0
        for keyword, weight in TAXONOMY_KEYWORDS:
            if keyword in hay:
                score += weight
        if score:
            scored.append((item["level"], score, item))
    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return scored[0][2]