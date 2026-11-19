#!/usr/bin/env bash
# Dynamic security scan of a STAGING server with OWASP ZAP (in Docker).
# Never point this at production: the active scan sends attack payloads
# and creates junk records.
#
# Needs: docker, curl, jq; a staging shop with a throwaway owner account.
#
#   STAGING_URL=https://staging.example.com \
#   SCAN_USER=0700000000 SCAN_PASSWORD='...' \
#   ./deploy/security/zap-scan.sh
#
# Writes zap-baseline.html (passive scan of the web app) and
# zap-api-N.html (authenticated active scan of each API endpoint) to ./zap-reports/.
# Then work through CHECKLIST.md next to this script by hand.
set -euo pipefail

: "${STAGING_URL:?set STAGING_URL, e.g. https://staging.example.com}"
: "${SCAN_USER:?set SCAN_USER (a throwaway staging owner)}"
: "${SCAN_PASSWORD:?set SCAN_PASSWORD}"
ZAP_IMAGE=${ZAP_IMAGE:-ghcr.io/zaproxy/zaproxy:stable}
OUT=${OUT:-$PWD/zap-reports}
mkdir -p "$OUT"

token=$(curl -fsS -X POST "$STAGING_URL/api/auth-token/" \
  -H 'Content-Type: application/json' \
  -d "$(jq -n --arg u "$SCAN_USER" --arg p "$SCAN_PASSWORD" '{username: $u, password: $p}')" | jq -r .token)
[ -n "$token" ] && [ "$token" != null ] || { echo 'Sign-in failed: check SCAN_USER / SCAN_PASSWORD' >&2; exit 1; }

# The API endpoints to start from: every list endpoint a signed-in owner sees.
cat > "$OUT/seeds.txt" <<EOF
$STAGING_URL/api/core/users/me/
$STAGING_URL/api/core/users/
$STAGING_URL/api/core/stores/
$STAGING_URL/api/core/store-roles/
$STAGING_URL/api/catalog/products/
$STAGING_URL/api/inventory/batches/
$STAGING_URL/api/pos/sales/
$STAGING_URL/api/pos/shifts/
$STAGING_URL/api/credit/customers/
$STAGING_URL/api/reports/dashboard/
$STAGING_URL/api/reports/sales/
$STAGING_URL/api/analytics/dimensions/
$STAGING_URL/api/audit/events/
$STAGING_URL/api/imports/
EOF

echo '== Passive scan of the web app (no attacks)'
docker run --rm -v "$OUT:/zap/wrk:rw" "$ZAP_IMAGE" \
  zap-baseline.py -t "$STAGING_URL" -r zap-baseline.html -I || true

echo '== Authenticated active scan of each API endpoint'
# The replacer adds the owner's token to every request ZAP sends; DRF's
# JSON answers link to their next pages, which ZAP's spider follows.
n=0
while read -r url; do
  n=$((n + 1))
  docker run --rm -v "$OUT:/zap/wrk:rw" "$ZAP_IMAGE" \
    zap-full-scan.py -t "$url" -r "zap-api-$n.html" -I -m 2 \
    -z "-config replacer.full_list(0).description=auth \
        -config replacer.full_list(0).enabled=true \
        -config replacer.full_list(0).matchtype=REQ_HEADER \
        -config replacer.full_list(0).matchstr=Authorization \
        -config replacer.full_list(0).regex=false \
        -config replacer.full_list(0).replacement=Token\ $token" || true
done < "$OUT/seeds.txt"

echo "Reports: $OUT/zap-baseline.html and $OUT/zap-api-*.html (one per endpoint in seeds.txt)"
echo 'Sign the scan user out afterwards (or reset its password): the token is valid for TOKEN_TTL_HOURS.'
