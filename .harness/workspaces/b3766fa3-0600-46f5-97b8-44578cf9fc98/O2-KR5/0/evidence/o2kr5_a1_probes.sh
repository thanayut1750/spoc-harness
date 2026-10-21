#!/usr/bin/env bash
# O2-KR5 attempt-1 single-shot probes: C1 (paste.rs POST) and C2 (GitHub Pages GET).
# Anti-spam: exactly ONE attempt per destination; NO retries on any outcome; no
# account creation; no credentials; failures recorded as failures.
# Run from the repository ROOT. Mirrors the O2-KR3 single-attempt-per-destination rule.
set -u
REPO="$(pwd)"
EV="$REPO/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0/evidence"
MIRROR="$EV/mirrored_listing.md"
C1="$EV/o2kr5_a1_c1_pasters_post.log"
C2="$EV/o2kr5_a1_c2_pages_get.log"
PRE="$EV/o2kr5_a1_probe_precheck.log"
TMPD="$(mktemp -d)"

# ---------- anti-spam precheck (both destinations, before any request) ----------
{
  echo "== ANTI-SPAM PRECHECK (before any request; both destinations must show 0 prior hits) =="
  date -u +"UTC_NOW=%Y-%m-%dT%H:%M:%SZ"
  echo -n "paste.rs hits in attempt-0 chain log (expect 0): "
  grep -c "paste\.rs" "$EV/o2kr5_fallback_chain.log" || true
  echo -n "paste.rs hits across push-A evidence files (expect 0 files): "
  grep -il "paste\.rs" "$EV"/citations.md "$EV"/decision_log.md "$EV"/mirrored_listing.md "$EV"/adjusted_offer.md "$EV"/ledger_decision_summary.log 2>/dev/null | wc -l
  echo -n "github.io hits in attempt-0 chain log (expect 0): "
  grep -c "github\.io" "$EV/o2kr5_fallback_chain.log" || true
  echo "RULE: single attempt per destination; any outcome (success or failure) is final; no retry; no account creation; no credentials."
} > "$PRE" 2>&1
cat "$PRE"

# ---------- C1: ONE POST to https://paste.rs ----------
{
  echo "== C1: single POST https://paste.rs (anonymous paste host, no account required) =="
  date -u +"UTC=%Y-%m-%dT%H:%M:%SZ"
  echo "METHOD=POST URL=https://paste.rs"
  echo "REQUEST_BODY=$MIRROR (announcement-derived mirrored listing; committed in push A 2d5b29c6eb0081240f41827848656a9d8e02a312)"
  echo -n "POSTED_BODY_SHA256="
  sha256sum "$MIRROR" | cut -d' ' -f1
  echo "CONTENT_RULE: body derived only from recorded ANNOUNCEMENT.md (ef3d4f69 tip, sha 430fce45...); only product URL is the recorded hosted-zip URL."
  echo "NO-RETRY RULE: exactly one attempt; any outcome is final."
} > "$C1"
HTTP=$(curl -sS --max-time 30 -o "$TMPD/c1_body" -D "$TMPD/c1_hdr" -w '%{http_code}' --data-binary @"$MIRROR" https://paste.rs 2>"$TMPD/c1_err"); CURL_EXIT=$?
{
  echo "CURL_EXIT=$CURL_EXIT"
  [ -s "$TMPD/c1_err" ] && { echo "CURL_STDERR:"; cat "$TMPD/c1_err"; }
  echo "HTTP_STATUS=$HTTP"
  echo "--- RESPONSE HEADERS ---"
  cat "$TMPD/c1_hdr"
  echo "--- RESPONSE BODY ---"
  cat "$TMPD/c1_body"; echo
  case "$HTTP" in
    200|201) head -c 400 "$TMPD/c1_body" | grep -qE '^https?://' \
        && echo "C1_OUTCOME=SUCCESS (mirror content accepted; paste URL above; this is delivery of a free-download notice, NOT any sale)" \
        || echo "C1_OUTCOME=FAILURE (HTTP $HTTP but response body is not a paste URL; recorded honestly)" ;;
    *) echo "C1_OUTCOME=FAILURE (HTTP_STATUS=$HTTP; recorded honestly; NO retry per anti-spam rule)" ;;
  esac
} >> "$C1"

# ---------- C2: ONE GET to the GitHub Pages URL implied by the repo ----------
{
  echo "== C2: single GET https://thanayut1750.github.io/spoc-harness/ (read-only probe) =="
  date -u +"UTC=%Y-%m-%dT%H:%M:%SZ"
  echo "METHOD=GET URL=https://thanayut1750.github.io/spoc-harness/"
  echo "NO-RETRY RULE: exactly one attempt; any outcome is final."
} > "$C2"
HTTP2=$(curl -sS --max-time 30 -o "$TMPD/c2_body" -D "$TMPD/c2_hdr" -w '%{http_code}' "https://thanayut1750.github.io/spoc-harness/" 2>"$TMPD/c2_err"); CURL2_EXIT=$?
{
  echo "CURL_EXIT=$CURL2_EXIT"
  [ -s "$TMPD/c2_err" ] && { echo "CURL_STDERR:"; cat "$TMPD/c2_err"; }
  echo "HTTP_STATUS=$HTTP2"
  echo "--- RESPONSE HEADERS ---"
  cat "$TMPD/c2_hdr"
  echo "--- RESPONSE BODY (first 20 lines) ---"
  head -20 "$TMPD/c2_body"
  if [ "$HTTP2" = "404" ]; then
    echo "BLOCKER: Pages enablement is a repo-settings human step"
    echo "C2_OUTCOME=FAILURE (HTTP 404; blocker above; NO retry)"
  elif [ "$HTTP2" = "200" ]; then
    echo "C2_OUTCOME=SUCCESS (page reachable; content is the repo mirror; no sale implied)"
  else
    echo "C2_OUTCOME=FAILURE (HTTP_STATUS=$HTTP2; recorded honestly; NO retry)"
  fi
} >> "$C2"
rm -rf "$TMPD"
echo "PROBES_DONE one_shot_each_no_retries"
grep -h "^C1_OUTCOME=\|^C2_OUTCOME=" "$C1" "$C2"
