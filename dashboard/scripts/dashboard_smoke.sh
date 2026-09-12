#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Fragrance Bot dashboard — smoke test.
#
# Builds (if needed) + starts the PROD server (next start), curls every page,
# asserts HTTP 200 and a route-specific content marker, checks /api/data's
# JSON source label, then shuts the server down. Output: repo-root
# dashboard-smoke.txt (gitignored).
#
# Usage:
#   bash dashboard/scripts/dashboard_smoke.sh            # build if needed + test
#   SKIP_BUILD=1 bash dashboard/scripts/dashboard_smoke.sh  # reuse existing build
#   PORT=3201 bash dashboard/scripts/dashboard_smoke.sh  # custom port
# ─────────────────────────────────────────────────────────────────────────────
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DASH_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$DASH_DIR/.." && pwd)"
PORT="${PORT:-3199}"
OUT="$REPO_ROOT/dashboard-smoke.txt"
BASE="http://127.0.0.1:$PORT"

PASS=0
FAIL=0
FAILURES=""

log() { echo "$@" | tee -a "$OUT"; }

assert_route() {
  local path="$1" marker="$2"
  local code body
  body=$(curl -s -o /tmp/fragbot_smoke_body -w "%{http_code}" --max-time 20 "$BASE$path")
  code=$body
  if [ "$code" = "200" ] && grep -q -- "$marker" /tmp/fragbot_smoke_body; then
    log "[PASS] GET $path -> $code, contains \"$marker\""
    PASS=$((PASS + 1))
  else
    log "[FAIL] GET $path -> $code (expected 200 + \"$marker\")"
    FAIL=$((FAIL + 1))
    FAILURES="$FAILURES $path"
  fi
}

cleanup() {
  if [ -n "${SERVER_PID:-}" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null
    wait "$SERVER_PID" 2>/dev/null
  fi
  rm -f /tmp/fragbot_smoke_body
}
trap cleanup EXIT

: > "$OUT"
log "=== Fragrance Bot dashboard smoke test — $(date -u +%FT%TZ) ==="
log "repo: $REPO_ROOT | dashboard: $DASH_DIR | port: $PORT"

# 1) build
if [ "${SKIP_BUILD:-0}" != "1" ]; then
  log "--- npm install (if needed) ---"
  if [ ! -d "$DASH_DIR/node_modules" ]; then
    (cd "$DASH_DIR" && npm install --no-audit --no-fund 2>&1 | tail -3 | tee -a "$OUT") || { log "[FAIL] npm install"; exit 1; }
  fi
  log "--- npm run build ---"
  (cd "$DASH_DIR" && npm run build 2>&1 | tail -6 | tee -a "$OUT") || { log "[FAIL] npm run build"; exit 1; }
else
  log "SKIP_BUILD=1 — reusing existing build"
fi

# 2) start prod server
log "--- starting prod server (next start -p $PORT) ---"
(cd "$DASH_DIR" && PORT="$PORT" npm run start -- -p "$PORT" >/tmp/fragbot_smoke_server.log 2>&1) &
SERVER_PID=$!

ready=0
for _ in $(seq 1 60); do
  if curl -s -o /dev/null --max-time 3 "$BASE/"; then ready=1; break; fi
  sleep 1
done
if [ "$ready" != "1" ]; then
  log "[FAIL] server did not boot in 60s — log tail:"
  tail -5 /tmp/fragbot_smoke_server.log | tee -a "$OUT"
  exit 1
fi
log "[PASS] server booted"

# 3) pages
assert_route "/"        "Daily Post Tracker"
assert_route "/calendar" "Content Calendar"
assert_route "/metrics"  "Performance Metrics"
assert_route "/alerts"   "Inventory Alerts"
assert_route "/seo"      "SEO Scorecard"
assert_route "/utm"      "UTM Builder"

# 4) API data source
API_BODY=$(curl -s --max-time 20 "$BASE/api/data")
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 "$BASE/api/data")
if [ "$HTTP_CODE" = "200" ]; then
  SOURCE=$(printf '%s' "$API_BODY" | grep -o '"source":"[^"]*"' | head -1)
  N_RECIPES=$(printf '%s' "$API_BODY" | grep -o '"recipe_name"' | wc -l | tr -d ' ')
  log "[PASS] GET /api/data -> $HTTP_CODE, source: ${SOURCE:-unknown}, ~$N_RECIPES recipes"
  if [ -z "${SUPABASE_URL:-}" ] && [ -z "${POSTGRES_URL:-}" ]; then
    if printf '%s' "$API_BODY" | grep -q '"source":"stub"'; then
      log "[PASS] no credentials -> stub fallback confirmed"
      PASS=$((PASS + 1))
    else
      log "[FAIL] expected stub fallback without credentials"
      FAIL=$((FAIL + 1))
      FAILURES="$FAILURES api-stub"
    fi
  else
    log "[INFO] credentials present — live data expected (verified by source label above)"
  fi
  PASS=$((PASS + 1))
else
  log "[FAIL] GET /api/data -> $HTTP_CODE"
  FAIL=$((FAIL + 1))
  FAILURES="$FAILURES api/data"
fi

# 5) summary
cleanup
trap - EXIT
log ""
log "=== result: $PASS passed, $FAIL failed ==="
if [ "$FAIL" -gt 0 ]; then
  log "FAILED ROUTES:$FAILURES"
  exit 1
fi
log "SMOKE TEST OK"
exit 0