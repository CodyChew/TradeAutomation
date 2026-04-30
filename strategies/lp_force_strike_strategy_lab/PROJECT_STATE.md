# LP Force Strike Strategy Lab Project State

Last updated: 2026-05-01 local time after the live Telegram UX refactor, fresh
live-send test cycle, and handoff cleanup.

## Purpose

This lab studies the combination of active LP level traps and raw Force Strike
patterns. It now has these layers:

- signal detection: LP break + raw Force Strike confirmation;
- experiment harness: fixed bracket trade-model candidates for research;
- execution contract: pure conversion from tested `TradeSetup` to guarded MT5
  order intent or explicit rejection;
- notification contract: Telegram-ready event rendering and delivery adapter;
- dry-run adapter: closed-candle MT5 polling, UTC normalization, local
  journal/state files, live spread logging, latest-closed-signal pending setup
  building, expired-pending rejection, and `order_check` only.
- live-send adapter: explicit local live enablement, broker-accurate
  `order_calc_profit` sizing, dynamic spread gating, MT5 `order_send`,
  pending/order/position/deal reconciliation, and restart-safe lifecycle
  notifications.

It still does not contain a combined TradingView indicator. V10-V13 add
portfolio-style research analytics. V14 adds account-risk sizing and drawdown
views. V15 adds 3-bucket risk-ladder sensitivity. The dry-run phase is
explicitly broker-safe and does not send orders; the live-send phase can place
real pending orders only when local live config is explicitly enabled.

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

## Experiment V12 LP Pivot Finalization

Experiment V12 tests whether LP4 or LP5 should replace LP3 after V10/V11 fixed
the practical portfolio and timeframe mechanics.

Detailed notes:

```text
docs/lp_force_strike_experiment_v12_lp_pivot_finalization.md
```

Run details:

- config:
  `../../configs/strategies/lp_force_strike_experiment_v12_lp_pivot_finalization.json`
- input trades:
  `reports/strategies/lp_force_strike_experiment_v9_lp_pivot_strength/20260429_123831/trades.csv`
- report:
  `reports/strategies/lp_force_strike_experiment_v12_lp_pivot_finalization/20260429_165713`
- dashboard: `docs/v12.html`
- pivots: LP3, LP4, LP5
- primary timeframe set: all `H4/H8/H12/D1/W1`
- diagnostic timeframe set: no H4, using `H8/H12/D1/W1`
- portfolio rule: `cap_4r`, one open trade per symbol
- guardrails: max closed-trade drawdown <= 30R and longest underwater <= 180D

All-timeframe result:

| LP | Trades | Total R | PF | Max DD | Underwater | Pass |
|---:|---:|---:|---:|---:|---:|---|
| 3 | 10,037 | 1,100.9R | 1.248 | 26.7R | 162D | Yes |
| 4 | 7,793 | 1,004.3R | 1.293 | 34.4R | 271D | No |
| 5 | 6,431 | 888.4R | 1.322 | 24.0R | 229D | No |

No-H4 diagnostic result:

| LP | Trades | Total R | PF | Max DD | Underwater | Pass |
|---:|---:|---:|---:|---:|---:|---|
| 3 | 5,361 | 792.6R | 1.305 | 23.5R | 159D | Yes |
| 4 | 4,197 | 729.3R | 1.393 | 21.6R | 150D | Yes |
| 5 | 3,397 | 634.1R | 1.424 | 19.4R | 138D | Yes |

Current conclusion:

- Keep LP3 as the practical LP pivot default.
- LP4 and LP5 have better quality metrics, but fail all-timeframe guardrails.
- The no-H4 diagnostic makes LP4/LP5 viable, but LP3 still has the highest
  Total R.
- Next research should focus on risk sizing, FTMO-style daily/max loss
  constraints, and execution-readiness rather than changing LP pivot strength.

## Experiment V13 Relaxed Portfolio Rule Selection

Experiment V13 retests whether `cap_4r` is too conservative by treating the old
30R max-drawdown / 180D underwater guardrails as context instead of hard
selection rules.

Detailed notes:

```text
docs/lp_force_strike_experiment_v13_relaxed_portfolio_selection.md
```

Run details:

- config:
  `../../configs/strategies/lp_force_strike_experiment_v13_relaxed_portfolio_selection.json`
- input trades:
  `reports/strategies/lp_force_strike_experiment_v9_lp_pivot_strength/20260429_123831/trades.csv`
- report:
  `reports/strategies/lp_force_strike_experiment_v13_relaxed_portfolio_selection/20260429_172705`
- dashboard: `docs/v13.html`
- fixed model: LP3, all `H4/H8/H12/D1/W1`, 0.5 signal-candle pullback, full
  FS structure stop, single 1R target, fixed 6-bar pullback wait.

Main result:

| Portfolio | Trades | Total R | PF | Max DD | Underwater | Neg years | Neg symbols |
|---|---:|---:|---:|---:|---:|---:|---:|
| take_all | 13,012 | 1,512.3R | 1.265 | 33.4R | 111D | 0 | 0 |
| one_symbol_no_cap | 11,519 | 1,267.1R | 1.248 | 33.7R | 172D | 0 | 0 |
| cap_6r | 11,226 | 1,235.6R | 1.249 | 32.6R | 125D | 0 | 0 |
| cap_4r | 10,037 | 1,100.9R | 1.248 | 26.7R | 162D | 0 | 0 |

Current conclusion:

- Use `take_all` as the current research baseline if account risk per trade is
  kept small enough.
- `take_all` adds about 411R versus `cap_4r`, has shorter underwater, and has
  no negative years or negative symbols.
- At 0.25% risk per trade, `take_all` max closed-trade drawdown is about 8.3%;
  at 0.50% risk per trade it is about 16.7%.
- Exposure caveat: `take_all` reached 17 concurrent trades, 12 new trades at
  one timestamp, and max same-symbol stack of 4.
- Next research should test FTMO-style daily/max loss, account-risk sizing, and
  same-symbol stacking limits before execution work.

## Experiment V14 Risk Sizing And Drawdown

Experiment V14 converts the V13 `take_all` baseline into account-risk
drawdowns. It is not a prop-firm pass/fail test.

Detailed notes:

```text
docs/lp_force_strike_experiment_v14_risk_sizing_drawdown.md
```

Run details:

- config:
  `../../configs/strategies/lp_force_strike_experiment_v14_risk_sizing_drawdown.json`
- input trades:
  `reports/strategies/lp_force_strike_experiment_v9_lp_pivot_strength/20260429_123831/trades.csv`
- report:
  `reports/strategies/lp_force_strike_experiment_v14_risk_sizing_drawdown/20260429_235134`
- dashboard: `docs/v14.html`
- fixed model: LP3, all `H4/H8/H12/D1/W1`, `take_all`, 0.5 signal-candle
  pullback, full FS structure stop, single 1R target, fixed 6-bar pullback
  wait.

Main result:

| Schedule | Total return | Realized DD | Risk-reserved DD | Worst month | Max open risk |
|---|---:|---:|---:|---:|---:|
| Fixed 0.10% | 151.2% | 3.3% | 3.9% | -1.6% | 2.0% |
| Fixed 0.25% | 378.1% | 8.3% | 9.8% | -4.1% | 5.0% |
| Fixed 0.50% | 756.1% | 16.7% | 19.5% | -8.1% | 10.0% |
| Conservative equal-LTF | 240.3% | 4.8% | 6.7% | -2.7% | 4.2% |
| Balanced equal-LTF | 332.6% | 6.2% | 8.6% | -3.6% | 5.7% |
| Tight H12-D1 basket | 324.2% | 5.9% | 7.9% | -3.0% | 5.1% |
| Quality-weighted diagnostic | 303.7% | 6.1% | 8.5% | -3.8% | 5.6% |
| High-timeframe tilt | 250.1% | 8.0% | 10.5% | -4.3% | 5.6% |

Current conclusion:

- Use the tight H12-D1 basket as the first practical risk schedule:
  H4 `0.15%`, H8 `0.15%`, H12 `0.30%`, D1 `0.30%`, W1 `0.45%`.
- It gives up only about `8.4%` total return versus Balanced equal-LTF, while
  lowering realized DD, risk-reserved DD, worst month, and max reserved open
  risk.
- Balanced equal-LTF remains the growth-tilted ladder:
  H4 `0.15%`, H8 `0.15%`, H12 `0.25%`, D1 `0.40%`, W1 `0.60%`.
- Fixed `0.25%` is the closest simple alternative. It has higher total return
  but does not upweight the cleaner higher timeframes.
- Fixed `0.50%` is useful as a stress diagnostic, but is too aggressive for the
  first practical default.
- Risk-reserved drawdown is the key stress view because it subtracts full open
  trade risk while trades are active.

Risk tolerance calibration:

- V14 now includes a `Risk Tolerance Calibration` table in `docs/v14.html`.
- For more or less aggressive sizing, scale the tight H12-D1 ladder first:
  `multiplier = target risk-reserved DD / 7.86`.
- This keeps the tested timeframe weighting intact.
- Increasing only H4/H8 is a separate ladder hypothesis because H4/H8 are more
  frequent and lower-quality than D1/W1.

Scaled balanced ladder examples:

| Target risk-reserved DD | H4 | H8 | H12 | D1 | W1 | Est. return |
|---:|---:|---:|---:|---:|---:|---:|
| 10% | 0.19% | 0.19% | 0.38% | 0.38% | 0.57% | 412% |
| 15% | 0.29% | 0.29% | 0.57% | 0.57% | 0.86% | 618% |
| 20% | 0.38% | 0.38% | 0.76% | 0.76% | 1.14% | 825% |

Decision question:

```text
Can the V13 take-all baseline stay practical after daily loss, max loss,
same-symbol stacking, and concurrent-trade execution constraints are applied
to the V14 balanced equal-LTF risk schedule?
```

Potential follow-up question:

```text
Does a deliberately more aggressive lower-timeframe ladder improve total return
enough to justify additional H4/H8 noise and drawdown?
```

## Experiment V15 Risk Bucket Sensitivity

Experiment V15 tests the V14 follow-up question by separating account risk into
three buckets: `H4/H8`, `H12/D1`, and `W1`.

Detailed notes:

```text
docs/lp_force_strike_experiment_v15_bucket_sensitivity.md
```

Run details:

- config:
  `../../configs/strategies/lp_force_strike_experiment_v15_bucket_sensitivity.json`
- input trades:
  `reports/strategies/lp_force_strike_experiment_v9_lp_pivot_strength/20260429_123831/trades.csv`
- report:
  `reports/strategies/lp_force_strike_experiment_v15_bucket_sensitivity/20260430_125620`
- dashboard: `docs/v15.html`
- fixed model: LP3, all `H4/H8/H12/D1/W1`, `take_all`, 0.5 signal-candle
  pullback, full FS structure stop, single 1R target, fixed 6-bar pullback
  wait.

Grid:

- `H4/H8`: `0.10%`, `0.15%`, `0.20%`, `0.25%`.
- `H12/D1`: `0.20%`, `0.30%`, `0.40%`, `0.50%`.
- `W1`: `0.30%`, `0.45%`, `0.60%`, `0.75%`.

Practical filters:

- risk-reserved max DD <= `10%`;
- max reserved open risk <= `6%`;
- worst month >= `-5%`.

Main result:

| Row | H4/H8 | H12/D1 | W1 | Total return | Reserved DD | Max open risk | Worst month |
|---|---:|---:|---:|---:|---:|---:|---:|
| V14 tight baseline | 0.15% | 0.30% | 0.45% | 324.2% | 7.9% | 5.1% | -3.03% |
| Most-efficient practical | 0.20% | 0.30% | 0.75% | 383.2% | 7.9% | 5.75% | -3.22% |
| Highest-return practical | 0.25% | 0.30% | 0.60% | 421.8% | 9.7% | 5.95% | -4.05% |

Current conclusion:

- Use the most-efficient practical row as the first account-constraint
  candidate: H4/H8 `0.20%`, H12/D1 `0.30%`, W1 `0.75%`.
- Keep H4/H8 `0.25%`, H12/D1 `0.30%`, W1 `0.60%` as the growth alternative.
- H4/H8 upweighting helped materially, but H4/H8 `0.25%` sits at the top of
  the tested lower-timeframe range and near the open-risk limit.
- Do not increase H12/D1 above `0.30%` without a separate drawdown-tolerance
  decision because no `0.40%` or `0.50%` middle-bucket row passed the practical
  filters.

Decision question:

```text
Can the V15 efficient bucket row survive daily loss, max loss, same-symbol
stacking, and concurrent-trade constraints, and how much extra return does the
growth alternative retain after those constraints?
```

## MT5 Execution Contract

The execution contract lives in:

```text
src/lp_force_strike_strategy_lab/execution_contract.py
../../docs/mt5_execution_contract.md
```

It is pure Python contract logic. It does not import MetaTrader5 and does not
send orders.

Current encoded execution basis:

- V13 mechanics: LP3, all H4/H8/H12/D1/W1, `take_all`, 0.5 signal-candle
  pullback, FS structure stop, 1R target, fixed 6-bar pullback wait.
- V15 efficient risk buckets: H4/H8 `0.20%`, H12/D1 `0.30%`, W1 `0.75%`.

Ready order intent behavior:

- long setup -> `BUY_LIMIT` only if entry is below current ask;
- short setup -> `SELL_LIMIT` only if entry is above current bid;
- expiry -> `fs_signal_time + timeframe_delta * 7`;
- dry-run lot size -> account equity risk divided by tick-value/tick-size risk
  per lot, capped by broker max volume and optional `max_lots_per_order`,
  rounded down to broker volume step;
- live-send lot size -> broker/account-currency risk from
  `mt5.order_calc_profit`, then the same volume cap/floor/reject rules;
- intent records target and actual risk percentage.

Pre-send rejection coverage:

- duplicate signal key;
- invalid side/symbol/market/account;
- invalid long/short geometry;
- spread cap breach;
- entry already marketable instead of pending pullback;
- broker stop/freeze distance too close;
- missing risk bucket or risk above cap;
- invalid tick or volume metadata;
- volume below broker minimum;
- same-symbol stack, concurrent trade, or max-open-risk breach.
- pending expiration already at or before current broker market time.

Current test coverage includes ready long/short intents, volume capping,
max-open-risk equality, idempotency, broker-distance checks, bad geometry,
spread, symbol/account errors, broker risk override, and sizing failures.

## Telegram Notification Contract

The notification contract lives in:

```text
src/lp_force_strike_strategy_lab/notifications.py
../../docs/telegram_notifications.md
```

Telegram is reporting only. It must not decide trades. Credentials must come
from environment variables:

```powershell
$env:TELEGRAM_BOT_TOKEN = "<bot token>"
$env:TELEGRAM_CHAT_ID = "<chat id>"
```

Supported event kinds include:

- signal detected;
- setup rejected;
- order intent created;
- order-check passed or failed;
- order sent or rejected;
- pending expired or cancelled;
- position opened;
- stop loss / take profit hit;
- executor error;
- kill switch activated.

The notifier defaults to dry-run behavior. Tests use fake HTTP clients and do
not contact Telegram.

Telegram delivery is now trader-facing rather than log-like. The local journal
still records signal, intent, rejection, order-check, and live lifecycle rows.
Telegram uses compact plain-text cards, while raw retcodes, broker comments,
exact floats, and diagnostics stay in JSONL.

Live Telegram messages add real broker lifecycle alerts:

- `ORDER PLACED`;
- `ENTERED`;
- `TAKE PROFIT`;
- `STOP LOSS`;
- `WAITING` for retryable spread-only blocks;
- `SKIPPED` / `REJECTED` / `CANCELLED`.

Fill, close, expiry, and cancellation alerts reply to the original
`ORDER PLACED` Telegram message when Telegram returns a message ID. The live
state stores those IDs under `telegram_message_ids`. The manual summary script
is `../../scripts/summarize_lpfs_live_trades.py --config config.local.json
--limit 5`.

## Current Live Execution State

The connected MT5 account is real. Treat `scripts/run_lp_force_strike_live_executor.py`
as real-order capable whenever ignored local config enables live-send.

Current local run scope is the full V15 universe: 28 major/cross pairs across
`H4/H8/H12/D1/W1`, or 140 checks per cycle. The current FTMO-style terminal
uses `Europe/Helsinki` broker-time normalization.

Latest corrected full-universe dry-run cycle found four current
order-check-passing intents: `AUDJPY D1 short`, `EURNZD H8 short`,
`GBPJPY H12 short`, and `NZDCHF H4 long`.

Local broker testing now uses `risk_bucket_scale=0.1`, reducing V15 sizing to
H4/H8 `0.02%`, H12/D1 `0.03%`, and W1 `0.075%` while preserving the relative
timeframe weighting. Broker volume steps/minimums can make actual risk slightly
lower or reject very wide setups.

Live-send state as of 2026-05-01:

- Module:
  `src/lp_force_strike_strategy_lab/live_executor.py`.
- Runner:
  `../../scripts/run_lp_force_strike_live_executor.py --config config.local.json`.
- Required config:
  `live_send.execution_mode="LIVE_SEND"`,
  `live_send.live_send_enabled=true`, and
  `live_send.real_money_ack="I_UNDERSTAND_THIS_SENDS_REAL_ORDERS"`.
- Low-risk defaults: `risk_bucket_scale=0.05`, `max_open_risk_pct=0.65`,
  full V15 stack caps, and `max_spread_risk_fraction=0.1`.
- Scaled risk ladder: H4/H8 `0.01%`, H12/D1 `0.015%`, W1 `0.0375%`.
- MT5 is the source of truth. The executor reconciles open orders, historical
  orders, open positions, and close deals before scanning new signals.
- Late-start missed-entry guard is active: if MT5 bars after the signal candle
  already touched the planned pullback entry before the live order could be
  placed, the setup is rejected instead of placing a stale pending order.
- Signal idempotency is based on:
  `lpfs:{SYMBOL}:{TIMEFRAME}:{SIGNAL_INDEX}:{SIDE}:{CANDIDATE_ID}:{FS_SIGNAL_TIME}`.
  A next-candle signal gets a new key; manually deleting a pending order does
  not create a new signal or re-arm the old one.
- Previous live journal/state were intentionally archived on 2026-05-01 before
  a fresh live test:
  `../../data/live/lpfs_live_journal.jsonl.bak_20260501_034805` and
  `../../data/live/lpfs_live_state.json.bak_20260501_034805`.
- Fresh live-send test cycle result:
  140 frames processed, 2 orders sent, 2 setups rejected.
- Current tracked/MT5 strategy pending orders after that cycle:
  `EURNZD H8 SHORT SELL_LIMIT #257048012` and
  `GBPJPY H12 SHORT SELL_LIMIT #257048014`.
- Current tracked strategy positions: none.
- Skipped in the fresh cycle:
  `AUDJPY D1 SHORT` because entry was already touched before placement, and
  `NZDCHF H4 LONG` because live spread was about `11.5%` of risk versus the
  `10.0%` gate.
- Telegram message IDs for the order cards are stored in live state so future
  fill/close/cancel alerts should reply to those original cards.
- Recent spread-gate sanity check across 720 recent detected setups showed the
  `10%` spread/risk gate passed 714/720 (`99.2%`). Current recommendation:
  keep `max_spread_risk_fraction=0.1`; consider H4-only relaxation to `0.15`
  only if live evidence shows too many high-quality H4 setups are skipped.
- Spread-too-wide live blocks are now retryable WAITING events. A spread-only
  block does not mark the signal processed, so a future cycle can place the
  order if spread improves before entry touch or expiry. The one old NZDCHF
  spread skip was cleaned from local live state explicitly instead of keeping
  compatibility code.
- After a pending order is placed, spread widening does not auto-cancel it and
  does not currently trigger a dedicated Telegram alert.

Expected next scope:

1. Inspect `../../data/live/lpfs_live_journal.jsonl`,
   `../../data/live/lpfs_live_state.json`, MT5 pending orders/positions, and
   Telegram lifecycle messages before running again.
2. Run only finite live-send cycles until a kill switch exists.
3. If a user manually deletes a pending order, let the next reconciliation
   record it as cancelled/missing; do not clear state unless intentionally
   re-arming the current latest-candle setups.
4. Add retry policy and a real kill switch before unattended operation.

## Dashboard Interpretation UX

The dashboard interpretation metadata lives in:

```text
../../configs/dashboards/lp_force_strike_pages.json
```

On 2026-04-30, V6-V15 were given a `decision_brief` section in that metadata.
The shared renderer now shows a prominent `Decision Brief` near the top of each
page, before the tables. This preserves the concise chat-style interpretation
the user found useful, for example the V11 bullets explaining why removing H4
or H8 is not worth replacing the baseline.

V14 is rendered by:

```text
../../scripts/run_lp_force_strike_risk_sizing_experiment.py
```

V15 is rendered by:

```text
../../scripts/run_lp_force_strike_bucket_sensitivity_experiment.py
```

That generator also owns the V14 `Risk Schedule Composition` and `Risk
Tolerance Calibration` tables. The V15 generator owns the bucket leaderboard,
bucket-effect, heatmap, and contribution sections. Do not hand-edit generated
dashboard pages directly.

## Boundary

This lab intentionally excludes SMA context and EA logic. V10/V11/V12/V13
portfolio analytics are research-only closed-trade R simulations. V14 and V15
add account-risk sizing. The execution contract defines broker-facing intent
and rejection rules. The live-send adapter is real-order capable only through
explicit ignored local config; dry-run remains order-check only.
