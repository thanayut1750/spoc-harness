# Gumroad dashboard-listing human step — click-by-click walkthrough
**Product:** Python Dev Toolkit (pydevtoolkit 1.0.0) · **Price:** $15.00 USD ·
**Work package:** O2-KR2-WP1 (O2-KR2 criterion 1 — Gumroad first branch)

| Header | Value |
|---|---|
| Invoked (UTC) | 2026-10-21T01:25:01Z |
| Field source | `offer/GUMROAD_LISTING_PACKAGE.md` — sha256 `3542cfa267a91f8c901730cda5086f7b96e3fef480fb87f5d17cb132e32445a6`, 10,452 B. Every block in "Copy-ready blocks" below is copied verbatim from it. |
| Recorded outcome | `evidence/gumroad_human_step_outcome.md` — **BLOCKED** at autonomous-run time (no Gumroad credential exists on this machine). Any human operator with a Gumroad account can execute the steps below and update that file to `completed`. |
| Time-box | 60 minutes (playbook `O1-KR1/1/o1_kr1_gtm_playbook_python_dev_toolkit.md` §4). |
| Fallback chain | On expiry: Lemon Squeezy dashboard (playbook ch. 2) → Fiverr gig / Upwork Project Catalog at $15 (ch. 3) → prepared-asset mode (ch. 4), which is the current staged state (`offer/CHECKOUT_INSTRUCTIONS.md`). |

## Why this is a human (credential-bearing) step

* Gumroad API: `POST https://api.gumroad.com/v2/products` → **HTTP 401** at
  `2026-10-21T00:46:55Z`–`00:46:56Z` (unauthenticated by design: no credential exists;
  verbatim capture `evidence/gumroad_api_retry.log`, `x-request-id`
  `0d645075-c56f-4638-a7b8-63ca546065f2`, body sha256
  `9db2c820f62f7e95a8b8cfb31c5f4c99d4f2b4891ad9f23291192dbaec233294`). This reproduces the
  run-1 canonical 401 of `2026-10-20T22:28:39Z` archived in
  `../1/evidence/BLOCKER_EVIDENCE.md` (sha256
  `532a1b6a29fd5def0ec19336d5c756ba48bfec95ec3bd2d012b2f288325c6649`).
* Credential sweep: **zero** Gumroad/Lemon Squeezy credentials in environment, `~/.netrc`
  (absent), `~/.config`, `~/.env*`, or git config (`evidence/gumroad_credentials_sweep.log`,
  `2026-10-21T00:46:35Z`). The dashboard session, not the API, is therefore the
  credential-bearing path (playbook §4: single irreducible human step).

## Operator prerequisites (playbook §5)

1. A web browser and an email address for a (new or existing) Gumroad account.
2. **Do not reuse any repository secret.** The only secret on this machine is the GitHub PAT
   embedded in the git origin URL — it is not a Gumroad credential and must not be entered
   into any web form.
3. The product file is **downloaded from the repository URL** in Block G below; nothing is
   uploaded from this machine to any third-party host.

## Click-by-click steps

**Step 1 — Sign up / sign in.** Open `https://gumroad.com` → click **Log in** →
**Sign up** (or the **Get started / Start selling** button). Enter your email and a
password → **Create account**. If you already have a Gumroad account, click **Log in**
instead and skip to Step 3.

**Step 2 — Verify email.** Open the Gumroad verification email and click the confirm link
(check spam). If signup is blocked (region restriction, verification loop, KYC demand), do
not stall the 60-minute box: record the verbatim blocker in
`evidence/gumroad_human_step_outcome.md` and switch to the fallback chain above (playbook
§5 skip paths).

**Step 3 — New product.** From the dashboard, left-nav **Products** → **New product**
(plus / "Add product" button).

**Step 4 — Name, price, type** (on the creation form; Block A, B, C):
- **Name:** `Python Dev Toolkit`
- **Price:** currency `USD`, amount `15` (the form shows **$15.00**)
- **Type:** select **Digital product** ("I want to sell this product" → content is a
  digital file)
- Click **Next / Create product**.

**Step 5 — Permalink / URL name** (Block J): set the URL slug to `python-dev-toolkit`.
After publishing, the product page is expected at
`https://gumroad.com/l/python-dev-toolkit`. **This is the requested permalink, not a
verified live URL** — do not treat it as live until Step 11 returns HTTP 200.

**Step 6 — Category** (Block C): if the dashboard asks for a taxonomy, choose
**Software** → **Developer tools**.

**Step 7 — Product file** (Block G): download the zip via the commit-pinned URL in
Block G (branch-pinned variant in the same block), then check the downloaded file:
`sha256sum pydevtoolkit-1.0.0.zip` must print
`f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99` (40,299 bytes). In the
Gumroad **Content** tab, upload the downloaded `pydevtoolkit-1.0.0.zip` as the product
file and confirm Gumroad reports ≈40 KB (40,299 B).

**Step 8 — Description** (Blocks D and E): copy the **long description** (Block E) into
the product **Description** field. If a separate short-summary/SEO field exists, use the
**short description** line (Block D). Optionally append the "What's included" list
(Block F) below the description.

**Step 9 — Cover and thumbnail** (Block H): in the **Checkout / design** tab, generate the
two PNG images locally per the cover spec (1280×720 cover + 600×600 square thumbnail,
copy text verbatim from Block H) and upload them.

**Step 10 — Receipt / instructions note** (Block I): if the dashboard offers an
"Instructions" or receipt-note field, copy the install/test quickstart block (Block I)
into it.

**Step 11 — Publish and verify.** Click **Publish**. Then, in a logged-out (incognito)
window, verify the page resolves:

```
curl -s -o /dev/null -w '%{http_code}' https://gumroad.com/l/python-dev-toolkit
```

Only a printed `200` counts as live. Any other status (404, 403, 000) means the listing is
not live — record the verbatim status instead.

**Step 12 — Record the outcome.**
1. Update `evidence/gumroad_human_step_outcome.md` to **`completed`** with the product URL,
   the curl status code, and an ISO-8601 UTC timestamp (a URL is recorded only after the
   HTTP-200 check above).
2. Then, and only then, perform the repository's **single** checkout-link hand-off defined
   in `offer/CHECKOUT_INSTRUCTIONS.md`. This walkthrough deliberately adds **no** second
   hand-off and contains no link blank; `store/CHECKOUT_LINK.txt` stays link-free until
   that single step completes.

## Copy-ready blocks (verbatim from `offer/GUMROAD_LISTING_PACKAGE.md`)

**Block A — Product name (Step 4)**

```text
Python Dev Toolkit
```

**Block B — Price (Step 4)**

```text
$15.00 USD — one-time payment, single price tier. (Gumroad API cents value: 1500.)
```

**Block C — Product type / category (Steps 4, 6)**

```text
Digital product; Software (developer tools)
```

**Block D — Short description (Step 8)**

```text
16 offline CLI developer utilities built on the Python standard library. JSON, CSV, hashing, text, archives: no dependencies, Python 3.8+.
```

**Block E — Long description (Step 8)**

```text
Python Dev Toolkit (pydevtoolkit) 1.0.0 — 16 command-line developer utilities built
exclusively on the Python standard library: no third-party dependencies, no network
access, works anywhere Python 3.8+ runs. Every utility has an argparse CLI with
-h/--help, file and stdin input, and clean exit codes (0 success / 1 runtime / 2
usage).

Utilities: jsonfmt, csvstat, hashfile, b64, urlenc, difftxt, regexfind, timestamp,
textstat, uniqcount, filesize, pickrand, passwdgen, hexdump, utfcheck, lorem.

Install with `python3 -m pip install --no-build-isolation .` (or `sh install.sh` for
~/.local/bin wrappers); run the 92-test suite with `python3 run_tests.py`. Full
copy-paste usage examples for all 16 utilities are in the included README.md.

What you get: a 40 KB zip with the pydevtoolkit package, 16 console scripts, a 307-line
README with verified install/test commands and per-utility examples, the MIT license,
and the full 92-test stdlib unittest suite. Verified offline: `python3 -m pip install
--no-build-isolation .` exits 0 ("Successfully installed pydevtoolkit-1.0.0") and
`python3 run_tests.py` runs all 92 tests with exit 0.
```

**Block F — What's included (optional, Step 8)**

```text
- `pydevtoolkit-1.0.0.zip` — the product archive (40,299 bytes; sha256
  f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99)
- The `pydevtoolkit` Python package — 16 CLI utilities, all stdlib-only, offline:
  jsonfmt (pretty-print/compact/sort JSON), csvstat (CSV column stats), hashfile
  (sha256/md5 digests), b64 (base64 encode/decode), urlenc (URL encode/decode),
  difftxt (line diff), regexfind (regex search/extract), timestamp (ISO-8601
  convert), textstat (word/char/line counts), uniqcount (unique-line counts),
  filesize (human-readable sizes), pickrand (random line/element pick), passwdgen
  (passphrase/password generator), hexdump (hex view), utfcheck (UTF-8 validation),
  lorem (placeholder text generator)
- 16 console-script entry points (`pydevtoolkit-jsonfmt`, `pydevtoolkit-csvstat`, …),
  each usable uninstalled as `python3 -m pydevtoolkit.<tool>`
- `README.md` (307 lines): verified install/test commands plus 16 usage sections with
  copy-ready console examples captured from real runs (Python 3.12.15)
- `install.sh` — offline wrapper installer: `sh install.sh` copies all 16 command
  wrappers into `~/.local/bin`
- `tests/` — the full test suite (92 tests, stdlib `unittest` only) + `run_tests.py`
- `LICENSE` — MIT (Copyright (c) 2026 Python Dev Toolkit contributors)
```

**Block G — Product file (Step 7)** — download this, verify the sha256, upload the
downloaded file as the Gumroad content:

```text
https://raw.githubusercontent.com/thanayut1750/spoc-harness/a8563e06532ea3fd0af2b51331ba8d3be66eff5b/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip
```

- Branch-pinned equivalent:
  `https://raw.githubusercontent.com/thanayut1750/spoc-harness/codex/spoc-harness-v1/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip`
- Size: **40,299 bytes**; Content-Type: `application/zip`; `unzip -t` OK
- SHA-256: `f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99`
- Verify after download: `curl -sL <url> -o pydevtoolkit-1.0.0.zip && sha256sum pydevtoolkit-1.0.0.zip`

**Block H — Cover / thumbnail spec (Step 9)** (no raster cover exists in the repository —
generate the images in any editor from this spec; copy text verbatim):

```text
- File: one 1280×720 PNG (Gumroad cover) + one 600×600 PNG (square thumbnail)
- Heading (large, centered): `Python Dev Toolkit`
- Tagline: `16 CLI developer utilities · stdlib-only · offline`
- Second line: `jsonfmt · csvstat · hashfile · b64 · urlenc · difftxt · regexfind · timestamp · textstat · uniqcount · filesize · pickrand · passwdgen · hexdump · utfcheck · lorem`
- Price badge: `$15.00`; footer: `Python 3.8+ · MIT · 92 tests`
```

**Block I — Post-purchase install & test instructions (Step 10)** (from
`pydevtoolkit-1.0.0/README.md`):

```text
QUICKSTART (from pydevtoolkit-1.0.0/README.md)

1. Unzip the download and enter the directory:

   unzip pydevtoolkit-1.0.0.zip
   cd pydevtoolkit-1.0.0

2. Install (verified command — run from this directory; offline, exits 0):

   python3 -m pip install --no-build-isolation .

   This installs the pydevtoolkit package and 16 console scripts
   (pydevtoolkit-jsonfmt, pydevtoolkit-csvstat, ...). Use `python3 -m pip` rather
   than bare `pip` so the package installs into the same interpreter as `python3`.

   Offline alternative (no pip needed): `sh install.sh` copies ready-to-use wrappers
   for all 16 commands into ~/.local/bin and prints every installed path. This form
   works even when an extraction tool drops the executable bit. Each utility also
   runs without installing: python3 -m pydevtoolkit.<tool>.

3. Run the tests (single command, run from this directory; 92 tests, exit 0 only if
   every test passes):

   python3 run_tests.py

4. Try a utility:

   printf '{"name":"ada","ok":true}\n' | python3 -m pydevtoolkit.jsonfmt -s

Full per-utility ready-to-copy examples (16 sections) are in README.md.
License: MIT — see the LICENSE file at the package root.
```

**Block J — Permalink (Step 5)**

```text
python-dev-toolkit
```

## Explicit non-claims

* **No product exists yet and no live URL is claimed.**
  `https://gumroad.com/l/python-dev-toolkit` is the **requested** permalink (package §10),
  never a verified offer URL.
* The single checkout-link hand-off remains `offer/CHECKOUT_INSTRUCTIONS.md`; this
  document duplicates nothing and `store/CHECKOUT_LINK.txt` stays link-free until that
  step completes with a verifiably live URL.
