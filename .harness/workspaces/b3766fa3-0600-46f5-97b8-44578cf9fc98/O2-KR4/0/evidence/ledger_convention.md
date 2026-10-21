# evidence/ledger_convention.md — O2-KR4 ledger entry convention

UTC_NOW: 2026-10-21T05:24:04Z
tool: revenue_ledger, tool_id `tool:7bdf3aa0d66a5279c833dabe2820f852` (registered, tested mission tool)
ledger file: `revenue_ledger.json` in the O2-KR4 attempt workspace (written ONLY by the tool; never hand-edited)

## Mandatory convention for any future `add` entry

The ledger tool has **no dedicated proof-reference field**, so the proof reference MUST be
embedded inside the `description` string. Any future `add` invocation MUST carry ALL of:

1. `description` (string, required by tool) — human-readable description of what produced
   the revenue, AND a **resolvable proof URL** (order/transaction URL or hosted receipt)
   embedded in the description text. The URL must resolve (HTTP 200) at recording time.
2. `channel` (string) — sales channel, e.g. `gumroad`, `fiverr`, `lemonsqueezy`.
   Never leave it to the default `unspecified` when the source is known.
3. `amount` (number) — **strictly greater than 0**. The tool rejects amount <= 0
   (verified by evidence/ledger_zero_amount_probe.log); that rejection is the
   anti-fabrication guard and must never be circumvented.
4. `currency` (string) — `USD` explicitly on every entry (ledger enforces a single
   currency across all entries).
5. `timestamp` (optional) — ISO-8601; omit to let the tool stamp current UTC time.

## Operational rules

- Every invocation goes through `run_mission_tool` with the exact tool_id
  `tool:7bdf3aa0d66a5279c833dabe2820f852`; arguments and raw output are archived to
  `evidence/ledger_tool_calls.log`.
- `revenue_ledger.json` is never created/modified by hand; only the tool writes it.
- Every `summary` run passes `goal=100` and `currency="USD"` explicitly, with
  `include_entries=true`, and is archived (baseline: `evidence/ledger_baseline_summary.log`;
  final: `evidence/ledger_summary_final.log`).
- An entry with no resolvable proof URL is treated as fabricated and MUST NOT be recorded.
- If the tool behaves unexpectedly, archive the raw failure verbatim and escalate —
  never improvise a workaround that writes ledger state.
