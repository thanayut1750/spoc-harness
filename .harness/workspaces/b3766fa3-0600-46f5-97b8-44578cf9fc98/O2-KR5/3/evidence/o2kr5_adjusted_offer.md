# ADJUSTED OFFER (v2) — Python Dev Toolkit — Solo Bundle (pydevtoolkit 1.0.0)

**Document type:** OFFER DOCUMENT (an adjusted variant of the recorded prepared offer).
**Chain position:** 3 of 3, O1-KR1 fallback chain (mirrored listing → gig platforms →
adjusted offer), executed under KR O2-KR5 / WP-O2KR5-3-FALLBACK-CLOSE.
**Adjusted at:** 2026-10-21T12:20Z (UTC).
**Supersedes (price and packaging only):** `O2-KR5/0/ADJUSTED_OFFER.md` ($9.00), which
superseded the prepared package price in `O2-KR2/2/offer/GUMROAD_LISTING_PACKAGE.md` §2 ($15.00).

---

## ⚠️ HONEST STATUS — NO LIVE OFFER, NO BUY/ORDER/CHECKOUT URL EXISTS

**This document adjusts a PREPARED offer only. There is no live offer, no purchasable
checkout URL, no buy URL, and no order page of any kind.** The marketplace publish
remains pending with a human: seller credentials are unavailable on this machine
(O2-KR2 machine-wide credential sweep clean; unauthenticated marketplace API POST
returned HTTP 401, archived in O2-KR2 evidence), so this adjusted offer **cannot be
bought, sold, or fulfilled until the human completes the marketplace publish**. Any URL
claiming to sell this product did not come from this project. If and when a live listing
URL is created by the human, it will be recorded only after HTTP-200 verification in the
mission log — never pre-announced here.

**Distribution is limited to repo publication:** this offer document is published only
inside the public GitHub repository `thanayut1750/spoc-harness` on branch
`codex/spoc-harness-v1`. No external posting, mirror, ping, or submission is performed
by this package (zero new outbound contact attempts; all external channels are closed —
see Blockers).

## What changed (adjusted price / scope / packaging)

| Field | Prior adjusted offer (`O2-KR5/0/ADJUSTED_OFFER.md`) | **ADJUSTED v2 (this document)** |
|---|---|---|
| One-time price | $9.00 USD (API cents `900`) | **$7.00 USD (API cents `700`)** |
| Marketplace fee model | ≈10% + $0.50 | ≈10% + $0.50 (unchanged) |
| Net per sale | ≈$7.60 | **≈$5.80** |
| Prepared-plan sales to cover the $100 goal | 14 × $7.60 = $106.40 | **18 × $5.80 = $104.40** |
| Packaging / tier name | (untitled one-time purchase) | **"Solo Bundle"** — one-time purchase tier of the same product |
| Scope | 16 CLI tools, 92 tests, MIT | **unchanged** — the product file is byte-identical |

Rationale: with zero sales recorded and every primary/fallback channel blocked or
exhausted (O2-KR3: 7 blocked + 1 posted notice; O2-KR5 chain positions 1–2 closed —
mirrored listing published without effect on revenue, both gig platforms unavailable),
the price is lowered again from $9.00 to $7.00 to minimize the buyer's barrier for the
future listing while keeping the prepared-plan net-per-sale math able to reach the $100
goal (18 sales). **This is prepared-plan arithmetic, not a projection of actual
earnings: actual earnings to date are $0.00 (ledger `total_earned: 0`, `entry_count: 0`)
and no sale has ever occurred.**

## Unchanged offer contents (from the recorded prepared package)

- **Product:** Python Dev Toolkit (pydevtoolkit) 1.0.0 — 16 stdlib-only, offline CLI
  developer utilities (jsonfmt, csvstat, hashfile, b64, urlenc, difftxt, regexfind,
  timestamp, textstat, uniqcount, filesize, pickrand, passwdgen, hexdump, utfcheck,
  lorem), 92-test suite, MIT license.
- **Product file (free, already hosted in this repository, byte-identical):**
  https://raw.githubusercontent.com/thanayut1750/spoc-harness/a8563e06532ea3fd0af2b51331ba8d3be66eff5b/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip
  (40,299 bytes; sha256 `f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99`).
  This remains a **free download** exactly as announced in
  `O2-KR3/0/offer/ANNOUNCEMENT.md`; a future paid listing would only add the convenience
  of the marketplace purchase flow — the zip itself stays free here.
- **Permalink request (prepared only):** `python-dev-toolkit` — requested only; no live
  product exists.
- **License:** MIT.
- **Source repo:** https://github.com/thanayut1750/spoc-harness (branch `codex/spoc-harness-v1`).

The ONLY URLs in this document are the free hosted zip above and this repository. There
is no buy/order/checkout URL of any kind, and none will be invented.

## Blockers — every external channel, with recorded receipts

No compliant machine-executable sales or outreach path exists. Every external channel is
closed on recorded evidence (no new attempts made by this package):

| Channel | Recorded outcome | Receipt / evidence path |
|---|---|---|
| Gumroad API (primary listing) | **401** Unauthorized — no machine credentials exist; publish human-only | `.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/gumroad_api_retry.log` (body shows `HTTP_STATUS: 401`); credentials sweep: `…/O2-KR2/2/evidence/gumroad_credentials_sweep.log` |
| Lemon Squeezy API (fallback listing) | **401** Unauthorized — same credential blocker | `.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/lemonsqueezy_fallback_retry.log` (body shows `HTTP_STATUS: 401`); credentials sweep: `…/O2-KR2/2/evidence/lemonsqueezy_credentials_sweep.log` |
| IndexNow ping | **422** — single attempt recorded | `.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR3/0/evidence/outreach_log.md` (IndexNow 422 entry; archived body `indexnow-422-body.json`) |
| Reddit / X / Mastodon / dev.to / GitHub issues / Hacker News (outreach) | **403 block pages / 401 auth walls / login wall** — 7 destinations blocked, 1 notice posted | `.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR3/0/evidence/outreach_log.md` (8 single attempts, pinned sha256 `c764677b…`) |
| Fiverr (gig listing) | **403** PXCR10002539 "It needs a human touch" — receipt `f0c68766b0e2651f0c35783b537ab39e`; destination NOT re-contacted | `.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0/evidence/citations.md` row B3 @ `6c83c9dfc29ec1d04b5980734da5f822a99b9817`; `…/O2-KR5/3/evidence/o2kr5_gig_channels.log` ROW 1/2 |
| Upwork (gig listing) | **403** Cloudflare ("Attention Required!"; Ray `a4dfe5f8a919d326`) on the single recorded probe; account creation human-only; NOT repeated | `.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0/evidence/o2kr5_a2_gig_probe_upwork.log` @ `ec18db2c298876efc003719b33ae0d1d67708dd1`; `…/O2-KR5/3/evidence/o2kr5_gig_channels.log` ROW 2/2 |
| 0x0.st / dpaste.org (attempt-0 mirror hosts) | **503** / **403** — single attempts recorded | `.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0/evidence/citations.md` §B (receipts `35acc17b…`, `c0139919…`) |
| GitHub Pages mirror | **404** — Pages enablement is a repo-settings human step | `.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0/evidence/o2kr5_a1_c2_pages_get.log` (blocker quote recorded there) |
| paste.rs mirror | **201** created (free mirror only; never claimed as a sale); NOT re-contacted | `.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0/evidence/o2kr5_a1_c1_pasters_post.log` (mirror URL + body sha256 recorded there) |

## For the human publisher (when unblocking)

Use the existing dashboard walkthrough `O2-KR2/2/offer/GUMROAD_HUMAN_STEP.md`, with two
changes: **set the price to `7.00` USD (API cents value `700`)** instead of `15.00` /
`1500`, and use the tier/packaging name **"Solo Bundle"** in the listing copy. After
publishing, record the live URL in the mission log only after an HTTP-200 verification,
then and only then may the revenue ledger accept a real, proof-bearing sale via
`tool:7bdf3aa0d66a5279c833dabe2820f852` with `action=add`.
