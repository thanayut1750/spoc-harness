# ADJUSTED OFFER (O2-KR5) — Version 4 (tiered-pricing adjustment)

- OFFER_ID: OFFER-ADJUSTED-O2KR5-V4
- GENERATED_UTC: 2026-10-21T17:18:13Z (authoring session; pre-work tip `f50ec538314e67ef109386a6cefdc1390ee9a49e`)
- SUPERSESSION: v4 supersedes v3 (`O2-KR5/4/listing/OFFER_ADJUSTED_O2KR5.md`, single price $9.00, sha256 `aab35d40ad0b52c4326e540ccb0c89a2a74bcc17a726733338285c0cbebf79a9`, fetch-back-verified at commit `963255f`), which superseded v2 (`O2-KR5/3/evidence/o2kr5_adjusted_offer.md`, $7.00), which superseded v1 (`O2-KR5/0/ADJUSTED_OFFER.md`, $9.00), which superseded the original listing package (`GUMROAD_LISTING_PACKAGE.md` §2, $15.00). Only the newest version on the `codex/spoc-harness-v1` branch is the current offered structure.
- ADJUSTMENT (concrete, tiered pricing): the single $9.00 price point is replaced by **two tiers** —
  - **Tier A "Solo Docs" — $5.00 USD** (API cents 500): the downloadable package plus a consolidated documentation bundle; no support included.
  - **Tier B "Solo Bundle" — $9.00 USD** (API cents 900): unchanged scope from v3 — the downloadable package plus usage support by repository issue.
  Nothing else changes.

## 1. What is being sold (scope)

- The core artifact zip remains **FREE** and is already published in this repository (no purchase required for the base artifact):
  - URL: https://raw.githubusercontent.com/thanayut1750/spoc-harness/a8563e06532ea3fd0af2b51331ba8d3be66eff5b/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip
  - Size 40,299 bytes; sha256 `f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99` (receipt: O2-KR3 positive re-verify, GET HTTP 200 application/zip).
- The paid tiers add documentation (Tier A) or documentation plus usage support (Tier B). Neither tier contains additional binary content beyond the free zip.

## 2. Price and payout math (CALC-ONLY — not a live listing)

- Tier A: price **$5.00** (API cents 500). Estimated net per sale at the recorded marketplace fee structure (10% + $0.50): $5.00 − $0.50 − $0.50 = **$4.00 net**. Sales needed to reach the $100.00 goal: 25 sales → 25 × $4.00 = **$100.00** (CALC-ONLY).
- Tier B: price **$9.00** (API cents 900). Estimated net per sale: $9.00 − $0.90 − $0.50 = **$7.60 net**. Sales needed: 14 sales → 14 × $7.60 = **$106.40** (CALC-ONLY).
- These figures are arithmetic intent only. **Zero sales have occurred; no revenue has been earned (ledger total_earned = $0.00, entry_count = 0; evidence/o2kr5_ledger_rerun.log).**

## 3. Purchase / checkout status — HONEST STATE (no invented URLs)

- **There is NO live offer and NO buy/order/checkout URL.** This document deliberately contains none.
- The marketplace publish step remains **pending with a human**, per the recorded O2-KR2 terminal BLOCKED state: no machine credentials exist; Gumroad API returned HTTP 401 and Lemon Squeezy API returned HTTP 401 on the recorded attempts (see `O2-KR2/2/evidence/gumroad_api_retry.log` and `O2-KR2/2/evidence/lemonsqueezy_fallback_retry.log`); credential sweeps found zero tokens.
- When a human completes the marketplace seller authorization, the human publish step would list the two tiers at the prices in §2. Until then, **no purchase is possible anywhere** and any page claiming to sell this package is not ours.
- Sales can only ever be recorded in the revenue ledger after (a) a live listing URL exists, (b) it is verified by an HTTP-200 fetch, and (c) a genuine receipt-bearing sale occurs. None of these conditions exists today.

## 4. Chain position

This adjusted offer is the third and final channel of the O1-KR1 fallback chain (mirrored listing → gig platforms → adjusted offer). Publishing this tiered structure in the repository is the only distribution action available to this agent; per-channel terminal states are recorded in `evidence/o2kr5_gig_channels.log` and `evidence/o2kr5_decision_log.md` (ENTRY 2).
