# Gumroad listing — pydevtoolkit 1.0.0

Dashboard-ready listing content for the Gumroad product page.
Prepared: 2026-10-20 (UTC). Offer price: **$15.00** (Gumroad API `price=1500` cents).

## Product fields

| Field | Value |
|---|---|
| Name | pydevtoolkit 1.0.0 — 16 CLI developer utilities |
| Price | 1500 (Gumroad cents = **$15.00**) |
| Type | Digital product |
| Content | Attach both asset files below (zip + tar.gz) |

## Short description (product summary box)

16 command-line developer utilities built exclusively on the Python standard
library — no dependencies, no network access, runs anywhere Python 3.8+ runs.

## Description (README-based)

**Python Dev Toolkit (pydevtoolkit) 1.0.0** is a collection of **16
command-line developer utilities built exclusively on the Python standard
library** — no third-party dependencies, no network access, and it works
anywhere Python 3.8+ runs (the packaged test suite was verified with Python
3.12.15). Every utility exposes an argparse CLI with `-h/--help`, a
`main(argv) -> int` entry point that returns 0 on success, file **and** stdin
input, and seedable randomness where output is random.

**The 16 utilities:**

* `jsonfmt` — pretty-print, compact, or key-sort JSON
* `csvstat` — CSV summary: row/column counts and min/max/mean per numeric column
* `hashfile` — md5/sha1/sha256 digests of files or stdin
* `b64` — Base64 encode/decode text
* `urlenc` — percent-encode/decode strings, files, or stdin
* `difftxt` — unified line diff between two text files
* `regexfind` — regex matches with optional line numbers and capture groups
* `timestamp` — convert epoch seconds to ISO-8601 UTC and back
* `textstat` — line/word/char counts and estimated reading time
* `uniqcount` — word-frequency counts, sorted most-frequent first
* `filesize` — human-readable (or raw byte) sizes of files and directory trees
* `pickrand` — pick N random lines, seedable for reproducible output
* `passwdgen` — secrets-based password generator (seedable test mode)
* `hexdump` — canonical hex dump (offset, hex bytes, ASCII)
* `utfcheck` — UTF-8 validity check and non-ASCII character report
* `lorem` — placeholder text from a built-in word list, seedable

**Install (verified, offline, exits 0):**

```console
$ python3 -m pip install --no-build-isolation .
Successfully installed pydevtoolkit-1.0.0
```

Use `python3 -m pip` rather than bare `pip` so the package installs into the
same interpreter as `python3`. No pip? `sh install.sh` copies ready-to-use
wrappers for all 16 commands into `~/.local/bin`. Each utility also runs
without installing: `python3 -m pydevtoolkit.jsonfmt -s data.json`.

**Run the tests (single command, 92 tests):**

```console
$ python3 run_tests.py
```

**Conventions:** exit 0 = success, 1 = runtime error, 2 = usage error; every
utility reads from a file or stdin; random-output utilities (`pickrand`,
`passwdgen`, `lorem`) accept a seed flag. Licensed MIT (see `LICENSE`).
Full usage examples for all 16 utilities are in the included `README.md`.

## Assets to attach (files + SHA-256)

Recomputed fresh on 2026-10-20T22:12:06Z; both match `build/CHECKSUMS.txt`.

| File | Size (B) | SHA-256 |
|---|---|---|
| `build/pydevtoolkit-1.0.0.zip` | 40,299 | `f272da222502854fd3b8d12204505e3289c9a61ea129c1e44054ccf956dd4a99` |
| `build/pydevtoolkit-1.0.0.tar.gz` | 19,799 | `8833fb1d3d22aa94b5bdbf239e9bd2e5418d2f2ec10607a481e61bc156677eca` |

## Pricing note (playbook basis)

Per the O1-KR1 playbook, Gumroad's fee basis for profile/direct links is
"10% + $0.50 per transaction" (Gumroad pricing page, fetched 2026-10-20 UTC):
$15.00 × (1 − 0.10) − $0.50 = **$13.00 net per sale**; ~8 sales to cover the
$100 target (8 × $13.00 = $104 ≥ $100). Discover feed items carry a distinct
30% fee (caveat noted in the playbook).
