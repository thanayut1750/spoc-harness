# CHECKOUT INSTRUCTIONS — pydevtoolkit 1.0.0 ($15.00 USD)

**Status: prepared-asset mode, STAGED. No checkout link exists yet. This is the single
hand-off document for minting one. Nothing in this document mints or implies a checkout
link.**

## The one action (must be performed by a human)

1. Create the product on **Gumroad or Lemon Squeezy** at **$15.00 USD** (price
   `1500` cents), attach the hosted zip URL below as the product file, **publish** the
   product, then **paste the minted checkout link into `store/CHECKOUT_LINK.txt`**
   (branch `codex/spoc-harness-v1`, path
   `.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/1/store/CHECKOUT_LINK.txt`).

That is the only action this document requests. Nothing else needs to change.

## Reference data (verified)

| Item | Value |
|---|---|
| Product (suggested name) | pydevtoolkit 1.0.0 — 16 CLI developer utilities |
| Price | **$15.00 USD** (1500 cents) |
| Hosted zip (branch-pinned) | `https://raw.githubusercontent.com/thanayut1750/spoc-harness/codex/spoc-harness-v1/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip` |
| Hosted zip (commit-pinned, immutable) | `https://raw.githubusercontent.com/thanayut1750/spoc-harness/a8563e06532ea3fd0af2b51331ba8d3be66eff5b/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip` |
| Hosted zip **sha256** | `f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99` |
| Hosted zip size / integrity | 40,299 bytes · `unzip -t` OK · serves HTTP 200 `application/zip` |
| Offer copy (OFFER.md) | `https://raw.githubusercontent.com/thanayut1750/spoc-harness/codex/spoc-harness-v1/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/store/OFFER.md` |
| Checkout-link destination | `store/CHECKOUT_LINK.txt` (currently contains no link — by design) |
| Blocker archive | `evidence/BLOCKER_EVIDENCE.md` (why the automated channels are blocked) |

## Why a human action is required

Both automated channels are blocked and archived in `evidence/BLOCKER_EVIDENCE.md`:
Gumroad `POST /v2/products` → **HTTP 401** (no credentials exist in this environment);
Lemon Squeezy `POST /v1/products` → **HTTP 405** "The POST method is not supported for
route v1/products. Supported methods: GET, HEAD." (product creation via REST is
structurally impossible here regardless of key).

## What this document does NOT contain

No checkout URL — no real, example, sample, or placeholder checkout link appears anywhere
in this document, because none has been minted. The checkout link exists only after a
human completes the single action above, and it then lives in `store/CHECKOUT_LINK.txt`.
