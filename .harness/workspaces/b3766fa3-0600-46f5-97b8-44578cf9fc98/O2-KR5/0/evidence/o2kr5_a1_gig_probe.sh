#!/usr/bin/env bash
# O2-KR5 attempt 1 - FALLBACK 2 (gig platforms): single anonymous unauthenticated probe.
# Scope: exactly ONE GET to https://www.upwork.com/ (host never contacted before).
# Fiverr: NO new attempt - its single permitted attempt was consumed in attempt 0
#   (GET https://www.fiverr.com/start_selling -> HTTP 403 PXCR10002539, receipt
#   f0c68766b0e2651f0c35783b537ab39e, citations.md B3). One-attempt-per-destination rule.
# No login, no signup, no account creation, no credentials, no retry. Honest outcome logged.
set -u
EV="$(cd "$(dirname "$0")" && pwd)"
OUT="$EV/o2kr5_a1_gig_probe_upwork.log"
URL="https://www.upwork.com/"
REPO="/home/dx/Agentic-harness/spoc-harness"

cd "$REPO" || exit 3
UPHITS=$(git grep -i "upwork" HEAD -- 2>/dev/null | wc -l)
FIVHITS=$(git grep -i "fiverr" HEAD -- 2>/dev/null | wc -l)

if [ "$UPHITS" -ne 0 ]; then
  {
    echo "== O2-KR5 attempt 1 - FALLBACK 2 gig-platform probe =="
    echo "UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "PRECHECK_FAIL: upwork hits in tracked tree at HEAD = $UPHITS (expected 0)."
    echo "NO REQUEST WAS MADE. Aborting before any network action (anti-spam precheck failed)."
  } > "$OUT" 2>&1
  exit 2
fi

{
  echo "== O2-KR5 attempt 1 - FALLBACK 2 (gig platforms): single-shot probe =="
  echo "UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "METHOD=GET URL=$URL"
  echo "AUTH=none (curl only; no cookies, no tokens, no account, no signup; unauthenticated anonymous probe)"
  echo "NO-RETRY RULE: exactly one attempt; any outcome is final; this host is never contacted again by this attempt."
  echo "FIVERR_NOTE: no new fiverr attempt (single permitted attempt consumed in attempt 0: HTTP 403 PXCR10002539, citations.md B3, receipt f0c68766b0e2651f0c35783b537ab39e)."
  echo "--- PRECHECK (tracked tree at HEAD $(git rev-parse HEAD)) ---"
  echo "upwork hits (required 0 before the request): $UPHITS"
  echo "fiverr hits (expected only attempt-0 B3 records; no new request made): $FIVHITS"
  echo "--- PROBE ---"
  BODY="$(mktemp)"
  HDRS="$(mktemp)"
  CODE=$(curl -sS --max-time 30 -o "$BODY" -D "$HDRS" -w "%{http_code}" "$URL")
  CURL_EXIT=$?
  echo "CURL_EXIT=$CURL_EXIT"
  echo "HTTP_STATUS=$CODE"
  echo "--- RESPONSE HEADERS ---"
  cat "$HDRS"
  BYTES=$(wc -c < "$BODY")
  SHA=$(sha256sum "$BODY" | cut -d' ' -f1)
  echo "BODY_BYTES=$BYTES"
  echo "BODY_SHA256=$SHA"
  echo "--- RESPONSE BODY (first 12 lines; http(s) URL strings redacted for citation hygiene - full-body sha256 above is the integrity anchor) ---"
  head -12 "$BODY" | sed -E 's#https?://[^ )"'"'"'<>#]+#<URL-REDACTED>#g'
  rm -f "$BODY" "$HDRS"
  echo "BLOCKER: gig submission requires account creation + identity verification, which is human-only for this agent; zero machine credentials exist (recorded O2-KR2 terminal BLOCKED: API 401s, credential sweeps empty) [pinned citations.md A1-A7]."
  echo "GIG_OUTCOME=UNAVAILABLE_WITH_BLOCKER (probe status above is informational reachability only; NO submission possible or attempted; no account created; no credentials used; this documents the channel as unavailable, not as a sale or lead)"
} > "$OUT" 2>&1
echo "WROTE $OUT"
exit 0
