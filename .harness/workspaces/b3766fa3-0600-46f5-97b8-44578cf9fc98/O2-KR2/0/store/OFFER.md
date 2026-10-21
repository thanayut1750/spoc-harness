# OFFER — pydevtoolkit 1.0.0 · $15.00 · offer copy (listing-ready)

STATUS: **prepared-asset mode.** Both automated publish channels were attempted for real and
blocked (evidence archived in `evidence/publish/BLOCKERS.md`):

* **Gumroad API** — `POST https://api.gumroad.com/v2/products` returned **HTTP 401**
  (no access token in environment) — `evidence/publish/gumroad_attempt.log`, 2026-10-20T22:12:53Z.
* **Lemon Squeezy REST API** — `POST https://api.lemonsqueezy.com/v1/products` returned
  **HTTP 405 Method Not Allowed**: the API answered that `v1/products` supports **GET, HEAD
  only**, so products cannot be created via REST at all — `evidence/publish/lemonsqueezy_attempt.log`,
  2026-10-20T22:13:33Z (raw error body in `evidence/publish/lemonsqueezy_body.txt`).

This document is **offer copy only**. It requests no action, collects no checkout link, and
mints no link. Minting is governed by the branch's single paste-checkout-link instruction
document: `../../1/offer/CHECKOUT_INSTRUCTIONS.md` (path relative to this file; branch
`codex/spoc-harness-v1`), whose consolidated blocker archive is
`../../1/evidence/BLOCKER_EVIDENCE.md`. No checkout link exists yet.

> Supersession note (audit WP-O2KR2-2, 2026-10-21): this file previously self-described as the
> "single hand-off instruction" and carried Step A / Step B dashboard walkthroughs ending in
> checkout-link paste actions. That role now belongs exclusively to
> `offer/CHECKOUT_INSTRUCTIONS.md`, so the branch carries exactly one checkout instruction
> document. All offer terms below are unchanged from the prior revision of this file.

## The offer

| Field | Value |
|---|---|
| Product name | pydevtoolkit 1.0.0 — 16 CLI developer utilities |
| Price | **$15.00 USD** (API cents value: `1500`) |
| License | MIT (file included in both packages) |
| Assets | `build/pydevtoolkit-1.0.0.zip` (40,299 B) · `build/pydevtoolkit-1.0.0.tar.gz` (19,799 B) |

**Description (use verbatim on the listing):**

> Python Dev Toolkit (pydevtoolkit) 1.0.0 — 16 command-line developer utilities built
> exclusively on the Python standard library: no third-party dependencies, no network
> access, works anywhere Python 3.8+ runs. Every utility has an argparse CLI with
> `-h/--help`, file and stdin input, and clean exit codes (0 success / 1 runtime / 2
> usage). Utilities: jsonfmt, csvstat, hashfile, b64, urlenc, difftxt, regexfind,
> timestamp, textstat, uniqcount, filesize, pickrand, passwdgen, hexdump, utfcheck,
> lorem. Install with `python3 -m pip install --no-build-isolation .` (or `sh install.sh`
> for `~/.local/bin` wrappers); run the 92-test suite with `python3 run_tests.py`.
> Full copy-paste usage examples for all 16 utilities are in the included README.md.

Longer dashboard-ready copy (with the 16-utility table and pricing/fee note):
`store/gumroad_listing.md`.

Reference REST call (as attempted; per the API's own 405 response `v1/products` accepts
GET/HEAD only, so **product creation must be done in the dashboard** — the curl below is the
exact shape that was sent, with a placeholder key, for reproduction/audit):

```console
$ curl -sS -o ls_body.txt -w 'HTTP_STATUS:%{http_code}\n' -X POST https://api.lemonsqueezy.com/v1/products \
    -H "Authorization: Bearer REPLACE_WITH_LEMON_SQUEEZY_API_KEY" \
    -H "Accept: application/vnd.api+json" \
    -H "Content-Type: application/vnd.api+json" \
    --data-binary @evidence/publish/lemonsqueezy_payload.json
```

## Assets, sizes and SHA-256 (fresh recompute)

Recomputed with `sha256sum` on 2026-10-20 (see `evidence/publish/offer_asset_checksums.log`);
**both values match `build/CHECKSUMS.txt` exactly** (`cd build && sha256sum -c CHECKSUMS.txt` → all OK).

| Asset path | Size (bytes) | SHA-256 |
|---|---|---|
| `build/pydevtoolkit-1.0.0.zip` | 40,299 | `f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99` |
| `build/pydevtoolkit-1.0.0.tar.gz` | 19,799 | `8833fb1d3d22aa94b5bdbf239e9bd2e5418d2f2ec10607a481e61bc156677eca` |

Pricing basis (playbook): Gumroad fee ≈ 10% + $0.50 → **$13.00 net per $15 sale**;
8 sales cover the $100 target (8 × $13.00 = $104).

## Evidence index

* `evidence/publish/gumroad_attempt.log` — Gumroad POST, HTTP **401**, exact command + UTC timestamps
* `evidence/publish/gumroad_body.txt` — raw Gumroad response body (0 bytes; sha256 of empty string logged)
* `evidence/publish/lemonsqueezy_attempt.log` — Lemon Squeezy POST, HTTP **405**, exact command + UTC timestamps
* `evidence/publish/lemonsqueezy_body.txt` — raw JSON:API error body (184 B)
* `evidence/publish/offer_asset_checksums.log` — fresh asset checksum recompute
* `evidence/publish/BLOCKERS.md` — blocker register (one section per blocked attempt)
* `store/PUBLISH_REPORT.md` — full execution report · `mission_log.md` — mission log entry
