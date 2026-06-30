# IC Pending Terminal-History Repair Review

## Change Gate

- State: verified
- Change type: broker/MT5 order lifecycle evidence; journal/Telegram evidence
- Materiality: material, because stale pending-order reconciliation affects live state truth and strategy evidence
- Lead owner: LPFS Strategy Improvement Agent
- Reviewers/verifiers: Independent Issue Verifier, Reliability Reviewer, Documentation and Workflow Agent
- Scope: `live_executor.py` pending-order reconciliation and focused tests only

## Issue Verification

The 2026-06-30 midweek watch packet showed IC as `AMBIGUOUS` because local
state still tracked pending order `4446914924`, while broker pending orders did
not contain that ticket. Preserved journal evidence for the same ticket showed
repeated `pending_missing_unresolved` rows with `reason=history_deals_present`.

Repository inspection confirmed the stale-pending classifier checked MT5
history deals before terminal MT5 history-order state. If a missing pending
order had deal rows and an expired/rejected history order, the deal branch
returned unresolved before the terminal order state could prove resolution.

## Patch Decision

The fix is narrow and conservative:

- Terminal MT5 history-order states `expired` and `rejected`, plus proven manual
  broker cancel, are evaluated before deal-row ambiguity.
- Deal-only or non-active-position deal evidence still remains fail-closed as
  `pending_missing_unresolved`.
- Broker-history-proven expired missing orders now emit `pending_expired` and
  remove stale pending state idempotently.
- Manual cancels keep the existing `pending_cancelled` behavior.

No broker send, strategy, risk, sizing, SL/TP, recovery, config, scheduler,
watchdog, VPS task, runtime-state, production journal, or broker artifact
change is included.

## Verification

Passed locally:

- `.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_live_executor`
  - `75 tests OK`
- `.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_live_executor strategies.lp_force_strike_strategy_lab.tests.test_notifications`
  - `88 tests OK`
- `.\venv\Scripts\python -m unittest discover -s strategies\lp_force_strike_strategy_lab\tests`
  - `538 tests OK`
- `.\venv\Scripts\python scripts\run_core_coverage.py`
  - `7181 statements`, `2420 branches`, `100.00%`
- `git diff --check`
  - passed with CRLF warnings only

## Deployment Note

This patch is not a live-state repair by itself. After review and publication,
deploy sequentially with normal runner restart proof. IC should then be
observed to resolve the stale pending state from MT5 broker history without
manual state edits or broker mutation.
