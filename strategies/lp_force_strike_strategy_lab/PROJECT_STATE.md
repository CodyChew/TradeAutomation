# LP Force Strike Strategy Lab Project State

Last updated: 2026-07-09 ICT after operator-approved LPFS flatten and project
hold.

This is the current LPFS strategy/live/research state. Historical packet
narratives moved to `../../docs/history/lpfs_operations.md`, packet hashes to
`../../docs/evidence_catalog.md`, and experiment chronology to
`docs/experiment_history.md`.

## Current Live-Ops State

Read `START_HERE.md`, `../../SESSION_HANDOFF.md`, and
`../../docs/lpfs_c01_live_safety_release.md` before any LPFS operation.

LPFS live trading and live data collection are on hold. On 2026-07-09 ICT the
operator approved flattening both LPFS lanes and pausing the project for review
and next-step planning. Both lane tasks are disabled, both kill switches are
active, and broker-authoritative LPFS pending orders and active positions are
`0` on both FTMO and IC.

Flatten/hold packet:
`../../reports/live_ops/lpfs_flatten_hold_20260709_050513`, manifest SHA-256
`2e0cf51d45b705cef5a23f5126e330028cf69b3de006a874f6b29d698aef55c0`.
Final dual-status report:
`../../reports/live_ops/lpfs_flatten_hold_20260709_050513/final_dual_status/lpfs_dual_vps_status_20260709_051800.md`,
SHA-256 `e8bba7a9dbdb5cdd37dc2332cff022becf29671a3dbdba644e7e96bc1939e7f1`.

The final status is expected to be `AMBIGUOUS` because the broker was manually
flattened while runtime state and journals were left immutable. Treat the
state/broker mismatch and state-not-in-broker entries as quarantined hold-state
evidence. A future resumption requires a separate reviewed plan for
broker-truth prechecks, state/journal handling, and sequential FTMO-first then
IC proof.

The latest deployed robustness/runtime boundary before the hold remains the
2026-06-15 RA-002/RA-003 robustness deploy at runtime SHA
`6c4ecb131d7499e455ef42cfeb91ba0bc0a75490`. Historical running packets before
2026-07-09 are superseded for current operations.

Relevant deployed safety history:

- Phase 1 live quote telemetry separation deployed at SHA
  `027e0afe932081713067dc24b2bc457cddf1041e`. Lifecycle journals no longer
  receive new live `market_snapshot` rows; market snapshots route to separate
  telemetry journals.
- Active-position state/broker repair deployed at SHA
  `45efa748423f20881507cda9d4f81e4afe617bde`. Full MT5 close-deal volume proof
  is required before local active state can remove a broker-missing position.
- Transient market-data frame-skip handling is included in current runtime SHA
  `6c4ecb131d7499e455ef42cfeb91ba0bc0a75490`; broker/account/order/position
  failures still fail closed.

Do not rerun reconciliation, run a canary, start a duplicate runner, manually
modify broker orders or positions, enable recovery, edit runtime state, edit
production journals, clear kill switches, enable tasks, or change
strategy/risk/sizing/SL/TP/broker-send behavior without a separately approved
operation.

Historical IC promotion state is superseded by Stage 5 resumption and the
latest dual VPS status packet for current IC. Older C-01, Stage 3, and Stage 5
rollout packets remain historical context only.

## Purpose

This lab studies the combination of active LP level traps and raw Force Strike
patterns. It includes:

- signal detection: LP break plus raw Force Strike confirmation;
- experiment harness: fixed bracket trade-model candidates for research;
- execution contract: conversion from tested `TradeSetup` to guarded MT5 order
  intent or explicit rejection;
- dry-run adapter: closed-candle MT5 polling, UTC normalization, local
  journal/state files, live spread logging, order intent building, and
  `order_check` only;
- live-send adapter: explicitly enabled MT5 pending-order placement with
  guarded broker/account/order/position handling;
- diagnostics: sparse additive lifecycle payloads and offline diagnostic
  reporting;
- native EA migration: isolated Strategy Tester-only MQL5 scaffold under
  `../../mql5/lpfs_ea`.

Python and MT5 broker evidence remain canonical for research and live execution.
TradingView/Pine is for chart inspection and alerts.

## Current Baseline

Current LPFS baseline: V13 mechanics plus V15 risk buckets plus V22 LP/FS
separation.

- LP3 take-all across H4/H8/H12/D1/W1.
- Selected LP pivot must be before the Force Strike mother bar.
- `0.5` signal-candle pullback entry.
- Full Force Strike structure stop.
- Single `1R` target.
- Fixed 6-bar pullback wait.

Current live-validation risk interpretation:

- FTMO live/default bucket: H4/H8 `0.20%`, H12/D1 `0.30%`, W1 `0.75%`.
- IC analysis bucket: H4/H8 `0.25%`, H12/D1 `0.30%`, W1 `0.75%`.
- Live sizing policy epochs are tracked in `../../configs/live_policy_ledger.csv`.

Experiment chronology and older candidates live in `docs/experiment_history.md`.

## Current Strategy Review State

Latest eligible weekly strategy-review packet:
`../../reports/live_ops/lpfs_weekly_strategy_review/20260627_080107/weekly/20260627_010107`.
Both lanes were `analysis_eligible=true` with `coverage_status=complete`.

- FTMO: `20` closed trades, `+1.99R`, broker PnL `+11.24`, PF `1.21`,
  historical band `p46.9`.
- IC: `22` closed trades, `-4.84R`, broker PnL `-11.79`, PF `0.65`,
  historical band `<=p10`.
- Combined: `42` closes, `-2.85R`, broker PnL `-0.55`, PF `0.88`.

Current research closeout:
`../../reports/live_ops/lpfs_strategy_research_readiness/20260627_131500`,
manifest SHA-256
`1a6136209337be1b1d4b28e3da4e8e7f4da97421872d67c74af8270f09065ec6`.

Current maintained candidate matrix:
`../../reports/live_ops/lpfs_candidate_backtest_matrix/20260705_064500`,
manifest SHA-256
`23c3d3da7afff6fab030816bcfc30645c0a900da443a8490d6a257ded53f4b6a`.

Current skipped-opportunity diagnostics:
`../../reports/live_ops/lpfs_skipped_opportunity_diagnostics/20260705_080000`,
manifest SHA-256
`ca63c162ee7e89fc8cf0846f65fc2075f7fb546e576143cc9a0846acb1fcc03f`.
It found `4` IC `volume_below_min` broker-minimum skips and `0` FTMO
broker-minimum skips in the safe July 4 filtered lifecycle evidence window.

Decision:

- No live strategy change is approved.
- Reject the H8 low-spread-only filter because it was live-weak but
  historically positive.
- Keep H8 compressed risk (`timeframe=H8`, `risk_atr_bucket=lt_0p5`) as the
  leading active research candidate.
- Deployment is blocked by small live sample size and contradictory 12M
  backtest evidence.
- Treat broad long-side, setup-age, and structure buckets as diagnostic only.
- Treat IC `volume_below_min` rows as account-size comparability evidence, not
  closed-trade performance or live sizing-change approval.

Use `../../docs/lpfs_strategy_iteration_context.md` for the current strategy
queue and `../../docs/lpfs_strategy_improvement_workflow.md` for cadence,
trigger/triage outcomes, candidate-register rules, and human-operator
responsibilities.

## Evidence Requirements

Future strategy review must preserve enough evidence to explain why a trade was
taken, how it was executed, and why it won, lost, or was missed.

Required context includes setup identity, market/session context, spread-risk,
execution quality, broker ticket/order/deal IDs, lifecycle close evidence,
reconciliation status, lane identity, policy epoch, and offline indicator tags
when used for research.

Use `analysis_eligible=true` and `coverage_status=complete` for weekly
strategy-review rows. Segment IC results around the live policy ledger boundary
`2026-05-30T17:14:27Z` until report builders assign ledger `policy_id`
automatically.

## Safety Rules

- Do not change live strategy behavior during diagnostic/reporting work.
- Do not add indicator or percentile calculations to the live runner loop by
  default.
- Do not expand high-volume `market_snapshot` rows.
- Do not scan active production journals with unsafe file-open semantics.
- Use bounded/tail reads and `FileShare.ReadWrite` for production-adjacent
  journal/state reads.
- Follow production-adjacent remote journal/state reads with a fresh dual-VPS
  status packet.
- Do not run a manual live process while scheduled live runners are active.
- Do not touch MT5 orders, positions, history, live state, or live journals
  unless the user approves a separate operator plan.
- Treat logging deploys as operational changes requiring explicit restart and
  verification.

## Current Evidence Index

Use `../../docs/evidence_catalog.md` for hashes and paths. Current key rows:

- `lpfs-status-20260627`
- `lpfs-weekly-20260627`
- `lpfs-candidate-matrix-20260705`
- `lpfs-skipped-opportunities-20260705`
- `lpfs-research-closeout-20260627`
- `lpfs-ra002-ra003-20260615`
- `lpfs-active-repair-final-20260609`
- `lpfs-telemetry-ftmo-20260607`
- `lpfs-telemetry-ic-20260607`

## How To Continue Safely

1. Run `git status --short` and inspect intended files.
2. Classify the task as docs-only, reporting-only, research-only, or
   production-adjacent.
3. For docs-only work, do not touch live runners or VPS state.
4. For reporting-only work, use safe local journal copies and explicit
   provenanced candle datasets. FTMO/IC live-lane candle-derived attribution
   requires lane-authoritative candle roots; unverified workstation candles are
   a `DATA_GAP`.
5. For production-adjacent reads, use approved safe bounded/shared-read tooling
   and verify both VPS lanes afterward.
6. For any live deploy or restart, create a separate kill-switch-first operator
   plan and get explicit approval.

## Verification

For docs/process or first-read updates:

```powershell
.\venv\Scripts\python -B scripts\audit_repo_process.py
.\venv\Scripts\python -B -m unittest strategies.lp_force_strike_strategy_lab.tests.test_repo_process_audit
.\venv\Scripts\python -B -m unittest strategies.lp_force_strike_strategy_lab.tests.test_dashboard_pages
git diff --check
```

For behavior changes, use the focused tests and core coverage gates in
`../../AGENTS.md` and `../../docs/testing_strategy.md`.

## Current Non-Actions

The 2026-07-04 context hardening is docs/process-only. It did not change live
strategy behavior, entry/exit logic, risk sizing, SL/TP logic, spread gates,
broker-send behavior, configs, scheduler/watchdog state, runtime state,
journals, reports, generated dashboards, VPS state, broker orders, broker
positions, account state, or market recovery.
