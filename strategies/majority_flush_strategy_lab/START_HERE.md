# Majority Flush Strategy Lab Start Here

Last updated: 2026-05-22 after the M30/all-timeframe V1 comparison.

This is the first-read file for future work on a possible strategy built around
the Majority Flush concept. The lane is research-only right now. It has no MT5
live runner, no dry-run executor, no MQL5 EA, and no production scheduled task.

## Current Status

- Reusable concept already exists at `concepts/majority_flush_lab`.
- Concept source of truth:
  `concepts/majority_flush_lab/src/majority_flush_lab/flush.py`.
- Concept spec:
  `concepts/majority_flush_lab/docs/majority_flush_spec.md`.
- V1 strategy spec: `docs/majority_flush_strategy_spec.md`.
- V1 source and tests exist under `src/` and `tests/`.
- V1 runner: `scripts/run_majority_flush_baseline_experiment.py`.
- V1 config: `configs/strategies/majority_flush_strategy_baseline_v1.json`.
- M30/all-timeframe config:
  `configs/strategies/majority_flush_strategy_all_timeframes_v1.json`.
- V1 dashboard: `docs/majority_flush_strategy.html`.
- Latest full report:
  `reports/strategies/majority_flush_strategy_all_timeframes/20260522_025142`.
- Latest decision: `reject_or_rework_baseline`; continue research only, do not
  plan dry-run/live execution.

## Read Order

1. `SESSION_HANDOFF.md` for current workspace and live-system context.
2. `docs/system_troubleshooting.md` before diagnosing existing LPFS systems.
3. `PROJECT_STATE.md` for the overall repo state.
4. This file for the Majority Flush strategy lane.
5. `strategies/majority_flush_strategy_lab/PROJECT_STATE.md` for current
   research status.
6. `strategies/majority_flush_strategy_lab/docs/majority_flush_strategy_spec.md`
   for V1 signal and baseline trade rules.
7. `docs/majority_flush_strategy.html` for the latest V1 dashboard result.
8. `concepts/majority_flush_lab/PROJECT_STATE.md` and
   `concepts/majority_flush_lab/docs/majority_flush_spec.md`.
9. `shared/market_data_lab/docs/market_data_spec.md`.
10. `shared/backtest_engine_lab/docs/backtest_engine_spec.md`.
11. `docs/testing_strategy.md` before changing core Python modules.

## Safety Boundary

LP + Force Strike remains the only live Python strategy. Do not touch these
live paths while developing Majority Flush research unless the user explicitly
asks for LPFS operations work:

- `scripts/run_lp_force_strike_live_executor.py`
- `scripts/run_lpfs_live_forever.ps1`
- `scripts/Get-LpfsLiveStatus.ps1`
- `scripts/Get-LpfsDualVpsStatus.ps1`
- `scripts/Set-LpfsKillSwitch.ps1`
- `config.local.json`
- `config.lpfs_icmarkets_raw_spread.local.json`
- `C:\TradeAutomationRuntime`
- `C:\TradeAutomationRuntimeIC`
- VPS tasks `LPFS_Live` and `LPFS_IC_Live`

Majority Flush research should use local datasets and generated local reports
only. It must not place, cancel, modify, or reconcile broker orders.

## Latest V1 M30/All-Timeframe Result

The latest full run processed `168` datasets across the 28-pair FTMO FX
universe on `M30`, `H4`, `H8`, `H12`, `D1`, and `W1`.

- signals: `175,295`;
- trades: `174,968`;
- skipped setups: `327`;
- failed datasets: `0`;
- total net R: `-16,581.66`;
- average net R: `-0.09477`;
- win rate: `50.29%`;
- profit factor: `0.8282`;
- max closed-trade drawdown: `16,590.48R`.

M30 was the clear failure point: `139,411` trades, `-16,576.46R`, average
`-0.1189R`, and PF `0.7894`. Without M30, the original higher-timeframe basket
was roughly flat at `-5.20R`.

Keep `H8`, `H12`, `D1`, and `W1` for the next iteration. Treat `H4` as
rework/deprioritize unless entry-model tests explain the drag. Do not optimize
stops, targets, or risk sizing before understanding entry and timeframe
segmentation.

## Intended Workflow

Stage 1: strategy hypothesis

- Completed for V1 in `docs/majority_flush_strategy_spec.md`.

Stage 2: Python source and tests

- Completed for the V1 signal and baseline trade model.
- The new package is included in the strict `scripts/run_core_coverage.py`
  gate.

Stage 3: backtest experiments

- Drive runs from JSON configs under `configs/strategies/`.
- Use the existing dataset configs under `configs/datasets/`.
- Write original non-M30 outputs under
  `reports/strategies/majority_flush_strategy_baseline/...`.
- Write M30/all-timeframe outputs under
  `reports/strategies/majority_flush_strategy_all_timeframes/...`.
- Persist signals, trades, skipped setups, candidate definitions, dataset
  coverage rows, and summary metrics for every run.
- Keep gap-symbol and incomplete-live-tail caveats visible in reports.

Stage 4: dashboard view

- Dashboard builder: `scripts/build_majority_flush_strategy_dashboard.py`.
- Generated dashboard: `docs/majority_flush_strategy.html`.
- It is linked from `docs/index.html`.
- The dashboard shows current stage, tested hypothesis, dataset window,
  candidate model, trade count, net R, profit factor, drawdown, skipped reasons,
  symbol/timeframe breakdown, and next decision.

Stage 5: feasibility decision

- Promote the idea only if backtests are stable across symbols, timeframes,
  costs, and reasonable parameter perturbations.
- Reject or pause the idea if the result depends on one symbol, one timeframe,
  one small date range, untested intrabar assumptions, or excessive filtering.
- Do not design dry-run/live execution until the research dashboard has a clear
  evidence trail.

Stage 6: execution planning, only if feasible

- Create a separate dry-run and execution contract plan.
- Reuse shared abstractions only where they are genuinely strategy-neutral.
- Keep comments, magic numbers, runtime roots, state files, journals, Telegram
  channels, and configs separate from LPFS.
- Require an explicit user decision before any live-send path is added.

## Handoff Requirements

Every substantial session should update:

- `strategies/majority_flush_strategy_lab/PROJECT_STATE.md`
- this `START_HERE.md` if the workflow or source-of-truth map changes
- root `PROJECT_STATE.md` if the overall workspace state changes
- dashboard source and generated HTML if a dashboard exists

Keep generated data and reports ignored unless a small summary artifact is
intentionally promoted into tracked docs.
