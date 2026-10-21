#!/usr/bin/env bash
# WP-O2KR3-1: post-push raw fetch-back of EVERY file committed in 6bb5530.
# For each file: GET raw.githubusercontent.com/<repo>/<COMMIT>/<path>,
# record HTTP status + fetched sha256 + bytes, compare byte-exact vs `git show COMMIT:<path>`.
set -u
COMMIT=6bb55308e7dd8e2436e182a32814e7a64cea5444
REPO=/home/dx/Agentic-harness/spoc-harness
PREFIX=.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98
LOG="$REPO/$PREFIX/O2-KR3/0/evidence/o2kr3_fetchback.log"
TMP=$(mktemp -d)
cd "$REPO"

{
  echo "# evidence/o2kr3_fetchback.log — O2-KR3 run 0 post-push raw fetch-back"
  echo "# Addendum 9 promised: post-push raw fetch-back of every committed file in this follow-up commit."
  echo "BRANCH: codex/spoc-harness-v1"
  echo "COMMIT_UNDER_TEST: $COMMIT"
  echo "COMMIT_SUBJECT: $(git log -1 --format=%s "$COMMIT")"
  echo "FILE_COUNT_EXPECTED: $(git diff-tree --no-commit-id --name-only -r "$COMMIT" | wc -l)"
  echo "FETCH_STARTED_UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "METHOD: curl -sS -o <tmpbody> -w '%{http_code}' <commit-pinned raw URL>; sha256(fetched) vs sha256(git show COMMIT:<path>)"
  echo "URL_BASE: https://raw.githubusercontent.com/thanayut1750/spoc-harness/$COMMIT/"
  echo
} > "$LOG"

i=0; match=0; mismatch=0; err=0
while IFS= read -r f; do
  i=$((i+1))
  url="https://raw.githubusercontent.com/thanayut1750/spoc-harness/$COMMIT/$f"
  body="$TMP/fb_$(printf '%02d' "$i")"
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  code=$(curl -sS -o "$body" -w '%{http_code}' "$url" 2>"$TMP/curlerr_$i")
  curl_exit=$?
  fsha=$(sha256sum "$body" | cut -d' ' -f1)
  fbytes=$(wc -c < "$body")
  lsha=$(git show "$COMMIT:$f" | sha256sum | cut -d' ' -f1)
  lbytes=$(git cat-file -s "$COMMIT:$f")
  if [ "$code" = "200" ] && [ "$fsha" = "$lsha" ]; then
    verdict="MATCH"
    match=$((match+1))
  else
    verdict="MISMATCH"
    mismatch=$((mismatch+1))
  fi
  {
    echo "FB$(printf '%02d' "$i") | UTC=$ts | FILE=$f"
    echo "FB$(printf '%02d' "$i") | URL=$url"
    echo "FB$(printf '%02d' "$i") | HTTP_STATUS=$code CURL_EXIT=$curl_exit FETCHED_SHA256=$fsha FETCHED_BYTES=$fbytes"
    echo "FB$(printf '%02d' "$i") | LOCAL_SHA256=$lsha LOCAL_BYTES=$lbytes"
    echo "FB$(printf '%02d' "$i") | VERDICT=$verdict"
  } >> "$LOG"
  [ -s "$TMP/curlerr_$i" ] && { cat "$TMP/curlerr_$i" >> "$LOG"; err=$((err+1)); }
done < <(git diff-tree --no-commit-id --name-only -r "$COMMIT" | sort)

{
  echo
  echo "FETCHBACK_SUMMARY: files=$i HTTP200_MATCH=$match MISMATCH=$mismatch CURL_ERRORS=$err"
  echo "FETCHBACK_FINISHED_UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "RESULT: $( [ "$match" = "$i" ] && echo ALL_COMMITTED_FILES_FETCHED_BACK_HTTP200_BYTE_EXACT || echo FAILURES_PRESENT )"
} >> "$LOG"
rm -rf "$TMP"
echo "SCRIPT_EXIT=0 match=$match mismatch=$mismatch err=$err"
