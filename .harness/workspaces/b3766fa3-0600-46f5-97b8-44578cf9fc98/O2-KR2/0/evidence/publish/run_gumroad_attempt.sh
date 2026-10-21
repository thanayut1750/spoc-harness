#!/usr/bin/env bash
# O2-KR2 STEP 1(c): Gumroad product-listing attempt (primary channel).
# Runs the real API POST and tee's exact output to evidence/publish/gumroad_attempt.log.
cd "$(dirname "$0")/../.." || exit 9
LOG=evidence/publish/gumroad_attempt.log
BODY=evidence/publish/gumroad_body.txt
{
  echo "# Gumroad product-listing API attempt (primary channel, O2-KR2 STEP 1)"
  echo "UTC_TIMESTAMP: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "ENDPOINT: POST https://api.gumroad.com/v2/products"
  echo "CREDENTIAL_PROBE: env | grep -iE 'gumroad|access_token' matched nothing (no GUMROAD_ACCESS_TOKEN in environment); access_token sent empty per playbook command."
  echo "EXACT_COMMAND:"
  printf '%s\n' "curl -sS -o evidence/publish/gumroad_body.txt -w 'HTTP_STATUS:%{http_code}\\n' -X POST https://api.gumroad.com/v2/products -d \"access_token=\${GUMROAD_ACCESS_TOKEN:-}\" --data-urlencode \"name=pydevtoolkit 1.0.0 — 16 CLI developer utilities\" -d \"price=1500\" --data-urlencode \"description=\$(sed -n '1,120p' pydevtoolkit-1.0.0/README.md)\""
  echo "BEGIN_RAW_OUTPUT"
} > "$LOG"
curl -sS -o "$BODY" -w 'HTTP_STATUS:%{http_code}\n' -X POST https://api.gumroad.com/v2/products \
  -d "access_token=${GUMROAD_ACCESS_TOKEN:-}" \
  --data-urlencode "name=pydevtoolkit 1.0.0 — 16 CLI developer utilities" \
  -d "price=1500" \
  --data-urlencode "description=$(sed -n '1,120p' pydevtoolkit-1.0.0/README.md)" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
{
  echo "CURL_EXIT:$RC"
  echo "END_RAW_OUTPUT"
  echo "BODY_FILE: evidence/publish/gumroad_body.txt"
  echo "BODY_BYTES: $(wc -c < "$BODY")"
  echo "BODY_SHA256: $(sha256sum "$BODY" | cut -d' ' -f1)"
  echo "BODY_FIRST_10_LINES:"
  head -10 "$BODY"
  echo "UTC_FINISHED: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} >> "$LOG"
echo "=== LOG CONTENTS ==="
cat "$LOG"
