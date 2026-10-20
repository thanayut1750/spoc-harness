# OFFER — pydevtoolkit 1.0.0 · $15.00 · paste-checkout-link instruction sheet

STATUS: **prepared-asset mode.** Both automated publish channels were attempted for real and
blocked (evidence archived in `evidence/publish/BLOCKERS.md`):

* **Gumroad API** — `POST https://api.gumroad.com/v2/products` returned **HTTP 401**
  (no access token in environment) — `evidence/publish/gumroad_attempt.log`, 2026-10-20T22:12:53Z.
* **Lemon Squeezy REST API** — `POST https://api.lemonsqueezy.com/v1/products` returned
  **HTTP 405 Method Not Allowed**: the API answered that `v1/products` supports **GET, HEAD
  only**, so products cannot be created via REST at all — `evidence/publish/lemonsqueezy_attempt.log`,
  2026-10-20T22:13:33Z (raw error body in `evidence/publish/lemonsqueezy_body.txt`).

This document is the **single hand-off instruction**. Complete either Step A or Step B
(~5 minutes), then paste the resulting checkout link on the marked line below **and** write
the same URL into `store/CHECKOUT_LINK.txt` (currently an intentionally empty placeholder).

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

## PASTE CHECKOUT LINK HERE: ____________

## Step A — list on Gumroad (primary, ~5 steps)

1. Sign in at <https://gumroad.com> (create a free account if needed), then open
   <https://gumroad.com/products/new>.
2. **Name:** `pydevtoolkit 1.0.0 — 16 CLI developer utilities` · **Price:** `15` USD
   (equivalently `1500` cents — matches `price=1500` sent to the API in the archived attempt).
3. Paste the description above (or the fuller version from `store/gumroad_listing.md`)
   into the product description, and upload **both** asset files:
   `build/pydevtoolkit-1.0.0.zip` and `build/pydevtoolkit-1.0.0.tar.gz`
   (sha256 checksums below — verify after upload).
4. Click **Publish**, open the product page, and copy the checkout link
   (format `https://<your-subdomain>.gumroad.com/l/<permalink>`).
5. Paste that URL on the marked line in this document and into `store/CHECKOUT_LINK.txt`,
   then commit both.

## Step B — list on Lemon Squeezy (fallback; dashboard — REST cannot create products)

1. Sign in at <https://app.lemonsqueezy.com> (create the store if needed; TEST MODE is fine
   for staging — run the one-time activation review before selling live).
2. **Products → `+` New product**: name `pydevtoolkit 1.0.0 — 16 CLI developer utilities`,
   description as above, price **$15.00**.
3. Attach both asset files (`build/pydevtoolkit-1.0.0.zip`, `build/pydevtoolkit-1.0.0.tar.gz`)
   and set the product status to **Published**.
4. Copy the product's **buy-now / checkout URL** from the product page
   (the API calls this `buy_now_url`).
5. Paste that URL on the marked line in this document and into `store/CHECKOUT_LINK.txt`.

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
