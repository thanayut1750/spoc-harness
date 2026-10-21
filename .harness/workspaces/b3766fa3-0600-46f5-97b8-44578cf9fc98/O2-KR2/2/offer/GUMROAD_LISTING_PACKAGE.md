# Gumroad listing package — Python Dev Toolkit (pydevtoolkit 1.0.0) — $15.00

Work package: O2-KR2-WP1 (O2-KR2 criterion 1 — Gumroad first branch). This document
contains every field needed to create the Gumroad product listing, filled and ready to
copy in. Playbook basis: **no dedicated O2-KR2 playbook exists in the repository**; the
mandated field list is `O1-KR1/1/o1_kr1_gtm_playbook_python_dev_toolkit.md` §3
"Channel 1 — Gumroad (PRIMARY)" (steps 1–8), corroborated by
`O1-KR1/5/playbook.md` §3 Channel 1, plus the literal field list in the O2-KR2-WP1
tactical assignment. The dashboard walkthrough that consumes this package is
`offer/GUMROAD_HUMAN_STEP.md` in this directory.

Offer terms (unchanged from the audited offer copy `O2-KR2/0/store/OFFER.md`):
Gumroad fee ≈ 10% + $0.50 → **$13.00 net per $15 sale**; 8 sales cover the $100 target
(8 × $13.00 = $104).

---

## 1. Product name

**Python Dev Toolkit**

(Playbook §3 step 3 mandates the buyer-facing name `Python Dev Toolkit`; the permalink
`python-dev-toolkit` below matches it. The earlier staged draft title
"pydevtoolkit 1.0.0 — 16 CLI developer utilities" from `O2-KR2/0/store/gumroad_listing.md`
is compatible and may be used as the listing's subtitle/first description line.)

## 2. Price

**$15.00 USD** — one-time payment, single price tier. (Gumroad API cents value: `1500`.)

## 3. Product type / category

- Product type: **Digital product**
- Category: **Software** (Gumroad category "Software"; sub-topic: developer tools / CLI)
- If the dashboard requires a taxonomy selection: Software → Developer tools.

## 4. Short description (summary line, ≤ 160 characters)

```text
16 offline CLI developer utilities built on the Python standard library. JSON, CSV, hashing, text, archives: no dependencies, Python 3.8+.
```

## 5. Long description (copy verbatim)

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

## 6. What's included

- `pydevtoolkit-1.0.0.zip` — the product archive (40,299 bytes; sha256
  `f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99`)
- The `pydevtoolkit` Python package — 16 CLI utilities, all stdlib-only, offline:
  `jsonfmt` (pretty-print/compact/sort JSON), `csvstat` (CSV column stats), `hashfile`
  (sha256/md5 digests), `b64` (base64 encode/decode), `urlenc` (URL encode/decode),
  `difftxt` (line diff), `regexfind` (regex search/extract), `timestamp` (ISO-8601
  convert), `textstat` (word/char/line counts), `uniqcount` (unique-line counts),
  `filesize` (human-readable sizes), `pickrand` (random line/element pick), `passwdgen`
  (passphrase/password generator), `hexdump` (hex view), `utfcheck` (UTF-8 validation),
  `lorem` (placeholder text generator)
- 16 console-script entry points (`pydevtoolkit-jsonfmt`, `pydevtoolkit-csvstat`, …),
  each usable uninstalled as `python3 -m pydevtoolkit.<tool>`
- `README.md` (307 lines): verified install/test commands plus 16 usage sections with
  copy-ready console examples captured from real runs (Python 3.12.15)
- `install.sh` — offline wrapper installer: `sh install.sh` copies all 16 command
  wrappers into `~/.local/bin`
- `tests/` — the full test suite (92 tests, stdlib `unittest` only) + `run_tests.py`
- `LICENSE` — MIT (Copyright (c) 2026 Python Dev Toolkit contributors)

## 7. Product file (the file a buyer downloads)

Use the **commit-pinned hosted zip URL** (the file is already hosted on the repository
branch — download it in the dashboard and upload as the Gumroad product file, or keep
the URL as the content source):

```text
https://raw.githubusercontent.com/thanayut1750/spoc-harness/a8563e06532ea3fd0af2b51331ba8d3be66eff5b/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip
```

- Branch-pinned equivalent:
  `https://raw.githubusercontent.com/thanayut1750/spoc-harness/codex/spoc-harness-v1/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip`
- Size: **40,299 bytes**; Content-Type: `application/zip`; zip integrity `unzip -t` OK
- SHA-256: `f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99`
- Verify after download: `curl -sL <url> -o pydevtoolkit-1.0.0.zip && sha256sum pydevtoolkit-1.0.0.zip`
  (must print the hash above; local `O2-KR2/0/build` copy also passes
  `sha256sum -c CHECKSUMS.txt`)

## 8. Cover / thumbnail

No raster cover asset exists in the repository (the publish tool and branch carry text
artifacts only), so generate the cover in the dashboard from this prepared spec, whose
copy is taken verbatim from the audited offer copy:

- File: one 1280×720 PNG (Gumroad cover) + one 600×600 PNG (square thumbnail)
- Heading (large, centered): `Python Dev Toolkit`
- Tagline: `16 CLI developer utilities · stdlib-only · offline`
- Second line: `jsonfmt · csvstat · hashfile · b64 · urlenc · difftxt · regexfind · timestamp · textstat · uniqcount · filesize · pickrand · passwdgen · hexdump · utfcheck · lorem`
- Price badge: `$15.00`; footer: `Python 3.8+ · MIT · 92 tests`
- Copy source: `O2-KR2/0/store/OFFER.md` ("The offer" table + description block)

## 9. Post-purchase install & test instructions (from `pydevtoolkit-1.0.0/README.md`)

Copy into the Gumroad "instructions" / receipt note:

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

## 10. Permalink / URL name

`python-dev-toolkit` → expected live URL `https://gumroad.com/l/python-dev-toolkit`
(playbook §3 step 7). **No live product exists yet** — this is the requested permalink,
not a verified offer URL.

## 11. License

MIT (see `pydevtoolkit-1.0.0/LICENSE`; included in the zip).

---

## Field checklist (gate: every row non-empty)

| Field | Value-or-reference | Playbook section |
|---|---|---|
| Product name | Python Dev Toolkit | O1-KR1/1 §3 step 3; O1-KR1/5 §3 step 3 |
| Price | $15.00 USD one-time (cents 1500) | O1-KR1/1 §3 step 4; O1-KR1/5 §3 step 4 ($15) |
| Product type / category | Digital product; Software (developer tools) | Gumroad dashboard field; O1-KR1/1 §3 step 3 |
| Short description | 16 offline CLI developer utilities built on the Python standard library… (§4 above) | O2-KR2-WP1 field list (no O2-KR2 playbook; source copy O2-KR2/0/store/OFFER.md) |
| Long description | Python Dev Toolkit (pydevtoolkit) 1.0.0 — 16 command-line developer utilities… (§5 above, verbatim from OFFER.md) | O1-KR1/1 §3 step 6 (prepared listing copy, §5) |
| What's included | zip + 16 utilities + console scripts + README 307 lines + install.sh + 92-test suite + MIT LICENSE (§6 above) | O1-KR1/1 §3 step 6 (what's included) |
| Product file | https://raw.githubusercontent.com/thanayut1750/spoc-harness/a8563e06532ea3fd0af2b51331ba8d3be66eff5b/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip (application/zip, 40,299 B, sha256 f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99) | O1-KR1/1 §3 step 5 (upload staged ZIP bundle) |
| Cover / thumbnail | Generated in-dashboard per spec in §8 (1280×720 + 600×600 PNG; copy verbatim from O2-KR2/0/store/OFFER.md; no raster asset exists in-repo) | O1-KR1/1 §3 step 5 (attach cover image + thumbnail) |
| Install instructions | unzip → `python3 -m pip install --no-build-isolation .` → `python3 run_tests.py` (92 tests); offline `sh install.sh` (§9, from README §Install) | O1-KR1/1 §3 step 6 (quickstart); pydevtoolkit-1.0.0/README.md §Install |
| Test instructions | `python3 run_tests.py` from the extracted directory — 92 tests, exit 0 only if all pass (§9, from README §Run the tests) | O1-KR1/1 §3 step 6 (quickstart); pydevtoolkit-1.0.0/README.md §Run the tests |
| Permalink / URL name | python-dev-toolkit → https://gumroad.com/l/python-dev-toolkit (requested; not yet live) | O1-KR1/1 §3 step 7 |
| License | MIT (pydevtoolkit-1.0.0/LICENSE, included in zip) | O1-KR1/1 §3 step 6 (license) |

End of package. The consuming walkthrough is `offer/GUMROAD_HUMAN_STEP.md`; its
recorded outcome lives in `evidence/gumroad_human_step_outcome.md`. No live offer URL
exists at the time of writing; any live URL will be recorded only in the mission log
after HTTP-200 verification.
