#!/usr/bin/env bash
# O2-KR5 attempt-1 fetch-back: 7 new files at tip 2d5b29c... + 4 attempt-0 files at final attempt-0 tip 4e0b93f...
set -u
BASE_RAW="https://raw.githubusercontent.com/thanayut1750/spoc-harness"
W=".harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0"
TIP_PA="2d5b29c6eb0081240f41827848656a9d8e02a312"
TIP_A0="4e0b93f686d7b060f56b33f5de1cafaa00faeb0f"
LOG="o2kr5_a1_fb_body.log"
: > "$LOG"
fb() { # $1=tag $2=tip $3=relpath
  local url="$BASE_RAW/$2/$3" http body sha_local sha_remote verdict
  http=$(curl -sS -o "$LOG" -w "%{http_code}" "$url") || http="CURL_FAIL"
  if [ "$http" = "200" ]; then
    sha_remote=$(sha256sum "$LOG" | awk '{print $1}')
    sha_local=$(sha256sum "$3" | awk '{print $1}')
    if [ "$sha_remote" = "$sha_local" ]; then verdict=MATCH; else verdict=MISMATCH; fi
  else
    sha_remote="-"; sha_local="-"; verdict=FAIL_HTTP_$http
  fi
  echo "FB|$1|TIP=$2|PATH=$3|HTTP=$http|REMOTE_SHA=$sha_remote|LOCAL_SHA=$sha_local|VERDICT=$verdict"
}
i=0
for f in citations.md ledger_decision_summary.log decision_log.md mirrored_listing.md adjusted_offer.md o2kr5_a1_fetch.sh o2kr5_a1_fetch_receipt.log; do
  i=$((i+1)); fb "PA-FB$i" "$TIP_PA" "$W/evidence/$f"
done
fb "A0-FB1" "$TIP_A0" "$W/ADJUSTED_OFFER.md"
fb "A0-FB2" "$TIP_A0" "$W/evidence/o2kr5_decision_log.md"
fb "A0-FB3" "$TIP_A0" "$W/evidence/o2kr5_fallback_chain.log"
fb "A0-FB4" "$TIP_A0" "$W/evidence/o2kr5_publish_check.log"
