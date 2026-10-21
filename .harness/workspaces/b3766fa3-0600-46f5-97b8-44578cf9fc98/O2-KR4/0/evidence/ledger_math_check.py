#!/usr/bin/env python3
"""Independent arithmetic verification of the O2-KR4 revenue ledger (WP-O2KR4-1-LEDGER).

Reads the archived baseline and final revenue_ledger summary outputs, independently
recomputes the sum of recorded entry amounts, verifies remaining/progress/goal math,
and asserts zero invented order/product URLs across all O2-KR4 deliverables.
Read-only: never writes or edits any ledger state.
"""
import json
import glob
import re
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

WS = Path(__file__).resolve().parent.parent
EV = WS / "evidence"
LEDGER = WS / "revenue_ledger.json"

failures = []
n_checks = 0


def check(cond, label):
    global n_checks
    n_checks += 1
    status = "PASS" if cond else "FAIL"
    print(f"CHECK {n_checks:02d}: {label} ... {status}")
    if not cond:
        failures.append(label)


def extract_output_json(log_path):
    """Pull the verbatim raw tool-output line from an archived summary log."""
    for line in log_path.read_text().splitlines():
        s = line.strip()
        if s.startswith('{"tool_id"') and s.endswith("}"):
            return json.loads(s)
    raise SystemExit(f"FATAL: no raw output JSON line found in {log_path}")


# --- load archived summaries -------------------------------------------------
final_wrap = extract_output_json(EV / "ledger_summary_final.log")
baseline_wrap = extract_output_json(EV / "ledger_baseline_summary.log")
final = final_wrap["output"]
baseline = baseline_wrap["output"]

print("== inputs (archived, verbatim) ==")
print("baseline summary: total_earned=%r entry_count=%r entries=%r"
      % (baseline["total_earned"], baseline["entry_count"], baseline["entries"]))
print("final    summary: total_earned=%r entry_count=%r entries=%r"
      % (final["total_earned"], final["entry_count"], final["entries"]))

# --- independent recompute with Decimal --------------------------------------
entries = final["entries"]
amounts = [Decimal(str(e["amount"])) for e in entries]
recomputed_total = sum(amounts) if amounts else Decimal("0")
total_earned = Decimal(str(final["total_earned"]))
goal = Decimal(str(final["goal"]))
remaining = Decimal(str(final["remaining"]))
progress = Decimal(str(final["progress_percent"]))

print("== arithmetic ==")
print("sum(entries amounts) = %s  (from %d entries)" % (recomputed_total, len(amounts)))
print("tool total_earned    = %s" % total_earned)

check(recomputed_total == total_earned,
      "sum(entry amounts) == total_earned")
check(len(entries) == final["entry_count"] == 0,
      "recorded-entry count is 0 (list len %d == field %d)" % (len(entries), final["entry_count"]))
check(entries == [],
      "entries list is exactly [] (no fabricated entries)")
check(goal == Decimal("100"),
      "goal == 100 (goal param passed explicitly on every summary run)")
check(final["currency"] == "USD",
      "currency == USD")
check(remaining == goal - total_earned,
      "remaining (%s) == goal - total_earned (%s)" % (remaining, goal - total_earned))
expected_progress = (recomputed_total / goal * Decimal("100")).quantize(
    Decimal("0.01"), rounding=ROUND_HALF_UP)
check(progress == expected_progress,
      "progress_percent (%s) == total/goal*100 (%s)" % (progress, expected_progress))
check(final["goal_reached"] is False,
      "goal_reached is false ($100 goal honestly UNMET)")
check(baseline["total_earned"] == final["total_earned"]
      and baseline["entry_count"] == final["entry_count"]
      and baseline["entries"] == final["entries"],
      "baseline summary consistent with final summary (no entries appeared between runs)")
check(final_wrap["tool_id"] == "tool:7bdf3aa0d66a5279c833dabe2820f852",
      "final summary emitted by the registered revenue_ledger tool_id")

# --- ledger file state (tool-only writes; never hand-edited) -----------------
if LEDGER.exists():
    raw = json.loads(LEDGER.read_text())
    tool_entries = raw.get("entries", [])
    check(tool_entries == [],
          "ledger JSON on disk exists but contains 0 entries (tool-written)")
else:
    print("NOTE: revenue_ledger.json does not exist on disk (tool writes it lazily on")
    print("      first 'add'; zero 'add' entries were ever accepted, consistent with")
    print("      evidence/ledger_zero_amount_probe.log)")
    check(True, "ledger file absent is consistent with zero accepted entries")

# --- anti-fabrication URL grep across all O2-KR4 deliverables ----------------
patterns = [
    ("gumroad product/order URL", r"gumroad\.com/l/"),
    ("gumroad library/receipt URL", r"gumroad\.com/library"),
    ("gumroad API URL", r"api\.gumroad\.com"),
    ("lemonsqueezy tenant/checkout URL", r"[a-z0-9-]+\.lemonsqueezy\.com"),
    ("lemonsqueezy other store URL", r"lemonsqueezy\.com/(?!docs)"),
    ("generic payment/order id field", r"order_id|receipt_url|transaction_id"),
]
deliverables = sorted(
    [p for p in glob.glob(str(EV / "*")) if Path(p).is_file()]
    + [str(WS / "revenue_ledger.json")]  # included only if it exists
)
deliverables = [p for p in deliverables if Path(p).exists()
                and Path(p).name != "ledger_math_check.py"]
hits = []
for path in deliverables:
    text = Path(path).read_text(errors="replace")
    for name, pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            line_no = text[: m.start()].count("\n") + 1
            hits.append((Path(path).name, line_no, name, m.group(0)))
print("== anti-fabrication URL grep ==")
check(len(hits) == 0,
      "0 invented order/product/transaction URLs across %d O2-KR4 deliverable files" % len(deliverables))
print("scanned files:")
for p in deliverables:
    print("  - %s" % Path(p).name)
if hits:
    for h in hits:
        print("  HIT: %s:%d %s %r" % h)
print("scanned patterns:")
for name, pat in patterns:
    print("  - %s  /%s/" % (name, pat))

# --- verdict ------------------------------------------------------------------
print("")
print("CHECKS_RUN: %d" % n_checks)
print("FAILED_CHECKS: %s" % (", ".join(failures) if failures else "none"))
print("ENTRY_COUNT: %d" % len(entries))
print("SUM_OF_ENTRIES: %s" % recomputed_total)
print("TOOL_TOTAL_EARNED: %s" % total_earned)
print("GOAL: %s  REMAINING: %s  PROGRESS_PERCENT: %s  GOAL_REACHED: %s"
      % (goal, remaining, progress, final["goal_reached"]))
verdict = "PASS" if not failures else "FAIL"
print("VERDICT: %s" % verdict)
sys.exit(0 if not failures else 1)
