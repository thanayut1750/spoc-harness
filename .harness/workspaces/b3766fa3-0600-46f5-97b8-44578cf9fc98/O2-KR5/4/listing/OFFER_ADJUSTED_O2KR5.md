# ADJUSTED OFFER (O2-KR5) — Version 3 (price-only adjustment)

- OFFER_ID: OFFER-ADJUSTED-O2KR5-V3
- GENERATED_UTC: 2026-10-21T15:14:22Z
- SUPERSESSION: v3 supersedes v2 (`O2-KR5/3/evidence/o2kr5_adjusted_offer.md`, $7.00, sha256 8f126fe115c9f224247ef77e2365c62f6e80d4acf0e3265995f82ab2c593f01a), which superseded v1 (`O2-KR5/0/ADJUSTED_OFFER.md`, $9.00), which superseded the original listing package (`GUMROAD_LISTING_PACKAGE.md` §2, $15.00). Only the newest version on the `codex/spoc-harness-v1` branch is the current offered price point.
- ADJUSTMENT (concrete, price-only): price point **$7.00 → $9.00 USD** (Gumroad API cents **700 → 900**). Tier name and scope are unchanged from v2 ("Solo Bundle": the same downloadable package plus usage support). Nothing else changes.

## 1. What is being sold (scope, unchanged from v2)

- Tier: **Solo Bundle** — the complete spoc-harness deliverable package plus usage support by repository issue.
- The core artifact zip remains **FREE** and is already published in this repository (no purchase required for the base artifact):
  - URL: https://raw.githubusercontent.com/thanayut1750/spoc-harness/a8563e06532ea3fd0af2b51331ba8d3be66eff5b/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/artifacts/spoc_harness_bundle.zip
  - Size 40,299 bytes; sha256 f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99 (receipt: O2-KR3 positive re-verify, GET HTTP 200 application/zip).
- The paid tier adds usage support and consolidated documentation. It contains no additional binary content beyond the free zip.

## 2. Price and payout math (CALC-ONLY — not a live listing)

- Price point: **$9.00 USD** (API cents 900).
- Estimated net per sale at the recorded marketplace fee structure (10% + $0.50): $9.00 − $0.90 − $0.50 = **$7.60 net** (CALC-ONLY).
- Sales needed to reach the $100.00 goal: ⌈$100.00 / $7.60⌉ = **14 sales** → 14 × $7.60 = **$106.40** (CALC-ONLY).
- These figures are arithmetic intent only. **Zero sales have occurred; no revenue has been earned (ledger total_earned = $0.00, entry_count = 0).**

## 3. Purchase / checkout status — HONEST STATE (no invented URLs)

- **There is NO live offer and NO buy/order/checkout URL.** This document deliberately contains none.
- The marketplace publish step remains **pending with a human**, per the recorded O2-KR2 terminal BLOCKED state: no machine credentials exist; Gumroad API returned HTTP 401 and Lemon Squeezy API returned HTTP 401 on the recorded attempts (see `O2-KR2/2/evidence/gumroad_api_retry.log` and `O2-KR2/2/evidence/lemonsqueezy_fallback_retry.log`); credential sweeps found zero tokens.
- When a human completes the marketplace seller authorization, the human publish step would list the Solo Bundle at the price in §2. Until then, **no purchase is possible anywhere** and any page claiming to sell this package is not ours.
- Sales can only ever be recorded in the revenue ledger after (a) a live listing URL exists, (b) it is verified by an HTTP-200 fetch, and (c) a genuine receipt-bearing sale occurs. None of these conditions exists today.

## 4. Chain position

This adjusted offer is the third and final channel of the O1-KR1 fallback chain (mirrored listing → gig platforms → adjusted offer). Publishing this price-point adjustment in the repository is the only distribution action available to this agent; see `evidence/o2kr5_fallback_chain.md` for the full chain close-out.
