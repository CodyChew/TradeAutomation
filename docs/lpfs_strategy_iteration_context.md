# LPFS Strategy Iteration Context

Last updated: 2026-06-07 ICT after LPFS minimum-safety resumption.

This is the durable handoff for the current LPFS diagnostic reporting and
strategy-iteration work. A new Codex chat should be able to read this file,
`SESSION_HANDOFF.md`, and `strategies/lp_force_strike_strategy_lab/START_HERE.md`
without needing prior conversation history.

## Current Objective

Make LPFS strategy iteration evidence-based without changing live trading
behavior. The immediate prerequisite is the C-01 live-safety release documented
in `docs/lpfs_c01_live_safety_release.md`: historical production MT5 epochs
were shifted through `Europe/Helsinki`, so production-derived analysis must use
immutable normalized evidence. After that repair, run offline first-month cause
attribution from enriched live trade diagnostics, compare FTMO and IC together,
and produce defensible future strategy-change candidates only after enough
evidence exists.

The current work is reporting/context only. It is not a live strategy change,
not a live deployment, and not approval to change entries, exits, risk,
timeframe selection, spread gates, recovery behavior, or broker execution.

H8 was discussed as an example. H8 is not a selected change candidate unless
future diagnostics prove a persistent cross-lane issue.

Stage 5 minimum-safety resumption completed on 2026-06-07 ICT. FTMO and IC
live data collection are running again, recovery remains disabled, and final
proof recorded zero pending broker orders plus unchanged active-position
inventories. Before strategy analysis, refresh current status from the dual
VPS status packet and use normalized C-01 evidence for production-derived
historical timestamps.

## Current Project State

- LPFS live operation has two production lanes: FTMO and IC. They run the same
  strategy and should be reviewed together for confluence.
- Live sizing policy epochs are tracked in `configs/live_policy_ledger.csv`.
  Use that ledger when reading live results across FTMO and IC so analysis does
  not mix strategy performance with risk-policy changes. The active IC
  scale-down is a future-order sizing policy change, not a strategy-rule
  change.
- Diagnostic lifecycle payloads already preserve
  `diagnostics.strategy.risk_bucket_scale`, and flattened trade reports expose
  `diagnostic_strategy_risk_bucket_scale`. The current offline report builder
  does not yet assign ledger `policy_id` or automatically group comparisons by
  sizing-policy epoch. Until that enhancement exists, segment IC rows
  explicitly using the ledger activation boundary `2026-05-30T17:14:27Z` and
  the flattened diagnostic scale field.
- The latest completed weekly checkpoint is
  `reports/live_ops/lpfs_weekly_performance/20260530_150637`. Its generated
  dashboard has an FTMO fetch-timeout caveat, so the authoritative FTMO
  checkpoint read is the supplemental local-snapshot review at
  `reports/live_ops/lpfs_weekly_performance/20260530_150637/local_snapshot_review.md`.
- 2026-05-30 latest completed week, 2026-05-25 05:00 SGT to 2026-05-30
  05:00 SGT: FTMO had 13 closed trades, `-0.56R`, 6 wins / 7 losses, PF
  `0.92`, historical percentile `p32.4`; IC had 16 closed trades, `-3.63R`,
  7 wins / 9 losses, PF `0.67`, historical percentile `p12.5`.
- This was mixed rather than a clean cross-lane failure: FTMO was acceptable
  and IC was weak/watch but still above p10. Current confluence is H4 weakness
  (`-4.37R` combined over 17 trades), while H8 was not weak this week
  (`+0.14R` combined over 8 trades).
- FTMO previously had three completed weeks below p30, and IC had two
  completed weeks below p30. The 2026-05-30 weekly checkpoint alone does not
  justify a live strategy change, but the first-month monthly view escalates
  the next step from passive monitoring to offline investigation now.
- First-month monthly review: `docs/lpfs_monthly_evidence_20260530.md`.
  Against the accepted V22 separated commission-adjusted monthly backtest
  distribution, FTMO May 2026 live closed trades are `-15.09R` over 71 trades
  at monthly p1.67, and IC is `-13.47R` over 61 trades at monthly p0.83.
  The 10-year backtest did not have every month profitable: FTMO had 28 losing
  months out of 120, and IC had 20 losing months out of 121. The current live
  month is still near the historical lower tail and warrants cause attribution.
- Diagnostic lifecycle logging has already been deployed to production as a
  logging-only change. It adds sparse `diagnostics` payloads to signal/order/
  recovery/fill/close/block events.
- The local diagnostic report builder has been extended to make those logs
  useful for future strategy review. This reporting change has not been
  deployed to the VPS and does not need a runner restart unless the user later
  wants the report code available on the VPS checkout.
- Current enriched closed-trade sample is still too small for an informed live
  heuristic change. The 2026-05-30 diagnostic report has 29 closed trades with
  `diagnostic_schema_version`; all 29 are from the latest week, but only 16
  have full setup geometry, spread gate, order retcode, and backtest join
  fields.

## Approved Scope

Approved now:

- Offline diagnostic reporting from safely collected local journal copies.
- Offline candle-derived enrichment from local dataset roots.
- FTMO/IC confluence views.
- Recent 3, 6, and 12 month analysis windows, with the full 10-year backtest
  as the robustness guardrail.
- Documentation and handoff updates that preserve this operating context.
- Tests for report generation, backward-compatible journal parsing, and
  unchanged executor behavior.

Not approved now:

- Live strategy heuristic changes.
- Per-timeframe rules beyond existing risk buckets.
- Entry, exit, stop, target, recovery, spread, risk, or exposure changes.
- Config default changes, except the separately executed IC future-order
  scale-down captured in `configs/live_policy_ledger.csv`.
- Live runner loop indicator calculations.
- VPS deployment or runner restarts for this reporting-only work.
- Manual edits to live state, journals, MT5 orders, MT5 positions, or history.

## Files Changed So Far

Intentional LPFS diagnostic/reporting/context files changed in this work:

- `scripts/build_lpfs_trade_diagnostics.py`
- `strategies/lp_force_strike_strategy_lab/tests/test_diagnostic_logging.py`
- `docs/lpfs_diagnostic_logging.md`
- `docs/lpfs_strategy_iteration_context.md`
- `PROJECT_STATE.md`
- `SESSION_HANDOFF.md`
- `docs/live_weekly_performance.html`
- `reports/live_ops/lpfs_weekly_performance/20260530_150637/local_snapshot_review.md`
- `docs/lpfs_monthly_evidence_20260530.md`
- `strategies/lp_force_strike_strategy_lab/START_HERE.md`
- `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md`

Current local worktree may contain uncommitted documentation/report artifacts
from the 2026-05-30 checkpoint. Run `git status --short` before staging and do
not stage, revert, or mix unrelated files into an LPFS diagnostic/reporting
commit unless separately reviewed.

## Files To Inspect First

Start here in a fresh Codex chat:

1. `SESSION_HANDOFF.md`
2. `strategies/lp_force_strike_strategy_lab/START_HERE.md`
3. `docs/lpfs_strategy_iteration_context.md`
4. `docs/lpfs_diagnostic_logging.md`
5. `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md`
6. `docs/live_weekly_performance.html`
7. `docs/mt5_execution_contract.md`
8. `docs/lpfs_lightsail_vps_runbook.md`
9. `docs/lpfs_icmarkets_vps_runbook.md`

Before touching production-adjacent data, verify current repo status and live
status. Do not assume this handoff is live-state truth.

## How To Continue Safely

1. Run `git status --short` and separate intended LPFS diagnostic files from
   unrelated dirty files.
2. Read the files listed above before making changes.
3. Decide whether the task is docs-only, reporting-only, research-only, or
   production-adjacent.
4. For docs-only work, do not touch live runners or VPS state.
5. For reporting-only work, use local journal copies and local candle datasets.
6. For production-adjacent reads, use safe bounded/shared-read tooling and
   verify both VPS lanes afterward.
7. For any live deploy or restart, create a separate kill-switch-first operator
   plan and get explicit approval.

## What Not To Touch

- Live entry, exit, stop, target, recovery, spread, risk, exposure, or
  timeframe-selection logic.
- Config defaults or ignored live configs.
- MT5 orders, positions, deal history, live state, live journals, or runtime
  files.
- Scheduled tasks or live runners unless the user explicitly approves an
  operator plan.
- High-volume `market_snapshot` logging.
- Unrelated dirty files in the current worktree.

## Analysis Workflow To Improve The Strategy

The workflow is evidence-gated manual adaptation:

1. Collect safe local copies of FTMO and IC journals.
2. Build the offline LPFS diagnostic trade report.
3. Review FTMO and IC together, not independently.
4. Identify whether weakness is broad or concentrated by timeframe, symbol,
   side, session, weekday, setup geometry, volatility regime, momentum regime,
   tick-volume regime, spread-risk, execution path, recovery path, hold time,
   or exit reason.
5. Treat one-lane weakness first as broker/feed/execution divergence.
6. Use recent 3, 6, and 12 month benchmark windows as the primary research
   lens.
7. Use the full 10-year FTMO and IC backtests as the overfitting guardrail.
8. Research both defensive and constructive candidates only after evidence
   supports the cause.
9. Deploy no live strategy change unless a separate approved strategy-change
   plan passes recent-window checks, full-history guardrails, and FTMO/IC
   confluence.

Defensive candidates include filters, gates, exposure reductions, session or
spread avoidance, setup-age/risk filters, and correlated exposure limits.

Constructive candidates include better entry timing, entry-zone changes,
stop/risk-distance changes, target/partial/exit changes, recovery behavior
changes, and regime-aware management.

## Evidence Thresholds

Use these as operating guidance, not automatic deploy rules:

| Timeframe class | Investigate after | Research candidate after |
| --- | ---: | ---: |
| Higher frequency, such as H4 | 20 combined enriched closed trades | 40 combined enriched closed trades |
| Mid frequency, such as H8/H12/D1 | 10 combined enriched closed trades | 20 combined enriched closed trades |
| Sparse, such as W1 | 5 combined enriched closed trades | 10 combined enriched closed trades |

Two weak weeks can justify monitoring or investigation when both FTMO and IC
show the same issue. Three to four weak weeks can justify candidate research if
the same timeframe/setup/regime repeatedly underperforms.

Sparse timeframes can trigger research with fewer live trades, but they require
stronger recent-window and full-history backtest confirmation before any live
deployment.

## Safety Rules

- Do not change live strategy behavior during diagnostic/reporting work.
- Do not add indicator or percentile calculations to the live runner loop.
- Do not expand high-volume `market_snapshot` rows.
- Do not scan active production journals with unsafe file-open semantics.
- Use bounded/tail reads and `FileShare.ReadWrite` for production-adjacent
  journal/state reads.
- Follow any production-adjacent remote journal/state read with a fresh
  dual-VPS status packet.
- Do not run a manual live process while scheduled live runners are active.
- Do not touch MT5 orders, positions, history, live state, or live journals
  unless the user approves a separate operator plan.
- Treat logging deploys as operational changes requiring explicit restart and
  verification.
- Treat reporting/docs-only changes as local-only unless the user explicitly
  asks to deploy docs to the VPS checkout.

## How To Run

Build a diagnostic report from local journal copies:

```powershell
.\venv\Scripts\python scripts\build_lpfs_trade_diagnostics.py `
  --journal "FTMO=path\to\lpfs_live_journal.jsonl" `
  --journal "IC=path\to\lpfs_ic_live_journal.jsonl"
```

Diagnostics accept archived, historical, synthetic, or safely collected local
evidence. Prefer `scripts/collect_lpfs_live_journal_snapshots.py` for
production journal evidence, capture a fresh dual-VPS status packet after the
collection, and never pass an active VPS runtime journal path to the diagnostic
builder. Compact summaries are stricter: they require a collector-produced,
manifest-backed `--journal-snapshot`.

Optional explicit candle roots:

```powershell
.\venv\Scripts\python scripts\build_lpfs_trade_diagnostics.py `
  --journal "FTMO=path\to\lpfs_live_journal.jsonl" `
  --journal "IC=path\to\lpfs_ic_live_journal.jsonl" `
  --candle-root "FTMO=data\raw\ftmo\forex" `
  --candle-root "IC=data\raw\lpfs_new_mt5_account\forex"
```

Focused verification for this work:

```powershell
.\venv\Scripts\python -m unittest `
  strategies.lp_force_strike_strategy_lab.tests.test_diagnostic_logging `
  strategies.lp_force_strike_strategy_lab.tests.test_live_trade_summary `
  strategies.lp_force_strike_strategy_lab.tests.test_live_weekly_performance `
  strategies.lp_force_strike_strategy_lab.tests.test_live_gate_attribution `
  strategies.lp_force_strike_strategy_lab.tests.test_dry_run_executor `
  strategies.lp_force_strike_strategy_lab.tests.test_live_executor
```

Full core verification:

```powershell
.\venv\Scripts\python scripts\run_core_coverage.py
```

Read-only live status, when needed:

```powershell
.\scripts\Get-LpfsDualVpsStatus.ps1 -JournalLines 20 -LogLines 40
```

## Output Expectations

`scripts/build_lpfs_trade_diagnostics.py` writes to:

```text
reports/live_ops/lpfs_trade_diagnostics/<timestamp>/
```

Expected files:

- `closed_trade_diagnostics.csv`: closed live trades with result fields,
  flattened diagnostics, offline time/session/setup buckets, execution buckets,
  recent-window flags, and candle-derived regimes where available.
- `backtest_diagnostics.csv`: benchmark backtest trades enriched with matching
  offline fields where available.
- `backtest_comparison.csv`: live-versus-backtest grouped comparisons across
  lane, timeframe, symbol, side, session, weekday, setup buckets, execution
  buckets, and candle regimes.
- `timeframe_confluence.csv`: FTMO/IC timeframe confluence rows, live/backtest
  deltas, sample thresholds, and current research action.
- `summary.md`: compact human-readable report summary.

The report is not expected to recommend automatic live changes. It should
surface hypotheses and evidence quality.

## Current Blockers

- Current enriched live closed-trade sample is too small for a live strategy
  change, but the live first-month monthly underperformance is strong enough
  to justify offline cause-attribution research now.
- Production diagnostic rows are only useful after enough real lifecycle and
  close events accumulate.
- The 2026-05-30 generated weekly dashboard hit an FTMO fetch timeout, so the
  FTMO weekly result must be read from the local lifecycle-snapshot review
  until the weekly report path supports bounded/local lifecycle input.
- True 10-year tick-level Bid/Ask/order-book data is not available from the
  current IC terminal; candle data and M1 spread fields are available.
- The current diagnostic report supports offline indicator/regime analysis, but
  any actual heuristic candidate still needs separate research/backtest work.
- The current diagnostic report preserves sizing scale per enriched trade but
  does not yet derive `policy_id` from `configs/live_policy_ledger.csv` or
  automatically produce policy-epoch comparison groups.
- There are unrelated dirty/untracked files in the local worktree that must not
  be mixed into LPFS diagnostic commits.

## Open Questions

- How many enriched closed live trades will accumulate per timeframe over the
  next several weeks?
- Are the first-month FTMO and IC losses driven by the same weak buckets or by
  broker/feed/execution divergence?
- Are weak weeks explained by sample variance, setup quality, execution,
  broker/feed divergence, timeframe/session concentration, or market regime?
- Which constructive improvements, if any, can improve recent performance
  without damaging full-history robustness?
- Whether future reports need safer automated journal-copy tooling or whether
  manual safe collection is enough.

## Testing Status

Latest verification completed on 2026-05-26 after the diagnostic-reporting
changes:

- Focused LPFS diagnostic/reporting/executor suites passed: `73` tests.
- `.\venv\Scripts\python scripts\run_core_coverage.py` passed.
- Core coverage report showed `100.00%` total coverage across the configured
  core suites.

Documentation-only edits after that do not change runtime behavior. If any
implementation file changes again, rerun focused tests and core coverage before
handoff.

## Recommended Next Implementation Steps

1. Keep the live runners unchanged.
2. Start offline first-month cause attribution from
   `reports/live_ops/lpfs_trade_diagnostics/20260530_153500`, with the monthly
   tail-risk result as the reason for escalation.
3. Compare FTMO and IC by timeframe, symbol, side, session/weekday, setup
   geometry, spread-risk, execution path, recovery path, and candle-derived
   recent-regime fields.
4. Segment IC analysis by the historical scale-2 and active scale-1 policy
   epochs from `configs/live_policy_ledger.csv`; do not attribute PnL-size
   changes to strategy quality.
5. Check whether any weak bucket is also weak in recent 3/6/12 month V22
   benchmark windows and not just the full 10-year average.
6. Let production collect more sparse lifecycle diagnostics naturally.
7. At the next weekly checkpoint, safely collect local journal copies and build
   the diagnostic report.
8. Review `timeframe_confluence.csv` and `backtest_comparison.csv` for
   cross-lane, recent-window, and timeframe-normalized signals.
9. Watch H4 specifically because the 2026-05-30 checkpoint showed cross-lane
   H4 weakness, but do not change H4 rules unless repeated enriched evidence
   and recent/full backtests support it.
10. Improve weekly reporting so it can use bounded/local lifecycle snapshots
   and does not produce incomplete FTMO rows after a remote fetch timeout.
11. Add offline policy-ledger enrichment so future diagnostic reports derive a
   stable `policy_id` and comparison groups from lane plus lifecycle timestamp.
12. If evidence thresholds are met, create a separate research plan for one
   small reversible heuristic candidate.
13. Backtest any candidate on both FTMO and IC recent windows plus full-history
   guardrails.
14. Request explicit user approval before any live strategy-change deployment.

## Next Codex Handoff

Fresh-chat prompt:

```text
Read SESSION_HANDOFF.md, strategies/lp_force_strike_strategy_lab/START_HERE.md,
docs/lpfs_strategy_iteration_context.md, and docs/lpfs_diagnostic_logging.md.
Continue the LPFS diagnostic reporting and evidence-gated strategy-iteration
workflow from the current git state. Do not change live strategy behavior,
entry/exit logic, risk settings, broker/execution logic, config defaults, live
state, journals, MT5 orders, or MT5 positions.
```

Before making any change, the new chat should run `git status --short`, inspect
the intended files, and state whether the task is docs-only, reporting-only, or
production-adjacent.
