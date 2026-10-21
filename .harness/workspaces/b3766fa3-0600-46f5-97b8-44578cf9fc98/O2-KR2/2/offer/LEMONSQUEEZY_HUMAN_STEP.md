# offer/LEMONSQUEEZY_HUMAN_STEP.md — Lemon Squeezy dashboard listing step (human, credential-bearing)

**Invoked (UTC):** 2026-10-21T02:35:24Z
**Run:** O2-KR2 WP2 (fallback-chain Lemon Squeezy leg, dashboard branch)
**Product:** Python Dev Toolkit (pydevtoolkit 1.0.0) — $15.00 USD one-time (1,500 cents)
**Machine state:** zero Lemon Squeezy credentials exist anywhere on this machine
(evidence/lemonsqueezy_credentials_sweep.log, UTC_NOW=2026-10-21T02:04:17Z), so
the REST fallback is blocked (evidence/lemonsqueezy_fallback_retry.log: GET
/v1/products -> 401 @2026-10-21T02:34:56Z; documented POST /v1/checkouts -> 401
@2026-10-21T02:34:58Z; per the official docs product creation has no API
resource at all — evidence/lemonsqueezy_docs_notes.md). The only remaining
Lemon Squeezy path is a signed-in human performing it in the dashboard.

## Single human action (if a human with a Lemon Squeezy account executes it)

1. Sign in at https://app.lemonsqueezy.com/login (Lemon Squeezy dashboard).
2. Create a store if none exists, then create a **product** named exactly
   `Python Dev Toolkit`, priced **$15.00 USD** (one-time), category Software.
3. Upload the hosted zip by URL — use the commit-pinned file already staged and
   verified (HTTP 200, application/zip, 40,299 B,
   sha256 f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99):
   https://raw.githubusercontent.com/thanayut1750/spoc-harness/a8563e06532ea3fd0af2b51331ba8d3be66eff5b/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip
   (listing copy, price, descriptions, install/test instructions:
   offer/GUMROAD_LISTING_PACKAGE.md — channel-neutral, reuse verbatim).
4. Publish the product and copy the minted checkout/product URL.
5. Outcome goes to evidence/lemonsqueezy_human_step_outcome.md. If successful,
   the URL must be curl-verified (HTTP 200 + `15` visible) BEFORE it may be
   recorded in mission_log.md.

## Why this cannot be automated here

- Every documented REST creation resource requires `Authorization: Bearer
  {api_key}` (docs: https://docs.lemonsqueezy.com/api and
  https://docs.lemonsqueezy.com/api/checkouts/create-checkout).
- No api_key exists machine-wide (credential sweep, 4-char-prefix redaction
  applied) — verbatim 401 bodies archived in
  evidence/lemonsqueezy_fallback_retry.log.
- The agent must not invent a token, store, product or checkout URL.

**Status at write time:** awaiting a human with credentials → outcome recorded
as `blocked` in evidence/lemonsqueezy_human_step_outcome.md (2026-10-21T02:35:24Z).
