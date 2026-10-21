#!/usr/bin/env bash
# O2-KR5 gig-platform chain close-out (WP-O2KR5-2-GIG-CHAIN): single anonymous
# unauthenticated GET to https://www.upwork.com/ - the FIRST and ONLY permitted
# contact with this host (anti-spam: one attempt per destination, no retries).
#
# Refined from the prepared evidence/o2kr5_a1_gig_probe.sh (C7, untouched): that
# script's naive precheck (git grep -i upwork HEAD == 0) would now abort because the
# tracked tree legitimately contains documentation mentions of upwork (chain docs,
# citations, decision log). This refined precheck asserts the anti-retry fact
# directly: ZERO *upwork* contact-record files may exist anywhere before the request.
#
# Hard rules honored: no login, no signup, no account creation, no credentials,
# no cookies, exactly one request, honest outcome recorded whatever it is.
set -u
EV="$(cd "$(dirname "$0")" && pwd)"
OUT="$EV/o2kr5_a2_gig_probe_upwork.log"
BODY_OUT="$EV/o2kr5_a2_upwork_body.html"
URL="https://www.upwork.com/"
MAIN="/home/dx/Agentic-harness/spoc-harness"
CLONE="/tmp/o2kr5_a2"

# --- IDEMPOTENCY GUARD: never risk a second request (e.g. after a stopped receipt) ---
if [ -e "$OUT" ] || [ -e "$BODY_OUT" ]; then
  echo "ABORT_IDEMPOTENCY: output log or archived body already exists; NO REQUEST MADE." >&2
  exit 4
fi

# --- PRECHECK: zero upwork contact records anywhere (main worktree + publication clone) ---
UHITS_MAIN=$(find "$MAIN/.harness/workspaces" -iname '*upwork*' 2>/dev/null | wc -l)
UHITS_CLONE=$(find "$CLONE/.harness" -iname '*upwork*' 2>/dev/null | wc -l)
if [ "$UHITS_MAIN" -ne 0 ] || [ "$UHITS_CLONE" -ne 0 ]; then
  {
    echo "== O2-KR5 gig-platform chain close-out: upwork probe =="
    echo "UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "PRECHECK_FAIL: *upwork* files exist (main=$UHITS_MAIN clone=$UHITS_CLONE), expected 0."
    echo "NO REQUEST WAS MADE. Aborting before any network action (anti-retry precheck failed)."
  } > "$OUT" 2>&1
  exit 2
fi
DOC_HITS=$(grep -ril upwork "$CLONE/.harness" 2>/dev/null | wc -l)

{
  echo "== O2-KR5 gig-platform chain close-out (WP-O2KR5-2): single-shot anonymous upwork probe =="
  echo "UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "METHOD=GET URL=$URL"
  echo "AUTH=none (curl default headers only; no cookies, no tokens, no account, no signup; unauthenticated anonymous machine probe)"
  echo "NO-RETRY RULE: exactly one request; whatever the outcome, this host is not contacted again by this package."
  echo "FIVERR_NOTE: no fiverr request in this run - its single permitted attempt was consumed in attempt 0"
  echo "  (citations.md B3: GET https://www.fiverr.com/start_selling -> HTTP 403 PXCR10002539 \"It needs a human touch\","
  echo "   receipt f0c68766b0e2651f0c35783b537ab39e, body sha256 6af47b64215b75e2c237f1e4bb6409d9a457998c6ad0a2416f77eff72dbfe880)."
  echo "--- PRECHECK (anti-retry, evaluated immediately before the request) ---"
  echo "*upwork* contact-record files in main worktree: $UHITS_MAIN (required 0)"
  echo "*upwork* contact-record files in publication clone: $UHITS_CLONE (required 0)"
  echo "documentation-only upwork mentions in publication clone tree: $DOC_HITS files (chain/citation docs, NOT contact records)"
  echo "--- PROBE ---"
  TMPB="$(mktemp)"; TMPH="$(mktemp)"
  CODE=$(curl -sS --max-time 30 -o "$TMPB" -D "$TMPH" -w "%{http_code}" "$URL"); CURL_EXIT=$?
  echo "CURL_EXIT=$CURL_EXIT"
  echo "HTTP_STATUS=$CODE"
  echo "--- RESPONSE HEADERS ---"
  cat "$TMPH"
  BYTES=$(wc -c < "$TMPB"); SHA=$(sha256sum "$TMPB" | cut -d' ' -f1)
  echo "BODY_BYTES=$BYTES"
  echo "BODY_SHA256=$SHA"
  cp "$TMPB" "$BODY_OUT"; chmod 644 "$BODY_OUT"
  echo "BODY_ARCHIVED=$BODY_OUT (genuine response body kept verbatim for quote extraction and remote byte-exact fetch-back)"
  echo "--- BODY EXCERPT (first 12 lines; http(s) URL strings redacted; full body archived with sha256 above) ---"
  head -12 "$TMPB" | sed -E 's#https?://[^ )\"<>]+#<URL-REDACTED>#g'
  echo "--- QUOTE CANDIDATES (verbatim strings from the archived body; URL strings redacted) ---"
  grep -o -i -E '<title>[^<]*</title>' "$TMPB" | head -2 | sed -E 's#https?://[^ )\"<>]+#<URL-REDACTED>#g'
  grep -o -i -E '.{0,60}(access denied|request blocked|captcha|verify (that )?you are human|unusual traffic|forbidden|not available in your country).{0,60}' "$TMPB" | head -5 | sed -E 's#https?://[^ )\"<>]+#<URL-REDACTED>#g'
  rm -f "$TMPB" "$TMPH"
  echo "STRUCTURAL_BLOCKER (verbatim from decision_log.md ENTRY 2, citations A2-A7): \"gig submission requires account creation + identity verification, which is human-only for this agent; zero machine credentials exist (recorded O2-KR2 terminal BLOCKED: API 401s, credential sweeps empty)\""
  echo "GIG_OUTCOME=UNAVAILABLE_WITH_BLOCKER (probe status above is informational reachability only; NO submission possible or attempted; no account created; no credentials used; this documents the channel as unavailable, not as a sale or lead)"
} > "$OUT" 2>&1
echo "WROTE $OUT"
exit 0
