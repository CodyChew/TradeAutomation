# LP Force Strike Strategy Lab Project State

Last updated: 2026-04-29 local time after running V11 practical timeframe mix
and regenerating V1-V11 dashboards.

## Purpose

This lab studies the combination of active LP level traps and raw Force Strike
patterns. It now has two layers:

- signal detection: LP break + raw Force Strike confirmation;
- experiment harness: fixed bracket trade-model candidates for research.

It still does not contain position sizing, portfolio accounting, live
execution, or a combined TradingView indicator. V10 adds portfolio-style
research analytics, but not live execution rules.

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

## Experiment V5 H8 Bridge

Experiment V5 H8 bridge is configured by
`../../configs/strategies/lp_force_strike_experiment_v5_h8_bridge.json`.

Latest local H8 bridge run:

- report folder:
  `reports/strategies/lp_force_strike_experiment_v5_h8_bridge/20260428_190048`
- dashboard: `docs/v5.html`
- scope: 24 clean FOREX major/cross pairs x H4/H8/D1/W1
- candidate: `signal_zone_0p5_pullback__fs_structure__1r`
- LP lookback windows: H4 uses 30 days, H8 uses 60 days, D1 uses 1 year,
  and W1 uses 4 years
- native MT5 H8 data: 28/28 pairs pulled, 28/28 coverage-ready
- signals: 11,533
- simulated trades: 9,341
- failed datasets: 0

Timeframe read:

- H4: 5,642 trades, about 0.084R average, about 1.185 PF.
- H8: 2,674 trades, about 0.099R average, about 1.221 PF.
- D1: 855 trades, about 0.208R average, about 1.527 PF.
- W1: 170 trades, about 0.252R average, about 1.678 PF.

Current conclusion:

- H8 is a modest improvement over H4, but not a clean midpoint between H4 and
  D1.
- The D1 quality step remains much larger than the H4-to-H8 improvement.
- Keep H8 available for future comparison, but do not pivot the main strategy
  research around H8 yet.

## Experiment V6 H12 Bridge

Experiment V6 H12 bridge is configured by
`../../configs/strategies/lp_force_strike_experiment_v6_h12_bridge.json`.

Latest local H12 bridge run:

- report folder:
  `reports/strategies/lp_force_strike_experiment_v6_h12_bridge/20260428_191017`
- dashboard: `docs/v6.html`
- scope: 24 clean FOREX major/cross pairs x H4/H8/H12/D1/W1
- candidate: `signal_zone_0p5_pullback__fs_structure__1r`
- LP lookback windows: H4 uses 30 days, H8 uses 60 days, H12 uses 180 days,
  D1 uses 1 year, and W1 uses 4 years
- native MT5 H12 data: 28/28 pairs pulled, 28/28 coverage-ready
- signals: 13,815
- simulated trades: 11,185
- failed datasets: 0

Timeframe read:

- H4: 5,642 trades, about 0.084R average, about 1.185 PF.
- H8: 2,674 trades, about 0.099R average, about 1.221 PF.
- H12: 1,844 trades, about 0.157R average, about 1.375 PF.
- D1: 855 trades, about 0.208R average, about 1.527 PF.
- W1: 170 trades, about 0.252R average, about 1.678 PF.

Current conclusion:

- H12 is a materially better bridge than H8 for this model.
- H12 does not fully reach D1 quality, but it provides more than twice D1's
  trade count while sitting closer to D1 than to H8 by PF and average R.
- Keep H12 in the forward research set.

## Gap-Symbol Ad Hoc Check

The first official experiments used a clean 24-pair baseline by excluding
`GBPAUD`, `GBPNZD`, `NZDCAD`, and `NZDCHF`, because those symbols have known
broker-history gaps in the local FTMO candle feed.

On 2026-04-29, an ad hoc run tested only those four symbols with the same V6
candidate and timeframe set:

- config: `../../configs/strategies/lp_force_strike_gap_symbols_adhoc.json`
- report folder:
  `reports/strategies/lp_force_strike_gap_symbols_adhoc/20260429_061423`
- scope: `GBPAUD`, `GBPNZD`, `NZDCAD`, `NZDCHF` x H4/H8/H12/D1/W1
- candidate: `signal_zone_0p5_pullback__fs_structure__1r`
- signals: 2,246
- simulated trades: 1,827
- failed datasets: 0

Ad hoc result:

| Basket | Trades | Avg R | PF | Win Rate |
|---|---:|---:|---:|---:|
| Clean 24 V6 baseline | 11,185 | 0.112R | 1.253 | 57.7% |
| Gap 4 ad hoc | 1,827 | 0.142R | 1.335 | 59.7% |

By symbol:

| Symbol | Trades | Avg R | PF | Win Rate |
|---|---:|---:|---:|---:|
| GBPAUD | 467 | 0.173R | 1.421 | 60.2% |
| GBPNZD | 474 | 0.114R | 1.258 | 57.0% |
| NZDCAD | 423 | 0.107R | 1.243 | 58.2% |
| NZDCHF | 463 | 0.173R | 1.427 | 63.5% |

Only 3 of the 1,827 trades crossed or logically spanned a known large gap.
Removing those changed PF from about 1.335 to about 1.338. Current conclusion:
these symbols are usable and are not obvious outliers, but future reports should
keep the gap caveat visible. Production-grade research can add gap segmentation
later so signals and trades cannot span missing broker history.

## Experiment V7/V8 Entry Wait

Experiment V7/V8 tests whether the fixed 6-bar pullback wait should be replaced
with a rule that keeps the pending pullback alive until either entry fills or
the would-be 1R target is reached first.

Detailed notes:

```text
docs/lp_force_strike_experiment_v7_v8_entry_wait.md
```

V7:

- config:
  `../../configs/strategies/lp_force_strike_experiment_v7_entry_until_1r_cancel.json`
- report:
  `reports/strategies/lp_force_strike_experiment_v7_entry_until_1r_cancel/20260429_062506`
- dashboard: `docs/v7.html`
- same candle touches entry and would-be 1R: cancel first

V8:

- config:
  `../../configs/strategies/lp_force_strike_experiment_v8_entry_until_1r_entry_priority.json`
- report:
  `reports/strategies/lp_force_strike_experiment_v8_entry_until_1r_entry_priority/20260429_063204`
- dashboard: `docs/v8.html`
- same candle touches entry and would-be 1R: entry first

Full-28 comparison:

| Run | Trades | Avg R | PF | Win Rate |
|---|---:|---:|---:|---:|
| Fixed 6-bar baseline | 13,012 | 0.116R | 1.265 | 58.0% |
| V7 cancel-first | 4,885 | -0.321R | 0.519 | 35.7% |
| V8 entry-first | 9,627 | 0.062R | 1.133 | 55.3% |

Current conclusion:

- Do not replace the fixed 6-bar pullback wait with the 1R-cancel wait.
- V7 is unusable.
- V8 is positive, but weaker than the fixed 6-bar baseline on every timeframe.
- Keep the current fixed 6-bar entry wait as the active baseline.

Dashboard interpretation is now explicit:

- `configs/dashboards/lp_force_strike_pages.json` owns the human-readable
  title, research question, setup, conclusion, and next action for V1-V8.
- `docs/index.html` now leads with the current fixed 6-bar baseline, not V8.
- `docs/v7.html` and `docs/v8.html` show the fixed 6-bar baseline comparison
  at the top and state that the 1R-cancel wait rule is rejected.

## Experiment V9 LP Pivot Strength

Experiment V9 tests only LP pivot strength while keeping the current trade
model constant.

Detailed notes:

```text
docs/lp_force_strike_experiment_v9_lp_pivot_strength.md
```

Run details:

- config:
  `../../configs/strategies/lp_force_strike_experiment_v9_lp_pivot_strength.json`
- report:
  `reports/strategies/lp_force_strike_experiment_v9_lp_pivot_strength/20260429_123831`
- dashboard: `docs/v9.html`
- scope: all 28 FX major/cross pairs x H4/H8/H12/D1/W1
- pivot strengths: 2, 3, 4, 5
- failed datasets: 0
- signals across all pivot settings: 60,334
- simulated trades across all pivot settings: 48,941

All non-LP settings stayed constant:

- H4/H8/H12/D1/W1 lookbacks: 30D/60D/180D/365D/1460D
- LP break-to-FS window: 6 bars
- entry: 0.5 signal-candle pullback
- stop: full Force Strike structure
- target: single 1R
- pullback wait: fixed 6 bars
- costs: candle spread from MT5 data

Overall result:

| LP Pivot | Trades | Avg R | PF | Win Rate | Total R |
|---:|---:|---:|---:|---:|---:|
| 2 | 18,898 | 0.110R | 1.248 | 57.7% | 2,072.0R |
| 3 | 13,012 | 0.116R | 1.265 | 58.0% | 1,512.3R |
| 4 | 9,512 | 0.129R | 1.297 | 58.5% | 1,224.4R |
| 5 | 7,519 | 0.134R | 1.310 | 58.8% | 1,004.8R |

Current conclusion:

- LP5 has the best Avg R and PF.
- LP4 is the balanced comparison point because it improves quality over LP3
  while retaining more trades than LP5.
- LP2 has the most trades and total R, but the weakest quality metrics.
- Do not make LP5 the execution default yet. Use LP5 and LP4 in the next
  robustness slice.

## Experiment V10 Portfolio Baseline

Experiment V10 tests whether exposure caps improve drawdown enough to replace
taking every V9 trade.

Detailed notes:

```text
docs/lp_force_strike_experiment_v10_portfolio_baseline.md
```

Run details:

- config:
  `../../configs/strategies/lp_force_strike_experiment_v10_portfolio_baseline.json`
- input trades:
  `reports/strategies/lp_force_strike_experiment_v9_lp_pivot_strength/20260429_123831/trades.csv`
- report:
  `reports/strategies/lp_force_strike_experiment_v10_portfolio_baseline/20260429_133443`
- dashboard: `docs/v10.html`
- pivots: LP3, LP4, LP5
- timeframes: all H4/H8/H12/D1/W1 trades from V9

Rules tested:

- `take_all`: accepts every trade for the pivot.
- `cap_4r`, `cap_6r`, `cap_8r`, `cap_10r`: one open trade per symbol, max
  open risk equal to the cap, 1R risk per accepted trade.
- Same-symbol same-time conflicts prefer higher timeframe first:
  W1 > D1 > H12 > H8 > H4.
- Guardrails: max closed-trade drawdown <= 30R and longest underwater <= 180D.

Result highlights:

| LP | Portfolio | Trades | Total R | PF | Max DD | Underwater | Pass |
|---:|---|---:|---:|---:|---:|---:|---|
| 3 | take all | 13,012 | 1,512.3R | 1.265 | 33.4R | 111D | No |
| 3 | cap 4R | 10,037 | 1,100.9R | 1.248 | 26.7R | 162D | Yes |
| 3 | cap 6R | 11,226 | 1,235.6R | 1.249 | 32.6R | 125D | No |
| 4 | take all | 9,512 | 1,224.4R | 1.297 | 35.5R | 249D | No |
| 5 | take all | 7,519 | 1,004.8R | 1.310 | 31.7R | 254D | No |
| 5 | cap 4R | 6,431 | 888.4R | 1.322 | 24.0R | 229D | No |

Current conclusion:

- Only LP3 cap 4R passed both V10 guardrails.
- Taking all LP3 trades produces higher total R, but breaches the 30R drawdown
  guardrail.
- LP5 keeps the best quality metrics, but its underwater periods are too long
  under the 180D rule.
- Use LP3 cap 4R as the current practical portfolio baseline.
- V11 should keep this exposure rule and test timeframe subsets/combinations.

## Experiment V11 Practical Timeframe Mix

Experiment V11 tests whether the V10 LP3 cap 4R practical baseline should keep
all timeframes or remove lower-timeframe exposure.

Detailed notes:

```text
docs/lp_force_strike_experiment_v11_timeframe_mix.md
```

Run details:

- config:
  `../../configs/strategies/lp_force_strike_experiment_v11_timeframe_mix.json`
- input trades:
  `reports/strategies/lp_force_strike_experiment_v9_lp_pivot_strength/20260429_123831/trades.csv`
- report:
  `reports/strategies/lp_force_strike_experiment_v11_timeframe_mix/20260429_144259`
- dashboard: `docs/v11.html`
- primary pivot: LP3
- diagnostics: LP4 and LP5 only for all timeframes, remove H4, and remove H4+H8
- portfolio rule: `cap_4r`, one open trade per symbol
- guardrails: max closed-trade drawdown <= 30R and longest underwater <= 180D

Main LP3 result:

| Timeframe set | Trades | Total R | Max DD | Underwater | Pass |
|---|---:|---:|---:|---:|---|
| All H4/H8/H12/D1/W1 | 10,037 | 1,100.9R | 26.7R | 162D | Yes |
| Remove H4 | 5,361 | 792.6R | 23.5R | 159D | Yes |
| Remove H8 | 8,451 | 943.9R | 23.5R | 182D | No |
| Remove H4+H8 | 3,003 | 567.7R | 19.4R | 254D | No |
| H8+H12 | 4,789 | 655.0R | 25.3R | 172D | Yes |

Current conclusion:

- Keep all `H4/H8/H12/D1/W1` timeframes for the current practical baseline.
- Removing H4 reduces drawdown only modestly while giving up about 308R.
- Removing H8 is close but misses the underwater guardrail and gives up about
  157R.
- LP4 and LP5 become guardrail-viable in the no-H4 diagnostic set, but with
  lower total R than LP3 all timeframes.
- V12 should retest LP3/LP4/LP5 on all timeframes and no-H4 before changing the
  LP pivot default.

## Boundary

This lab intentionally excludes SMA context, account-currency position sizing,
broker order execution, and EA logic. V10/V11 portfolio analytics are research-only
closed-trade R simulations.
