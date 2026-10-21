#!/usr/bin/env bash
# O2-KR5 dir-8 reconciliation fetch-backs (WP-O2KR5-1-TRIGGER-MIRROR).
# Read-only raw.githubusercontent.com verification of recorded anchors and of the
# pre-existing O2-KR5 evidence from earlier attempts (dirs 0,2,3,4,5,7).
# No external destination is contacted; this script only GETs repo raw content.
set -u
WS=".harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98"
R="thanayut1750/spoc-harness"
TIP="6c66cec8018960324e906d3ff9f84c03ccc6bc5f"
RAWB="https://raw.githubusercontent.com/${R}"

echo "O2KR5_DIR8_RECONCILIATION_START_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "PREWORK_TIP_EXPECTED=${TIP}"
echo "PREWORK_TIP_LSREMOTE=$(git ls-remote "https://github.com/${R}.git" refs/heads/codex/spoc-harness-v1 | awk '{print $1}')"

fetch() { # label sha-commit path expected_sha(- if none) local_path(- if none)
  label="$1"; cmt="$2"; pth="$3"; exp="$4"; loc="$5"
  body="/tmp/o2kr5fb_$(echo "$label" | tr '/' '_').bin"
  code="$(curl -sS -o "$body" -w '%{http_code}' "${RAWB}/${cmt}/${pth}")"
  rc_curl=$?
  if [ "$rc_curl" -ne 0 ]; then echo "FB ${label} CURL_EXIT=${rc_curl} HTTP=${code} VERDICT=FETCH_ERROR"; return; fi
  sha="$(sha256sum "$body" | awk '{print $1}')"
  size="$(wc -c < "$body")"
  out="FB ${label} COMMIT=${cmt} HTTP=${code} BYTES=${size} FETCHED_SHA256=${sha}"
  if [ "$exp" != "-" ]; then
    if [ "$sha" = "$exp" ]; then out="${out} EXPECTED=${exp} VERDICT=MATCH"; else out="${out} EXPECTED=${exp} VERDICT=MISMATCH"; fi
  fi
  if [ "$loc" != "-" ]; then
    lsha="$(sha256sum "$loc" | awk '{print $1}')"
    if [ "$sha" = "$lsha" ]; then out="${out} LOCAL_SHA256=${lsha} LOCAL_VERDICT=BYTE_EXACT_MATCH"; else out="${out} LOCAL_SHA256=${lsha} LOCAL_VERDICT=MISMATCH"; fi
  fi
  echo "$out"
}

ANCHOR_ANN=430fce456a3481353d7678af2b1204000154f50c963acaac5d8d92f4845c5f91
ANCHOR_OUT=c764677b7d8369253f6ad1139f8039e475f022aa602232808a9bfe0225a47007
ANCHOR_RPT=dc2b4ebae4048181cfb3e3a938eaa18cc11ce5f1f7098ad26ab62554988d41db
ANCHOR_D7MIRROR=2a21fcf7d0bbb44922edd0fba09c34391f12296dcdbc6b7dbd2ffccc9d748b6f

# (1) Recorded upstream anchors
fetch A1_ANNOUNCEMENT_AT_6BB5530 6bb55308e7dd8e2436e182a32814e7a64cea5444 "${WS}/O2-KR3/0/offer/ANNOUNCEMENT.md" "$ANCHOR_ANN" "-"
fetch A2_OUTREACH_LOG_AT_6BB5530 6bb55308e7dd8e2436e182a32814e7a64cea5444 "${WS}/O2-KR3/0/evidence/outreach_log.md" "$ANCHOR_OUT" "-"
fetch A3_EARNINGS_REPORT_AT_780D7FD 780d7fd0e57b3e1ca1f9f91ca9b9374ff1e2b459 "${WS}/O2-KR4/0/report/EARNINGS_REPORT_O2KR4.md" "$ANCHOR_RPT" "-"

# (2) Prior attempt dir-7 (rejected incomplete chain) evidence at its recorded commits
fetch B1_D7_MIRROR_AT_30CB3A1 30cb3a1c526d10d27a459c05daf22987c19c30e6 "${WS}/O2-KR5/7/listing/MIRROR_O2KR5.md" "$ANCHOR_D7MIRROR" "-"
fetch B2_D7_DECISION_LOG_AT_6C66CEC 6c66cec8018960324e906d3ff9f84c03ccc6bc5f "${WS}/O2-KR5/7/evidence/o2kr5_decision_log.md" "-" "${WS}/O2-KR5/7/evidence/o2kr5_decision_log.md"

# (3) Prior mirrors of earlier attempts, existence + byte check at current tip (read-only)
fetch C1_D0_MIRROR_AT_TIP "$TIP" "${WS}/O2-KR5/0/evidence/mirrored_listing.md" "-" "${WS}/O2-KR5/0/evidence/mirrored_listing.md"
fetch C2_D2_MIRROR_AT_TIP "$TIP" "${WS}/O2-KR5/2/listing/MIRROR_O2KR5.md" "-" "${WS}/O2-KR5/2/listing/MIRROR_O2KR5.md"
fetch C3_D4_MIRROR_AT_TIP "$TIP" "${WS}/O2-KR5/4/listing/MIRROR_O2KR5.md" "-" "${WS}/O2-KR5/4/listing/MIRROR_O2KR5.md"
fetch C4_D5_MIRROR_AT_TIP "$TIP" "${WS}/O2-KR5/5/listing/MIRROR_O2KR5.md" "-" "${WS}/O2-KR5/5/listing/MIRROR_O2KR5.md"

# (4) Verbatim quotes pinned for the decision log (from fetched bytes)
echo "QUOTE_A3=$(grep -o 'ACTUAL AMOUNT EARNED: \$0.00 USD' /tmp/o2kr5fb_A3_EARNINGS_REPORT_AT_780D7FD.bin | head -1)"
echo "QUOTE_A3b=$(grep -o 'GOAL: UNMET' /tmp/o2kr5fb_A3_EARNINGS_REPORT_AT_780D7FD.bin | head -1)"
echo "QUOTE_B1=$(grep -c -i 'gumroad' /tmp/o2kr5fb_B1_D7_MIRROR_AT_30CB3A1.bin)"

echo "O2KR5_DIR8_RECONCILIATION_END_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
