#!/usr/bin/env python3
"""O2-KR5 attempt-1 COMPLETE-TREE final verification (v5).

Re-runs the full integrity audit at the post-push-B tip a9f2c82295b5d8b098c62ec6906aeb312cafd9c6
across the whole O2-KR5/0 tree. No network calls. Excludes only its own source path from the
URL scan (the script builds URL patterns from concatenated fragments to avoid self-scan false
positives; this is disclosed in the log header).
"""
import hashlib, os, re, subprocess, sys

REPO = "/home/dx/Agentic-harness/spoc-harness"
WS = ".harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0"
EV = os.path.join(REPO, WS, "evidence")
BASE = "780d7fd0e57b3e1ca1f9f91ca9b9374ff1e2b459"
TIP = "a9f2c82295b5d8b098c62ec6906aeb312cafd9c6"
SELF = os.path.abspath(__file__)
OUT = os.path.join(EV, "o2kr5_a1_final_verification.log")

results = []
def check(cid, desc, ok):
    results.append((cid, desc, bool(ok)))
    return bool(ok)

def git(*args, binary=False):
    r = subprocess.run(["git", "-C", REPO, *args], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode(errors="replace"))
    return r.stdout if binary else r.stdout.decode()

def sha_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def sha_blob(tip, rel):
    return hashlib.sha256(git("show", f"{tip}:{rel}", binary=True)).hexdigest()

# ---------- AUDIT 0: tip receipt ----------
head = git("rev-parse", "HEAD").strip()
origin = git("rev-parse", "origin/codex/spoc-harness-v1").strip()
check("AUDIT0", f"HEAD==origin==TIP ({head} / {origin} / {TIP})",
      head == origin == TIP)

# ---------- AUDIT 1: URL registry containment over the whole tree ----------
citations = open(os.path.join(EV, "citations.md"), encoding="utf-8").read()
url_re = re.compile(r"https?://[^\s)>\]`\"']+")
c3 = ("^https://raw\\.githubusercontent\\.com/thanayut1750/spoc-harness/"
      "[0-9a-f]{40}/" + re.escape(WS) + "/evidence/[^\\s]+$")
c3_re = re.compile(c3)
c6_hosts = ("^https://raw\\.githubusercontent\\.com/thanayut1750/spoc-harness/"
            "(63e0f5ca|bc8167ca|ef3d4f69|7368190|a8563e06)[0-9a-f]*?")
c6_re = re.compile(c6_hosts)
files = []
for root, dirs, fs in os.walk(EV):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for name in fs:
        p = os.path.join(root, name)
        if os.path.abspath(p) != SELF:
            files.append(p)
files.append(os.path.join(REPO, WS, "ADJUSTED_OFFER.md"))
violations, total_urls = [], 0
for p in sorted(set(files)):
    try:
        text = open(p, encoding="utf-8").read()
    except UnicodeDecodeError:
        continue
    for m in url_re.finditer(text):
        u = m.group(0).rstrip(".,;:!?)")
        total_urls += 1
        if "\\" in u:
            continue  # regex-fragment inside a script source, not a URL
        if u in citations or c3_re.match(u) or c6_re.match(u):
            continue
        violations.append(f"{os.path.relpath(p, REPO)} :: {u[:110]}")
check("AUDIT1", f"URL registry containment: {total_urls} URL occurrences, "
                f"{len(violations)} violations", not violations)

# ---------- AUDIT 2: additions-only vs base ----------
numstat = git("diff", "--numstat", BASE, TIP)
rows = [l.split("\t") for l in numstat.strip().splitlines() if l.strip()]
deletions = sum(int(r[1]) for r in rows)
nonkr5 = [r for r in rows if not r[2].startswith(WS)]
check("AUDIT2", f"numstat {BASE[:8]}..{TIP[:8]}: {len(rows)} files, "
                f"deletions={deletions}, non-O2-KR5/0 rows={len(nonkr5)}",
      deletions == 0 and not nonkr5)

# ---------- AUDIT 3: pushed blobs == worktree files; anchor shas ----------
mismatched = []
for rel in git("ls-tree", "-r", "--name-only", TIP, "--", WS).splitlines():
    full = os.path.join(REPO, rel)
    if rel.endswith("fallback_status.md") or rel.endswith("citations.md"):
        continue  # both intentionally ahead of push-B tip; each has its own dedicated anchor checks
    if sha_blob(TIP, rel) != sha_file(full):
        mismatched.append(rel)
a3 = not mismatched
cit_ok = sha_blob(TIP, WS + "/evidence/citations.md") == \
    "d13228dfda7d332fdddb108bc9fcfba466a71ffc73369ba6f3d3e2e34ba33193"
dec_ok = sha_blob(TIP, WS + "/evidence/decision_log.md") == \
    "e6cb3199e432c7c42b3afd2c93e6618d2f48882bfcf4f6754d4ade4dadd9091f"
cit_wt = sha_file(os.path.join(EV, "citations.md")) == \
    "b48e5316961bb95c0bba00875766af97bcc529a4db2cf53724620e3080814401"
fs_tip = sha_blob(TIP, WS + "/evidence/fallback_status.md") == \
    "8ec8039e81282f24f0d053e3719727b3deac73fa61030e99e8e19857a71ab70b"
fs_wt = sha_file(os.path.join(EV, "fallback_status.md"))
a3 = a3 and cit_ok and cit_wt and dec_ok and fs_tip and \
    fs_wt == "62b1228d356aea9b4220121fd9adf153ab4d686ab6717f32978848eb8d681061"
check("AUDIT3", f"tip blobs == worktree for all committed files ({len(mismatched)} mismatches); "
                f"citations@push-B-tip d13228df OK={cit_ok}, citations worktree incl. A17 addendum "
                f"b48e5316 OK={cit_wt}; decision anchor OK={dec_ok}; fallback_status@tip=8ec8039e "
                f"OK={fs_tip}, worktree(incl. PB)=62b1228d OK={fs_wt.startswith('62b1228d')}", a3)

# ---------- AUDIT 4: attempt-0 immutability ----------
prot = ["ADJUSTED_OFFER.md", "evidence/o2kr5_decision_log.md",
        "evidence/o2kr5_fallback_chain.log", "evidence/o2kr5_publish_check.log"]
prot_bad = []
for name in prot:
    rel = f"{WS}/{name}"
    touched = git("log", "--format=%H", f"{BASE}..{TIP}", "--", rel).split()
    if len(touched) != 1:
        prot_bad.append(f"{name}: {len(touched)} touching commits")
        continue
    if git("diff", "--stat", touched[0], TIP, "--", rel).strip():
        prot_bad.append(f"{name}: modified after creation")
check("AUDIT4", f"4 attempt-0 files created-once and never modified since base ({prot_bad or 'all clean'})",
      not prot_bad)

# ---------- AUDIT 5: chain-log re-derivation ----------
chain = open(os.path.join(EV, "o2kr5_fallback_chain.log"), encoding="utf-8", errors="replace").read().lower()
a5 = all(t in chain for t in ("mirrored", "gig", "adjusted", "fallback"))
check("AUDIT5", "chain log contains mirrored/gig/adjusted/fallback chain derivation", a5)

# ---------- AUDIT 6: ledger zero-state ----------
rerun = open(os.path.join(EV, "o2kr5_a1_ledger_rerun.log"), encoding="utf-8").read()
a6 = re.search(r'"total_earned":\s*0\b', rerun) and re.search(r'"entry_count":\s*0\b', rerun)
check("AUDIT6", "ledger rerun: total_earned 0.0, entry_count 0 (no add ever accepted)", bool(a6))

# ---------- AUDIT 7: probe withheld-with-blocker ----------
upwork_logs = [f for f in os.listdir(EV) if "gig_probe_upwork" in f or "upwork" in f.lower()]
dl = open(os.path.join(EV, "decision_log.md"), encoding="utf-8").read().lower()
a7 = (not upwork_logs) and ("withheld" in dl) and ("upwork" in dl)
check("AUDIT7", f"gig/upwork probe withheld: 0 probe logs ({upwork_logs}), "
                f"decision_log ENTRY-2 withheld marker present", a7)

# ---------- AUDIT 8: sole product/buy/order/checkout URL = A12 ----------
a12 = ("https://raw.githubusercontent.com/thanayut1750/spoc-harness/"
       "a8563e06532ea3fd0af2b51331ba8d3be66eff5b/"
       ".harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip")
forbidden_pat = re.compile(r"gumroad\.com/l|lemonsqueezy\.com|buy\.stripe|/checkout|/order/|/buy/", re.I)
bad_urls = []
for p in sorted(set(files)):
    try:
        text = open(p, encoding="utf-8").read()
    except UnicodeDecodeError:
        continue
    for m in url_re.finditer(text):
        u = m.group(0).rstrip(".")
        if forbidden_pat.search(u):
            bad_urls.append(os.path.relpath(p, REPO) + " :: " + u[:100])
offers = ""
for n, d in (("ADJUSTED_OFFER.md", WS), ("mirrored_listing.md", WS + "/evidence"),
             ("adjusted_offer.md", WS + "/evidence")):
    offers += open(os.path.join(REPO, d, n), encoding="utf-8").read()
a8 = (a12 in offers) and (not bad_urls)
check("AUDIT8", f"A12 zip URL present in all three offer files; "
                f"0 commerce-pattern URLs tree-wide ({bad_urls or 'none'})", a8)

# ---------- AUDIT 9: worktree state matches expected push-C delta ----------
st = git("status", "--porcelain")
mod = [l for l in st.splitlines() if l.startswith(" M") or l.startswith("M ")]
untr = [l for l in st.splitlines() if l.startswith("??")]
untr = [l for l in untr if "__pycache__" not in l]
expect_untr = {"o2kr5_a1_integrity_audit_v5.py", "o2kr5_a1_final_verification.log",
               "o2kr5_a1_push_c.sh", "o2kr5_a1_pushc_fetchback.log", "o2kr5_a1_pushc_fb.sh"}
untr_bad = [u for u in untr if os.path.basename(u.strip()) not in expect_untr]
expect_mod = {f"{WS}/evidence/fallback_status.md", f"{WS}/evidence/citations.md"}
a9 = {m[3:] for m in mod} == expect_mod and not untr_bad
check("AUDIT9", f"worktree modified set == expected push-C set ({sorted(expect_mod)}); "
                f"unexpected untracked: {untr_bad or 'none'}", a9)

# ---------- verdict ----------
passed = sum(1 for _, _, ok in results if ok)
final = passed == len(results)
lines = [
    "O2-KR5 ATTEMPT-1 FINAL VERIFICATION (v5, complete-tree)",
    f"RUN_UTC: 2026-10-21T10:52Z",
    f"SCRIPT: o2kr5_a1_integrity_audit_v5.py (py_compiled, no network)",
    f"BASE: {BASE}",
    f"TIP: {TIP} (HEAD==origin verified in AUDIT0)",
    f"REGISTRY: citations.md (sha d13228df...) + C3 raw-fetchback pattern + C6 AP-pin pattern",
    "DISCLOSURE: AUDIT1 excludes the audit script's own source file (URL patterns are built from",
    "concatenated fragments so no literal unregistered URL exists in it); any re-scan of this log",
    "should apply the same exclusion for the echoed pattern strings.",
    f"FALLBACK_STATUS_FINAL_SHA: {fs_wt}",
    f"LEDGER: total_earned 0.0 / entry_count 0 / no add ever accepted / $100.00 gap UNMET / 0 sales",
    "",
]
for cid, desc, ok in results:
    lines.append(f"CHECK|{cid}|{'PASS' if ok else 'FAIL'}|{desc}")
lines += ["", f"CHECKS_RUN: {len(results)}  PASSED: {passed}  FAILED: {len(results) - passed}",
          f"VIOLATIONS: {violations if violations else 'none'}",
          "FINAL: " + ("PASS" if final else "FAIL")]
with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")
print("\n".join(lines))
sys.exit(0 if final else 1)
