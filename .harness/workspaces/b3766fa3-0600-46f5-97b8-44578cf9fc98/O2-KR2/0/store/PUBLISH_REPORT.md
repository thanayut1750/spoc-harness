# O2-KR2 publish execution report — pydevtoolkit 1.0.0 @ $15.00

Executed by Offer Publish Chain Executor (Gumroad → Lemon Squeezy → prepared-asset).
All timestamps UTC (`date -u +%Y-%m-%dT%H:%M:%SZ`). Every HTTP fact below traces to a
saved command output; no response, status, or URL was fabricated.

**Final outcome: prepared-asset mode (terminal sanctioned fallback).** No live offer URL
exists — both automated channels were blocked for real. The single hand-off instruction
document is **`store/OFFER.md`** (exactly one `PASTE CHECKOUT LINK HERE` field);
`store/CHECKOUT_LINK.txt` is the intentionally empty placeholder.

## Per-step execution record

| # | Step | UTC timestamp | Command (exact) | Result |
|---|------|---------------|-----------------|--------|
| 0 | Workspace setup | 2026-10-20T22:05:49Z | `mkdir -p store evidence/publish`; playbook search over `*.md` (`O1-KR1` playbook found and followed for pricing/channel logic) | ready |
| 0a | Credential probe | 2026-10-20T22:05:49Z | `env \| grep -iE 'gumroad\|access_token'` | no matches — no `GUMROAD_ACCESS_TOKEN` |
| 0b | Credential probe | 2026-10-20T22:05:49Z | `env \| grep -iE 'lemon\|squeezy'` | no matches — no `LEMON_SQUEEZY_API_KEY` |
| 0c | Network sanity | 2026-10-20T22:05:49Z | real curl probe to `api.gumroad.com` | `HTTP_STATUS:401` — network was never the blocker |
| 1 | Listing content | 2026-10-20T22:12Z | wrote `store/gumroad_listing.md` | dashboard-ready: name, price 1500 (= $15), README-based description, both assets + sha256 |
| 2 | Gumroad POST (primary) | 2026-10-20T22:12:53Z–54Z | `curl -sS -o evidence/publish/gumroad_body.txt -w 'HTTP_STATUS:%{http_code}\n' -X POST https://api.gumroad.com/v2/products -d "access_token=${GUMROAD_ACCESS_TOKEN:-}" --data-urlencode "name=pydevtoolkit 1.0.0 — 16 CLI developer utilities" -d "price=1500" --data-urlencode "description=$(sed -n '1,120p' pydevtoolkit-1.0.0/README.md)"` | **BLOCKED — HTTP 401**, curl exit 0, 0-byte body (sha256 of empty string recorded) → `evidence/publish/gumroad_attempt.log` |
| 3 | LS payload | 2026-10-20T22:13Z | wrote `evidence/publish/lemonsqueezy_payload.json` (JSON:API, price 1500, published) | ready; docs fetched via `read_web_page` (docs.lemonsqueezy.com/api/products — retrieve/list only, no create endpoint) |
| 4 | Lemon Squeezy POST (fallback) | 2026-10-20T22:13:33Z–34Z | `curl -sS -o evidence/publish/lemonsqueezy_body.txt -w 'HTTP_STATUS:%{http_code}\n' -X POST https://api.lemonsqueezy.com/v1/products -H "Authorization: Bearer ${LEMON_SQUEEZY_API_KEY:-}" -H "Accept: application/vnd.api+json" -H "Content-Type: application/vnd.api+json" --data-binary @evidence/publish/lemonsqueezy_payload.json` | **BLOCKED — HTTP 405** "POST not supported for route v1/products. Supported methods: GET, HEAD." (184 B body) → `evidence/publish/lemonsqueezy_attempt.log`; product creation is dashboard-only regardless of key |
| 5 | Live-URL verification | — | not applicable | no product/checkout URL was ever returned by either channel, so no `live_url_check.log` (none required) |
| 6 | Prepared-asset mode | 2026-10-20T22:14Z | wrote `store/OFFER.md` (single hand-off doc, `grep -c 'PASTE CHECKOUT LINK HERE'` = **1**), `store/CHECKOUT_LINK.txt` (0-byte placeholder), `evidence/publish/BLOCKERS.md` | staged |
| 7 | Asset checksums | 2026-10-20T22:14:40Z | `sha256sum build/pydevtoolkit-1.0.0.zip build/pydevtoolkit-1.0.0.tar.gz`; `cd build && sha256sum -c CHECKSUMS.txt` | both OK, match `build/CHECKSUMS.txt` → `evidence/publish/offer_asset_checksums.log` (`SHA256SUM_C_EXIT:0`) |
| 8 | Git host/commit | 2026-10-20T22:18Z | `git add -f <store/ evidence/publish/ build/{zip,tar.gz,CHECKSUMS.txt}>` (`.harness/` is gitignored, `-f` required); `git commit` | **commit `3fa8026214c698d1f28e9117bbebaeeca23950ca`** — 15 files: store/ (3), evidence/publish/ (9), build/ package files (3) |
| 9 | Fresh build/ integrity | 2026-10-20T22:19:44Z | `cd build && sha256sum -c CHECKSUMS.txt` | `pydevtoolkit-1.0.0.zip: OK` / `pydevtoolkit-1.0.0.tar.gz: OK`, **exit 0** — build/ untouched by publish work |

## Deliverables

* `store/OFFER.md` — THE single paste-checkout-link instruction document (offer title,
  README description, $15 price, both assets + fresh-recomputed sha256, ~5-step Gumroad
  dashboard procedure, ready-to-run Lemon Squeezy REST curl with placeholder key, paste
  target). Published artifact `c1e3709ea22a3cb52affef770fab3392`.
* `store/gumroad_listing.md` — dashboard-ready listing (title, price 1500 = $15,
  README-based description, both asset files with sha256, fee note).
  Published artifact `3bce35f90a0123f44ad151d5e0bde9ca`.
* `store/CHECKOUT_LINK.txt` — empty placeholder (0 bytes; to be filled with the checkout
  URL by the human publisher).
* `evidence/publish/BLOCKERS.md` — blocker register, one section per blocked attempt with
  UTC timestamps, exact status lines, raw response excerpts, log paths.
  Published artifact `22772cdffcf6402958c3f5782e06008d`.
* `evidence/publish/gumroad_attempt.log` — artifact `0b1bb54fb26787dee2a0bc42d710666e`;
  raw body `gumroad_body.txt` (0 bytes — publish tool rejects empty files, bytes pinned
  in git commit `3fa8026214c698d1f28e9117bbebaeeca23950ca`).
* `evidence/publish/lemonsqueezy_attempt.log` — artifact `e666302f67d9b4494e2fee9078632e5a`;
  raw body `lemonsqueezy_body.txt` — artifact `7e0e197f69c481fd072acb819b919f9c`;
  payload `lemonsqueezy_payload.json` — artifact `16915d3b4dcba9acb69ee0ebbc9de7b4`;
  runner scripts `run_gumroad_attempt.sh` / `run_lemonsqueezy_attempt.sh`.
* `evidence/publish/offer_asset_checksums.log` — fresh recompute receipt.
* `mission_log.md` (workspace root) — O2-KR2 entry with channel outcomes, staged path,
  evidence pointers, commit hash.
* Package assets (unchanged from O2-KR1): `build/pydevtoolkit-1.0.0.zip` 40,299 B
  sha256 `f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99`;
  `build/pydevtoolkit-1.0.0.tar.gz` 19,799 B sha256
  `8833fb1d3d22aa94b5bdbf239e9bd2e5418d2f2ec10607a481e61bc156677eca`.

## Verification summary (acceptance)

* Gumroad primary executed for real: recorded block **HTTP 401** with exact status/body
  (`evidence/publish/gumroad_attempt.log`, empty body sha256 recorded).
* Lemon Squeezy REST fallback executed for real: recorded block **HTTP 405** with exact
  status/body; API corroborated as retrieve/list-only (no create endpoint) via docs.
* No live URL exists → prepared-asset mode staged: `grep -c 'PASTE CHECKOUT LINK HERE'
  store/OFFER.md` = **1**; `store/CHECKOUT_LINK.txt` present, 0 bytes; blocker evidence
  archived in `evidence/publish/BLOCKERS.md` and published.
* Offer + evidence committed to git: **`3fa8026214c698d1f28e9117bbebaeeca23950ca`**.
* `cd build && sha256sum -c CHECKSUMS.txt` → all OK, **exit 0** (fresh run
  2026-10-20T22:19:44Z); build/ artifacts unchanged throughout KR execution.

O2-KR2 publish execution: COMPLETE
