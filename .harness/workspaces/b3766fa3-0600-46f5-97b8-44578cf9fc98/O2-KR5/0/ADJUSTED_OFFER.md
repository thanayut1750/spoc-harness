# ADJUSTED OFFER — Python Dev Toolkit (pydevtoolkit 1.0.0)

**Chain position:** 3 of 3, O1-KR1 fallback chain (mirrored listing → gig platforms →
adjusted offer), executed under KR O2-KR5 / WP-O2KR5-1-CHAIN.
**Adjusted at:** 2026-10-21 (UTC) by the O2-KR5 Fallback Chain Executor.
**Supersedes (price only):** `O2-KR2/2/offer/GUMROAD_LISTING_PACKAGE.md` §2 ($15.00 USD).

---

## ⚠️ HONEST STATUS — NO PURCHASABLE CHECKOUT URL EXISTS

**This document adjusts a PREPARED offer only. There is no purchasable checkout URL,
no buy URL, and no live listing.** The marketplace publish remains pending with a
human: seller credentials are unavailable on this machine (O2-KR2 machine-wide
credential sweep clean; unauthenticated marketplace API POST returned HTTP 401,
archived in O2-KR2 evidence), so this adjusted offer **cannot be bought, sold, or
fulfilled until the human completes the marketplace publish**. Any URL claiming to
sell this product did not come from this project. If and when a live listing URL is
created by the human, it will be recorded only after HTTP-200 verification in the
mission log — never pre-announced here.

## What changed

| Field | Prepared package (O2-KR2/2) | ADJUSTED (this document) |
|---|---|---|
| One-time price | $15.00 USD (cents `1500`) | **$9.00 USD (cents `900`)** |
| Marketplace fee model | ≈10% + $0.50 → ≈$13.00 net/sale | ≈10% + $0.50 → **≈$7.60 net/sale** |
| Sales to cover the $100 goal | 8 × $13.00 = $104.00 | **14 × $7.60 = $106.40** |
| Everything else | — | **unchanged** (product, deliverables, file, license, install/test instructions, permalink request) |

Rationale: with zero sales recorded and every primary/fallback outreach channel
blocked or exhausted (O2-KR3: 7 blocked + 1 posted notice; O2-KR5 chain positions 1–2
unavailable), the price is lowered from $15.00 to $9.00 to reduce the buyer's barrier
for the future listing while keeping the net-per-sale math able to reach the $100
goal (14 sales). The goal arithmetic is a prepared-plan calculation, not a projection
of actual earnings: **actual earnings to date are $0.00 (ledger `total_earned: 0`,
`entry_count: 0`) and no sale has ever occurred.**

## Unchanged offer contents (from the prepared package)

- **Product:** Python Dev Toolkit (pydevtoolkit) 1.0.0 — 16 stdlib-only, offline CLI
  developer utilities (jsonfmt, csvstat, hashfile, b64, urlenc, difftxt, regexfind,
  timestamp, textstat, uniqcount, filesize, pickrand, passwdgen, hexdump, utfcheck,
  lorem), 92-test suite, MIT license.
- **Product file (free, already hosted in this repository):**
  https://raw.githubusercontent.com/thanayut1750/spoc-harness/a8563e06532ea3fd0af2b51331ba8d3be66eff5b/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip
  (40,299 bytes; sha256 `f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99`).
  This remains a **free download** exactly as announced in `O2-KR3/0/offer/ANNOUNCEMENT.md`;
  the adjusted paid listing would only add the convenience of the marketplace purchase
  flow — the zip itself stays free here.
- **Permalink request:** `python-dev-toolkit` (as prepared in the listing package §10;
  requested only — no live product exists).
- **License:** MIT.

## For the human publisher (when unblocking)

Use the existing dashboard walkthrough `O2-KR2/2/offer/GUMROAD_HUMAN_STEP.md`, with the
single change: **set the price to `9.00` USD (API cents value `900`)** instead of
`15.00` / `1500`. After publishing, record the live URL in the mission log only after
an HTTP-200 verification, then and only then may the revenue ledger accept a real,
proof-bearing sale via `tool:7bdf3aa0d66a5279c833dabe2820f852` with `action=add`.
