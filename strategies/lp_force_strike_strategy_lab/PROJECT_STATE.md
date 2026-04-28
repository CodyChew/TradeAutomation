# LP Force Strike Strategy Lab Project State

Last updated: 2026-04-29 local time after running the V3 H4/D1/W1 entry-zone,
ATR-filter, and partial-exit experiment.

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

## Experiment V2 Focus

Experiment V2 focus is configured by
`../../configs/strategies/lp_force_strike_experiment_v2_focus.json`.

Latest local focused run:

- report folder:
  `reports/strategies/lp_force_strike_experiment_v2_focus/20260428_161441`
- scope: 24 clean FOREX major/cross pairs x H4/D1/W1
- entry model: midpoint pullback only
- stop models: FS structure and FS structure with max ATR risk filters
- signals: 8,203
- simulated candidate trades: 128,685
- failed datasets: 0

Current best robust family:

- `signal_midpoint_pullback__fs_structure_max_1atr__1r`
- positive Avg R on H4, D1, and W1
- average focus R: about 0.191R
- worst focused timeframe Avg R: about 0.080R on H4

The 1.25 ATR max-risk version is very close. This led to V3, which keeps the
same H4/D1/W1 scope and tests entry zones plus partial exits.

## Experiment V3 Entry/Exit

Experiment V3 entry/exit is configured by
`../../configs/strategies/lp_force_strike_experiment_v3_entry_exit.json`.

Latest local focused run:

- report folder:
  `reports/strategies/lp_force_strike_experiment_v3_entry_exit/20260428_163456`
- scope: 24 clean FOREX major/cross pairs x H4/D1/W1
- entry model: signal-candle zone pullback
- entry zones: 0.5, 0.6, and 0.7 of the signal candle range
- stop models: FS structure and FS structure with max ATR risk filters
- max ATR filters: 0.75, 1.0, and 1.25 ATR
- exit models: single target and 50% partial at 1R with runner
- signals: 8,203
- simulated candidate trades: 619,092
- failed datasets: 0

Current best individual candidate:

- `signal_zone_0p5_pullback__fs_structure__1r`
- trades: 6,667
- average R: about 0.104R
- profit factor: about 1.235

Current best by timeframe:

- H4: `signal_zone_0p5_pullback__fs_structure__1r`, about 0.084R
- D1: `signal_zone_0p5_pullback__fs_structure_max_1atr__1r`, about 0.212R
- W1: `signal_zone_0p5_pullback__fs_structure_max_1atr__1r`, about 0.283R

Current read:

- The 0.5 signal-candle zone remains the strongest entry zone.
- 0.6 and 0.7 entry zones degrade, especially on H4.
- Single-target 1R remains the strongest individual candidate family.
- Partial exits improve some broad group averages, but did not beat the best
  individual 1R single-target candidates.
- Partial exits are still MT5-portable through two positions or partial close
  at 1R plus a runner.

## Experiment V4 Stability

Experiment V4 stability is configured by
`../../configs/strategies/lp_force_strike_experiment_v4_stability.json`.

Latest local stability run:

- report folder:
  `reports/strategies/lp_force_strike_experiment_v4_stability/20260428_182026`
- input run:
  `reports/strategies/lp_force_strike_experiment_v3_entry_exit/20260428_163456`
- split time: `2023-01-01T00:00:00Z`
- candidate family: 0.5 signal-candle pullback, 1R single target, structure
  stop plus 0.75/1.0/1.25 ATR stop-width variants
- filters tested: no pair filter and several training-period symbol/timeframe
  stability filters

Current read:

- The train-learned symbol/timeframe filters did not improve the later test
  period.
- Best test rows were the unfiltered baseline candidates.
- Best test candidate:
  `signal_zone_0p5_pullback__fs_structure_max_1p25atr__1r`, about 0.142R
  average R and about 1.33 profit factor.
- Do not add symbol/timeframe filtering yet. The weak pockets are real, but
  this filtering method looks like in-sample cleanup rather than a robust
  improvement.

## Boundary

This lab intentionally excludes SMA context, portfolio-level risk, position
sizing, and order execution.
