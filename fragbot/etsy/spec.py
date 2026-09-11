"""Machine-readable parameter maps extracted from the OFFICIAL Etsy OpenAPI.

Source: the OpenAPI v3 document the Etsy reference app itself loads
(``https://www.etsy.com/openapi/generated/oas/3.0.0.json``, fetched
2026-09-11). The verify_etsy.py harness lint-checks every payload the client
builds against these sets, so nothing drifts from Etsy's real API surface.

IMPORTANT SPEC FINDINGS (differences from the owner's draft field names):
* ``createListingDraft`` (POST /v3/application/shops/{shop_id}/listings) has
  **no ``is_digital`` parameter** — the digital nature comes from the
  ``type`` enum (``physical | download | both``) plus actually uploading a
  digital file. We pass ``type=download`` AND upload the PDF file.
* ``tags`` is a single form field holding a comma-separated list.
* ``uploadListingImage``/``uploadListingFile`` are multipart; the file goes
  in the ``image`` / ``file`` field respectively, ``rank`` is an integer.
* Listing activation is done via ``updateListing``
  (PATCH .../listings/{listing_id}) with ``state=active``.
* ``getListing`` carries no body; the public URL comes back in the
  response's ``url`` field.
* Also note the Etsy docs: "Setting a draft listing to active ... requires
  that the listing have an image set" — so images MUST be uploaded before
  activation (the pipeline already does that).
"""
from __future__ import annotations

# POST /v3/application/shops/{shop_id}/listings — createListingDraft form fields
CREATE_LISTING_FIELDS = {
    "quantity", "title", "description", "price", "who_made", "when_made",
    "taxonomy_id", "shipping_profile_id", "return_policy_id", "materials",
    "shop_section_id", "processing_min", "processing_max",
    "readiness_state_id", "tags", "styles", "item_weight", "item_length",
    "item_width", "item_height", "item_weight_unit", "item_dimensions_unit",
    "production_partner_ids", "image_ids", "is_supply", "is_customizable",
    "should_auto_renew", "is_taxable", "type",
}

# POST .../listings/{listing_id}/images — uploadListingImage multipart fields
UPLOAD_IMAGE_FIELDS = {
    "image", "listing_image_id", "rank", "overwrite", "is_watermarked",
    "alt_text",
}

# POST .../listings/{listing_id}/files — uploadListingFile multipart fields
UPLOAD_FILE_FIELDS = {"listing_file_id", "file", "name", "rank"}

# PATCH .../listings/{listing_id} — updateListing form fields (we only use state)
UPDATE_LISTING_FIELDS = {
    "image_ids", "title", "description", "materials", "should_auto_renew",
    "shipping_profile_id", "return_policy_id", "shop_section_id",
    "item_weight", "item_length", "item_width", "item_height",
    "item_weight_unit", "item_dimensions_unit", "is_taxable", "taxonomy_id",
    "tags", "who_made", "when_made", "featured_rank", "state", "is_supply",
    "production_partner_ids", "type",
}

# GET /v3/application/listings/{listing_id} — getListing query params
GET_LISTING_QUERY = {"includes", "language", "allow_suggested_title"}

# GET /v3/application/shops — findAllShops query params
FIND_SHOPS_QUERY = {"shop_name", "limit", "offset"}

# Role of each field in the payload we actually send.
CREATE_LISTING_REQUIRED = {
    "quantity", "title", "description", "price", "who_made", "when_made",
    "taxonomy_id",
}
ENUM_WHO_MADE = {"i_did", "someone_else", "collective"}
ENUM_WHEN_MADE = {
    "made_to_order", "2020_2026", "2010_2019", "2007_2009", "before_2007",
    "2000_2006", "1990s", "1980s", "1970s", "1960s", "1950s", "1940s",
    "1930s", "1920s", "1910s", "1900s", "1800s", "1700s", "before_1700",
}
ENUM_TYPE = {"physical", "download", "both"}
ENUM_STATE = {"active", "inactive"}

# Endpoint -> allowed request-body fields, used by verify_etsy.py check 6.
SPEC_BODY_FIELDS = {
    "createListingDraft": CREATE_LISTING_FIELDS,
    "uploadListingImage": UPLOAD_IMAGE_FIELDS,
    "uploadListingFile": UPLOAD_FILE_FIELDS,
    "updateListing": UPDATE_LISTING_FIELDS,
}