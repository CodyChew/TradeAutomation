# TradeAutomation Session Handoff

Last updated: 2026-07-09 ICT after operator-approved LPFS flatten and project
hold.

This is the latest volatile handoff. It is not live broker truth by itself.
Before any live operation, capture fresh broker/status evidence from the
approved dual-lane status path and follow `AGENTS.md`.

## Read First

1. `AGENTS.md` for standing roles, live-safety boundaries, change-gate policy,
   code-change boundaries, and verification expectations.
2. `docs/change_gate.md` before material live/deployment, broker, strategy,
   risk, evidence, generated-artifact, first-read, or process changes.
3. `docs/context_architecture.md` for the current source-of-truth map.
4. `docs/repo_maintenance_policy.md` and `docs/decision_log.md` before
   repo-structure, onboarding, workflow, or decision-history work.
5. `PROJECT_STATE.md` for the concise workspace state.
6. `strategies/lp_force_strike_strategy_lab/START_HERE.md` for the LPFS
   first-read path, source-of-truth matrix, environment boundaries, and resume
   prompts.
7. `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md` for current LPFS
   live/research detail.
8. `docs/lpfs_strategy_iteration_context.md` and
   `docs/lpfs_strategy_improvement_workflow.md` before strategy review,
   candidate research, automation cadence, or workflow changes.
9. `docs/evidence_catalog.md` for packet paths, hashes, current/historical
   labels, and questions answered.
10. `docs/history/lpfs_operations.md` for old operational incidents,
    deployment history, and packet narratives moved out of this handoff.
11. `docs/system_troubleshooting.md` before troubleshooting live runners, MT5,
    datasets, dashboards, or generated reports.
12. `docs/codex_worktree_workflow.md` before editing from a Codex or linked
    worktree.
13. `configs/live_policy_ledger.csv` before interpreting live performance
    across FTMO/IC sizing-policy epochs or changing live risk settings.
14. `docs/lpfs_diagnostic_logging.md` before changing LPFS journal fields,
    diagnostic reports, or live-vs-backtest analysis fields.

## Current Handoff Boundary

LPFS live trading and live data collection are on hold. On 2026-07-09 ICT the
operator approved flattening both LPFS lanes and pausing the project for review
and next-step planning. Both lane tasks are disabled, both kill switches are
active, and the operation targeted LPFS-managed exposure only.

Flatten/hold packet:
`reports/live_ops/lpfs_flatten_hold_20260709_050513`, manifest SHA-256
`2e0cf51d45b705cef5a23f5126e330028cf69b3de006a874f6b29d698aef55c0`.
Final dual-status report:
`reports/live_ops/lpfs_flatten_hold_20260709_050513/final_dual_status/lpfs_dual_vps_status_20260709_051800.md`,
SHA-256 `e8bba7a9dbdb5cdd37dc2332cff022becf29671a3dbdba644e7e96bc1939e7f1`.

Final broker/ops facts from that packet:

- FTMO: `LPFS_Live` disabled, kill switch active, runner/watchdog rows `0`,
  broker status `OK`, LPFS pending orders `0`, LPFS active positions `0`.
- IC: `LPFS_IC_Live` disabled, kill switch active, runner/watchdog rows `0`,
  broker status `OK`, LPFS pending orders `0`, LPFS active positions `0`.
- Recovery remained disabled on both lanes.
- No reconciliation-only run, canary, market-recovery enablement,
  strategy/risk/sizing/SL/TP/broker-send/config change, production journal
  edit, or runtime-state edit was performed.

Important: status is expected to show state/broker mismatch after the manual
broker flatten because local runtime state and journals were intentionally not
rewritten. Treat the old state entries as quarantined hold-state evidence. Do
not resume, reconcile, edit runtime state, or interpret the mismatch as an
active broker exposure without a separate reviewed plan and fresh MT5 proof.

The latest deployed robustness/runtime boundary before the hold remains the
2026-06-15 RA-002/RA-003 robustness deploy at runtime SHA
`6c4ecb131d7499e455ef42cfeb91ba0bc0a75490`. It includes:

- RA-002 final pre-send quote-unavailable block;
- RA-003 Stage 5 contract pin refresh;
- Phase 1 live quote telemetry separation at SHA
  `027e0afe932081713067dc24b2bc457cddf1041e`;
- active-position state/broker repair at SHA
  `45efa748423f20881507cda9d4f81e4afe617bde`;
- transient market-data frame-skip handling.

The previous same-day dual VPS status packet recorded in first-read context is
`reports/live_ops/lpfs_dual_vps_status_20260627_080624.md`, SHA-256
`b56f0ad7bf543ac157522522173620a01c2ce584b1c4925974738681e616728d`.
It showed both lanes `RUNNING`, runtime SHA `6c4ecb1`, kill switches clear,
broker status `OK`, recovery disabled, market-data fetch failures `0`,
telemetry write/retention failures `0`, and active state/broker mismatch count
`0`. Broker exposure in that packet was FTMO `7` pending / `4` active strategy
items and IC `2` pending / `5` active strategy items.

Treat those counts as superseded historical packet facts only. Capture a fresh
dual VPS status packet before future live operations, deployment decisions,
restarts, reconciliation, canaries, broker-adjacent actions, or runtime-state
decisions.

## Current Strategy And Evidence State

Latest eligible weekly strategy-review packet:
`reports/live_ops/lpfs_weekly_strategy_review/20260627_080107/weekly/20260627_010107`.
Both lanes were `analysis_eligible=true` with `coverage_status=complete`.
FTMO had `20` closed trades, `+1.99R`, broker PnL `+11.24`, PF `1.21`, and
historical band `p46.9`. IC had `22` closed trades, `-4.84R`, broker PnL
`-11.79`, PF `0.65`, and historical band `<=p10`. Combined result was `42`
closed trades, `-2.85R`, broker PnL `-0.55`, PF `0.88`.

Latest strategy research readiness packet:
`reports/live_ops/lpfs_strategy_research_readiness/20260627_131500`, manifest
SHA-256 `1a6136209337be1b1d4b28e3da4e8e7f4da97421872d67c74af8270f09065ec6`.

Latest maintained candidate matrix:
`reports/live_ops/lpfs_candidate_backtest_matrix/20260705_064500`, manifest
SHA-256 `23c3d3da7afff6fab030816bcfc30645c0a900da443a8490d6a257ded53f4b6a`.

Latest skipped-opportunity diagnostics:
`reports/live_ops/lpfs_skipped_opportunity_diagnostics/20260705_080000`,
manifest SHA-256
`ca63c162ee7e89fc8cf0846f65fc2075f7fb546e576143cc9a0846acb1fcc03f`.
That packet found `4` IC `volume_below_min` broker-minimum skips and `0` FTMO
broker-minimum skips in the safe July 4 filtered lifecycle evidence window.

Current strategy decision:

- No live strategy change is approved.
- Reject the simple H8 low-spread-only filter unless future evidence overturns
  the 2026-06-27 rejection.
- Keep H8 compressed risk (`timeframe=H8`, `risk_atr_bucket=lt_0p5`) as the
  leading active research candidate, but do not promote it yet because the
  live sample is still small and the 12M backtest window remains contradictory.
- Treat broad long-side, setup-age, and structure buckets as diagnostic only.
- Treat IC `volume_below_min` rows as account-size comparability evidence, not
  closed-trade performance and not live sizing-change approval.

Use `docs/lpfs_strategy_iteration_context.md` for the current strategy queue
and `docs/evidence_catalog.md` for packet hashes.

## Live Operations Boundary

Do not access VPS, MT5, Task Scheduler, live runtime state, production
journals, broker orders, broker positions, kill switches, reconciliation,
canaries, runner restarts, VPS pulls, runtime-state edits, or market recovery
unless the user explicitly approves that operational scope.

For approved future live operations, first acknowledge that both lanes are held
flat and local runtime state is intentionally stale. A restart/resumption plan
must include broker-truth prechecks, a state/journal handling decision, and
reviewer approval before clearing kill switches or enabling tasks. Preserve the
FTMO-first, IC-second review order unless a new reviewed plan says otherwise.
Keep `live_send.market_recovery_mode` disabled unless a separate recovery
re-enable plan is approved. Stop on ambiguity, duplicate runner uncertainty,
stale heartbeat, MT5 `ERROR/UNKNOWN`, unexplained broker exposure,
active-position drift, unreviewed state/broker mismatch, telemetry failure,
market-data degradation affecting the
decision, or recovery-mode drift.

Do not build automation that assumes `scripts/Get-LpfsLiveStatus.ps1` emits
`LPFS_SNAPSHOT_JSON`. Use `scripts/Get-LpfsDualVpsStatus.ps1` for structured
dual-lane proof, or add a tested explicit structured single-lane mode before
consuming single-lane status output in automation.

## Evidence And Journal Rules

Broker history, orders, deals, positions, ticket IDs, fill prices, close
prices, volume, commission, swap, and realized PnL are broker facts. Journals,
state files, Telegram alerts, dashboards, inferred timestamps, R values, and
strategy labels are local or derived evidence.

Primary lifecycle journals are append-only. Do not migrate, compact, truncate,
or rewrite historical production journals. Do not use active journal hashing as
a health probe. Production-adjacent journal/state reads must use bounded or
shared-read tooling and should be followed by fresh dual-VPS status proof.

## Historical Context Pointers

Historical packet narratives were moved out of this handoff to keep the current
state readable:

- Operations history: `docs/history/lpfs_operations.md`.
- Evidence packet index: `docs/evidence_catalog.md`.
- LPFS experiment chronology:
  `strategies/lp_force_strike_strategy_lab/docs/experiment_history.md`.
- Material review for this context hardening:
  `docs/reviews/2026-07-04-context-architecture-hardening.md`.

Historical IC promotion state is superseded by Stage 5 resumption and the
latest dual VPS status packet for current IC. Do not treat old IC promotion,
C-01 paused-state, Stage 3, or Stage 5 rollout packets as current broker truth.

## Current Non-Actions

This handoff update is docs/process-only. It did not change live strategy
behavior, entry/exit logic, risk sizing, SL/TP logic, spread gates, broker-send
behavior, configs, scheduler/watchdog state, runtime state, journals, reports,
generated dashboards, VPS state, broker orders, broker positions, account
state, or market recovery.

## Verification To Run For This Context Surface

For first-read, process, or context hardening changes:

```powershell
.\venv\Scripts\python -B scripts\audit_repo_process.py
.\venv\Scripts\python -B -m unittest strategies.lp_force_strike_strategy_lab.tests.test_repo_process_audit
.\venv\Scripts\python -B -m unittest strategies.lp_force_strike_strategy_lab.tests.test_dashboard_pages
git diff --check
```

Full core coverage is not required for docs/audit-tooling-only changes unless
source behavior changes. If strategy, execution, reporting builders,
configurable runtime behavior, generated dashboard builders, or shared live
behavior change, use the focused tests and coverage gates in `AGENTS.md` and
`docs/testing_strategy.md`.
