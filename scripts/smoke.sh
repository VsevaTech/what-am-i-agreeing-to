#!/usr/bin/env bash
# End-to-end smoke test against a running instance (used by CI against the Docker image).
# Works without an AI key: analysis degrades gracefully, the result is still stored and deletable.
set -euo pipefail
BASE="${1:-http://127.0.0.1:8000}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
fail() { echo "SMOKE FAIL: $*" >&2; exit 1; }

# 1. Analyze a demo PDF (full page, no htmx).
curl -fsS -D "$tmp/h" -o "$tmp/r.html" -F "file=@$ROOT/examples/simple-subscription.pdf" "$BASE/analyze"
grep -qi '^cache-control: no-store, private' "$tmp/h" || fail "/analyze missing Cache-Control: no-store"
token="$(grep -o 'action="/results/[^/"]*/delete"' "$tmp/r.html" | head -1 | sed 's#action="/results/##; s#/delete"##')"
[ -n "$token" ] || fail "no delete form / token in result page"
echo "token acquired"

# 2. Result URL is reachable and not cacheable.
curl -fsS -D "$tmp/h2" -o /dev/null "$BASE/results/$token"
grep -qi '^cache-control: no-store, private' "$tmp/h2" || fail "/results missing Cache-Control"

# 3. Delete, then everything about the analysis is gone.
[ "$(code -X POST "$BASE/results/$token/delete")" = "303" ] || fail "delete did not redirect"
[ "$(code "$BASE/results/$token")" = "404" ] || fail "result still reachable after delete"
[ "$(code "$BASE/source/$token/payment")" = "404" ] || fail "source still reachable after delete"
[ "$(code -X POST "$BASE/results/$token/delete")" = "303" ] || fail "second delete was not safe"
[ "$(code "$BASE/results/$token/delete")" = "405" ] || fail "GET must not delete"

# 4. Static assets stay cacheable (no blanket no-store).
curl -fsS -D "$tmp/h3" -o /dev/null "$BASE/static/style.css"
if grep -qi '^cache-control: no-store' "$tmp/h3"; then fail "static assets must not be no-store"; fi

echo "SMOKE OK"
