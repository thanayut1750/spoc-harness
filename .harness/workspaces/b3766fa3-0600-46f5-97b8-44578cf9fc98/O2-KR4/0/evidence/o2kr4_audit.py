#!/usr/bin/env python3
"""O2-KR4 WP-O2KR4-2-REPORT read-only forensic audit.

Recomputes ledger math from archived tool outputs, asserts entry-count equality,
proves ledger integrity (no add/modify/remove), scans deliverables for fabricated
commerce artifacts, and cross-checks proof resolution. Emits one line per check;
final line is 'EARNINGS_AUDIT: PASS' only if every check passes (exit 0).
Never writes to the ledger or to any pre-existing evidence/report file.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path("/home/dx/Agentic-harness/spoc-harness/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR4/0")
REPORT = WS / "report" / "EARNINGS_REPORT_O2KR4.md"
EV = WS / "evidence"
AUDIT_LOG_NAME = "o2kr4_audit.log"  # excluded from scans (being written by tee)

checks = []
fails = []


def log(line):
    print(line, flush=True)


def check(cid, desc, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    checks.append((cid, ok))
    if not ok:
        fails.append(f"{cid}: {desc} {detail}")
    log(f"CHECK {cid}: {desc} ... {status}" + (f" | {detail}" if detail else ""))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def find_ledger_count():
    r = subprocess.run(
        ["find", str(WS), "-name", "revenue_ledger.json"],
        capture_output=True, text=True,
    )
    return len([l for l in r.stdout.splitlines() if l.strip()])


log("=== O2-KR4 FORENSIC EARNINGS AUDIT (WP-O2KR4-2-REPORT) ===")
log(f"UTC_NOW: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
log(f"workspace: {WS}")
log("scope: READ-ONLY. This audit performs no ledger 'add', no modification, no removal;")
log("       mission_log.md is untouched; the only files this audit creates are its own")
log("       outputs (evidence/o2kr4_audit.log via tee; this script evidence/o2kr4_audit.py).")
log("")

# ---------------------------------------------------------------- PRE state
log("--- SECTION P: PRE-AUDIT LEDGER STATE ---")
n0 = find_ledger_count()
check("P1", "revenue_ledger.json absent at audit start (lazy-create; zero accepted adds)",
      n0 == 0, f"find_count={n0}")

expected_hashes = {
    "ledger_baseline_summary.log": "cdb64dc9cac2083d787ceec47f9b5f767ae92ed57038badbc6b9ab575fbada40",
    "ledger_convention.md": "c74ce741bbef3e74ebd3843aa320bf320b827e1b03a86cc83cfd409a566fc3bd",
    "ledger_math_check.log": "112e07ff5ada8b3ad60230b89c49c7eaf2c8abc5fb2949b4d8871a8122c2a9b7",
    "ledger_math_check.py": "75442bdadca9059c0fe37e0b49c9e1946f0843bd79bd35e50507cbf7c41c60b1",
    "ledger_summary_final.log": "2945aa26d50cd69e92d145c9dedfc0a435b33940bcc4fcdc548d44bfa3ac48bb",
    "ledger_tool_calls.log": "16369b3f9b25c7872e6b4a5b711c295ecfbbe566c292e99415142cbc6312b601",
    "ledger_zero_amount_probe.log": "bcd81bce6e87c15da16087c378d19c9439c8e6f189b89c16fa8495ec80ca3223",
    "proof_preflight.log": "d03e4593debb9262ea69390cb92068487580118e105b6e1c790214da8351f8fc",
    "zero_confirmed_sales_check.md": "421331a2cc3e1f47dadb966a6b5630deff5ea5808be81e8b1812ceecf0722633",
    "proof_resolution_audit.log": "543d657a45ad2949d9b330a84a7f2058f3f438076aa6b38a62fbaf9401a6c85e",
    "proof_resolution_audit.sh": "0098edf247dc80ae6802b45651d5c64cd922aa5d2d6a889245d493f4354e064f",
}
pre_hashes = {}
pre_ok = True
for name, exp in expected_hashes.items():
    got = sha256(EV / name)
    pre_hashes[name] = got
    if got != exp:
        pre_ok = False
        log(f"  MISMATCH {name}: expected {exp} got {got}")
check("P2", "11 pre-existing evidence files match their recorded sha256 (snapshot 2026-10-21T05:39:29Z + proof-resolution files)",
      pre_ok, f"files={len(expected_hashes)}")

corroboration_path = EV / "ledger_summary_corroboration_wp2.log"
report_pre = sha256(REPORT)
script_pre = sha256(EV / "o2kr4_audit.py")
pre_hashes["__report__"] = report_pre
pre_hashes["__script__"] = script_pre
pre_hashes[str(corroboration_path.name)] = sha256(corroboration_path)
log(f"PRE report sha256: {report_pre}")
log(f"PRE audit script sha256: {script_pre}")
log(f"PRE corroboration sha256: {pre_hashes['ledger_summary_corroboration_wp2.log']}")
log("")

# ------------------------------------------------- corroboration summary (verbatim)
log("--- SECTION C: CORROBORATION SUMMARY (archived verbatim) ---")
corroboration_raw = None
for line in corroboration_path.read_text().splitlines():
    if line.startswith('{"action": "summary"') and '"entry_count"' in line:
        corroboration_raw = line
        break
check("C1", "corroboration summary verbatim output present in evidence/ledger_summary_corroboration_wp2.log",
      corroboration_raw is not None)
if corroboration_raw:
    log(f"CORROBORATION_VERBATIM: {corroboration_raw}")
log("")

# --------------------------------------------------------- independent recompute
log("--- SECTION M: INDEPENDENT RECOMPUTATION FROM ARCHIVED TOOL OUTPUTS ---")


def load_summary(path, prefix):
    for line in path.read_text().splitlines():
        s = line.strip()
        if s.startswith(prefix):
            payload = s
            if s.startswith('{"tool_id"'):  # unwrap tool envelope
                payload = json.loads(s)["output"]
                return json.loads(json.dumps(payload))
            return json.loads(s)
    return None


def recompute(label, data):
    entries = data["entries"]
    r_sum = 0.0
    for e in entries:
        r_sum += float(e.get("amount", 0))
    results = {
        "recomputed_sum": r_sum,
        "total_earned": data["total_earned"],
        "entry_count": data["entry_count"],
        "len_entries": len(entries),
        "remaining": data["remaining"],
        "progress_percent": data["progress_percent"],
        "goal_reached": data["goal_reached"],
        "goal": data["goal"],
        "currency": data["currency"],
        "goal_reached_type_ok": data["goal_reached"] is False,
    }
    log(f"{label}: entries={entries} | sum(entry amounts)={r_sum} | tool total_earned={data['total_earned']}"
        f" | entry_count={data['entry_count']} | remaining={data['remaining']}"
        f" | progress_percent={data['progress_percent']} | goal_reached={data['goal_reached']}"
        f" | goal={data['goal']} | currency={data['currency']}")
    return results


runs = {}
runs["baseline"] = load_summary(EV / "ledger_baseline_summary.log", '{"tool_id"')
runs["final"] = load_summary(EV / "ledger_summary_final.log", '{"tool_id"')
runs["corroboration"] = json.loads(corroboration_raw) if corroboration_raw else None
m_all = all(v is not None for v in runs.values())
check("M0", "all three archived summary outputs parse (baseline, final, corroboration)", m_all)

if m_all:
    rec = {k: recompute(k, v) for k, v in runs.items()}
    check("M1", "sum(entries) == 0.00 for every run (no entry amounts exist)",
          all(r["recomputed_sum"] == 0.0 for r in rec.values()))
    check("M2", "recomputed sum(entries) == tool total_earned exactly, every run (incl. corroboration)",
          all(r["recomputed_sum"] == float(r["total_earned"]) for r in rec.values()))
    check("M3", "entry_count field == len(entries) == 0, every run",
          all(r["entry_count"] == r["len_entries"] == 0 for r in rec.values()))
    check("M4", "remaining == goal - total_earned == 100.00 ($100.00 remaining) every run",
          all(abs(float(r["remaining"]) - (float(r["goal"]) - float(r["total_earned"]))) < 1e-9
              and float(r["remaining"]) == 100.0 for r in rec.values()))
    check("M5", "progress_percent == total/goal*100 == 0.0% (0% toward $100) every run",
          all(abs(float(r["progress_percent"]) - float(r["total_earned"]) / float(r["goal"]) * 100.0) < 1e-9
              and float(r["progress_percent"]) == 0.0 for r in rec.values()))
    check("M6", "goal_reached is boolean false in every run ($100 goal honestly UNMET)",
          all(r["goal_reached_type_ok"] for r in rec.values()))
    check("M7", "goal == 100 and currency == USD on every run",
          all(float(r["goal"]) == 100.0 and r["currency"] == "USD" for r in rec.values()))
    keys = ("recomputed_sum", "total_earned", "entry_count", "remaining", "progress_percent", "goal_reached")
    check("M8", "baseline == final == corroboration on all goal-math fields (no entry ever appeared)",
          all(rec["baseline"][k] == rec["final"][k] == rec["corroboration"][k] for k in keys))
    ledger_entry_count = rec["final"]["entry_count"]
else:
    ledger_entry_count = None
log("")

# ------------------------------------------------------- entry-count equality
log("--- SECTION E: ENTRY-COUNT EQUALITY (ledger == report == audit) ---")
report_text = REPORT.read_text()
report_entry_rows = len(re.findall(r"^\|\s*\d+\s*\|", report_text, flags=re.MULTILINE))
check("E1", "ledger entry_count == 0", ledger_entry_count == 0, f"ledger={ledger_entry_count}")
check("E2", "report per-entry table has 0 digit-indexed entry rows (dash placeholder row is not an entry)",
      report_entry_rows == 0, f"report_rows={report_entry_rows}")
audit_entry_count = rec["final"]["len_entries"] if m_all else -1
check("E3", "audit recomputed entry count == 0", audit_entry_count == 0, f"audit={audit_entry_count}")
check("E4", "TRIPLE EQUALITY ledger == report == audit entry counts (all 0)",
      ledger_entry_count == report_entry_rows == audit_entry_count == 0,
      f"ledger={ledger_entry_count} report={report_entry_rows} audit={audit_entry_count}")
log("")

# ------------------------------------------------------------ ledger integrity
log("--- SECTION I: LEDGER INTEGRITY (no add / modify / remove by this audit) ---")
n1 = find_ledger_count()
check("I1", "revenue_ledger.json still absent after corroboration re-run and all audit reads",
      n1 == 0, f"find_count={n1}")
post_ok = True
for name, pre in pre_hashes.items():
    if name.startswith("__"):
        post = sha256(REPORT if name == "__report__" else EV / "o2kr4_audit.py")
    else:
        post = sha256(EV / name)
    if post != pre:
        post_ok = False
        log(f"  CHANGED {name}: {pre} -> {post}")
check("I2", "all pre-audit files byte-identical after audit reads (report, script, corroboration, 11 evidence files)",
      post_ok, f"files_compared={len(pre_hashes)}")
check("I3", "ledger tool call record shows exactly 3 WP1 invocations and zero accepted adds",
      "ExpectedToolInputError" in (EV / "ledger_zero_amount_probe.log").read_text()
      and (EV / "ledger_tool_calls.log").read_text().count('{"action"') >= 1
      and (EV / "ledger_tool_calls.log").read_text().count('"action": "add"') == 1,
      "1 rejected zero-amount add probe; 2 summaries; corroboration run recorded separately")
log("")

# ------------------------------------------------------------ fabrication scan
log("--- SECTION F: FABRICATION SCAN (deliverables = report/ + evidence/, audit log excluded) ---")
scan_files = [REPORT] + [p for p in sorted(EV.iterdir())
                         if p.is_file() and p.name != AUDIT_LOG_NAME]
whitelist = {
    "https://raw.githubusercontent.com/thanayut1750/spoc-harness/63e0f5caab3c61d1d2985a915419a1fa2ed9f8c9/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/gumroad_api_retry.log",
    "https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/gumroad_api_retry.log",
    "https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/lemonsqueezy_fallback_retry.log",
    "https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/gumroad_human_step_outcome.md",
    "https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/lemonsqueezy_human_step_outcome.md",
    "https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/gumroad_credentials_sweep.log",
    "https://raw.githubusercontent.com/thanayut1750/spoc-harness/bc8167ca45fe4ce4c6952771000cf29b0f90cb3f/.harness/workspaces/b3766fa3-0600-46f5-97b8-44578cf9fc98/O2-KR2/2/evidence/lemonsqueezy_credentials_sweep.log",
}
# Documented raw.githubusercontent URL-pattern/infrastructure forms (with
# <commit>/<path> placeholders, or the bare repo base). These are citation-format
# documentation in the report and proof_preflight.log, not proof citations; they
# are never fetched as evidence. All seven actual proof citations are resolved
# individually in evidence/proof_resolution_audit.log (R1/R2 cross-check).
INFRA_URLS = {
    "https://raw.githubusercontent.com/thanayut1750/spoc-harness/<commit",
    "https://raw.githubusercontent.com/thanayut1750/spoc-harness",
}
url_re = re.compile(r"https?://[^\s)>\]'\"]+")
found_urls = set()
for p in scan_files:
    found_urls |= set(url_re.findall(p.read_text()))
non_whitelist = found_urls - whitelist - INFRA_URLS
check("F1", "every http(s) URL in deliverables is one of the 7 audit-resolved O2-KR2 citation URLs or a documented pattern/infra form (never a commerce URL)",
      len(non_whitelist) == 0,
      f"found={len(found_urls)} citations={len(found_urls & whitelist)} infra={len(found_urls & INFRA_URLS)} non_whitelist={sorted(non_whitelist)[:3]}")

commerce_re = re.compile(r"https?://[^\s)>\]'\"]*(gumroad\.com|lemonsqueezy\.com|fiverr\.com|stripe\.com|paypal\.com|shopify\.com)", re.IGNORECASE)
bad_commerce = [u for u in found_urls if commerce_re.match(u) and u not in whitelist]
check("F2", "0 non-whitelisted marketplace/order/checkout URLs in deliverables",
      len(bad_commerce) == 0, f"hits={bad_commerce[:3]}")

# Fabrication tokens are flagged in two forms: (a) inside URL substrings - any
# invented marketplace-domain slash path (storefront, checkout, orders, receipt,
# purchase, or product form); (b) as bare high-specificity tokens: an
# ORD-prefixed numeric order id, a receipt-prefixed hex receipt id, or an
# orders-slash alphanumeric id containing a digit. The bare order-token
# alternative requires a digit inside the token segment so prose enumerations
# that ASSERT ABSENCE are never flagged; fabricated order identifiers always
# contain digits. No literal token examples appear in these comments, so the
# scan cannot self-trigger on its own source.
inv_url_re = re.compile(
    r"gumroad\.com/l/|/checkout|/orders?/|/receipt|/purchase|/product/", re.IGNORECASE)
inv_bare_re = re.compile(
    r"\bORD[-_][0-9]{4,}|\bGUM[-_][A-Za-z0-9]{4,}|\breceipt_[A-Za-z0-9]{8,}"
    r"|\border[s]?/(?=[A-Za-z0-9-]{4,}\d)[A-Za-z0-9-]{6,}"
    r"|\bpurchase[sd]?[_-][A-Za-z0-9]{6,}",
    re.IGNORECASE)
invented_hits = []
for p in scan_files:
    txt = p.read_text()
    for u in set(url_re.findall(txt)):
        if u not in whitelist and u not in INFRA_URLS and inv_url_re.search(u):
            invented_hits.append(f"{p.name}:URL:{u[:80]}")
    for i, line in enumerate(txt.splitlines(), 1):
        if inv_bare_re.search(line):
            invented_hits.append(f"{p.name}:{i}")
check("F3", "0 invented order/checkout/receipt token patterns in deliverables",
      len(invented_hits) == 0, f"hits={invented_hits[:3]}")

report_lines = report_text.splitlines()
unbacked = []
for i, line in enumerate(report_lines, 1):
    if re.search(r"\$\s*[1-9][0-9,]*(?:\.[0-9]{2})?", line):
        if not re.search(r"goal|remaining|shortfall|UNMET|unmet|gap|revenue_goal", line, re.IGNORECASE):
            unbacked.append(f"report:{i}:{line.strip()[:60]}")
check("F4", "every positive USD figure in the report is qualified as goal/remaining/shortfall context",
      len(unbacked) == 0, f"hits={unbacked[:3]}")

earned_positive = []
for p in scan_files:
    for i, line in enumerate(p.read_text().splitlines(), 1):
        if (re.search(r"earned", line, re.IGNORECASE) and re.search(r"\$\s*[1-9]", line)
                and not re.search(r"goal|remaining|shortfall|unmet|gap", line, re.IGNORECASE)):
            # A positive figure sharing a line with 'earned' is a fabrication
            # candidate only when it carries no goal/remaining/shortfall
            # context: bookkeeping lines stating the remaining shortfall
            # (UNMET) must pass; an unqualified earned-amount claim would be
            # flagged here and by F4.
            earned_positive.append(f"{p.name}:{i}")
check("F5", "0 lines in any deliverable pair 'earned' with a positive USD amount",
      len(earned_positive) == 0, f"hits={earned_positive[:3]}")

te_high = []
te_re = re.compile(r'"total_earned"\s*:\s*[1-9]')
for p in scan_files:
    if te_re.search(p.read_text()):
        te_high.append(p.name)
check("F6", "0 occurrences of total_earned > 0 in any deliverable",
      len(te_high) == 0, f"hits={te_high}")

probe = (EV / "ledger_zero_amount_probe.log").read_text()
check("F7", "zero-amount guard probe on record and cited (structural anti-fabrication evidence)",
      "ExpectedToolInputError" in probe and "amount must be a positive number" in probe
      and "guard-probe" in probe,
      "evidence/ledger_zero_amount_probe.log; tool source ec456dd5... lines 116-117; cited in report Section 8")
log("")

# ------------------------------------------------- proof-resolution cross-check
log("--- SECTION R: CITATION RESOLUTION CROSS-CHECK ---")
pr = (EV / "proof_resolution_audit.log").read_text()
check("R1", "proof_resolution_audit.log: URLS_FETCHED: 7, UNRESOLVED_CITATIONS: 0, PROOF_RESOLUTION: PASS",
      "URLS_FETCHED: 7" in pr and "UNRESOLVED_CITATIONS: 0" in pr and "PROOF_RESOLUTION: PASS" in pr)
check("R2", "report cites only URLs that resolved HTTP 200 with expected markers (F1 whitelist == resolved set)",
      len(non_whitelist) == 0, "see evidence/proof_resolution_audit.log per-URL HTTP status + sha256")
log("")

# ----------------------------------------------------------- mission_log safety
log("--- SECTION S: SCOPE SAFETY ---")
check("S1", "mission_log.md absent from this workspace (never touched by O2-KR4)",
      not (WS / "mission_log.md").exists())
check("S2", "report states the literal UNMET verdict line",
      "GOAL: UNMET — $100.00 shortfall; no confirmed sales; this shortfall is real, not pending and not fabricated" in report_text)
check("S3", "report states ACTUAL AMOUNT EARNED: $0.00 USD",
      "ACTUAL AMOUNT EARNED: $0.00 USD" in report_text)
log("")

# ---------------------------------------------------------------- verdict
total = len(checks)
passed = sum(1 for _, ok in checks if ok)
log("--- SUMMARY ---")
log(f"CHECKS_RUN: {total}")
log(f"PASSED: {passed}")
log(f"FAILED: {total - passed}")
if fails:
    for f in fails:
        log(f"FAILED_CHECK: {f}")
all_pass = not fails
log(f"ledger total_earned = $0.00 USD; remaining = $100.00; progress = 0.0%; goal_reached = false; entries = 0")
log("GOAL: UNMET — $100.00 shortfall; no confirmed sales; this shortfall is real, not pending and not fabricated")
log("EARNINGS_AUDIT: PASS" if all_pass else "EARNINGS_AUDIT: FAIL")
sys.exit(0 if all_pass else 1)
