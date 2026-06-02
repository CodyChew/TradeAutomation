# LPFS C-01 Live-Safety Release

Last updated: 2026-06-01 ICT during implementation on
`codex/lpfs-c01-live-safety-release`.

## Current Objective

Repair C-01 before resuming LPFS production: MT5 epoch values were historically
relocalized through `Europe/Helsinki` even though MT5 Python epochs are UTC.
The release must preserve trustworthy diagnostic evidence for later
evidence-gated strategy research without changing LPFS entries, exits, risk
settings, timeframe mix, or strategy heuristics.

This is a live-safety release, not a strategy-improvement release.

## Contained Production State

Both VPS lanes were intentionally contained before implementation work:

| Lane | Task | Kill switch | Runner processes | LPFS broker pending | Active positions |
|---|---|---|---:|---:|---:|
| FTMO | `LPFS_Live` disabled | active | 0 | 0 | 3 |
| IC | `LPFS_IC_Live` disabled | active | 0 | 0 | 2 |

Both VPS machines remain powered on. Active positions are untouched and remain
supervised broker-side. Do not clear either kill switch, enable either task,
start a watchdog, restart a runner, modify broker orders, or rewrite runtime
state or journals until the reviewed release and deployment plan are approved.

Containment evidence:

- status packet:
  `reports/live_ops/lpfs_dual_vps_status_20260601_112826.md`
- FTMO strict broker export:
  `reports/live_ops/lpfs_c01_containment/20260601_112441/ftmo_mt5_evidence.json`
- IC strict broker export:
  `reports/live_ops/lpfs_c01_containment/20260601_112441/ic_mt5_evidence.json`

The evidence paths are ignored local artifacts. Runtime ignored configs were
updated in place to `live_send.market_recovery_mode="disabled"` while both
lanes were paused. Timestamped config backups were preserved on each VPS.

## FTMO Stage 1 Stop And Forward-Fix Gate

An approved sequential deployment attempted FTMO-only Stage 1 on 2026-06-02
ICT and stopped before IC. FTMO pulled reviewed commit
`79a3b21548653c4729eda07dc5f6da066d8018be`, passed `100` VPS-focused tests,
passed strict read-only broker exports before and after `--reconcile-only`,
and preserved broker exposure unchanged: pending orders `0`, active positions
`3`, and no broker history delta. FTMO remains contained with `KILL_SWITCH`
active, `LPFS_Live` disabled, runner process count `0`, and recovery disabled.
IC was not touched after the stop condition.

Authoritative ignored local FTMO stop packet:

```text
reports/live_ops/lpfs_c01_deploy/20260602_003007/ftmo
```

Its `evidence_manifest.json` SHA-256 is:

```text
87192736fe10ed2179f1d74b7089b9d20adf4ba29d4ecfecddf82a6230d51c09
```

The stop exposed two forward-fix gaps:

- `Get-LpfsLiveStatus.ps1` assumed normal-cycle heartbeat counters and failed
  under strict mode when the reconciliation heartbeat omitted them.
- clean reconciliation with no stale local pending records returned before
  atomic v2 persistence, so schema-v1 state remained in place without a
  deterministic receipt or completion-row replay anchor.

The forward fix makes heartbeat rendering tolerant of absent optional counters
and commits one deterministic `clean_noop_migration` receipt through the same
atomic v2 path as pending cleanup. Replay remains idempotent and backfills
missing deterministic lifecycle rows without applying migration twice.

Do not pull either VPS, rerun reconciliation, clear kill switches, enable
tasks, restart watchdogs, run a canary, or mutate broker state until the
forward-fix diff is reviewed and separately approved.

## Approved Scope

Allowed changes:

- parse MT5 bars, ticks, positions, and deals directly as UTC epochs;
- retain a deprecated `broker_time_epoch_to_utc` compatibility wrapper;
- require `live_send.market_recovery_mode="disabled"` in code;
- write v2 production state atomically with a downgrade tripwire;
- fail closed when required MT5 reads return `None`;
- compare canonical and deterministic legacy Helsinki-shifted signal keys;
- normalize mixed legacy/v2 close cursors under recorded semantics;
- add an isolated `--reconcile-only` mode for proof-backed stale pending
  cleanup while `KILL_SWITCH` exists;
- add a guarded `--one-cycle-canary` acknowledgment contract;
- add read-only evidence export and immutable normalization tools;
- update tests, generated operations docs, and handoff docs.

Not allowed:

- strategy heuristic changes;
- entry, exit, timeframe, or risk-setting changes;
- broker order or active-position edits;
- runtime state or journal deletion, reset, or manual rewrite;
- enabling market recovery;
- VPS pull, live deploy, reconcile-only execution, live canary, runner restart,
  task enablement, or watchdog resumption without separate operator approval.

## Timestamp Contract

New sparse broker-derived rows use:

```text
mt5_epoch_utc_v2
```

Legacy shifted tracked records default to:

```text
legacy_helsinki_relocalized_v1
```

The historical compatibility transform is fixed to `Europe/Helsinki`; it does
not depend on the current configured broker timezone. New diagnostics preserve
raw `time`, raw `time_msc`, normalized UTC, timestamp semantics, and provenance
where MT5 supplies them. Missing broker timestamps are recorded as unavailable
or fail closed where lifecycle ordering requires a timestamp. They are not
fabricated with `now()`.

## V2 State And Rollback

Production state uses schema v2:

```json
{
  "state_schema_version": 2,
  "minimum_reader_schema_version": 2,
  "processed_signal_keys": null,
  "state": {
    "state_writer_timestamp_semantics_version": "mt5_epoch_utc_v2"
  }
}
```

The top-level `processed_signal_keys: null` is deliberate: legacy loaders fail
before scanning or sending. All v2 production writes require atomic
replacement. A failed atomic replace activates or preserves `KILL_SWITCH`,
journals `live_state_atomic_replace_failed` where possible, and returns a
terminal watchdog code.

After any v2 state write or v2 send, rollback is forward-fix only. Do not run an
old timestamp binary against v2 state.

## Reconcile-Only Contract

`scripts/run_lp_force_strike_live_executor.py --reconcile-only` is routed
before the normal kill-switch early exit. It requires the kill switch, takes
the normal state-adjacent lock, validates account identity and broker reads,
and refuses unexpected broker pending orders or active-position mismatches.

It does not scan setups or candles and does not call `order_check`,
`order_send`, or cancellation requests. A local stale pending record is removed
only when validated MT5 broker history proves a terminal outcome. This release
does not accept an operator-evidence fallback. Ambiguous records abort with
local state unchanged.

Each commit has a deterministic reconciliation operation ID and a receipt in
v2 state. Reruns backfill missing deterministic lifecycle rows without applying
cleanup twice.

## Canary Contract

A direct one-cycle live canary requires:

```text
--one-cycle-canary
--cycles 1
--canary-exposure-ack I_ACCEPT_ONE_CYCLE_MAY_PLACE_AND_FILL_MULTIPLE_REAL_ORDERS
```

This does not bypass `KILL_SWITCH`. The operator wrapper must clear the kill
switch only for the CLI invocation, restore it in `finally`, verify it exists
again, and immediately inventory broker pending orders and active positions.
Skip the canary if multi-order exposure is unacceptable.

## C-01 Deployment Order

For this release only, deploy and review `FTMO` first, then `IC`. Older
`IC`-first instructions in handoff history describe the earlier watchdog
rollout and do not apply to C-01. Keep both lanes contained until a separate
operator-approved deployment step begins.

## Evidence Tools

Read-only full MT5 export:

```powershell
.\venv\Scripts\python scripts\export_lpfs_mt5_evidence.py `
  --config config.local.json `
  --lane FTMO
```

Immutable legacy journal normalization:

```powershell
.\venv\Scripts\python scripts\normalize_lpfs_c01_evidence.py `
  --journal "<local-legacy-journal-copy>"
```

The normalizer is semantics-aware: it preserves `mt5_epoch_utc_v2`, corrects
only affected legacy broker/candle-derived fields, prefers raw MT5 epochs where
available, rebuilds timestamp-bearing signal and trade keys, and records
unresolved warnings for unsupported timestamp paths. Every historical `*_utc`
leaf is explicitly classified as corrected, preserved, or unresolved. It
fails closed on unknown semantics. It does not shift heartbeat timestamps,
collection metadata, `occurred_at_utc`, actual placement timestamps, or VPS
startup timestamps. Preserve raw evidence and use normalized evidence for
production-derived strategy conclusions.

Affected historical timestamp inventory:

- bar-derived setup paths: `lp_break_time_utc`, `fs_signal_time_utc`,
  `signal_time_utc`, `signal_closed_time_utc`,
  `latest_closed_candle_time_utc`, and `first_expired_bar_time_utc`;
- tick-derived paths: `market_time_utc`;
- broker lifecycle paths: `opened_utc`, `closed_utc`, expiration paths, and
  touch-path timestamps. Expiration paths explicitly include
  `expiration_utc`, `broker_backstop_expiration_utc`,
  `old_expiration_utc`, and `new_broker_backstop_expiration_utc`;
- timestamp-bearing identities: `signal_key`, embedded signal keys in
  `event_key`, and diagnostic `trade_key`. Embedded `event_key` rebuilding
  accepts both `T` and space-separated historical timestamp forms;
- explicitly preserved system paths: `occurred_at_utc`, `placed_time_utc`,
  `collected_at_utc`, `boot_time_utc`, `detected_at_utc`, and
  `restart_event_time_utc`.

Unsupported timestamp-bearing paths are preserved and emitted as unresolved
warnings. Do not use a normalized packet for strategy conclusions until its
warning inventory has been reviewed. The packet manifest records
`safe_for_strategy_analysis=false` whenever unresolved warnings exist.

The diagnostic builder intentionally retains flexible local `--journal`
inputs. Compact live summaries remain stricter: they consume
collector-manifest-backed local snapshots.

## Analysis Workflow After Recovery

Once both lanes are safely migrated and normalized evidence exists:

1. rebuild FTMO and IC diagnostics plus weekly and monthly reports;
2. compare matched cross-lane setups and isolate broker/feed execution
   divergence before calling a strategy defect;
3. emphasize recent `3`, `6`, and `12` month windows while retaining the
   10-year backtest as a guardrail;
4. research small reversible candidates only when FTMO/IC evidence is
   directionally confluent;
5. deploy no heuristic change without a separate approved strategy-change
   plan.

## Files To Inspect First

1. `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/timestamp_semantics.py`
2. `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/live_executor.py`
3. `scripts/run_lp_force_strike_live_executor.py`
4. `scripts/run_lpfs_live_forever.ps1`
5. `scripts/Get-LpfsDualVpsStatus.ps1`
6. `scripts/export_lpfs_mt5_evidence.py`
7. `scripts/normalize_lpfs_c01_evidence.py`
8. `strategies/lp_force_strike_strategy_lab/tests/test_c01_live_safety.py`

## Current Blockers And Open Questions

- The FTMO-only Stage 1 attempt is stopped pending review of the narrow
  heartbeat-rendering and clean no-op migration forward fix.
- Do not pull either VPS or rerun reconciliation until that forward-fix diff is
  reviewed and separately approved.
- Decide whether the operator accepts a canary that may place and fill multiple
  real orders. If not, defer canary until a separately reviewed one-order cap
  exists.
- `PLAN.md` does not exist in this repository. The external working copy at
  `C:\Users\Cody\Downloads\PLAN.md` was updated to match this release and its
  apostrophe encoding was made ASCII-safe.

## Verification Status

Completed locally on 2026-06-01 ICT:

```powershell
.\venv\Scripts\python -m unittest `
  strategies.lp_force_strike_strategy_lab.tests.test_c01_live_safety `
  strategies.lp_force_strike_strategy_lab.tests.test_diagnostic_logging `
  strategies.lp_force_strike_strategy_lab.tests.test_dry_run_executor `
  strategies.lp_force_strike_strategy_lab.tests.test_live_executor `
  strategies.lp_force_strike_strategy_lab.tests.test_live_runner `
  strategies.lp_force_strike_strategy_lab.tests.test_dashboard_pages `
  strategies.lp_force_strike_strategy_lab.tests.test_live_trade_summary `
  strategies.lp_force_strike_strategy_lab.tests.test_live_weekly_performance `
  strategies.lp_force_strike_strategy_lab.tests.test_notifications `
  strategies.lp_force_strike_strategy_lab.tests.test_live_policy_ledger
.\venv\Scripts\python -m unittest discover -s strategies\lp_force_strike_strategy_lab\tests
.\venv\Scripts\python scripts\run_core_coverage.py
git diff --check
```

Results:

- focused C-01/executor/reporting set: `164` tests passed;
- full LPFS suite: `392` tests passed;
- strict core coverage: `6396` statements and `2190` branches at `100.00%`;
- `docs/live_ops.html` regeneration produced the same SHA-256:
  `9E43C278F60219BCE480E29BE53EF689D2E160A9429B4D08D81EBD4F86B3A57C`;
- local archived-row normalization rehearsal: `275578` snapshot rows,
  `461270` deterministic changes, and `0` unresolved warnings;
- `git diff --check`: passed;
- manual scope audit: no strategy heuristic, entry/exit, timeframe-selection,
  risk-bucket, sizing-limit, or broker-send expansion.

No deployment was performed. The final reviewed handoff must still record the
commit hash and any separately approved deployment result. Until then,
production remains intentionally paused.
