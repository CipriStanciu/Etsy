#!/usr/bin/env python3
"""Local mock Etsy Open API v3 server for verification (stdlib only).

Serves realistic JSON for every endpoint the Fragrance Bot Etsy client uses,
records every request (monotonic timestamp + method + path + content-type)
so tests can prove rate limiting and retry behaviour, and supports fault
injection for 429/500 scenarios.

Endpoints
---------
    POST /v3/public/oauth/token                        refresh-token grant
    GET  /v3/application/shops/{shop_id}               getShop
    GET  /v3/application/seller-taxonomy/nodes         getSellerTaxonomyNodes
    POST /v3/application/shops/{shop_id}/listings      createListingDraft (201)
    POST /v3/application/shops/{shop_id}/listings/{id}/images   uploadListingImage (201)
    POST /v3/application/shops/{shop_id}/listings/{id}/files    uploadListingFile (201)
    PATCH /v3/application/shops/{shop_id}/listings/{id}         updateListing
    GET  /v3/application/listings/{listing_id}         getListing
    POST /__config                                     fault injection
    GET  /__log                                       request log (JSON)
    GET  /__state                                    server state (JSON)

Fault injection — POST /__config with a JSON body:
    {"faults": {"<endpoint_key>": [status, times]}}
endpoint keys: "createListing", "images", "files", "activate", "listing",
"shop", "taxonomy". Each fault fires `times` times then clears.
Also: {"activate_requires_file": true} makes the mock reject activation
until a digital file exists (404 w/ a message mentioning "digital file"),
exercising the pipeline's fallback.

Usage
-----
    python3 scripts/mock_etsy.py --port 8765 --state-dir /tmp/mock-etsy
"""
from __future__ import annotations

import argparse
import cgi
import io
import json
import re
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

SHOP_ID = "12345"

# A realistic slice of the seller taxonomy (shape per the OpenAPI schema:
# id, level, name, parent_id, children, full_path_taxonomy_ids).
TAXONOMY = [
    {
        "id": 563, "level": 0, "name": "Craft Supplies & Tools",
        "parent_id": None, "full_path_taxonomy_ids": [563],
        "children": [
            {
                "id": 6642, "level": 1, "name": "DIY Projects & Crafts",
                "parent_id": 563, "full_path_taxonomy_ids": [563, 6642],
                "children": [
                    {
                        "id": 7587, "level": 2,
                        "name": "Home & Hobby Projects",
                        "parent_id": 6642,
                        "full_path_taxonomy_ids": [563, 6642, 7587],
                        "children": [
                            {
                                "id": 24246, "level": 3,
                                "name": "Candle Making Kits",
                                "parent_id": 7587,
                                "full_path_taxonomy_ids": [563, 6642, 7587, 24246],
                                "children": [],
                            },
                            {
                                "id": 24247, "level": 3,
                                "name": "Soap & Bath Recipes",
                                "parent_id": 7587,
                                "full_path_taxonomy_ids": [563, 6642, 7587, 24247],
                                "children": [],
                            },
                        ],
                    },
                    {
                        "id": 7588, "level": 2,
                        "name": "Patterns & How To",
                        "parent_id": 6642,
                        "full_path_taxonomy_ids": [563, 6642, 7588],
                        "children": [],
                    },
                ],
            }
        ],
    }
]


class MockEtsyState:
    """Shared state: listings, uploads, request log, fault config."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.lock = None  # single-threaded handler usage below
        self.listings: Dict[str, Dict[str, Any]] = {}
        self.images: Dict[str, List[Dict[str, Any]]] = {}
        self.files: Dict[str, List[Dict[str, Any]]] = {}
        self.next_id = 9000001
        self.refresh_tokens = {"seed-refresh-token": "rot-token-1"}
        self.token_counter = 0
        self.requests: List[Dict[str, Any]] = []
        self.faults: Dict[str, List[int]] = {}
        self.activate_requires_file = False
        self._log_path = self.state_dir / "requests.jsonl"

        # recover persisted state (allows restarting the mock between tests)
        if self._log_path.exists():
            try:
                for line in self._log_path.read_text().splitlines():
                    if line.strip():
                        self.requests.append(json.loads(line))
            except (ValueError, OSError):
                pass

    def log(self, method: str, path: str, ctype: str = "", note: str = "") -> None:
        entry = {
            "ts": time.monotonic(), "monotonic": time.monotonic(),
            "method": method, "path": path, "content_type": ctype, "note": note,
        }
        self.requests.append(entry)
        try:
            with self._log_path.open("a") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    def new_listing_id(self) -> str:
        self.next_id += 1
        return str(self.next_id)

    def fault_for(self, key: str) -> Optional[int]:
        """Pop one fault status for an endpoint, or None."""
        queue = self.faults.get(key)
        if not queue:
            return None
        status = queue.pop(0)
        if not queue:
            self.faults.pop(key, None)
        return status


STATE: Optional[MockEtsyState] = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep verification output clean
        pass

    # -- helpers ------------------------------------------------------------
    def _json(self, status: int, obj: Any) -> None:
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, status: int, code: str, msg: str) -> None:
        raw = json.dumps({"error": code, "error_description": msg}).encode("utf-8")
        self.send_response(status)
        if status == 429:
            # realistic: Etsy tells clients how long to wait
            self.send_header("Retry-After", "1")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            length = 0
        return self.rfile.read(length) if length else b""

    def _parse_multipart(self, body: bytes) -> Dict[str, Any]:
        """Parse a multipart body manually (stdlib; cgi is unreliable here).

        File parts become {'name','filename','data','size'}; text fields are
        decoded strings.
        """
        ctype = self.headers.get("Content-Type", "")
        m = re.search(r'boundary="?([^";]+)"?', ctype)
        if not m:
            return {}
        boundary = m.group(1)
        out: Dict[str, Any] = {}
        for part in body.split(f"--{boundary}".encode()):
            if part in (b"", b"\r\n", b"--", b"--\r\n"):
                continue
            if part.startswith(b"--"):
                part = part[2:]
            if b"\r\n\r\n" not in part:
                continue
            head, content = part.split(b"\r\n\r\n", 1)
            if content.endswith(b"\r\n"):
                content = content[:-2]
            head_text = head.decode("utf-8", errors="replace")
            name_m = re.search(r'name="([^"]+)"', head_text)
            if not name_m:
                continue
            name = name_m.group(1)
            file_m = re.search(r'filename="([^"]*)"', head_text)
            if name in ("image", "file") and file_m and file_m.group(1):
                out[name] = {
                    "data": content,
                    "filename": file_m.group(1),
                    "size": len(content),
                }
            else:
                out[name] = content.decode("utf-8", errors="replace")
        return out

    # -- routing ------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        self._route("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._route("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self._route("PATCH")

    def _route(self, method: str) -> None:
        state = STATE
        assert state is not None
        path = self.path.split("?")[0]

        # control endpoints
        if path == "/__config" and method == "POST":
            cfg = json.loads(self._read_body() or b"{}")
            for key, spec in cfg.get("faults", {}).items():
                status, times = spec[0], spec[1]
                state.faults[key] = [status] * times
            if "activate_requires_file" in cfg:
                state.activate_requires_file = bool(cfg["activate_requires_file"])
            state.log(method, path, note="config")
            self._json(200, {"ok": True})
            return
        if path == "/__log":
            self._json(200, state.requests)
            return
        if path == "/__state":
            self._json(200, {
                "listings": state.listings,
                "images": state.images,
                "files": state.files,
                "faults": state.faults,
                "activate_requires_file": state.activate_requires_file,
            })
            return

        state.log(method, path, ctype=self.headers.get("Content-Type", ""))
        try:
            self._dispatch(method, path)
        except BrokenPipeError:
            pass

    def _dispatch(self, method: str, path: str) -> None:
        state = STATE
        assert state is not None

        # --- OAuth token ---------------------------------------------------
        if path == "/v3/public/oauth/token" and method == "POST":
            form = self._read_body().decode("utf-8", errors="replace")
            params = dict(re.findall(r"([^&=]+)=([^&]*)", form))
            if params.get("grant_type") == "refresh_token":
                rt = params.get("refresh_token", "")
                if rt not in state.refresh_tokens and rt != "seed-refresh-token":
                    self._error(400, "invalid_grant", "refresh_token is invalid")
                    return
                state.token_counter += 1
                new_access = f"1.{uuid.uuid4().hex}"
                new_refresh = f"rot.{uuid.uuid4().hex}"
                state.refresh_tokens[rt] = new_refresh  # rotation: old -> new
                self._json(200, {
                    "access_token": new_access,
                    "token_type": "Bearer",
                    "refresh_token": new_refresh,
                    "expires_in": 3600,
                    "scope": "listings_r listings_w transactions_r shops_r",
                })
                return
            self._error(400, "unsupported_grant_type", "only refresh_token is supported")
            return

        # --- shop ----------------------------------------------------------
        m = re.fullmatch(r"/v3/application/shops/(\d+)", path)
        if m and method == "GET":
            sid = m.group(1)
            if sid != SHOP_ID:
                self._error(404, "not_found", f"shop {sid} not found")
                return
            fault = state.fault_for("shop")
            if fault:
                self._error(fault, "fault", "injected fault")
                return
            self._json(200, {
                "shop_id": int(sid), "shop_name": "Fragrance Bot Shop",
                "user_id": 12345678, "active_listing_count": 1,
            })
            return

        # --- taxonomy ------------------------------------------------------
        if path == "/v3/application/seller-taxonomy/nodes" and method == "GET":
            fault = state.fault_for("taxonomy")
            if fault:
                self._error(fault, "fault", "injected fault")
                return
            self._json(200, {"count": len(TAXONOMY), "results": TAXONOMY})
            return

        # --- createListingDraft -------------------------------------------
        m = re.fullmatch(r"/v3/application/shops/(\d+)/listings", path)
        if m and method == "POST":
            fault = state.fault_for("createListing")
            if fault:
                self._error(fault, "fault", "injected fault")
                return
            form = self._read_body().decode("utf-8", errors="replace")
            params = dict(re.findall(r"([^&=]+)=([^&]*)", form))
            if not all(k in params for k in
                       ("quantity", "title", "description", "price",
                        "who_made", "when_made", "taxonomy_id")):
                self._error(400, "bad_request",
                            "missing required createListingDraft params")
                return
            lid = state.new_listing_id()
            qty = int(params.get("quantity", 999))
            listing: Dict[str, Any] = {
                "listing_id": int(lid),
                "title": params["title"],
                "price": {"amount": int(float(params["price"]) * 100),
                          "divisor": 100, "currency_code": "USD"},
                "description": params.get("description", ""),
                "quantity": qty,
                "state": "draft",
                "who_made": params.get("who_made"),
                "when_made": params.get("when_made"),
                "taxonomy_id": int(params.get("taxonomy_id")),
                "type": params.get("type", "physical"),
                "tags": [t for t in params.get("tags", "").split(",") if t],
                "shop_id": int(m.group(1)),
                "url": f"https://www.etsy.com/listing/{lid}",
                "is_digital": params.get("type") == "download",
                # A digital listing only HAS a file once uploadListingFile runs
                "has_digital_download": False,
            }
            state.listings[lid] = listing
            state.images[lid] = []
            state.files[lid] = []
            self._json(201, listing)
            return

        # --- images --------------------------------------------------------
        m = re.fullmatch(r"/v3/application/shops/(\d+)/listings/(\d+)/images", path)
        if m and method == "POST":
            lid = m.group(2)
            fault = state.fault_for("images")
            if fault:
                self._error(fault, "fault", "injected fault")
                return
            if lid not in state.listings:
                self._error(404, "not_found", f"listing {lid} not found")
                return
            parts = self._parse_multipart(self._read_body())
            rank = int(parts.get("rank", 1))
            img_id = int(f"{lid[-4:]}{rank:02d}{len(state.images[lid])}")
            state.images[lid].append({
                "listing_image_id": img_id, "rank": rank,
                "alt_text": parts.get("alt_text", ""),
                "size_bytes": parts.get("image", {}).get("size", 0),
            })
            state.listings[lid]["num_images"] = len(state.images[lid])
            self._json(201, {
                "listing_image_id": img_id,
                "listing_id": int(lid),
                "rank": rank,
                "alt_text": parts.get("alt_text", ""),
                "url_75x75": f"https://mock.etsy.local/img/{img_id}/75",
                "url_fullxfull": f"https://mock.etsy.local/img/{img_id}/full",
                "is_watermarked": False,
            })
            return

        # --- digital file --------------------------------------------------
        m = re.fullmatch(r"/v3/application/shops/(\d+)/listings/(\d+)/files", path)
        if m and method == "POST":
            lid = m.group(2)
            fault = state.fault_for("files")
            if fault:
                self._error(fault, "fault", "injected fault")
                return
            if lid not in state.listings:
                self._error(404, "not_found", f"listing {lid} not found")
                return
            parts = self._parse_multipart(self._read_body())
            file_part = parts.get("file", {})
            name = parts.get("name") or file_part.get("filename", "recipe.pdf")
            f_id = int(f"{lid[-4:]}{len(state.files[lid]) + 1:02d}")
            state.files[lid].append({
                "listing_file_id": f_id, "name": name,
                "size_bytes": file_part.get("size", 0),
            })
            state.listings[lid]["has_digital_download"] = True
            state.listings[lid]["type"] = "download"
            self._json(201, {
                "listing_file_id": f_id, "listing_id": int(lid),
                "name": name, "rank": int(parts.get("rank", 1)),
                "size_bytes": file_part.get("size", 0),
                "downloadable_url": f"https://mock.etsy.local/dl/{f_id}",
            })
            return

        # --- updateListing (activation) ------------------------------------
        m = re.fullmatch(r"/v3/application/shops/(\d+)/listings/(\d+)", path)
        if m and method == "PATCH":
            lid = m.group(2)
            fault = state.fault_for("activate")
            if fault:
                self._error(fault, "fault", "injected fault")
                return
            if lid not in state.listings:
                self._error(404, "not_found", f"listing {lid} not found")
                return
            form = self._read_body().decode("utf-8", errors="replace")
            params = dict(re.findall(r"([^&=]+)=([^&]*)", form))
            new_state = params.get("state", state.listings[lid]["state"])
            if new_state == "active":
                # simulate Etsy's guard: a digital listing needs a file
                if state.activate_requires_file and not state.files[lid]:
                    self._error(
                        404, "missing_digital_file",
                        "Listing must have an attached digital file before it "
                        "can be activated. Upload a digital file and retry.",
                    )
                    return
                if not state.images[lid]:
                    self._error(
                        400, "missing_image",
                        "Setting a draft listing to active requires an image.",
                    )
                    return
            state.listings[lid]["state"] = new_state
            self._json(200, state.listings[lid])
            return

        # --- getListing ----------------------------------------------------
        m = re.fullmatch(r"/v3/application/listings/(\d+)", path)
        if m and method == "GET":
            lid = m.group(1)
            fault = state.fault_for("listing")
            if fault:
                self._error(fault, "fault", "injected fault")
                return
            if lid not in state.listings:
                self._error(404, "not_found", f"listing {lid} not found")
                return
            self._json(200, state.listings[lid])
            return

        self._error(404, "not_found", f"no route: {method} {path}")


def main(argv: Optional[List[str]] = None) -> int:
    global STATE
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--state-dir", default="/tmp/mock-etsy")
    args = ap.parse_args(argv)

    STATE = MockEtsyState(Path(args.state_dir))
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"mock Etsy API listening on http://{args.host}:{args.port}", flush=True)
    print(f"state dir: {args.state_dir}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nmock stopped", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())