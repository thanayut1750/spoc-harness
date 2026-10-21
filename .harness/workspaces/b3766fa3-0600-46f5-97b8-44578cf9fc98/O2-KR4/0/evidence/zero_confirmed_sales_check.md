# evidence/zero_confirmed_sales_check.md — O2-KR4 zero-confirmed-sales verification

UTC_NOW: 2026-10-21T05:24:04Z
kr_id: O2-KR4 (WP-O2KR4-1-LEDGER)
dependency_record: O2-KR2 terminal state "prepared-asset BLOCKED" (commits pinned below)

## Finding

**Zero confirmed sales exist. No 'add' entry is recorded in the O2-KR4 ledger.**

The dependency work package O2-KR2 terminated in the state `prepared-asset BLOCKED`:
zero Gumroad/Lemon Squeezy credentials existed machine-wide, every unauthenticated
API attempt against both payment rails returned HTTP 401, no human dashboard step
was ever completed, and consequently **no product/checkout URL was ever minted and
no live offer ever existed**. With no live offer there is no payment rail, and with
no payment rail no order/transaction/receipt can exist. Therefore the only honest
ledger state for O2-KR4 is **0 confirmed sales, $0.00 earned, 0 recorded entries**.

## Citations (every URL preflight-verified HTTP 200 with its expected marker present; see evidence/proof_preflight.log)

1. **Gumroad API path blocked — HTTP 401, no product created, no product URL returned**
   https://raw.githubusercontent.com/thanayut1750/spoc-harness/63e0f5caab3c61d1d2985a915419a1fa2ed9f8c9/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/gumroad_api_retry.log
   - HTTP 200, 6,478 B, sha256 `f9cbcb971ca6d404d42bda22d38811eef014b97be840b06bf3cd495c1b52d0e6`
   - marker `HTTP_STATUS:401` present (2 occurrences); log's own CONCLUSION: "the Gumroad API product-creation path is BLOCKED without a credential - no product was created and no product URL was returned"
   - identical content also resolves at commit pin `bc8167ca45fe4ce4c6952771000cf29b0f90cb3f` (same sha256, verified in preflight)

2. **Lemon Squeezy REST fallback blocked — HTTP 401 on GET /v1/products and POST /v1/checkouts**
   https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/lemonsqueezy_fallback_retry.log
   - HTTP 200, 4,397 B, sha256 `8c3bd823e8382ab55370317045717d42c274e6907836eda97d81acafefdc06e4`
   - marker `HTTP_STATUS: 401` present (2 occurrences — one per documented endpoint)

3. **Gumroad dashboard human step recorded blocked (no product URL)**
   https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/gumroad_human_step_outcome.md
   - HTTP 200, 3,159 B, sha256 `11fb27c65e0e97de7b4f3572118edabf7fc6027e7b5e0214596b33ac8276e129`
   - marker `OUTCOME: `blocked`` present

4. **Lemon Squeezy dashboard human step recorded blocked**
   https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/lemonsqueezy_human_step_outcome.md
   - HTTP 200, 2,810 B, sha256 `984a03e9351d0003329d917fa5bc328dc79fe81dfd128d5cfc9a46baae6283f2`
   - marker `OUTCOME: `blocked`` present; "No product" minted, no dashboard session, no credential

5. **Machine-wide credential sweep — no Gumroad/Lemon Squeezy credential exists**
   https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/gumroad_credentials_sweep.log
   - HTTP 200, 6,156 B, sha256 `aa9b29bb3124504034d61637e82975a55e084f2dafd37e916a4747abef83d205`
   - marker "No Gumroad or Lemon Squeezy credential" present

6. **Machine-wide credential sweep — ZERO Lemon Squeezy credentials**
   https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/lemonsqueezy_credentials_sweep.log
   - HTTP 200, 1,553 B, sha256 `03ae852c1258d63c16ac55c448621ee6679aebe5205bfcdbdc806e1969ccb7e3`
   - marker "ZERO Lemon Squeezy credentials" present

## Reasoning chain (each link backed by a citation above)

credentials = 0 (citations 5, 6)
  -> every API creation call returns HTTP 401 (citations 1, 2)
  -> dashboard human steps blocked, no operator available (citations 3, 4)
  -> no product/checkout URL ever minted, no live offer exists (citations 1-4)
  -> no payment rail exists, so no order/transaction/receipt can exist (citations 1-4)
  -> **confirmed sales = 0 -> ledger 'add' entries recorded by O2-KR4 = 0 -> total_earned = $0.00**

## Ledger consequence

The persistent ledger at `revenue_ledger.json` (this workspace) legitimately contains
zero entries. No entry is fabricated to progress toward the $100 goal; the shortfall
is carried honestly as **$100.00 unmet (0.0% progress)** per the baseline and final
summary runs archived in this evidence directory.
