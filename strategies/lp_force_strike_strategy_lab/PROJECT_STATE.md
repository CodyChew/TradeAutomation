# LP Force Strike Strategy Lab Project State

Last updated: 2026-04-28 local time after adding the first configurable
trade-model experiment harness.

## Purpose

This lab studies the combination of active LP level traps and raw Force Strike
patterns. It now has two layers:

- signal detection: LP break + raw Force Strike confirmation;
- experiment harness: fixed bracket trade-model candidates for research.

It still does not contain position sizing, portfolio accounting, live
execution, or a combined TradingView indicator.

## Concept Dependencies

- LP levels: `../../concepts/lp_levels_lab`
- Raw Force Strike pattern: `../../concepts/force_strike_pattern_lab`

Python remains the source of truth for MT5-data strategy development.
TradingView combined visuals should be built after this signal contract is
stable.

Future PnL backtests should load candles through
`../../shared/market_data_lab` so this strategy uses the same broker data and
validation contract as other strategies.

Future trade simulation should use `../../shared/backtest_engine_lab` so entry,
stop, target, spread, slippage, commission, and same-bar assumptions stay
consistent across strategy labs.

## Current Signal Rules

- Bullish force bottom starts when price wick-breaks active support LP.
- Bearish force top starts when price wick-breaks active resistance LP.
- If a candle breaks multiple support LPs, bullish uses the lowest broken
  support.
- If a candle breaks multiple resistance LPs, bearish uses the highest broken
  resistance.
- A valid raw Force Strike signal must occur within 6 bars from the LP break.
- The LP break candle is counted as bar 1.
- Bullish FS execution candle must close at or above the selected support LP.
- Bearish FS execution candle must close at or below the selected resistance LP.
- If multiple LP-break windows match one FS signal, the most recent valid break
  window is used.

## Experiment V1

Experiment V1 is configured by
`../../configs/strategies/lp_force_strike_experiment_v1.json` and run with
`../../scripts/run_lp_force_strike_experiment.py`.

Current trade-model dimensions:

- entry: next candle open, or signal-candle midpoint pullback;
- stop: full FS structure, or full FS structure skipped when wider than a
  configured ATR multiple;
- targets: configured R multiples such as 1R, 1.25R, 1.5R, 1.7R, and 2R;
- costs: delegated to `../../shared/backtest_engine_lab`.

The experiment simulates each signal/candidate independently. It is designed to
compare heuristics, not to model a portfolio with one-position-at-a-time rules.

Latest local baseline run:

- report folder:
  `reports/strategies/lp_force_strike_experiment_v1/20260428_144145`
- scope: 24 clean FOREX major/cross pairs x M30/H4/D1/W1
- signals: 57,340
- simulated candidate trades: 864,520
- failed datasets: 0

Early read: midpoint-pullback entries are materially better than next-open
entries. M30 was negative across the tested candidates, while H4, D1, and W1
showed positive average R for the midpoint-pullback structure-stop candidates.
Treat this as a first pass only; it is not yet a final strategy decision.

## Boundary

This lab intentionally excludes SMA context, portfolio-level risk, position
sizing, and order execution.
