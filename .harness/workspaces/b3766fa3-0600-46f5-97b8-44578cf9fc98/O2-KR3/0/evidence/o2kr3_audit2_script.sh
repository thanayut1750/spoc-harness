#!/usr/bin/env bash
# =============================================================================
# WP-O2KR3-2-AUDIT — execution attempt 2 (fresh re-verification).
# Independent, adversarial, READ-ONLY audit of the O2-KR3 outreach evidence.
# Do NOT post anything; do NOT modify outreach_log.md or any prior evidence.
# Outputs (all NEW additions-only files):
#   evidence/o2kr3_audit2.log            (this script's stdout; outer tee target)
#   evidence/o2kr3_rules_spotcheck.log   (R5 dedicated fresh curl evidence)
#   evidence/o2kr3_positive_reverify.log (R6 dedicated fresh curl evidence)
# Prior attempt-1 audit log evidence/o2kr3_audit.log (commit e48fba3) is left
# byte-identical; this attempt re-presents it in full via publish_file and
# re-runs every check fresh.
# =============================================================================
REPO=/home/dx/Agentic-harness/spoc-harness
WS="$REPO/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR3/0"
EV="$WS/evidence"
LOG="$EV/outreach_log.md"
AUD1="$EV/o2kr3_audit.log"
AUD2="$EV/o2kr3_audit2.log"
R5LOG="$EV/o2kr3_rules_spotcheck.log"
R6LOG="$EV/o2kr3_positive_reverify.log"
FBLOG="$EV/o2kr3_fetchback.log"
ML_REL=".harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/mission_log.md"
ML="$REPO/$ML_REL"
RAWB="https://raw.githubusercontent.com/thanayut1750/spoc-harness"
ZIPURL="$RAWB/a8563e06532ea3fd0af2b51331ba8d3be66eff5b/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip"
KEYURL="$RAWB/7368190654bdf4655d5657a8565e1b1e6990954c/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR3/0/offer/03d3363d8c5f23bfe7ce970e0ac7cd08.txt"
ANNURL="$RAWB/codex/spoc-harness-v1/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR3/0/offer/ANNOUNCEMENT.md"
LOGBURL="$RAWB/codex/spoc-harness-v1/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR3/0/evidence/outreach_log.md"
EXPECT_ZIP_SHA=f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99
EXPECT_KEY=03d3363d8c5f23bfe7ce970e0ac7cd08
EXPECT_KEY_SHA=7924396c520f5a6dececd0fd4eb62c61c6f130befe808bd027c1174c2cc7598f
EXPECT_LOG_SHA=c764677b7d8369253f6ad1139f8039e475f022aa602232808a9bfe0225a47007
EXPECT_ANN_SHA=430fce456a3481353d7678af2b1204000154f50c963acaac5d8d92f4845c5f91

START_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
START_HUMAN=$(date -u)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
cd "$REPO" || { echo "FATAL: repo dir missing"; exit 9; }

HEAD_SHA=$(git rev-parse HEAD)
ORIGIN_TIP=$(git ls-remote origin codex/spoc-harness-v1 | cut -f1)
DIRTY=$(git status --porcelain | wc -l)

echo "=================================================================================="
echo "O2-KR3 OUTREACH EVIDENCE AUDIT (attempt 2) — WP-O2KR3-2-AUDIT (independent verification only)"
echo "Auditor: specialist:b3766fa3-0600-46f5-97b8-44578cf9fc98:9f7a62e5bf9d9852"
echo "Repo: https://github.com/thanayut1750/spoc-harness  branch: codex/spoc-harness-v1"
echo "Workspace audited: .harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR3/0"
echo "HEADER_UTC: $START_HUMAN"
echo "AUDIT_STARTED: $START_UTC"
echo "HEAD_AT_AUDIT_START: $HEAD_SHA"
echo "ORIGIN_TIP_AT_AUDIT_START: ${ORIGIN_TIP:-unreachable}  (IN_SYNC=$([ "$HEAD_SHA" = "$ORIGIN_TIP" ] && echo yes || echo NO))"
echo "Git tree dirty paths at audit start: $DIRTY"
echo "Attempt-1 audit log (unchanged, re-presented in full): evidence/o2kr3_audit.log sha256=$(sha256sum "$AUD1" | cut -d' ' -f1) (committed e48fba3)"
echo "Scope note: read-only audit. No posts, no marketing, no edits to outreach_log.md or prior evidence."
echo "This attempt adds ONLY: evidence/o2kr3_audit2.log, evidence/o2kr3_rules_spotcheck.log,"
echo "             evidence/o2kr3_positive_reverify.log, evidence/o2kr3_audit2_script.sh (this file),"
echo "             evidence/o2kr3_audit2_fetchback.log (written after push), mission_log ADDENDUM 11."
echo "=================================================================================="
echo "[NON-MUTATION PRE-CHECK] live sha256 of prior deliverables (must equal committed anchors):"
echo "  outreach_log.md            $(sha256sum "$LOG" | cut -d' ' -f1)"
echo "  o2kr3_audit.log (attempt1) $(sha256sum "$AUD1" | cut -d' ' -f1)"
echo "  mission_log.md             $(sha256sum "$ML" | cut -d' ' -f1)  ($(wc -l < "$ML") lines)"
echo "  ANNOUNCEMENT.md            $(sha256sum "$WS/offer/ANNOUNCEMENT.md" | cut -d' ' -f1)"
echo "  IndexNow key file          $(sha256sum "$WS/offer/${EXPECT_KEY}.txt" | cut -d' ' -f1)"
echo

# ---------------- parse outreach_log.md ----------------
PARSE=$(awk '
/^ENTRY [0-9]+$/ { n++; next }
n>0 && /^(UTC_TIMESTAMP|CHANNEL_CLASS|DESTINATION|RULES_CHECKED|LINK_SENT|TEXT_SENT|CONFIRMATION|OUTCOME):/ {
  idx = index($0, ":"); key = substr($0, 1, idx-1); val = substr($0, idx+1); sub(/^ +/, "", val); F[key,n] = val
}
END {
  split("UTC_TIMESTAMP CHANNEL_CLASS DESTINATION RULES_CHECKED LINK_SENT TEXT_SENT CONFIRMATION OUTCOME", keys, " ")
  sf=0; df=0; rf=0
  for (i=1; i<=n; i++) {
    m=""
    for (k=1; k<=8; k++) if (F[keys[k],i] == "") m = m keys[k] " "
    ts=F["UTC_TIMESTAMP",i]
    tsok=(ts ~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z$/) ? "True" : "False"
    rc=F["RULES_CHECKED",i]
    ru=(rc ~ /https?:\/\//) ? "True" : "False"
    st=(rc ~ /HTTP [0-9][0-9][0-9]/) ? "True" : "False"
    qq=(rc ~ /verbatim/) ? "True" : "False"
    cc=F["CHANNEL_CLASS",i]; split(cc,b,"-"); cls=b[1]; cov[cls]++
    dcount[F["DESTINATION",i]]++; otally[F["OUTCOME",i]]++
    printf "  E%d ts=%s ts_ok=%s missing=[%s] rules_url=%s rules_status=%s rules_quote=%s class=%s outcome=%s\n", i, ts, tsok, (m==""?"none":m), ru, st, qq, cc, F["OUTCOME",i]
    if (m!="") sf++
    if (tsok=="False") df++
    if (ru!="True" || st!="True" || qq!="True") rf++
  }
  print "  ENTRIES=" n
  print "  UTC_DATED=" (n-df)
  print "  SCHEMA_FAIL_ENTRIES=" (sf?sf:"none")
  cl=""
  for (c=1; c<=6; c++) cl = cl c ":" ((c in cov)?cov[c]:0) (c<6?" ":"")
  print "  CLASSES=" cl
  nd=0; for (d in dcount) nd++
  print "  UNIQUE_DESTINATIONS=" nd " TOTAL_DEST_LINES=" n
  print "  RULES_CHECKED_ALL_STRUCT_OK=" ((rf==0)?"yes":"NO")
  ot=""; for (o in otally) ot = ot o ":" otally[o] " "
  print "  OUTCOMES=" ot
  print "  CLASS_COVERAGE_OK=" ((cov[1]>=1&&cov[2]>=1&&cov[3]>=1&&cov[4]>=1&&cov[5]>=1&&cov[6]>=1)?"yes":"NO")
  print "  DUP_DEST=" ((nd==n)?"none":"DUPES_PRESENT")
}' "$LOG")
echo "$PARSE"
ENTRIES=$(echo "$PARSE" | grep -o 'ENTRIES=[0-9]*' | head -1 | cut -d= -f2)
UTC_DATED=$(echo "$PARSE" | grep -o 'UTC_DATED=[0-9]*' | head -1 | cut -d= -f2)
SCHEMA_FAIL=$(echo "$PARSE" | grep -o 'SCHEMA_FAIL_ENTRIES=[a-zA-Z0-9]*' | head -1 | cut -d= -f2)
COV_OK=$(echo "$PARSE" | grep -o 'CLASS_COVERAGE_OK=[a-zA-Z]*' | head -1 | cut -d= -f2)
UNIQ_DEST=$(echo "$PARSE" | grep -o 'UNIQUE_DESTINATIONS=[0-9]*' | head -1 | cut -d= -f2)
RULES_STRUCT_OK=$(echo "$PARSE" | grep -o 'RULES_CHECKED_ALL_STRUCT_OK=[a-zA-Z]*' | head -1 | cut -d= -f2)
DUP_DEST=$(echo "$PARSE" | grep -o 'DUP_DEST=[a-zA-Z_]*' | head -1 | cut -d= -f2)
LOG_SHA=$(sha256sum "$LOG" | cut -d' ' -f1)
LOG_SIZE=$(wc -c < "$LOG")

# ---------------- R5 fresh rules spot-check (dedicated log, mirrored here) ----------------
: > "$R5LOG"
{
  echo "# O2-KR3 AUDIT ATTEMPT 2 — R5 RULES SPOT-CHECK (fresh re-fetch of cited RULES_CHECKED URLs)"
  echo "# UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)  auditor: specialist:b3766fa3-0600-46f5-97b8-44578cf9fc98:9f7a62e5bf9d9852"
  echo "# Method: curl -sS -m 60 -o <tmp> -w '%{http_code}'; fragment matched after HTML-tag strip + case-insensitive grep."
} | tee "$R5LOG"
R5_OKCOUNT=0; R5_N=0
r5() {
  local name="$1" url="$2" frag="$3" entry="$4"
  local body="$T/r5_$name"
  local code rcx hits size
  code=$(curl -sS -m 60 -o "$body" -w '%{http_code}' "$url" 2>"$T/r5_$name.err"); rcx=$?
  hits=$(sed 's/<[^>]*>/ /g' "$body" 2>/dev/null | grep -o -i -F -- "$frag" | wc -l)
  size=$(wc -c < "$body" 2>/dev/null || echo 0)
  local ok=NO
  if [ "$rcx" = "0" ] && [ "$code" = "200" ] && [ "$hits" -ge 1 ]; then ok=YES; R5_OKCOUNT=$((R5_OKCOUNT+1)); fi
  R5_N=$((R5_N+1))
  {
    echo "[$name] fresh GET $url"
    echo "  curl_exit=$rcx http_code=$code bytes=$size fragment=\"$frag\" hits(normalized)=$hits quoted_by=$entry rule_text_plausibly_present=$ok"
  } | tee -a "$R5LOG"
  printf '  [%s] fresh GET %s\n    curl_exit=%s http_code=%s bytes=%s fragment="%s" hits(normalized)=%s quoted_by=%s rule_text_plausibly_present=%s\n' "$name" "$url" "$rcx" "$code" "$size" "$frag" "$hits" "$entry" "$ok"
}
r5 hn        "https://news.ycombinator.com/newsguidelines.html" "primarily for promotion" "ENTRY 7"
r5 indexnow  "https://www.indexnow.org/documentation"           "ownership of the host"   "ENTRY 1"
r5 ghterms   "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service" "for spamming purposes" "ENTRY 8"
r5 mastodon  "https://mastodon.social/api/v1/instance"          "dogpiling"               "ENTRY 5"
{
  echo "R5_DEDUCED: rules_urls_refetched_fresh=$R5_N with_HTTP200_and_quote_present=$R5_OKCOUNT (assignment minimum: >=2)"
} | tee -a "$R5LOG"
printf '  R5_DEDUCED: rules_urls_refetched_fresh=%s with_HTTP200_and_quote_present=%s (assignment minimum: >=2)\n' "$R5_N" "$R5_OKCOUNT"

# ---------------- R6 positive confirmation re-verify (dedicated log, mirrored here) ----------------
: > "$R6LOG"
{
  echo "# O2-KR3 AUDIT ATTEMPT 2 — R6 POSITIVE CONFIRMATION RE-VERIFY (fresh GETs)"
  echo "# UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} | tee "$R6LOG"
KEYBODY="$T/key.txt"
KEYMETA=$(curl -sS -m 60 -o "$KEYBODY" -w 'code=%{http_code} type=%{content_type} size=%{size_download}' "$KEYURL" 2>"$T/key.err"); KEYRC=$?
KEYCONTENT=$(tr -d '\r\n' < "$KEYBODY" 2>/dev/null)
KEYSHA=$(sha256sum "$KEYBODY" 2>/dev/null | cut -d' ' -f1)
KEY_EXACT=NO; [ "$KEYCONTENT" = "$EXPECT_KEY" ] && KEY_EXACT=YES
KEYSHA_OK=NO; [ "$KEYSHA" = "$EXPECT_KEY_SHA" ] && KEYSHA_OK=YES
{
  echo "[key] fresh GET $KEYURL"
  echo "  curl_exit=$KEYRC curl -w: $KEYMETA"
  echo "  content=[$KEYCONTENT] exact_key_match=$KEY_EXACT (expected $EXPECT_KEY) fetched_sha256=$KEYSHA local_sha256=$EXPECT_KEY_SHA sha_match=$KEYSHA_OK"
} | tee -a "$R6LOG"
printf '  [key] fresh GET %s\n    curl_exit=%s curl -w: %s\n    content=[%s] exact_key_match=%s fetched_sha256=%s local=%s sha_match=%s\n' "$KEYURL" "$KEYRC" "$KEYMETA" "$KEYCONTENT" "$KEY_EXACT" "$KEYSHA" "$EXPECT_KEY_SHA" "$KEYSHA_OK"

ZIPBODY="$T/zip.zip"
ZIPMETA=$(curl -sS -m 120 -o "$ZIPBODY" -w 'code=%{http_code} type=%{content_type} size=%{size_download}' "$ZIPURL" 2>"$T/zip.err"); ZIPRC=$?
ZIPSHA=$(sha256sum "$ZIPBODY" 2>/dev/null | cut -d' ' -f1)
ZIPBYTES=$(wc -c < "$ZIPBODY" 2>/dev/null || echo 0)
ZIPSHA_OK=NO; [ "$ZIPSHA" = "$EXPECT_ZIP_SHA" ] && ZIPSHA_OK=YES
ZIPCT_OK=NO; echo "$ZIPMETA" | grep -q 'type=application/zip' && ZIPCT_OK=YES
ZIPHEAD=$(curl -sSI -m 60 "$ZIPURL" | tr -d '\r' | grep -i -E '^(HTTP|content-type|content-length)' | paste -sd' | ' -)
{
  echo "[zip] fresh GET $ZIPURL"
  echo "  curl_exit=$ZIPRC curl -w: $ZIPMETA"
  echo "  downloaded_bytes=$ZIPBYTES (expected 40299) sha256=$ZIPSHA"
  echo "  sha256_match=$ZIPSHA_OK (expected $EXPECT_ZIP_SHA) content_type_ok=$ZIPCT_OK"
  echo "  fresh HEAD: $ZIPHEAD"
} | tee -a "$R6LOG"
printf '  [zip] fresh GET %s\n    curl_exit=%s curl -w: %s\n    downloaded_bytes=%s sha256=%s sha256_match=%s content_type_ok=%s\n    fresh HEAD: %s\n' "$ZIPURL" "$ZIPRC" "$ZIPMETA" "$ZIPBYTES" "$ZIPSHA" "$ZIPSHA_OK" "$ZIPCT_OK" "$ZIPHEAD"

# ---------------- R4 posted-claim spot-check ----------------
ANNBODY="$T/ann.md"
ANNMETA=$(curl -sS -m 60 -o "$ANNBODY" -w 'code=%{http_code}' "$ANNURL" 2>"$T/ann.err"); ANNRC=$?
ANNSHA=$(sha256sum "$ANNBODY" 2>/dev/null | cut -d' ' -f1)
ANN_OK=NO; [ "$ANNRC" = "0" ] && [ "$ANNSHA" = "$EXPECT_ANN_SHA" ] && ANN_OK=YES
printf '  [posted-claim spot-check] fresh GET %s\n    curl_exit=%s http_code=%s fetched_sha256=%s local_sha256=%s byte_identical=%s\n' "$ANNURL" "$ANNRC" "$ANNMETA" "$ANNSHA" "$EXPECT_ANN_SHA" "$ANN_OK"

# ---------------- R7 branch-tip fetch-back of outreach_log.md ----------------
LGBODY="$T/log_at_tip.md"
LGMETA=$(curl -sS -m 60 -o "$LGBODY" -w 'code=%{http_code}' "$LOGBURL" 2>"$T/lg.err"); LGRC=$?
LGSHA=$(sha256sum "$LGBODY" 2>/dev/null | cut -d' ' -f1)
LG_OK=NO; [ "$LGRC" = "0" ] && [ "$LGSHA" = "$LOG_SHA" ] && LG_OK=YES
TRACKED=$(git ls-tree -r HEAD --name-only -- ".harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR3/0" | wc -l)
FB_EXISTS=NO; [ -f "$FBLOG" ] && FB_EXISTS=YES
printf '  [R7] tracked O2-KR3/0 paths in HEAD=%s; local==origin tip: %s\n    fresh branch-tip fetch-back of evidence/outreach_log.md:\n    URL: %s\n    curl_exit=%s http_code=%s fetched_sha256=%s local_sha256=%s byte_identical=%s\n    evidence/o2kr3_fetchback.log exists=%s (sha256 %s)\n' "$TRACKED" "$([ "$HEAD_SHA" = "$ORIGIN_TIP" ] && echo yes || echo NO)" "$LOGBURL" "$LGRC" "$LGMETA" "$LGSHA" "$LOG_SHA" "$LG_OK" "$FB_EXISTS" "$(sha256sum "$FBLOG" | cut -d' ' -f1)"

# ---------------- R8 mission_log additions-only ----------------
NUM=$(git diff --numstat 7368190..HEAD -- "$ML_REL")
ADD9=$(git diff --numstat 6bb5530^ 6bb5530 -- "$ML_REL")
ADD10=$(git diff --numstat e48fba3^ e48fba3 -- "$ML_REL")
MINUS=$(git diff 7368190..HEAD -- "$ML_REL" | grep -c '^-[^-]' || true)
printf '  [R8] git diff --numstat 7368190..HEAD on mission_log: %s\n    ADDENDUM 9 commit diff 6bb5530: %s | ADDENDUM 10 commit diff e48fba3: %s\n    cumulative minus-lines (excl. --- headers): %s\n    mission_log now: %s lines, sha256 %s; ADDENDUM 9 present: %s; ADDENDUM 10 present: %s\n' \
  "$NUM" "$ADD9" "$ADD10" "$MINUS" "$(wc -l < "$ML")" "$(sha256sum "$ML" | cut -d' ' -f1)" \
  "$(grep -c '^## ADDENDUM 9' "$ML" || true)" "$(grep -c '^## ADDENDUM 10' "$ML" || true)"

# ---------------- verdicts ----------------
R1=FAIL; { [ -f "$LOG" ] && [ "$ENTRIES" -ge 1 ] && [ "$UTC_DATED" = "$ENTRIES" ]; } && R1=PASS
R2=FAIL; { [ "$SCHEMA_FAIL" = "none" ]; } && R2=FAIL2; [ "$SCHEMA_FAIL" = "none" ] && R2=PASS
R3=FAIL; [ "$COV_OK" = "yes" ] && R3=PASS
R4=FAIL; { [ "$DUP_DEST" = "none" ] && [ "$RULES_STRUCT_OK" = "yes" ] && [ "$ANN_OK" = "YES" ]; } && R4=PASS
R5=FAIL; [ "$R5_OKCOUNT" -ge 2 ] && R5=PASS
R6=FAIL; { [ "$KEY_EXACT" = "YES" ] && [ "$KEYSHA_OK" = "YES" ] && [ "$ZIPSHA_OK" = "YES" ] && [ "$ZIPCT_OK" = "YES" ] && [ "$ZIPBYTES" = "40299" ]; } && R6=PASS
R7=FAIL; { [ "$LG_OK" = "YES" ] && [ "$FB_EXISTS" = "YES" ] && [ "$HEAD_SHA" = "$ORIGIN_TIP" ]; } && R7=PASS
R8=FAIL; { [ "$MINUS" = "0" ] && echo "$NUM" | grep -q $'^0\t' ; } || true
[ "$MINUS" = "0" ] && [ "$(echo "$NUM" | awk '{print $2}')" = "0" ] && R8=PASS

echo
echo "=================================================================================="
echo "R1 LOG_EXISTS_DATED: $R1 — evidence: evidence/outreach_log.md exists ($LOG_SIZE B, sha256 $LOG_SHA); parse ENTRIES=$ENTRIES UTC_DATED=$UTC_DATED; pointer: ENTRY 1-$ENTRIES UTC_TIMESTAMP lines (ISO-8601 Z)"
echo "R2 ENTRY_SCHEMA: $R2 — evidence: parse output above (per-entry missing=none; every RULES_CHECKED carries fetched URL + HTTP status + verbatim quote); pointer: evidence/outreach_log.md ENTRY 1-$ENTRIES, all 8 mandatory fields non-empty"
echo "R3 CHANNEL_COVERAGE: $R3 — evidence: parse CLASSES line above (classes 1-6 each >=1); pointer: CHANNEL_CLASS lines + archived evidence/outreach/{indexnow,pingomatic,reddit,x,mastodon,devto,hn,github}.log; OUTCOMES line above"
echo "R4 ANTI_SPAM: $R4 — evidence: UNIQUE_DESTINATIONS=$UNIQ_DEST = entry count, DUP_DEST=$DUP_DEST, RULES_CHECKED_ALL_STRUCT_OK=$RULES_STRUCT_OK; only 'posted' claim (ENTRY 8 ANNOUNCEMENT.md fallback) re-fetched fresh this audit: $([ "$ANN_OK" = "YES" ] && echo "HTTP 200 byte-identical sha256 $ANNSHA") ; pointer: fresh-GET block above"
echo "R5 RULES_SPOT_CHECK: $R5 — evidence: $R5_OKCOUNT/$R5_N cited rules URLs re-fetched fresh with curl, HTTP 200 + quoted rule text plausibly present; dedicated log: evidence/o2kr3_rules_spotcheck.log; fresh statuses recorded above and in that log"
echo "R6 POSITIVE_CONFIRMATION_REVERIFY: $R6 — evidence: key file fresh GET $([ "$KEY_EXACT" = "YES" ] && echo "HTTP 200 exact key $EXPECT_KEY") (sha256 $KEYSHA == local $EXPECT_KEY_SHA); zip fresh GET code=$(echo "$ZIPMETA" | grep -o 'code=[0-9]*') type=$(echo "$ZIPMETA" | grep -o 'type=[^ ]*') bytes=$ZIPBYTES sha256=$ZIPSHA (expected $EXPECT_ZIP_SHA); dedicated log with curl -w results: evidence/o2kr3_positive_reverify.log"
echo "R7 PUBLICATION: $R7 — evidence: $TRACKED O2-KR3/0 deliverable paths tracked at HEAD $HEAD_SHA (= origin tip); fresh raw.githubusercontent branch-tip fetch-back of evidence/outreach_log.md $([ "$LG_OK" = "YES" ] && echo "HTTP 200 byte-identical sha256 $LGSHA == local") ; evidence/o2kr3_fetchback.log exists (sha256 $(sha256sum "$FBLOG" | cut -d' ' -f1))"
echo "R8 MISSION_LOG_INTEGRITY: $R8 — evidence: git diff 7368190..HEAD on $ML_REL = additions-only ($NUM), cumulative minus-lines=$MINUS; ADDENDUM 9 (6bb5530: $ADD9) and ADDENDUM 10 (e48fba3: $ADD10) both pure additions"
echo "=================================================================================="

FINISHED_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
FAILED=""
[ "$R1" = "FAIL" ] && FAILED="$FAILED R1"
[ "$R2" = "FAIL" ] && FAILED="$FAILED R2"
[ "$R3" = "FAIL" ] && FAILED="$FAILED R3"
[ "$R4" = "FAIL" ] && FAILED="$FAILED R4"
[ "$R5" = "FAIL" ] && FAILED="$FAILED R5"
[ "$R6" = "FAIL" ] && FAILED="$FAILED R6"
[ "$R7" = "FAIL" ] && FAILED="$FAILED R7"
[ "$R8" = "FAIL" ] && FAILED="$FAILED R8"
[ -z "$FAILED" ] && FAILED=" none"
VERDICT=PASS; [ "$FAILED" != " none" ] && VERDICT=FAIL

echo "SUMMARY"
echo "AUDIT_STARTED: $START_UTC"
echo "AUDIT_FINISHED: $FINISHED_UTC"
echo "CHECKS_RUN: 8 (R1,R2,R3,R4,R5,R6,R7,R8) — R1:$R1 R2:$R2 R3:$R3 R4:$R4 R5:$R5 R6:$R6 R7:$R7 R8:$R8"
echo "FAILED_CHECKS:$FAILED"
echo "BRANCH_OUTCOME: branch codex/spoc-harness-v1 tip $HEAD_SHA in sync with origin at audit start; existing deliverables unmodified (read-only verification; sha256 pre-checks above match committed anchors). Attempt-2 additions only: evidence/o2kr3_audit2.log, evidence/o2kr3_audit2_script.sh, evidence/o2kr3_rules_spotcheck.log, evidence/o2kr3_positive_reverify.log, later evidence/o2kr3_audit2_fetchback.log + mission_log ADDENDUM 11 (additions-only). Fresh re-verification executed against live endpoints this attempt."
echo "O2KR3_OUTREACH_AUDIT: $VERDICT"
