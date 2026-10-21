#!/usr/bin/env bash
set -u
S=/tmp/o2kr5_a1_fetch; rm -rf "$S"; mkdir -p "$S"
LOG="$S/fetch_log.txt"
echo "APPROVED_INPUT_FETCH_LOG" > "$LOG"
echo "RUN_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
B=.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98
R=https://raw.githubusercontent.com/thanayut1750/spoc-harness
fetch() { name="$1"; url="$2"; out="$S/$name.body"
  code=$(curl -sS -o "$out" -w '%{http_code}' "$url" 2>>"$LOG")
  sz=$(wc -c < "$out" 2>/dev/null || echo 0)
  sha=$(sha256sum "$out" 2>/dev/null | cut -d' ' -f1 || echo NA)
  { echo "FETCH name=$name http=$code bytes=$sz sha256=$sha"; echo "  url=$url"; } >> "$LOG"
}
fetch AP1_gumroad401_63e0f5ca "$R/63e0f5caab3c61d1d2985a915419a1fa2ed9f8c9/$B/O2-KR2/2/evidence/gumroad_api_retry.log"
fetch AP2_gumroad401_bc8167ca "$R/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/$B/O2-KR2/2/evidence/gumroad_api_retry.log"
fetch AP3_lemon401_bc8167ca  "$R/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/$B/O2-KR2/2/evidence/lemonsqueezy_fallback_retry.log"
fetch AP4_gumroad_human      "$R/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/$B/O2-KR2/2/evidence/gumroad_human_step_outcome.md"
fetch AP5_lemon_human        "$R/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/$B/O2-KR2/2/evidence/lemonsqueezy_human_step_outcome.md"
fetch AP6_gumroad_sweep      "$R/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/$B/O2-KR2/2/evidence/gumroad_credentials_sweep.log"
fetch AP7_lemon_sweep        "$R/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/$B/O2-KR2/2/evidence/lemonsqueezy_credentials_sweep.log"
fetch AP8_outreach_log       "$R/ef3d4f69f2dce6d5c428572c55550ffe54d4ccec/$B/O2-KR3/0/evidence/outreach_log.md"
fetch AP9a_missionlog_KR3path "$R/ef3d4f69f2dce6d5c428572c55550ffe54d4ccec/$B/O2-KR3/0/evidence/mission_log.md"
fetch AP9b_missionlog_KR2path "$R/ef3d4f69f2dce6d5c428572c55550ffe54d4ccec/$B/O2-KR2/2/mission_log.md"
fetch AP10a_ann_evidence_path "$R/ef3d4f69f2dce6d5c428572c55550ffe54d4ccec/$B/O2-KR3/0/evidence/ANNOUNCEMENT.md"
fetch AP10b_ann_offer_path   "$R/ef3d4f69f2dce6d5c428572c55550ffe54d4ccec/$B/O2-KR3/0/offer/ANNOUNCEMENT.md"
fetch AP11_reverify          "$R/ef3d4f69f2dce6d5c428572c55550ffe54d4ccec/$B/O2-KR3/0/evidence/o2kr3_positive_reverify.log"
echo "== END_FETCH_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
echo "===== FETCH LOG ====="; cat "$LOG"
echo "===== HOSTED-ZIP URL from pinned o2kr3_positive_reverify.log ====="
grep -oE 'https://raw\.githubusercontent\.com/[^ )]+' "$S/AP11_reverify.body" | sort -u
echo "===== HTTP MARKERS ====="
echo "-- AP1/AP2/AP3 401 markers --"; grep -l '401' "$S"/AP1*.body "$S"/AP2*.body "$S"/AP3*.body
echo "-- AP4/AP5 human-step headers --"; head -4 "$S/AP4_gumroad_human.body"; head -4 "$S/AP5_lemon_human.body"
echo "-- AP6/AP7 sweep tails --"; tail -3 "$S/AP6_gumroad_sweep.body"; tail -3 "$S/AP7_lemon_sweep.body"
echo "===== CHAIN QUOTE: mission_log (O2-KR2/2 @ ef3d4f69) ====="
grep -n -i -B2 -A4 'mirrored listing' "$S/AP9b_missionlog_KR2path.body" | head -40
echo "===== CHAIN QUOTE: outreach_log ====="
grep -n -i -B2 -A6 'mirrored listing' "$S/AP8_outreach_log.body" | head -40
echo "===== END_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
