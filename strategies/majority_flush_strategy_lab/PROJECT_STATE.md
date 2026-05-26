# Majority Flush Strategy Lab Project State

Last updated: 2026-05-22 after running the M30/all-timeframe V1 comparison.

## Purpose

This lab tests whether the reusable Majority Flush concept can become a full
strategy. The concept detects displacement legs that force active LP levels.
This strategy lab decides whether those events are tradable, how entries and
exits should work, and whether the evidence is strong enough to justify a later
dry-run or live-execution design.

## Current State

- Status: V1 baseline implemented, tested, and extended to the M30/all-timeframe comparison.
- Source code: `src/majority_flush_strategy_lab/`.
- Backtest runner: `scripts/run_majority_flush_baseline_experiment.py`.
- Config: `configs/strategies/majority_flush_strategy_baseline_v1.json`.
- M30/all-timeframe config:
  `configs/strategies/majority_flush_strategy_all_timeframes_v1.json`.
- Dashboard: `docs/majority_flush_strategy.html`.
- Live execution: none.
- Production impact: none.

The existing concept package remains the source of truth for Majority Flush
detection:

```text
concepts/majority_flush_lab/src/majority_flush_lab/flush.py
```

The implemented V1 imports that package and adds strategy-specific final-LP
execution confirmation plus a simple next-open, flush-structure-stop, 1R
baseline trade model.

## Latest M30/All-Timeframe V1 Result

Full 10-year report:

```text
reports/strategies/majority_flush_strategy_all_timeframes/20260522_025142
```

Dashboard:

```text
docs/majority_flush_strategy.html
```

Run shape:

- dataset: existing FTMO 10-year FX Parquet data;
- universe: 28 major/cross pairs;
- timeframes: `M30`, `H4`, `H8`, `H12`, `D1`, `W1`;
- datasets processed: `168`;
- failed datasets: `0`;
- signals: `175,295`;
- trades: `174,968`;
- skipped setups: `327`;
- candidate: `next_open__flush_structure__1r`.

Headline result:

- total net R: `-16,581.66`;
- average net R: `-0.09477`;
- win rate: `50.29%`;
- profit factor: `0.8282`;
- max closed-trade drawdown: `16,590.48R`;
- dashboard decision: `reject_or_rework_baseline`.

Timeframe read:

- `M30`: `-16,576.46R`, avg `-0.119R`, PF `0.789`, `139,411` trades.
- `W1`: `+44.19R`, avg `+0.066R`, PF `1.143`, `666` trades.
- `D1`: `+76.53R`, avg `+0.024R`, PF `1.049`, `3,195` trades.
- `H12`: `+93.39R`, avg `+0.016R`, PF `1.032`, `5,918` trades.
- `H8`: `+39.70R`, avg `+0.005R`, PF `1.010`, `8,360` trades.
- `H4`: `-259.02R`, avg `-0.015R`, PF `0.971`, `17,418` trades.

Interpretation: M30 materially worsens the result and should not be kept in its
raw V1 form. The non-M30 basket remains the prior roughly flat result
(`-5.20R`). H8/H12/D1/W1 are still the only timeframes worth keeping for the
next research iteration; H4 should be reworked or deprioritized unless a new
entry model explains the drag. The raw signal is not ready for live or dry-run
planning.

Prior non-M30 baseline:

```text
reports/strategies/majority_flush_strategy_baseline/20260521_180025
```

That run used `H4`, `H8`, `H12`, `D1`, and `W1`: `140` datasets, `35,642`
signals, `35,557` trades, `85` skipped setups, total net R `-5.20`, PF
`0.9997`, and decision `reject_or_rework_baseline`.

## Architecture Decision

Use the current TradeAutomation repo instead of a new repo.

Reasons:

- Shared MT5 data contracts and dataset fingerprints already exist.
- The shared backtest engine already models bracket trades, costs, and
  conservative same-bar conflicts.
- Majority Flush is already a reusable concept in this repo.
- The repo already separates concepts, shared infrastructure, strategy labs,
  generated reports, dashboards, and live LPFS execution.

The main cleanliness risk is root-level script growth. For this strategy, keep
reusable behavior inside the strategy package and keep root scripts thin.

## Implemented Package Shape

```text
strategies/majority_flush_strategy_lab/
  pyproject.toml
  docs/
    majority_flush_strategy_spec.md
  src/
    majority_flush_strategy_lab/
      __init__.py
      signals.py
      experiment.py
  tests/
    test_signals.py
    test_experiment.py
```

Optional later modules:

- `portfolio.py` after raw trade results justify account-level testing.
- `execution_contract.py` only after dashboard evidence justifies dry-run
  planning.
- `dry_run_executor.py` only after a separate local MT5 order-check design.
- `live_executor.py` only after explicit approval for a real-account path.

## Backtesting Plan

The first backtest lane mirrors the LPFS research discipline:

- Verify the canonical dataset before broad runs:

```powershell
.\venv\Scripts\python.exe scripts\verify_dataset_fingerprint.py
```

- Use `configs/datasets/forex_major_crosses_10y.json` plus the existing H8 and
  H12 add-on datasets when those timeframes are part of the hypothesis.
- Drop incomplete latest bars for live-ended datasets.
- Use candle spread fields and explicit cost settings.
- Write generated all-timeframe comparison outputs to
  `reports/strategies/majority_flush_strategy_all_timeframes/<run_timestamp>/`.
  Keep the original non-M30 baseline under
  `reports/strategies/majority_flush_strategy_baseline/<run_timestamp>/`.
- Include raw signals, trade rows, skipped rows, candidate definitions,
  per-symbol/timeframe summaries, and config snapshots.
- Treat gap-symbol results separately when they materially affect conclusions.

## Dashboard

The first dashboard is generated from:

```powershell
.\venv\Scripts\python.exe scripts\build_majority_flush_strategy_dashboard.py --run-dir reports\strategies\majority_flush_strategy_all_timeframes\20260522_025142
```

It is linked from `docs/index.html` because it now has real generated results.

## Feasibility Gate

Do not convert this into a dry-run or live strategy unless the research shows:

- enough trades for the chosen symbol/timeframe universe;
- stable performance across reasonable parameter changes;
- no dependence on one outlier symbol or date window;
- costs and spread assumptions included;
- drawdown and open-risk behavior understood;
- skipped/setup rejection reasons understood;
- TradingView visuals reconciled against Python and MT5 data when used.

Current V1, including the M30 comparison, does not pass the dry-run/live
feasibility gate.

## Non-Goals

- Do not copy LPFS live execution files into this lab.
- Do not reuse LPFS magic numbers, runtime roots, state files, journals,
  Telegram channels, or broker comments.
- Do not attach any MQL5 EA to live FTMO or IC charts for this strategy.
- Do not change `LPFS_Live`, `LPFS_IC_Live`, or their runtime state while doing
  Majority Flush research.

## Next Best Work

1. Do not continue raw M30 V1 as a candidate; it needs a separate rework if it
   is revisited.
2. Keep `H8`, `H12`, `D1`, and `W1` for the next iteration because each was
   positive before entry optimization.
3. Treat `H4` as rework/deprioritize unless entry-model tests show it is poorly
   entered rather than structurally weak.
4. Run an entry-model iteration while keeping the V1 signal, flush-structure
   stop, and 1R target fixed. Compare next-open against execution-bar pullback
   and flush-leg pullback.
5. Keep all work research-only until a later dashboard clearly justifies
   dry-run planning.
