#!/usr/bin/env bash
# WP-O2KR4-2-REPORT: independent proof-resolution audit.
# Fetches every URL cited in the final report with curl, records HTTP status + sha256,
# requires HTTP 200 and the expected content marker. Read-only; writes only this log.
set -u
BASE="https://raw.githubusercontent.com/thanayut1750/spoc-harness"
WS=".harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2"
LOG="$(dirname "$0")/proof_resolution_audit.log"
TMP="$(mktemp -d)"
FAIL=0

emit() { printf '%s\n' "$*" >> "$LOG"; }

: > "$LOG"
emit "UTC_NOW: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
emit "purpose: WP-O2KR4-2-REPORT independent proof-resolution audit"
emit "method: curl -sS per URL; HTTP status, byte count, sha256 of body, expected marker grep; require HTTP 200 + marker"
emit "scope: every proof/verification URL cited in report/EARNINGS_REPORT_O2KR4.md"
emit ""

fetch() {
  local url="$1" marker="$2" tag="$3" status bytes sha
  status=$(curl -sS -o "$TMP/body" -w '%{http_code}' "$url"); rc=$?
  if [ $rc -ne 0 ]; then
    emit "[$tag] FETCH_ERROR curl_exit=$rc url=$url"; FAIL=1; return
  fi
  bytes=$(wc -c < "$TMP/body")
  sha=$(sha256sum "$TMP/body" | awk '{print $1}')
  if [ "$status" = "200" ] && grep -qF -- "$marker" "$TMP/body"; then
    occ=$(grep -cF -- "$marker" "$TMP/body")
    emit "[$tag] HTTP_STATUS: $status"
    emit "[$tag] bytes: $bytes"
    emit "[$tag] sha256: $sha"
    emit "[$tag] expected_marker: [$marker] occurrences: $occ"
    emit "[$tag] RESOLUTION: OK (HTTP 200, marker present)"
  else
    emit "[$tag] HTTP_STATUS: $status"
    emit "[$tag] sha256: $sha"
    emit "[$tag] RESOLUTION: FAIL (status=$status or marker missing)"; FAIL=1
  fi
  emit ""
}

U1="$BASE/63e0f5caab3c61d1d2985a915419a1fa2ed9f8c9/$WS/evidence/gumroad_api_retry.log"
U2="$BASE/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/$WS/evidence/gumroad_api_retry.log"
U3="$BASE/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/$WS/evidence/lemonsqueezy_fallback_retry.log"
U4="$BASE/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/$WS/evidence/gumroad_human_step_outcome.md"
U5="$BASE/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/$WS/evidence/lemonsqueezy_human_step_outcome.md"
U6="$BASE/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/$WS/evidence/gumroad_credentials_sweep.log"
U7="$BASE/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/$WS/evidence/lemonsqueezy_credentials_sweep.log"

fetch "$U1" "HTTP_STATUS:401"         "C1 gumroad_api_retry.log @63e0f5ca"
fetch "$U2" "HTTP_STATUS:401"         "C2 gumroad_api_retry.log @bc8167ca"
fetch "$U3" "HTTP_STATUS: 401"        "C3 lemonsqueezy_fallback_retry.log @bc8167ca"
fetch "$U4" 'OUTCOME: `blocked`'      "C4 gumroad_human_step_outcome.md @bc8167ca"
fetch "$U5" 'OUTCOME: `blocked`'      "C5 lemonsqueezy_human_step_outcome.md @bc8167ca"
fetch "$U6" "No Gumroad or Lemon Squeezy credential" "C6 gumroad_credentials_sweep.log @bc8167ca"
fetch "$U7" "ZERO Lemon Squeezy credentials"         "C7 lemonsqueezy_credentials_sweep.log @bc8167ca"

emit "URLS_FETCHED: 7"
emit "UNRESOLVED_CITATIONS: $FAIL"
if [ $FAIL -eq 0 ]; then
  emit "PROOF_RESOLUTION: PASS (all 7 citations HTTP 200 with expected markers)"
else
  emit "PROOF_RESOLUTION: FAIL (non-200 or marker-missing citations present)"
fi
rm -rf "$TMP"
exit $FAIL
