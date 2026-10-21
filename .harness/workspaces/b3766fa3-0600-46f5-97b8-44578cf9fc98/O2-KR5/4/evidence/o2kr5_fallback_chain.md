# O2-KR5 FALLBACK CHAIN MAP AND CLOSE-OUT — WP-O2KR5-2-GIG-OFFER-LEDGER stage 2
GEN_UTC=2026-10-21T15:14:22Z
KR=O2-KR5 (iterate the documented O1-KR1 fallback channels until cumulative net revenue reaches $100 or all documented channels are exhausted)
CHAIN_WORDED_BY_O1_KR1="(mirrored listing, gig platforms, adjusted offer)"

| # | CHANNEL | TERMINAL STATE | EVIDENCE (receipt-cited) | REVENUE CONTRIBUTED |
|---|---------|----------------|--------------------------|---------------------|
| 0 | Primary channel (marketplace listing, O1-KR1 → O2-KR2) | BLOCKED (human publish pending) | O2-KR2 terminal: zero machine credentials; Gumroad API 401 (O2-KR2/2/evidence/gumroad_api_retry.log); Lemon Squeezy API 401 (O2-KR2/2/evidence/lemonsqueezy_fallback_retry.log); credential sweeps empty | $0.00 |
| 1 | Mirrored listing (repo publication) | ATTEMPTED — evidence logged; closed stage 1 | listing/MIRROR_O2KR5.md + evidence/o2kr5_mirrored_listing.log committed at 6ad8ddb3fe9ca2a222a3deae545f5d2be3365c4c (PUSH_EXIT=0 receipts; 4/4 fetch-backs HTTP 200 byte-exact) | $0.00 (0 sales) |
| 2 | Gig platforms — Fiverr | UNAVAILABLE — concrete blocker | evidence/o2kr5_gig_channels.log ROW 1/2: HTTP 403, PXCR10002539 "It needs a human touch", attempt-0 receipt f0c68766b0e2651f0c35783b537ab39e, capture body sha256 db306837…; no account creation permitted | $0.00 |
| 3 | Gig platforms — Upwork | UNAVAILABLE — concrete blocker | evidence/o2kr5_gig_channels.log ROW 2/2: HTTP/2 403 "server: cloudflare", cf-ray a4dfe5f8a919d326-BKK (attempt-0 receipt 53a84610dac220fc97e0174afa1c050f); dir-4 challenge body sha256 194f5ee1…; no anonymous submission path | $0.00 |
| 4 | Adjusted offer | ATTEMPTED — evidence logged | listing/OFFER_ADJUSTED_O2KR5.md (v3, price-only $7.00 → $9.00, cents 900; CALC-ONLY math $7.60 net × 14 = $106.40) published additions-only on codex/spoc-harness-v1; purchase section states the human publish step is pending per O2-KR2 and contains NO buy/order/checkout URLs; receipts in evidence/o2kr5_adjusted_offer.log | $0.00 (no live listing exists; no sale possible) |

CHAIN_STATE: EXHAUSTED — every documented channel carries exactly one recorded terminal state
(attempted-with-evidence or unavailable-with-concrete-blocker). No documented channel remains untried.

HONEST OUTCOME (restated in evidence/o2kr5_ledger_rerun.log and the decision-log ENTRY 2):
- FINAL TOTAL EARNED: $0.00 USD (ledger total_earned 0; entry_count 0; revenue_ledger.json absent — no fabricated entries)
- REMAINING GAP: $100.00 USD — GOAL NOT REACHED. The chain being exhausted, the best-achieved total is $0.00 with full evidence rather than a fabricated or optimistic figure.
