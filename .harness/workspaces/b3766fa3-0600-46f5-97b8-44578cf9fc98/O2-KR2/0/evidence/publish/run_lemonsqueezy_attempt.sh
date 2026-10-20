#!/usr/bin/env bash
# O2-KR2 STEP 2: Lemon Squeezy REST fallback attempt.
# Runs the real API POST and tee's exact output to evidence/publish/lemonsqueezy_attempt.log.
cd "$(dirname "$0")/../.." || exit 9
LOG=evidence/publish/lemonsqueezy_attempt.log
BODY=evidence/publish/lemonsqueezy_body.txt
{
  echo "# Lemon Squeezy REST product-creation attempt (fallback channel, O2-KR2 STEP 2)"
  echo "UTC_TIMESTAMP: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "ENDPOINT: POST https://api.lemonsqueezy.com/v1/products"
  echo "CREDENTIAL_PROBE: env | grep -iE 'lemon|squeezy' matched nothing (no LEMON_SQUEEZY_API_KEY in environment); Authorization Bearer sent empty per assignment."
  echo "PAYLOAD_FILE: evidence/publish/lemonsqueezy_payload.json (JSON:API; name/description/price=1500/status published; description HTML per docs.lemonsqueezy.com/api/products artifact d487e23812901d61506b8dc8a3e0671f)"
  echo "DOCS_NOTE: https://docs.lemonsqueezy.com/api/products lists only Retrieve a product / List all products; no create-product endpoint documented (fetched 2026-10-20 UTC). POST executed anyway per assignment to capture the exact API response."
  echo "EXACT_COMMAND:"
  printf '%s\n' "curl -sS -o evidence/publish/lemonsqueezy_body.txt -w 'HTTP_STATUS:%{http_code}\n' -X POST https://api.lemonsqueezy.com/v1/products -H \"Authorization: Bearer \${LEMON_SQUEEZY_API_KEY:-}\" -H \"Accept: application/vnd.api+json\" -H \"Content-Type: application/vnd.api+json\" --data-binary @evidence/publish/lemonsqueezy_payload.json"
  echo "BEGIN_RAW_OUTPUT"
} > "$LOG"
curl -sS -o "$BODY" -w 'HTTP_STATUS:%{http_code}\n' -X POST https://api.lemonsqueezy.com/v1/products \
  -H "Authorization: Bearer ${LEMON_SQUEEZY_API_KEY:-}" \
  -H "Accept: application/vnd.api+json" \
  -H "Content-Type: application/vnd.api+json" \
  --data-binary @evidence/publish/lemonsqueezy_payload.json 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
{
  echo "CURL_EXIT:$RC"
  echo "END_RAW_OUTPUT"
  echo "BODY_FILE: evidence/publish/lemonsqueezy_body.txt"
  echo "BODY_BYTES: $(wc -c < "$BODY")"
  echo "BODY_SHA256: $(sha256sum "$BODY" | cut -d' ' -f1)"
  echo "BODY_FIRST_10_LINES:"
  head -10 "$BODY"
  echo "UTC_FINISHED: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >> "$LOG"
echo "=== LOG CONTENTS ==="
cat "$LOG"
