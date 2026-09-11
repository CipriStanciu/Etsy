#!/usr/bin/env python3
"""One-time Etsy OAuth 2.0 authorization helper (PKCE).

The owner authorizes the Fragrance Bot app ONCE; this script prints the
resulting **refresh token** which the owner saves as the ``ETSY_REFRESH_TOKEN``
secret (see README). The pipeline then refreshes access tokens automatically
and persists Etsy's rotating refresh token itself.

How it works
------------
1. Starts a tiny local HTTP server on http://localhost:8080/callback
2. Builds the Etsy authorize URL with PKCE (S256) and the scopes the
   pipeline needs: ``listings_r listings_w transactions_r``
   (plus ``shops_r`` so shop verification can read shop details).
3. Prints the URL — owner opens it, logs into Etsy as the shop owner and
   approves the app.
4. Etsy redirects to the local callback with a ``code``; the script
   exchanges it at the token endpoint and prints the refresh token.

Requirements
------------
* ETSY_KEYSTRING set (your App API Key keystring from
  https://www.etsy.com/developers/your-apps)
* The redirect URI http://localhost:8080/callback registered in the app's
  "Redirect URIs" (Etsy requires exact matches; localhost is allowed).

Usage
-----
    export ETSY_KEYSTRING=<keystring>
    python3 scripts/etsy_oauth.py
    # ...open the printed URL, approve, come back...
    # copy the printed refresh token into ETSY_REFRESH_TOKEN

Optional: --port, --host, --token-url (test), --only-url (just print the
authorize URL without starting the callback server).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import logging
import os
import secrets
import sys
import threading
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCOPES = "listings_r listings_w transactions_r shops_r"
TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
AUTHORIZE_URL = "https://www.etsy.com/oauth/connect"


def pkce_pair() -> tuple:
    """Return (code_verifier, code_challenge)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def build_authorize_url(client_id: str, redirect_uri: str, scope: str,
                        state: str, code_challenge: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(client_id: str, redirect_uri: str, code: str,
                  code_verifier: str, token_url: str) -> dict:
    form = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code": code,
        "code_verifier": code_verifier,
    }).encode("utf-8")
    req = urllib.request.Request(token_url, data=form, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Serves /callback, captures ?code=..., replies with a tiny page."""

    captured: dict = {}
    server_ref = None

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        qs = urllib.parse.parse_qs(parsed.query)
        self.captured.update(qs)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if "code" in qs:
            body = (
                "<html><body><h2>Authorization received</h2>"
                "<p>You can close this tab and return to the terminal.</p></body></html>"
            )
        else:
            body = (
                "<html><body><h2>Authorization failed</h2>"
                f"<p>{parsed.query[:400]}</p></body></html>"
            )
        self.wfile.write(body.encode("utf-8"))
        # Stop the server after the callback lands.
        if self.server_ref is not None:
            threading.Thread(
                target=self.server_ref.shutdown, daemon=True
            ).start()

    def log_message(self, *args):  # quieter logging
        pass


def wait_for_code(host: str, port: int) -> tuple:
    handler = CallbackHandler
    handler.captured = {}
    httpd = http.server.ThreadingHTTPServer((host, port), handler)
    handler.server_ref = httpd
    print(f"  callback server listening on http://{host}:{port}/callback ...")
    httpd.serve_forever(poll_interval=0.2)
    qs = handler.captured
    if "code" not in qs:
        raise RuntimeError(f"no code in callback; query was {qs}")
    if "state" in qs:
        return qs["code"][0], qs["state"][0]
    return qs["code"][0], None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--token-url", default=TOKEN_URL)
    ap.add_argument("--only-url", action="store_true",
                    help="just print the authorize URL, don't run the callback server")
    args = ap.parse_args()

    keystring = os.environ.get("ETSY_KEYSTRING", "").strip()
    if not keystring:
        print("ERROR: ETSY_KEYSTRING is not set.", file=sys.stderr)
        print("  It's the App API Key keystring from "
              "https://www.etsy.com/developers/your-apps", file=sys.stderr)
        return 2

    redirect_uri = f"http://{args.host}:{args.port}/callback"
    state = secrets.token_urlsafe(24)
    verifier, challenge = pkce_pair()
    url = build_authorize_url(
        keystring, redirect_uri, SCOPES, state, challenge
    )

    print("=" * 72)
    print("One-time Etsy authorization for Fragrance Bot")
    print("=" * 72)
    print(f"Scopes requested : {SCOPES}")
    print(f"Redirect URI     : {redirect_uri}  (must be registered in your Etsy app!)")
    print()
    print("Open this URL, log in as your shop's Etsy account, approve the app,")
    print("then come back here:")
    print()
    print(f"  {url}")
    print()

    if args.only_url:
        return 0

    try:
        code, returned_state = wait_for_code(args.host, args.port)
    except KeyboardInterrupt:
        print("\nAborted by the user.", file=sys.stderr)
        return 130
    except OSError as exc:
        print(f"ERROR: could not start the callback server: {exc}", file=sys.stderr)
        return 2

    if returned_state is not None and returned_state != state:
        print("ERROR: state mismatch — possible CSRF; aborting.", file=sys.stderr)
        return 2

    print("Authorization code received — exchanging for tokens ...")
    try:
        tokens = exchange_code(
            keystring, redirect_uri, code, verifier, args.token_url
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        print(f"ERROR: token exchange failed (HTTP {exc.code}): {detail}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR: token exchange network error: {exc}", file=sys.stderr)
        return 1

    access = tokens.get("access_token", "")
    refresh = tokens.get("refresh_token", "")
    if not refresh:
        print(f"ERROR: no refresh_token in response: {tokens}", file=sys.stderr)
        return 1

    print()
    print("=" * 72)
    print("SUCCESS — save these values somewhere SAFE (they grant access to")
    print("your Etsy shop; never commit them or paste them in public chats).")
    print("=" * 72)
    print()
    print("REFRESH TOKEN (save as the ETSY_REFRESH_TOKEN secret):")
    print(f"  {refresh}")
    print()
    print(f"ACCESS TOKEN (not needed by the pipeline; valid ~1 hour):")
    print(f"  {access[:40]}...")
    print()
    print("Scope granted:", tokens.get("scope"))
    print()
    print("Next steps:")
    print("  1. Store the REFRESH TOKEN in GitHub Secrets as "
          "ETSY_REFRESH_TOKEN (and ETSY_KEYSTRING, ETSY_SHOP_ID).")
    print("  2. The pipeline refreshes + rotates it automatically; rotated")
    print("     tokens are persisted in the etsy_tokens table (Supabase).")
    print("  3. Keep the token secret: anyone holding it controls the shop.")
    return 0


if __name__ == "__main__":
    sys.exit(main())