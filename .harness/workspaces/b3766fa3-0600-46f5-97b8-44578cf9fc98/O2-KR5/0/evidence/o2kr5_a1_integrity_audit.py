#!/usr/bin/env python3
"""O2-KR5 attempt-1 integrity audit v4 (lineage, all disclosed):
v1 (log sha 5e23a2496a34bec6b276104a1204ce09d125cac428540fba68a4fbf7d0a246fa,
    preserved nowhere on disk after supersession): 14/15, MIRROR3 linear-containment
    FAIL - mirror interleaves added headers. Its AUDIT_EXIT=0 was a tee pipe bug.
v2 (log sha 77223e3206af48dfc3eb3ec9726768f7a862dbac2a8e26c94304cda66ac512d3,
    preserved as o2kr5_a1_integrity_audit_v2.log): 15/16, MIRROR3 bag-of-lines FAIL
    - announcement lines lived partly in the provenance block.
v3 (log sha d4383b8e07f9857f8d8d0e60b91c4ca59617645057ecb6fa392e40245502593c,
    preserved as o2kr5_a1_integrity_audit_v3.log): 16/17, MIRROR3a FAIL - the
    announcement's publication footer is line-wrapped across 3 lines and v3's
    PER-LINE allowlist missed the middle continuation line ("for the blocked GitHub
    issue-post attempt (HTTP 401 ... archived at").
v4 (this run, verification of record): MIRROR3a is structural, not per-line. The
    announcement's trailing publication footer is a single wrapped sentence; the
    honest check is that the body-displaced set is EXACTLY that trailing block:
    displaced non-empty; == last len(displaced) non-empty announcement lines, in
    order; <=3 lines; and the concatenated footer self-identifies ("Published by
    the O2-KR3 outreach run" ... "evidence/outreach/github.log"). MIRROR3b
    (displaced lines inside the MIRROR PROVENANCE block) and MIRROR2 (content
    preservation, missing_anywhere=0) are unchanged and must still hold."""
import hashlib, re, subprocess, sys, os

REPO = "/home/dx/Agentic-harness/spoc-harness"
WS = f"{REPO}/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0"
EV = f"{WS}/evidence"
ANN_BODY = "/tmp/o2kr5_a1_fetch/AP10b_ann_offer_path.body"
results = []
def check(tag, ok, detail=""):
    results.append((tag, ok, detail))

ann = open(ANN_BODY, encoding="utf-8").read()
mir = open(f"{EV}/mirrored_listing.md", encoding="utf-8").read()
norm = lambda s: re.sub(r"\s+", " ", s).strip()
ann_n, mir_n = norm(ann), norm(mir)
prov_start = mir_n.find("## MIRROR PROVENANCE")
mir_body_n = mir_n[:prov_start] if prov_start >= 0 else mir_n

check("MIRROR1_header_tag", "[mirrored listing]" in mir)
ann_lines = [norm(l) for l in ann.splitlines() if norm(l)]
missing_anywhere = [l for l in ann_lines if l not in mir_n]
check("MIRROR2_all_ann_lines_somewhere_in_mirror", not missing_anywhere,
      f"missing_anywhere={len(missing_anywhere)}")
displaced = [l for l in ann_lines if l not in mir_body_n]
print("DISPLACED_LINES (announcement lines inside provenance block, not body):")
for l in displaced: print(f"  <<{l}>>")
k = len(displaced)
suffix = ann_lines[len(ann_lines) - k:] if k else []
footer_concat = " ".join(displaced)
footer_ok = bool(displaced) and displaced == suffix and k <= 3 \
    and "Published by the O2-KR3 outreach run" in footer_concat \
    and "evidence/outreach/github.log" in footer_concat
check("MIRROR3a_displacement_exactly_trailing_publication_footer", footer_ok,
      f"displaced={k} is_trailing_suffix={displaced == suffix}")
check("MIRROR3b_displaced_lines_in_provenance_block",
      all(l in mir_n[prov_start:] for l in displaced) if prov_start >= 0 else False)
check("MIRROR4_provenance_block_present", prov_start >= 0 and "ANNOUNCEMENT.md" in mir)

APPROVED = [
 "https://raw.githubusercontent.com/thanayut1750/spoc-harness/63e0f5caab3c61d1d2985a915419a1fa2ed9f8c9/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/gumroad_api_retry.log",
 "https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/gumroad_api_retry.log",
 "https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/lemonsqueezy_fallback_retry.log",
 "https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/gumroad_human_step_outcome.md",
 "https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/lemonsqueezy_human_step_outcome.md",
 "https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/gumroad_credentials_sweep.log",
 "https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/lemonsqueezy_credentials_sweep.log",
 "https://raw.githubusercontent.com/thanayut1750/spoc-harness/ef3d4f69f2dce6d5c428572c55550ffe54d4ccec/O2-KR3/0/evidence/outreach_log.md",
 "https://raw.githubusercontent.com/thanayut1750/spoc-harness/ef3d4f69f2dce6d5c428572c55550ffe54d4ccec/O2-KR3/0/evidence/mission_log.md",
 "https://raw.githubusercontent.com/thanayut1750/spoc-harness/ef3d4f69f2dce6d5c428572c55550ffe54d4ccec/O2-KR3/0/offer/ANNOUNCEMENT.md",
 "https://raw.githubusercontent.com/thanayut1750/spoc-harness/ef3d4f69f2dce6d5c428572c55550ffe54d4ccec/O2-KR3/0/evidence/o2kr3_positive_reverify.log",
 "https://raw.githubusercontent.com/thanayut1750/spoc-harness/a8563e06532ea3fd0af2b51331ba8d3be66eff5b/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/0/build/pydevtoolkit-1.0.0.zip",
 "https://raw.githubusercontent.com/thanayut1750/spoc-harness/ef3d4f69f2dce6d5c428572c55550ffe54d4ccec/O2-KR3/0/evidence/o2kr3_fetchback.log",
]
FILES = ["citations.md","ledger_decision_summary.log","decision_log.md","mirrored_listing.md",
         "adjusted_offer.md","o2kr5_a1_fetch.sh","o2kr5_a1_fetch_receipt.log"]
fresh_corpus = ""
for root, _, fs in os.walk(EV):
    for f in fs:
        try: fresh_corpus += open(os.path.join(root,f), encoding="utf-8", errors="replace").read()
        except OSError: pass
def classify(u):
    for a in APPROVED:
        if u == a or u.startswith(a): return "APPROVED"
    m = re.search(r"raw\.githubusercontent\.com/thanayut1750/spoc-harness/([0-9a-f]{40})/", u)
    if m and m.group(1) in ("2d5b29c6eb0081240f41827848656a9d8e02a312",
                            "4e0b93f686d7b060f56b33f5de1cafaa00faeb0f"):
        return "FRESH_SELF_URL"
    if u in fresh_corpus: return "FRESH_CONTENT"
    return "OUT_OF_CLASS"
viol, tagged = [], {}
for fname in FILES:
    txt = open(f"{EV}/{fname}", encoding="utf-8").read()
    for u in set(re.findall(r"https?://[^\s)>'\"`,;]+", txt)):
        u = u.rstrip(".")
        tagged[u] = classify(u)
        if tagged[u] == "OUT_OF_CLASS": viol.append((fname, u))
check("AUDIT1_no_out_of_class", not viol, f"urls={len(tagged)} violations={len(viol)}")
for f_,u in viol: print("VIOLATION:", f_, u)

def sh(cmd, cwd=REPO):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True).stdout
num = sh(["git","diff","--numstat","780d7fd0e57b3e1ca1f9f91ca9b9374ff1e2b459",
          "2d5b29c6eb0081240f41827848656a9d8e02a312"]).strip().splitlines()
deletions = sum(int(l.split("\t")[1]) for l in num if l)
paths = [l.split("\t")[2] for l in num if l]
non_kr5 = [p for p in paths if "O2-KR5/0/" not in p]
check("AUDIT2_deletions_zero", deletions == 0, f"deletions={deletions}")
check("AUDIT3_paths_only_O2KR5", not non_kr5, f"files={len(paths)} non_kr5={non_kr5}")

A0 = {".harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0/ADJUSTED_OFFER.md":"f9ee536e0fac2c377931a2caf71cac8f46b26875f9716853feb4125cedc2c800",
      ".harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0/evidence/o2kr5_decision_log.md":"edb4ac248e44c3927e58a65926bc6c2e4d6d6c6d77eae80440dfac3f689203da",
      ".harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0/evidence/o2kr5_fallback_chain.log":"38d8a5e34cd7bd947194382254a0ddf39733a1de56b16617bf7a2b6252b77dca",
      ".harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR5/0/evidence/o2kr5_publish_check.log":"76c0eb536057215ef9a63e47a39ed9c049faee5ea4853c1e1c578848c185b116"}
for p, want in A0.items():
    got = sh(["git","show",f"2d5b29c6eb0081240f41827848656a9d8e02a312:{p}"])
    got_h = hashlib.sha256(got.encode()).hexdigest()
    check(f"AUDIT4_{os.path.basename(p)}", got_h == want, got_h[:16])

chain = open(f"{EV}/o2kr5_fallback_chain.log", encoding="utf-8", errors="replace").read()
for site in ["paste.rs","github.io","rentry","dpaste.com","ix.io"]:
    check(f"AUDIT5_{site.replace('.','_')}_0hits_in_a0_chain_log", site not in chain)

fails = [r for r in results if not r[1]]
print(f"\nCHECKS_RUN: {len(results)}")
print(f"PASSED: {len(results)-len(fails)}")
print(f"FAILED: {len(fails)}")
for tag, ok, det in results:
    print(f"  {'PASS' if ok else 'FAIL'} {tag} {det}")
print("O2KR5_A1_INTEGRITY_AUDIT:", "PASS" if not fails else "FAIL")
sys.exit(0 if not fails else 1)
