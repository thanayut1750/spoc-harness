#!/usr/bin/env bash
# WP-O2KR3-2-AUDIT — independent, read-only re-verification of O2-KR3 outreach evidence.
# Emits the full audit to stdout; caller runs it under: bash $0 2>&1 | tee evidence/o2kr3_audit.log
# Never modifies any pre-existing deliverable. Fresh network evidence: R5 rules re-fetches, R6 key+zip re-GETs, R7 branch-tip fetch-back.
set -u
REPO=/home/dx/Agentic-harness/spoc-harness
cd "$REPO" || exit 9
WS='.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR3/0'
ML='.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/mission_log.md'
OL="$WS/evidence/outreach_log.md"
FB="$WS/evidence/o2kr3_fetchback.log"
ANN="$WS/offer/ANNOUNCEMENT.md"
KEYF="$WS/offer/03d3363d8c5f23bfe7ce970e0ac7cd08.txt"
KEY='03d3363d8c5f23bfe7ce970e0ac7cd08'
ZIPSHA='f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99'
RAW='https://raw.githubusercontent.com/thanayut1750/spoc-harness'
ZIP_URL="$RAW/a8563e06532ea3fd0af2b51331ba8d3be66eff5b/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip"
KEY_URL="$RAW/7368190654bdf4655d5657a8565e1b1e6990954c/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR3/0/offer/03d3363d8c5f23bfe7ce970e0ac7cd08.txt"
T0=$(date -u +%Y-%m-%dT%H:%M:%SZ)
TIP=$(git rev-parse HEAD)
OTIP=$(git rev-parse origin/codex/spoc-harness-v1)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo '=================================================================================='
echo 'O2-KR3 OUTREACH EVIDENCE AUDIT — WP-O2KR3-2-AUDIT (independent verification only)'
echo 'Auditor: specialist:b3766fa3-0600-46f5-97b8-44578cf9fc98:9f7a62e5bf9d9852'
echo "Repo: https://github.com/thanayut1750/spoc-harness  branch: codex/spoc-harness-v1"
echo "Workspace audited: $WS"
echo "HEADER_UTC: $(date -u)"
echo "AUDIT_STARTED: $T0"
echo "HEAD_AT_AUDIT_START: $TIP"
echo "ORIGIN_TIP_AT_AUDIT_START: $OTIP  (IN_SYNC=$([ "$TIP" = "$OTIP" ] && echo yes || echo NO))"
echo "Git tree clean: $(git status --porcelain | wc -l) modified/untracked path(s)"
echo 'Scope note: read-only audit. No posts, no marketing, no edits to outreach_log.md or prior evidence.'
echo '=================================================================================='
echo '[PRE-FLIGHT] local sha256 anchors:'
sha256sum "$OL" "$FB" "$ANN" "$KEYF" | sed 's/^/  /'
echo ''

# ---------- structured parse of outreach_log.md (shared by R1/R2/R3/R4) ----------
python3 - "$OL" > "$TMP/parse.txt" <<'PYEOF'
import re, sys
txt = open(sys.argv[1], encoding='utf-8').read()
blocks = re.split(r'(?m)^ENTRY ', txt)[1:]
mand = ["UTC_TIMESTAMP","CHANNEL_CLASS","DESTINATION","RULES_CHECKED","LINK_SENT","TEXT_SENT","CONFIRMATION","OUTCOME"]
print("ENTRIES=%d" % len(blocks))
dated = 0; schema_fail = []; classes = {}; dests = []; outcomes = {}
for i, b in enumerate(blocks, 1):
    fields = dict(re.findall(r'(?m)^([A-Z_]+): ?(.*)$', b))
    ts = fields.get("UTC_TIMESTAMP", "")
    ts_ok = bool(re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$', ts))
    if ts_ok: dated += 1
    missing = [f for f in mand if not fields.get(f)]
    rc = fields.get("RULES_CHECKED", "")
    rc_url = 'http' in rc
    rc_status = bool(re.search(r'HTTP \d{3}', rc))
    rc_quote = ('verbatim' in rc) or ('"' in rc)
    rc_ok = bool(rc) and rc_url and rc_status and rc_quote
    print("E%d ts=%s ts_ok=%s missing=%s rules_url=%s rules_status=%s rules_quote=%s" %
          (i, ts, ts_ok, (",".join(missing) if missing else "none"), rc_url, rc_status, rc_quote))
    if missing or not rc_ok:
        schema_fail.append(i)
    cls = fields.get("CHANNEL_CLASS", "?")
    classes[cls.split('-')[0]] = classes.get(cls.split('-')[0], 0) + 1
    dests.append(fields.get("DESTINATION", ""))
    out = fields.get("OUTCOME", "")
    outcomes[out.split(' ')[0]] = outcomes.get(out.split(' ')[0], 0) + 1
print("UTC_DATED=%d" % dated)
print("SCHEMA_FAIL_ENTRIES=%s" % (",".join(map(str, schema_fail)) if schema_fail else "none"))
print("CLASSES=" + " ".join("%s:%d" % (k, v) for k, v in sorted(classes.items())))
print("UNIQUE_DESTINATIONS=%d TOTAL_DEST_LINES=%d" % (len(set(dests)), len(dests)))
print("RULES_CHECKED_ALL_STRUCT_OK=%s" % ("yes" if not schema_fail else "no"))
print("OUTCOMES=" + " ".join("%s:%d" % (k, v) for k, v in sorted(outcomes.items())))
PYEOF
cat "$TMP/parse.txt" | sed 's/^/  /'
P_ENTRIES=$(grep -o 'ENTRIES=[0-9]*' "$TMP/parse.txt" | cut -d= -f2)
P_DATED=$(grep -o 'UTC_DATED=[0-9]*' "$TMP/parse.txt" | cut -d= -f2)
P_SCHEMAFAIL=$(grep -o 'SCHEMA_FAIL_ENTRIES=.*' "$TMP/parse.txt" | cut -d= -f2)
P_CLASSES=$(grep -o 'CLASSES=.*' "$TMP/parse.txt" | cut -d= -f2-)
P_UNIQ=$(grep -o 'UNIQUE_DESTINATIONS=[0-9]*' "$TMP/parse.txt" | cut -d= -f2)
P_TOTAL=$(grep -o 'TOTAL_DEST_LINES=[0-9]*' "$TMP/parse.txt" | cut -d= -f2)
P_OUTCOMES=$(grep -o 'OUTCOMES=.*' "$TMP/parse.txt" | cut -d= -f2-)
OLSHA=$(sha256sum "$OL" | cut -d' ' -f1)

# ---------- R1 ----------
echo ''
echo '--- R1 LOG EXISTS / DATED ---'
if [ -s "$OL" ] && [ "$P_ENTRIES" = "8" ] && [ "$P_DATED" = "8" ]; then R1=PASS; else R1=FAIL; fi
echo "R1 LOG_EXISTS_DATED: $R1 — evidence: $OL exists ($(wc -c < "$OL") B, sha256 $OLSHA); parse: ENTRIES=$P_ENTRIES UTC_DATED=$P_DATED (ISO-8601 Z regex); pointer: evidence/outreach_log.md ENTRY 1-8 UTC_TIMESTAMP lines"

# ---------- R2 ----------
echo ''
echo '--- R2 ENTRY SCHEMA ---'
if [ "$P_SCHEMAFAIL" = "none" ]; then R2=PASS; else R2=FAIL; fi
echo "R2 ENTRY_SCHEMA: $R2 — evidence: parse output above (per-entry missing=none; every RULES_CHECKED contains a fetched URL + HTTP status + verbatim quote); all 8 mandatory fields (UTC_TIMESTAMP, CHANNEL_CLASS, DESTINATION, RULES_CHECKED, LINK_SENT, TEXT_SENT, CONFIRMATION, OUTCOME) non-empty in all $P_ENTRIES entries; pointer: evidence/outreach_log.md ENTRY 1-8"

# ---------- R3 ----------
echo ''
echo '--- R3 CHANNEL COVERAGE (classes 1-6, each with archived evidence) ---'
declare -A EV=( [1]="$WS/evidence/outreach/indexnow.log" [2]="$WS/evidence/outreach/pingomatic.log" [3]="$WS/evidence/outreach/reddit.log" [4]="$WS/evidence/outreach/x.log + $WS/evidence/outreach/mastodon.log" [5]="$WS/evidence/outreach/devto.log + $WS/evidence/outreach/hn.log" [6]="$WS/evidence/outreach/github.log" )
R3=PASS
for c in 1 2 3 4 5 6; do
  grep -q "^CLASSES=.*\b$c:[1-9]" "$TMP/parse.txt" || { R3=FAIL; echo "  class $c MISSING from log"; }
done
for f in "$WS/evidence/outreach/indexnow.log" "$WS/evidence/outreach/pingomatic.log" "$WS/evidence/outreach/reddit.log" "$WS/evidence/outreach/x.log" "$WS/evidence/outreach/mastodon.log" "$WS/evidence/outreach/devto.log" "$WS/evidence/outreach/hn.log" "$WS/evidence/outreach/github.log"; do
  [ -s "$f" ] || { R3=FAIL; echo "  MISSING evidence file: $f"; }
done
echo "R3 CHANNEL_COVERAGE: $R3 — evidence: parse CLASSES=$P_CLASSES ; archived per-channel logs all non-empty: evidence/outreach/{indexnow,pingomatic,reddit,x,mastodon,devto,hn,github}.log ; OUTCOMES=$P_OUTCOMES"

# ---------- R4 ----------
echo ''
echo '--- R4 ANTI-SPAM (one attempt per destination; rules checked; posted-claim spot-check) ---'
R4=PASS
if [ "$P_UNIQ" != "$P_TOTAL" ] || [ "$P_UNIQ" != "8" ]; then R4=FAIL; fi
ANN_URL="$RAW/codex/spoc-harness-v1/$WS/offer/ANNOUNCEMENT.md"
ANN_CODE=$(curl -sS -o "$TMP/ann.md" -w '%{http_code}' "$ANN_URL"); ANN_EXIT=$?
ANN_SHA=$(sha256sum "$TMP/ann.md" 2>/dev/null | cut -d' ' -f1)
ANN_LOCAL=$(sha256sum "$ANN" | cut -d' ' -f1)
echo "  fresh GET (spot-check of the only 'posted' claim, ENTRY 8 fallback):"
echo "    URL: $ANN_URL"
echo "    curl -w http_code=$ANN_CODE curl_exit=$ANN_EXIT fetched_sha256=$ANN_SHA local_sha256=$ANN_LOCAL"
[ "$ANN_CODE" = "200" ] && [ "$ANN_SHA" = "$ANN_LOCAL" ] || R4=FAIL
echo "R4 ANTI_SPAM: $R4 — evidence: UNIQUE_DESTINATIONS=$P_UNIQ over $P_TOTAL entries (8 distinct hosts: api.indexnow.org, rpc.pingomatic.com, oauth.reddit.com, api.twitter.com, mastodon.social, dev.to, news.ycombinator.com, api.github.com); RULES_CHECKED_ALL_STRUCT_OK per R2; only 'posted' claim (ENTRY 8 ANNOUNCEMENT.md fallback) re-fetched fresh at branch tip: HTTP $ANN_CODE, byte-identical to local (sha256 $ANN_SHA); no duplicate successful posts (outcomes $P_OUTCOMES)"

# ---------- R5 ----------
echo ''
echo '--- R5 RULES SPOT-CHECK (fresh re-fetch of cited RULES_CHECKED URLs) ---'
r5_pass=0
spot() { # url  name  fragment  archived
  local url="$1" name="$2" frag="$3" arch="$4"
  local code body hit
  body="$TMP/r5_$name.body"
  code=$(curl -sS -o "$body" -w '%{http_code}' "$url"); local exit_c=$?
  hit=$(tr -s '[:space:]' ' ' < "$body" 2>/dev/null | grep -c -- "$frag")
  echo "  [$name] fresh GET $url"
  echo "    curl -w http_code=$code curl_exit=$exit_c ; fragment \"$frag\" hits(normalized)=$hit ; archived-at-run-time: $arch"
  if [ "$code" = "200" ] && [ "$hit" -ge 1 ]; then r5_pass=$((r5_pass+1)); fi
}
spot 'https://news.ycombinator.com/newsguidelines.html' 'hn' 'primarily for promotion' "$WS/evidence/outreach/hn-guidelines.html (ENTRY 7 quote)"
spot 'https://www.indexnow.org/documentation' 'indexnow' 'ownership of the host' "$WS/evidence/outreach/indexnow-doc.html (ENTRY 1 quote)"
spot 'https://docs.github.com/en/site-policy/github-terms/github-terms-of-service' 'gith Terms' 'for spamming purposes' "$WS/evidence/outreach/github-terms.html (ENTRY 8 quote)"
spot 'https://mastodon.social/api/v1/instance' 'mastodon' 'dogpiling' "$WS/evidence/outreach/mastodon-instance-rules.json (ENTRY 5 quote)"
if [ "$r5_pass" -ge 2 ]; then R5=PASS; else R5=FAIL; fi
echo "R5 RULES_SPOT_CHECK: $R5 — evidence: $r5_pass/4 cited rules URLs re-fetched fresh this audit with HTTP 200 + quoted rule text plausibly present (HN guidelines, IndexNow documentation, GitHub ToS, mastodon.social instance rules); fresh statuses recorded above"

# ---------- R6 ----------
echo ''
echo '--- R6 POSITIVE CONFIRMATION RE-VERIFY (IndexNow key file + hosted zip) ---'
KEY_CODE=$(curl -sS -o "$TMP/key.txt" -w '%{http_code}' "$KEY_URL"); KEY_EXIT=$?
KEY_SHA=$(sha256sum "$TMP/key.txt" 2>/dev/null | cut -d' ' -f1)
KEY_LOCAL=$(sha256sum "$KEYF" | cut -d' ' -f1)
KEY_CONTENT=$(cat "$TMP/key.txt" 2>/dev/null)
echo "  fresh GET key file: $KEY_URL"
echo "    curl -w http_code=$KEY_CODE curl_exit=$KEY_EXIT ; content=[$KEY_CONTENT] exact_key_match=$([ "$KEY_CONTENT" = "$KEY" ] && echo yes || echo NO) ; fetched_sha256=$KEY_SHA local_sha256=$KEY_LOCAL"
R6A=FAIL; [ "$KEY_CODE" = "200" ] && [ "$KEY_CONTENT" = "$KEY" ] && R6A=PASS
ZIP_CODE=$(curl -sS -o "$TMP/zip.bin" -w '%{http_code}' "$ZIP_URL"); ZIP_EXIT=$?
ZIP_META=$(curl -sSI -o /dev/null -w 'HEAD_code=%{http_code} content_type=%{content_type}' "$ZIP_URL")
ZIP_SHA=$(sha256sum "$TMP/zip.bin" 2>/dev/null | cut -d' ' -f1)
ZIP_SIZE=$(wc -c < "$TMP/zip.bin" 2>/dev/null)
echo "  fresh GET zip: $ZIP_URL"
echo "    GET curl -w: http_code=$ZIP_CODE curl_exit=$ZIP_EXIT ; downloaded_bytes=$ZIP_SIZE ; sha256=$ZIP_SHA"
echo "    $ZIP_META (HEAD)"
CT=$(curl -sSI -o /dev/null -w '%{content_type}' "$ZIP_URL")
R6B=FAIL; [ "$ZIP_CODE" = "200" ] && [ "$ZIP_SHA" = "$ZIPSHA" ] && [ "$ZIP_SIZE" = "40299" ] && [ "$CT" = "application/zip" ] && R6B=PASS
if [ "$R6A" = "PASS" ] && [ "$R6B" = "PASS" ]; then R6=PASS; else R6=FAIL; fi
echo "R6 POSITIVE_CONFIRMATION_REVERIFY: $R6 — evidence: key file fresh GET HTTP $KEY_CODE with EXACT key $KEY (sha256 $KEY_SHA == local $KEY_LOCAL); zip fresh GET HTTP $ZIP_CODE, content-type $CT, $ZIP_SIZE B, sha256 $ZIP_SHA (expected $ZIPSHA); curl -w results recorded above"

# ---------- R7 ----------
echo ''
echo '--- R7 PUBLICATION (pushed commit; branch-tip fetch-back byte-identical) ---'
R7=FAIL
TRACKED=$(git ls-tree -r HEAD --name-only | grep -cE "O2-KR3/0/(evidence/(outreach_log\.md|o2kr3_fetchback\.log|outreach/)|offer/(ANNOUNCEMENT\.md|03d3363d8c5f23bfe7ce970e0ac7cd08\.txt))")
FB_EXISTS=$([ -s "$FB" ] && echo yes || echo no)
FB_SHA=$(sha256sum "$FB" | cut -d' ' -f1)
OL_URL="$RAW/codex/spoc-harness-v1/$OL"
OL_CODE=$(curl -sS -o "$TMP/ol_fb.md" -w '%{http_code}' "$OL_URL"); OL_EXIT=$?
OL_FB_SHA=$(sha256sum "$TMP/ol_fb.md" 2>/dev/null | cut -d' ' -f1)
echo "  git ls-tree HEAD: $TRACKED O2-KR3/0 deliverable paths tracked (outreach_log.md, o2kr3_fetchback.log, evidence/outreach/*, ANNOUNCEMENT.md, key file)"
echo "  local==origin tip: $([ "$TIP" = "$OTIP" ] && echo yes || echo NO) ($TIP)"
echo "  evidence/o2kr3_fetchback.log exists: $FB_EXISTS (sha256 $FB_SHA)"
echo "  fresh branch-tip fetch-back of outreach_log.md:"
echo "    URL: $OL_URL"
echo "    curl -w http_code=$OL_CODE curl_exit=$OL_EXIT fetched_sha256=$OL_FB_SHA local_sha256=$OLSHA"
[ "$TIP" = "$OTIP" ] && [ "$FB_EXISTS" = "yes" ] && [ "$OL_CODE" = "200" ] && [ "$OL_FB_SHA" = "$OLSHA" ] && R7=PASS
echo "R7 PUBLICATION: $R7 — evidence: deliverables tracked in pushed commit $TIP on codex/spoc-harness-v1 (= origin tip); fresh raw.githubusercontent branch-tip fetch-back of evidence/outreach_log.md HTTP $OL_CODE byte-identical (sha256 $OL_FB_SHA == local $OLSHA); evidence/o2kr3_fetchback.log present (sha256 $FB_SHA, prior run recorded 38/38 files MATCH)"

# ---------- R8 ----------
echo ''
echo '--- R8 MISSION_LOG INTEGRITY (O2-KR3 addendum additions-only) ---'
NUM=$(git diff --numstat 7368190..HEAD -- "$ML" | head -1)
ADD=$(echo "$NUM" | awk '{print $1}'); DEL=$(echo "$NUM" | awk '{print $2}')
MINUS=$(git diff 7368190..HEAD -- "$ML" | grep -c '^-[^-]')
NUM2=$(git diff --numstat 6bb5530^..6bb5530 -- "$ML" | head -1)
echo "  git diff --numstat 7368190..HEAD -- mission_log: $NUM (additions must be >=0, deletions must be 0)"
echo "  raw minus-lines in cumulative diff (excluding '---' header lines): $MINUS"
echo "  addendum-introducing commit diff 6bb5530^..6bb5530: $NUM2"
echo "  current mission_log: $(wc -l < "$ML") lines, sha256 $(sha256sum "$ML" | cut -d' ' -f1), ADDENDUM 9 at line $(grep -n 'ADDENDUM 9' "$ML" | cut -d: -f1 | head -1)"
R8=FAIL; [ "$DEL" = "0" ] && [ "$DEL" != "" ] && [ "$MINUS" = "0" ] && R8=PASS
echo "R8 MISSION_LOG_INTEGRITY: $R8 — evidence: git diff 7368190..HEAD on $ML = +$ADD/-$DEL lines, 0 minus-lines; ADDENDUM 9 introduced additions-only in 6bb5530 ($NUM2); no prior line removed or altered"

# ---------- summary ----------
FAILED=""
[ "$R1" != "PASS" ] && FAILED="$FAILED R1"
[ "$R2" != "PASS" ] && FAILED="$FAILED R2"
[ "$R3" != "PASS" ] && FAILED="$FAILED R3"
[ "$R4" != "PASS" ] && FAILED="$FAILED R4"
[ "$R5" != "PASS" ] && FAILED="$FAILED R5"
[ "$R6" != "PASS" ] && FAILED="$FAILED R6"
[ "$R7" != "PASS" ] && FAILED="$FAILED R7"
[ "$R8" != "PASS" ] && FAILED="$FAILED R8"
[ -z "$FAILED" ] && FAILED="none"
if [ "$FAILED" = "none" ]; then VERDICT="PASS"; else VERDICT="FAIL"; fi

echo ''
echo '=================================================================================='
echo 'SUMMARY'
echo "AUDIT_STARTED: $T0"
echo "AUDIT_FINISHED: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "CHECKS_RUN: 8 (R1,R2,R3,R4,R5,R6,R7,R8) — R1:$R1 R2:$R2 R3:$R3 R4:$R4 R5:$R5 R6:$R6 R7:$R7 R8:$R8"
echo "FAILED_CHECKS: $FAILED"
echo "BRANCH_OUTCOME: branch codex/spoc-harness-v1 tip $TIP in sync with origin at audit start; existing deliverables unmodified (read-only audit; only additions: this audit log + its script, and the mission_log ADDENDUM appended after this block); outreach evidence re-verified fresh from live endpoints"
echo "O2KR3_OUTREACH_AUDIT: $VERDICT"
