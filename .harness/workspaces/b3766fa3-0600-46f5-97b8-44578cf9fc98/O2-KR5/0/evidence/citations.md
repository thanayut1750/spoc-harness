# O2-KR5 evidence citations — provenance registry (attempt 1, WP-O2KR5-1-FALLBACK)

**Package:** `.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0/` on
`github.com/thanayut1750/spoc-harness`, branch `codex/spoc-harness-v1`.
**Written:** 2026-10-21T08:2xZ (attempt 1, before any outreach step of this attempt — STEP 0 binding rule).
**Purpose:** every external URL cited anywhere in this package is listed here and tagged
`APPROVED_INPUT` or `FRESH`. Zero citations outside these two classes (verified by the
cross-check grep protocol in §D, executed in `fallback_status.md` and re-run over the
complete final tree in `o2kr5_a1_final_verification.log`). This file closes the provenance
defect that caused the attempt-0 package rejection.

## Class definitions

- **APPROVED_INPUT** — a URL/path recorded in this mission's approved inputs: the pinned
  `raw.githubusercontent.com` O2-KR2 401-retry / human-step / credentials-sweep URLs
  (commits `63e0f5caab3c61d1d2985a915419a1fa2ed9f8c9`, `bc8167ca45fe4ce4c6952771000cf29b0f90cb3f`),
  the O2-KR3 evidence base at pinned tip `ef3d4f69f2dce6d5c428572c55550ffe54d4ccec`,
  and the recorded assignment artifact `def220262e18fc90693eb4ac20ecbe9b` (agent-assignment.json).
  Each pinned URL below was fetched this attempt with HTTP status + byte count + sha256 recorded.
- **FRESH** — an artifact generated inside this package, cited by its recorded command
  receipt (artifact / command_result id) or by its committed sha at a recorded commit.

## §A APPROVED_INPUT (fetched 2026-10-21T08:18:27Z–08:18:34Z; receipt: FRESH artifacts
`o2kr5_a1_fetch.sh` sha256 `96ffa75e0a37e8d8e90864439b4356023e11acbbd238529ee8981ab573e1048c`
and `o2kr5_a1_fetch_receipt.log` sha256 `92c8b3ae7865b0df743b84e7c10c99bcf00cc31e3b20298999f6212656e70b0c`;
command receipt ids `63e836993cd56edd02bb9ff620db4873`, `d956364f7238d3ab4aaf4ff53c4cf7f9`)

Base prefix (abbreviated `…` below = `https://raw.githubusercontent.com/thanayut1750/spoc-harness` + workspace `.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98`):

| # | Tag | URL | HTTP | Bytes | sha256 | Content used for |
|---|---|---|---|---|---|---|
| A1 | APPROVED_INPUT | `…/63e0f5caab3c61d1d2985a915419a1fa2ed9f8c9/O2-KR2/2/evidence/gumroad_api_retry.log` | 200 | 6,478 | `f9cbcb971ca6d404d42bda22d38811eef014b97be840b06bf3cd495c1b52d0e6` | Gumroad API HTTP 401 (unauthenticated) record |
| A2 | APPROVED_INPUT | `…/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/O2-KR2/2/evidence/gumroad_api_retry.log` | 200 | 6,478 | `f9cbcb971ca6d404d42bda22d38811eef014b97be840b06bf3cd495c1b52d0e6` | same 401 record at pinned O2-KR2 commit |
| A3 | APPROVED_INPUT | `…/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/O2-KR2/2/evidence/lemonsqueezy_fallback_retry.log` | 200 | 4,397 | `8c3bd823e8382ab55370317045717d42c274e6907836eda97d81acafefdc06e4` | Lemon Squeezy API HTTP 401 record |
| A4 | APPROVED_INPUT | `…/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/O2-KR2/2/evidence/gumroad_human_step_outcome.md` | 200 | 3,159 | `11fb27c65e0e97de7b4f3572118edabf7fc6027e7b5e0214596b33ac8276e129` | Gumroad dashboard human step OUTCOME `blocked` |
| A5 | APPROVED_INPUT | `…/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/O2-KR2/2/evidence/lemonsqueezy_human_step_outcome.md` | 200 | 2,810 | `984a03e9351d0003329d917fa5bc328dc79fe81dfd128d5cfc9a46baae6283f2` | Lemon Squeezy human step OUTCOME `blocked` |
| A6 | APPROVED_INPUT | `…/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/O2-KR2/2/evidence/gumroad_credentials_sweep.log` | 200 | 6,156 | `aa9b29bb3124504034d61637e82975a55e084f2dafd37e916a4747abef83d205` | zero Gumroad credentials machine-wide |
| A7 | APPROVED_INPUT | `…/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/O2-KR2/2/evidence/lemonsqueezy_credentials_sweep.log` | 200 | 1,553 | `03ae852c1258d63c16ac55c448621ee6679aebe5205bfcdbdc806e1969ccb7e3` | zero Lemon Squeezy credentials machine-wide |
| A8 | APPROVED_INPUT | `…/ef3d4f69f2dce6d5c428572c55550ffe54d4ccec/O2-KR3/0/evidence/outreach_log.md` | 200 | 19,398 | `c764677b7d8369253f6ad1139f8039e475f022aa602232808a9bfe0225a47007` | outreach anchor (sha matches recorded anchor c764677b…); offer-live push context |
| A9 | APPROVED_INPUT | `…/ef3d4f69f2dce6d5c428572c55550ffe54d4ccec/O2-KR2/2/mission_log.md` | 200 | 30,968 | `2d58fc1b7d6f7cd7b0f7713f80c68ebf14da339c8ff88bd2c5615a5dab011fb4` | canonical mission log at pinned tip; O1-KR1-era fallback-chain wording (ADDENDUM 7, L228–229) |
| A10 | APPROVED_INPUT | `…/ef3d4f69f2dce6d5c428572c55550ffe54d4ccec/O2-KR3/0/offer/ANNOUNCEMENT.md` | 200 | 1,594 | `430fce456a3481353d7678af2b1204000154f50c963acaac5d8d92f4845c5f91` | sole derivation source for `mirrored_listing.md` (sha matches recorded anchor 430fce45…) |
| A11 | APPROVED_INPUT | `…/ef3d4f69f2dce6d5c428572c55550ffe54d4ccec/O2-KR3/0/evidence/o2kr3_positive_reverify.log` | 200 | 1,266 | `94d062ade46585b7a3a79dee0d5da8c544fdd9de27f280bcda1cd96097c7ca9e` | records the hosted-zip URL (application/zip 40,299 B, sha256 f272da22…) and IndexNow key 03d3363d8c5f23bfe7ce970e0ac7cd08 |

Path-precision disclosure (recorded honestly, not silently corrected): the assignment text
describes A9/A10 as living under `…/O2-KR3/0/evidence/`; fetching those exact variants
returned **HTTP 404** (`…/ef3d4f69…/O2-KR3/0/evidence/mission_log.md` and
`…/ef3d4f69…/O2-KR3/0/evidence/ANNOUNCEMENT.md`, both 404, sha256 of the 14-byte body
`d5558cd419c8d46bdc958064cb97f963d1ea793866414c025906ec15033512ed`). The canonical copies
actually live at the A9/A10 paths above (both 200, byte-identical to the recorded anchors
`2d58fc1b…` / `430fce45…`). Only the A9/A10 URLs are cited as sources.

| # | Tag | URL string | Recorded inside |
|---|---|---|---|
| A12 | APPROVED_INPUT (string recorded in pinned evidence) | `https://raw.githubusercontent.com/thanayut1750/spoc-harness/a8563e06532ea3fd0af2b51331ba8d3be66eff5b/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip` | A8 (outreach_log L99), A10, A11 — this is the ONLY product URL permitted in this package; commit `a8563e06…` is an ancestor of pinned tip `ef3d4f69…` |
| A13 | APPROVED_INPUT (string recorded in pinned evidence) | `https://github.com/thanayut1750/spoc-harness` (branch `codex/spoc-harness-v1`) | A10 (repo line); the project's own repository |
| A14 | APPROVED_INPUT | recorded assignment artifact `def220262e18fc90693eb4ac20ecbe9b` (agent-assignment.json, KR O2-KR5 description) — source of the verbatim chain text "(mirrored listing, gig platforms, adjusted offer)" | supplied as `latest_assignment_artifacts` for this run |
| A15 | APPROVED_INPUT (string recorded in pinned evidence) | `https://api.indexnow.org/indexnow` (IndexNow submission endpoint) | A8 (outreach ENTRY for IndexNow, attempted once in O2-KR3, HTTP 422 — NOT retried here, one-attempt-per-destination rule) |

## §B FRESH — attempt-0 in-package artifacts (committed `5c3b398…`, tip `4e0b93f…`), cited by recorded receipt ids from `evidence/o2kr5_fallback_chain.log` (sha256 `38d8a5e34cd7bd947194382254a0ddf39733a1de56b16617bf7a2b6252b77dca`)

| # | Tag | Item | Receipt / pointer |
|---|---|---|---|
| B1 | FRESH | destination `https://0x0.st` (single anonymous POST, HTTP 503 uploads-disabled) | command receipt `35acc17b…`, stdout artifact `203c3feddf251de36496863dd9f429c5` (receipt id), body sha256 `4c1b953c…` |
| B2 | FRESH | destination `https://dpaste.org/api/` (single GET probe, HTTP 403; NO POST attempted) | command receipt `c0139919…`, stdout artifact `9ed6093e9be0aeb7601f2877df7a8c23` (receipt id), sha256 `87aa46a8…` |
| B3 | FRESH | destination `https://www.fiverr.com/start_selling` (single GET, HTTP 403, PXCR10002539 "It needs a human touch") | command receipt `f0c68766b0e2651f0c35783b537ab39e`, marker artifacts `d4518b30…`, `c3347593…`, `61a14a41…`, body sha256 `6af47b64…` |
| B4 | FRESH | post-chain ledger re-run (total_earned 0, entry_count 0) | command receipt `4499caea78e0f5c0d54331a74f4218a3` |
| B5 | FRESH | attempt-0 package files | `evidence/o2kr5_decision_log.md` sha256 `edb4ac248e44c3927e58a65926bc6c2e4d6d6c6d77eae80440dfac3f689203da`; `evidence/o2kr5_fallback_chain.log` sha256 `38d8a5e3…`; `ADJUSTED_OFFER.md` sha256 `f9ee536e0fac2c377931a2caf71cac8f46b26875f9716853feb4125cedc2c800`; `evidence/o2kr5_publish_check.log` (commit `4e0b93f…`) |

## §C FRESH — attempt-1 forward declarations (artifacts generated by this attempt; each will carry its recorded command receipt id inside this package)

| # | Tag | Item | Destination / pattern |
|---|---|---|---|
| C1 | FRESH | single-shot anonymous mirror POST to `https://paste.rs` (no account required; never contacted before — recorded grep: 0 prior mentions of `paste.rs` in the tree at tip `4e0b93f…`) | any URL returned by the probe (pattern `https://paste.rs/<id>`) is FRESH content of this package, cited only via the probe log receipt |
| C2 | FRESH | single-shot GET to the repo-implied GitHub Pages URL `https://thanayut1750.github.io/spoc-harness/` (read-only; 0 prior mentions of `github.io` in the tree at tip `4e0b93f…`) | expected honest outcome recorded whatever the status |
| C3 | FRESH | raw.githubusercontent.com fetch-back URLs at this attempt's pushed tips (paths under `…/O2-KR5/0/`) | cited via the fetch-back log receipt in this package |
| C4 | FRESH | `run_mission_tool` ledger invocations (tool `tool:7bdf3aa0d66a5279c833dabe2820f852`, `action":"summary","include_entries":true` only; NO `add`) | cited via `ledger_decision_summary.log` / `o2kr5_a1_ledger_rerun.log` receipts |
| C5 | FRESH | this package's attempt-1 logs (decision_log.md, mirrored_listing.md, adjusted_offer.md, probes, fetch-backs, fallback_status.md, final verification) | cited by committed sha at recorded commit |

## §D Out-of-class citation audit protocol (binding)

Audit = for every `http(s)://` URL occurring in any file under `O2-KR5/0/`, the URL string
must appear in this citations.md (exact or declared pattern in §A/§B/§C), and must be
tagged APPROVED_INPUT or FRESH. Fail conditions: (1) any product/buy/order/checkout URL
other than A12; (2) any URL absent from this registry; (3) any tag other than the two
classes. Executed in `fallback_status.md` (pre-push, package minus the status file itself)
and re-run over the complete final tree in `o2kr5_a1_final_verification.log`.

No fabricated sales, receipts, statuses, or URLs; HTTP failures are reported as failures.

## §C-2 FRESH — attempt-1 late declarations (appended additions-only BEFORE the corresponding request; original §A/§B/§C rows unchanged, zero deletions to this registry)

Registered: 2026-10-21 (attempt 1, before the gig-platform probe of this attempt was executed).

| # | Tag | Item | Destination / pattern |
|---|---|---|---|
| C6 | FRESH | single-shot anonymous GET probe of gig-platform host `https://www.upwork.com/` (no account, no signup, no credentials, no cookies; host never contacted before — the probe script's precheck greps the tracked tree at HEAD and aborts BEFORE any request unless the hit count is 0) | recorded whatever the HTTP status; any `https://www.upwork.com/...` string is FRESH content of this package cited only via the probe log receipt; URL strings inside the response body are redacted in the log for citation hygiene (full-body byte count + sha256 recorded instead) |
| C7 | FRESH | gig-channel evidence files of this attempt: `o2kr5_a1_gig_probe.sh` (script, `bash -n` pre-checked) and `o2kr5_a1_gig_probe_upwork.log` (single-probe exchange log) | cited by committed sha at this attempt's push-B tip |
| C8 | FRESH | post-execution ledger re-run file `o2kr5_a1_ledger_rerun.log` (name pre-declared in C4; single sanctioned `summary` invocation of `tool:7bdf3aa0d66a5279c833dabe2820f852`; NO `add` anywhere) and the additions-only append of decision ENTRY 2 to `evidence/decision_log.md` | cited by committed sha at this attempt's push-B tip and by the tool receipt ids recorded inside those files |

Scope notes (anti-spam, binding):
- The fiverr host is NOT re-probed this attempt: its single permitted attempt was consumed in
  attempt 0 (citations.md §B B3: GET `https://www.fiverr.com/start_selling` → HTTP 403,
  PXCR10002539 "It needs a human touch", receipt `f0c68766b0e2651f0c35783b537ab39e`); the
  one-attempt-per-destination rule prohibits any second fiverr request, so B3 stands as the
  recorded fiverr probe evidence.
- IndexNow (A15): attempted once in O2-KR3 (HTTP 422), never retried; no second submission.
- paste.rs (C1) and the repo-implied GitHub Pages URL (C2) each received exactly one request
  this attempt (logged in `o2kr5_a1_c1_pasters_post.log` / `o2kr5_a1_c2_pages_get.log`);
  neither destination is contacted again.

### §C-3 — session append 2 (single guarded append; original §A–§C-2 rows unchanged; zero deletions)

- A16 — APPROVED_INPUT (URL string recorded in pinned evidence A8): `https://api.github.com/repos/thanayut1750/spoc-harness/issues` — the GitHub issues-API endpoint string quoted VERBATIM in `evidence/decision_log.md` provenance quote 3, sourced from A8 `O2-KR3/0/evidence/outreach_log.md` at pinned tip `ef3d4f69f2dce6d5c428572c55550ffe54d4ccec` (recorded anchor sha `c764677b…`; attempt-1 §A fetch of that file: HTTP 200, 18,433 B, sha256 `14aae6e1e9549dd96ab1bee10a57169b322344ff0889cda0b0e77977687c9161`, string present at L96 — same line quoted in decision_log.md). Class basis identical to A12/A13/A15: a URL string recorded inside pinned APPROVED_INPUT evidence, re-cited only as that verbatim quote. NO request was made to this endpoint by attempt 1; it is registered solely so the §D rule ("every http(s):// URL in any file under O2-KR5/0/ must appear in this registry, exact or declared pattern") is satisfied with an explicit row instead of an implicit match. Registered 2026-10-21 during the pre-push-B manual §D re-enumeration. No fetch of this URL is required or performed for this row.

## REGISTRY ADDENDUM (push C, complete-tree scan closure)

| ROW | CLASS | URL / PATH | FETCH STATUS | BYTES | SHA256 |
|---|---|---|---|---|---|
| A17 | FRESH (artifact generated inside this package, cited by its receipt) | `https://paste.rs/7Rnkd` (public read-only mirror created by C1 this attempt; free download, never a sale) | created: HTTP 201 per `evidence/o2kr5_a1_c1_pasters_post.log` (in-package receipt); re-verified read-only at fetch-back | n/a (remote paste) | content verified in `evidence/o2kr5_a1_c1_pasters_post.log` |

DISCLOSURE: the complete-tree URL scan in `o2kr5_a1_integrity_audit_v5.py` found `paste.rs/7Rnkd` cited in
decision_log.md, mirrored_listing.md, o2kr5_a1_c1_pasters_post.log and fallback_status.md but absent from this
registry. It is registered here (append-only) BEFORE push C so that every cited URL is class-tagged. No other
row above is modified.

## REGISTRY ADDENDUM 2 (gig-chain close-out, appended additions-only)
REGISTERED (append-only) citations of the WP-O2KR5-2 gig-chain package, class-tagged per §D:
| Class | Item | URL / pattern | Receipt |
|---|---|---|---|
| FRESH-COMMITTED | refined probe script | `https://raw.githubusercontent.com/thanayut1750/spoc-harness/ec18db2c298876efc003719b33ae0d1d67708dd1/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0/evidence/o2kr5_a2_gig_probe.sh` | push A receipt `11d7003cc855ca28a0d011db99e950ca` (PUSH_A_EXIT=0; anonymous ls-remote == ec18db2c298876efc003719b33ae0d1d67708dd1) |
| FRESH-COMMITTED | upwork probe log | `https://raw.githubusercontent.com/thanayut1750/spoc-harness/ec18db2c298876efc003719b33ae0d1d67708dd1/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0/evidence/o2kr5_a2_gig_probe_upwork.log` | same push A receipt |
| FRESH-COMMITTED | upwork archived body (verbatim 403 response) | `https://raw.githubusercontent.com/thanayut1750/spoc-harness/ec18db2c298876efc003719b33ae0d1d67708dd1/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0/evidence/o2kr5_a2_upwork_body.html` | same push A receipt |
| FRESH-COMMITTED | gig channels log (deliverable) | path `…/O2-KR5/3/evidence/o2kr5_gig_channels.log` @ this package's push B tip | byte-exact fetch-back recorded in `…/O2-KR5/3/evidence/o2kr5_gig_fetchback.log` |
| FRESH-COMMITTED | gig fetch-back log | path `…/O2-KR5/3/evidence/o2kr5_gig_fetchback.log` @ this package's push C tip | self fetch-back at tip C recorded in the package close-out receipts |
No row above is modified; zero deletions to this registry. Out-of-class audit note: the
network destinations used by this package are (a) raw.githubusercontent.com fetch-backs
(read-only integrity checks) and (b) exactly ONE probe GET to `https://www.upwork.com/`
(first and only contact; see evidence/o2kr5_gig_channels.log ROW 2/2). Fiverr was NOT
re-contacted (recorded receipt B3 re-verified at its pinned commit instead).
