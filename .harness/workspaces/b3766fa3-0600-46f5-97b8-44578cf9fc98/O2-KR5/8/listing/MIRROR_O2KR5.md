# MIRRORED LISTING (O2-KR5 fallback channel 1) — PyDevToolkit v1.0.0

- WORKSPACE: `.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/8`
- WORK PACKAGE: WP-O2KR5-1-TRIGGER-MIRROR (KR O2-KR5, attempt 8).
- PROVENANCE: byte-exact mirror of the recorded offer announcement
  `offer/ANNOUNCEMENT.md` at commit `6bb55308e7dd8e2436e182a32814e7a64cea5444`
  (committer date 2026-10-21T11:13:06+07:00 = 2026-10-21T04:13:06Z; sha256
  `430fce456a3481353d7678af2b1204000154f50c963acaac5d8d92f4845c5f91`; 1,594 bytes;
  fresh raw.githubusercontent.com fetch-back at that commit: HTTP 200, VERDICT=MATCH,
  recorded in `evidence/o2kr5_reconciliation.log` row A1).
- CHAIN POSITION: 1 of 3 — recorded O1-KR1 fallback chain
  "(mirrored listing, gig platforms, adjusted offer)" (verbatim chain text recorded in
  `O2-KR5/0/evidence/citations.md` row A14, source artifact
  `def220262e18fc90693eb4ac20ecbe9b`, KR O2-KR5 description; chain-order corroboration:
  `O2-KR5/0/ADJUSTED_OFFER.md` line 3 "Chain position: 3 of 3"). This file executes the
  mirrored-listing stage for THIS workspace via the only machine-verified publication
  channel (additions-only git push to branch `codex/spoc-harness-v1`).
- RECONCILIATION: earlier attempts already published mirrors in `O2-KR5/0`
  (`evidence/mirrored_listing.md`), `O2-KR5/2`, `O2-KR5/4`, `O2-KR5/5` and `O2-KR5/7`
  (`MIRROR_O2KR5.md` at commit `30cb3a1`, sha256 `2a21fcf7…`, fetch-back MATCH). This
  dir-8 file completes the mandated mirrored-listing deliverable for this workspace with
  fresh receipts; no external destination is contacted (one-attempt-per-destination
  preserved) and no prior file is modified.
- HONESTY: no live marketplace offer exists (O2-KR2 terminal BLOCKED — Gumroad and Lemon
  Squeezy APIs returned HTTP 401 with zero machine credentials; marketplace publish
  requires a human). This is a repository publication, not a sale, and records no revenue.
- NO INVENTED URLS: everything below the BEGIN marker is byte-identical to the source
  (`cmp`-verified). The only product URL is the recorded free-zip link reproduced
  verbatim; no buy, order, or checkout URL is added or implied.

<!-- ===== BEGIN VERBATIM MIRROR OF ANNOUNCEMENT.md (commit 6bb5530) ===== -->
# PyDevToolkit v1.0.0 — free Python CLI toolkit (zip)

**Free download (zip, 40,299 bytes):**
https://raw.githubusercontent.com/thanayut1750/spoc-harness/a8563e06532ea3fd0af2b51331ba8d3be66eff5b/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip

- zip sha256: `f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99`
- Source repo: https://github.com/thanayut1750/spoc-harness (branch `codex/spoc-harness-v1`)

## What it is

PyDevToolkit v1.0.0 is a Python CLI toolkit (developer-productivity niche) packaged as a
single downloadable zip and hosted in this public GitHub repository.

## Honest status — no purchase page exists

- The zip above is a **free** download served from this repository.
- A Gumroad listing has been packaged (`offer/GUMROAD_LISTING_PACKAGE.md`) but is
  **pending human publish**: publishing requires seller credentials that are not available
  on this machine (machine-wide credential sweep clean; unauthenticated Gumroad API POST
  returned HTTP 401, archived in O2-KR2 evidence).
- **There is no live purchase page and no buy URL.** Any URL claiming to sell this product
  did not come from this project.

## Verify the download

```
curl -L -o pydevtoolkit-1.0.0.zip <URL above>
sha256sum pydevtoolkit-1.0.0.zip
# expect: f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99
```

---
Published by the O2-KR3 outreach run at 2026-10-21T03:44Z (UTC) as the honest fallback
for the blocked GitHub issue-post attempt (HTTP 401 "Requires authentication" archived at
evidence/outreach/github.log).
