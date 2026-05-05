# LP Force Strike Strategy Lab Project State

Last updated: 2026-05-05 local time after running the local IC Markets Raw
Spread LPFS validation through audit, data pull, V22 backtest, comparison, and
dry-run.

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

It now includes a combined TradingView visual indicator for LPFS chart review
and alerts at `tradingview/lp_force_strike.pine`. V10-V13 add portfolio-style
research analytics. V14 adds account-risk sizing and drawdown views. V15 adds
3-bucket risk-ladder sensitivity. V16 adds broker-side bid/ask trigger realism
and spread-buffer research. V17 tests whether the Force Strike structure must
be close to or touching the broken LP. V18-V20 test TP-near close/protection
ideas as research-only evidence. V21 tests BTC/ETH crypto expansion on current
broker-history data, with SOL only as short-history exploratory evidence. V22
accepted the hard design rule that the selected LP pivot must be before the
Force Strike mother bar. The dry-run phase is explicitly broker-safe and does
not send orders; the live-send phase can place real pending orders only when
local live config is explicitly enabled.

## Concept Dependencies

- LP levels: `../../concepts/lp_levels_lab`
- Raw Force Strike pattern: `../../concepts/force_strike_pattern_lab`

Python remains the source of truth for MT5-data strategy development.
The combined TradingView visual lives at `tradingview/lp_force_strike.pine`.
It is for chart-side inspection and alerts only; Python/MT5 remains the source
of truth for research and live execution.

Canonical LPFS restart file:
`START_HERE.md`. Future AI agents should read it immediately after
`SESSION_HANDOFF.md` to get the source-of-truth map, environment boundaries,
VPS first commands, live-run safety rules, and resume prompts.

Future PnL backtests should load candles through
`../../shared/market_data_lab` so this strategy uses the same broker data and
validation contract as other strategies.

Future trade simulation should use `../../shared/backtest_engine_lab` so entry,
stop, target, spread, slippage, commission, and same-bar assumptions stay
consistent across strategy labs.

## Current Signal Rules

- Bullish force bottom starts when price wick-breaks active support LP.
- Bearish force top starts when price wick-breaks active resistance LP.
- If multiple support LP-break windows match one FS signal, bullish uses the
  lowest valid support LP.
- If multiple resistance LP-break windows match one FS signal, bearish uses the
  highest valid resistance LP.
- A valid raw Force Strike signal must occur within 6 bars from the LP break.
- The LP break candle is counted as bar 1.
- Bullish FS execution candle must close at or above the selected support LP.
- Bearish FS execution candle must close at or below the selected resistance LP.
- Equal-price LP selection ties use the latest valid break window.
- Current V15 live/research logic does not require the Force Strike structure
  itself to touch the selected LP. V17 tested strict-touch and ATR-gap filters
  and rejected them as trade filters for now.
- Current shared/research/dry-run/live-send baseline requires the selected LP
  pivot to be before the Force Strike mother bar:
  `lp_pivot_index < fs_mother_index`.
- The explicit legacy override is `require_lp_pivot_before_fs_mother=false`;
  use it only for reproducible historical comparison such as V22 control.
- Existing live `processed_signal_keys` do not include LP pivot index. Do not
  edit live state or rearm old skipped/processed signals for this rule change.

On 2026-05-01, this selector was revalidated by regenerating V9 and rerunning
V10-V15 from the new V9 trade source. Old/new V9 `signals.csv` and `trades.csv`
were byte-identical, so the V15 baseline metrics stayed unchanged.

## Current Research Checkpoint: V22 LP/Force-Strike Separation

V22 was added on 2026-05-05 as a research-only full FX rerun:

- config:
  `../../configs/strategies/lp_force_strike_experiment_v22_lp_fs_separation.json`
- runner:
  `../../scripts/run_lp_force_strike_v22_lp_fs_separation.py`
- report folder:
  `../../reports/strategies/lp_force_strike_experiment_v22_lp_fs_separation/20260505_111005`
- published dashboard:
  `../../docs/v22.html`

Question tested: should LPFS reject setups where the selected LP pivot is the
Force Strike mother bar or otherwise inside the Force Strike formation?

V22 variants:

- `control_current`: explicit legacy V15 signal rules
  (`require_lp_pivot_before_fs_mother=false`).
- `exclude_lp_pivot_inside_fs`: require `lp_pivot_index < fs_mother_index`.

V22 result:

- Control: 13,012 trades, 1,512.3R, 58.0% win rate, PF 1.265.
- Separated rule: 11,834 trades, 1,487.5R, 58.4% win rate, PF 1.289.
- Delta: -1,178 trades, -24.7R, +0.42 percentage points win rate,
  +0.025 PF, +0.0095 average R.
- Control contained 1,603 traded LP==mother / LP-inside-FS trade keys.
- Under separation, 1,295 of those trade keys were removed and 308 same Force
  Strike signals were reselected to an earlier valid LP.
- Overlap audit passed: zero duplicate trade keys, zero duplicate signal join
  keys, and zero missing trade-to-signal joins for both variants.

- V15 bucket rerun: separated rule's most efficient row improved return/DD
  to 50.95 with lower reserved DD, but with materially lower efficient total
  return than current V15.
- V16 bid/ask rerun: separated rule produced 11,749 trades, 1,507.2R,
  PF 1.294, and return/DD 60.29; this improves PF/return-DD versus V16 control
  but still gives up raw total R.

Decision: accepted quality tradeoff. The hard LP-before-FS rule is now the
baseline even though raw total R drops, because it removes invalid/self-
referential LP==mother setups while improving PF, win rate, and average R. The
9.05% trade-count drop and -24.7R raw R drop are accepted costs.

Research revalidation state after V22:

- Rerun already included in V22 for this decision: V9-style full signal/trade
  generation, V15 risk bucket sensitivity, and V16 bid/ask execution realism.
- Stale until rerun on the accepted separated signal universe: V17 LP/FS
  proximity, V18/V19 TP-near exits, V20 protection realism.
- V21 crypto expansion is stale before crypto live planning because it used the
  same old signal-rule family.
- V1-V8 remain historical context only and do not need rerun for this rule
  decision.

## Current Secondary Account Check: IC Markets Raw Spread

On 2026-05-05, a local-only IC Markets Raw Spread account validation was run
without touching the VPS live account.

Dashboard entry:

- `../../docs/account_validation.html`

Artifacts are intentionally ignored and local:

- audit:
  `../../reports/mt5_account_validation/lpfs_new_account/20260505_155656`
- data:
  `../../data/raw/lpfs_new_mt5_account/forex`
- V22 report:
  `../../reports/strategies/lp_force_strike_experiment_v22_new_mt5_account/20260505_160405`
- comparison:
  `../../reports/strategies/lp_force_strike_experiment_v22_new_mt5_account/20260505_160405/comparison_to_current_v22`
- dry-run config:
  `../../config.lpfs_icmarkets_raw_spread.local.json`

Audit:

- server: `ICMarketsSC-MT5-2`
- account currency: `USD`
- `28/28` FX symbols available and visible
- `140/140` H4/H8/H12/D1/W1 candle probes OK
- audited FX volume min/step: `0.01/0.01`
- audited stop/freeze levels: `0/0`

New-account data pull:

- `140` datasets written under `data/raw/lpfs_new_mt5_account/forex`
- `0` failures
- H4/H8/H12/D1 coverage starts around `2016-05-09`; W1 starts around
  `2016-05-08`.

Accepted V22 separated variant compared with the current FTMO-backed V22
baseline:

- trades: `11,937` vs `11,834`
- total R: `2,010.6R` vs `1,487.5R`
- average R: `0.1684R` vs `0.1257R`
- win rate: `59.09%` vs `58.37%`
- profit factor: `1.406` vs `1.289`
- max drawdown: `18.0R` vs `26.0R`

Cost caveat: this comparison included candle spreads but did not include
explicit commission or slippage (`round_turn_commission_points=0.0` in both
the current V22 baseline and IC rerun configs). Official source checks showed
FTMO Forex at `$2.50` per lot per side (`$5.00` round turn per lot) and IC
Markets Raw Spread MetaTrader at `$3.50` per lot per side (`$7.00` round turn
per lot). Run commission sensitivity before treating this as a net
profitability answer for the IC account.

First dry-run cycle on `config.lpfs_icmarkets_raw_spread.local.json` processed
all `140` frames. It found three latest-bar setups, but all were rejected
before broker check because raw volume rounded below the broker `0.01` minimum
lot. Therefore there were `0` `order_check` calls and `0` live orders.

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
- strategy expiry -> after 6 actual MT5 bars from the signal candle;
- broker backstop -> `fs_signal_time + timeframe_delta * 7` plus conservative
  padding: 10 calendar days for H4/H8/H12, 14 days for D1, and 21 days for W1;
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
- broker backstop expiration already at or before current broker market time.

Current test coverage includes ready long/short intents, volume capping,
max-open-risk equality, idempotency, broker-distance checks, bad geometry,
spread, symbol/account errors, broker risk override, and sizing failures.
Live lifecycle tests now cover H4/H8/H12/D1/W1 actual-bar expiry across weekend
gaps: Friday bars after the signal count, weekend time does not, and Monday
continues the remaining count rather than restarting it.

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
- order sent, adopted, or rejected;
- pending expired or cancelled;
- position opened;
- stop loss / take profit hit or manual/unknown position closed;
- runner started / runner stopped;
- executor error;
- kill switch activated.

The notifier defaults to dry-run behavior. Tests use fake HTTP clients and do
not contact Telegram.

Telegram delivery is now trader-facing rather than log-like. The local journal
still records signal, intent, rejection, order-check, and live lifecycle rows.
Telegram uses compact plain-text cards, while raw retcodes, broker comments,
exact floats, and diagnostics stay in JSONL.

`ORDER PLACED` cards now show signal-close time, order-placement time, and
placement lag in SGT. The journal stores the same timing fields as
`signal_closed_time_utc`, `placed_time_utc`, `placement_lag_seconds`, and
`latest_closed_candle_time_utc` so late-surfacing setups can be audited without
changing strategy rules or MT5 send semantics.

Live Telegram messages add real broker lifecycle alerts:

- `ORDER PLACED`;
- `ORDER ADOPTED`;
- `ENTERED`;
- `TAKE PROFIT`;
- `STOP LOSS`;
- `TRADE CLOSED`;
- `WAITING` for retryable spread-only blocks;
- `SKIPPED` / `REJECTED` / `CANCELLED`;
- `RUNNER STARTED` / `RUNNER STOPPED` for process lifecycle status.

Fill, close, expiry, and cancellation alerts reply to the original
`ORDER PLACED` or `ORDER ADOPTED` Telegram message when Telegram returns a
message ID. The live state stores those IDs under `telegram_message_ids`. The
manual performance summary script is
`../../scripts/summarize_lpfs_live_trades.py --config config.local.json --days
7` or `--weeks 4`; it is metric-only by default and lists exact trades only
with `--include-trades`. On the VPS, include
`--runtime-root C:\TradeAutomationRuntime` because production live state and
journal files live outside the repo checkout.

Runner start/stop cards are intentionally separate from trade lifecycle cards.
They show cadence, requested/completed cycles, runtime, state-save status, and
SGT start/stop time, and are also written to the live JSONL journal.

## Live Execution State And Last Verified Snapshot

The connected MT5 account is real. Treat `scripts/run_lp_force_strike_live_executor.py`
as real-order capable whenever ignored local config enables live-send.

AI-agent continuity rule: future LPFS live/runtime, Telegram, MT5 execution,
scheduled-task, or VPS operations work should be carried through to a clear
completion state by default. Include focused verification, commit/push status,
and concrete VPS steps in the final answer. The VPS sequence should pause with
the kill switch, verify the runner is stopped, pull/deploy, run focused checks,
resume `LPFS_Live`, and verify heartbeat, latest log, state, journal, MT5
orders/positions, and Telegram lifecycle cards. For docs-only changes that do
not affect runtime, state clearly that no VPS runner restart is required.
External assistant memory may be read-only, so keep this file and
`../../SESSION_HANDOFF.md` updated for continuity.

Historical timing-telemetry note:

- Order-placement timing telemetry was merged into `main` on 2026-05-05.
  `main` is the intended canonical branch for future LPFS work.
- The timing telemetry is observability-only. It adds signal-close time,
  order-placement time, and placement lag to `ORDER PLACED` Telegram cards and
  live journal rows; it does not change signal rules, order-send behavior,
  sizing, spread gates, expiry, live state schema, or TradingView visuals.

Current local run scope is the full V15 universe: 28 major/cross pairs across
`H4/H8/H12/D1/W1`, or 140 checks per cycle. The current FTMO-style terminal
uses `Europe/Helsinki` broker-time normalization.

Latest corrected full-universe dry-run cycle found four current
order-check-passing intents: `AUDJPY D1 short`, `EURNZD H8 short`,
`GBPJPY H12 short`, and `NZDCHF H4 long`.

Dry-run broker testing used `risk_bucket_scale=0.1`, reducing V15 sizing to
H4/H8 `0.02%`, H12/D1 `0.03%`, and W1 `0.075%` while preserving the relative
timeframe weighting. The current low-risk live-send test default is
`risk_bucket_scale=0.05`, reducing V15 sizing to H4/H8 `0.01%`, H12/D1
`0.015%`, and W1 `0.0375%`. Broker volume steps/minimums can make actual risk
slightly lower or reject very wide setups.

Live-send state as of 2026-05-01:

This is a historical handoff snapshot. Before acting, verify MT5, ignored live
state, and the JSONL journal because broker state can change after this file is
written.

- Module:
  `src/lp_force_strike_strategy_lab/live_executor.py`.
- Runner:
  `../../scripts/run_lp_force_strike_live_executor.py --config config.local.json`.
  For Phase 2 production operation it also supports `--runtime-root`,
  `--kill-switch-path`, and `--heartbeat-path`.
- Required config:
  `live_send.execution_mode="LIVE_SEND"`,
  `live_send.live_send_enabled=true`, and
  `live_send.real_money_ack="I_UNDERSTAND_THIS_SENDS_REAL_ORDERS"`.
- Current production environment is the Amazon Lightsail Windows VPS. Future
  live-operation iteration should start from VPS repo `C:\TradeAutomation`,
  runtime `C:\TradeAutomationRuntime`, scheduled task `LPFS_Live`, and the VPS
  MT5 terminal. Local OneDrive is development only until changes are explicitly
  pushed/pulled to the VPS and the task is intentionally restarted.
- Remote VPS maintenance is available through Tailscale + OpenSSH:
  `ssh lpfs-vps ...` from the local PC reaches VPS host `EC2AMAZ-ON6FOF2`
  (`100.115.34.38`) as `Administrator`. Use it first for read-only status
  packets and repo checks. Environment boundary: local OneDrive is development;
  VPS `C:\TradeAutomation` plus `C:\TradeAutomationRuntime` is production.
- Low-risk defaults: `risk_bucket_scale=0.05`, `max_open_risk_pct=0.65`,
  full V15 stack caps, and `max_spread_risk_fraction=0.1`.
- Scaled risk ladder: H4/H8 `0.01%`, H12/D1 `0.015%`, W1 `0.0375%`.
- Pending-order strategy expiry is now enforced from actual MT5 bar opens after
  the signal candle. The broker-side expiration is a conservative emergency
  backstop only.
- MT5 is the source of truth. The executor reconciles open orders, historical
  orders, open positions, and close deals before scanning new signals.
- Live state writes are atomic, and broker-affecting state is persisted
  immediately after successful live send/adoption, reconciliation mutations, and
  notification idempotency changes.
- The runner holds a single-runner lock beside the live state file. A second
  runner against the same state exits fail-closed before MT5 initialization.
- Immediately before live `order_send`, the executor checks MT5 for an exact
  matching strategy pending order or matching open position and adopts that
  broker item instead of sending a duplicate.
- Pending-to-position fill matching now requires broker comment or historical
  order/deal linkage; same symbol/magic/volume alone is not considered enough.
- Manual or unknown close reasons are reported as `TRADE CLOSED` with MT5 PnL/R,
  not mislabeled as stop losses.
- Late-start missed-entry recovery is active by default: if MT5 bars after the
  signal candle already touched the planned pullback entry before the live order
  could be placed, the runner attempts better-than-entry market recovery before
  skipping. Recovery sends `TRADE_ACTION_DEAL`, keeps the original structure
  stop, recalculates TP to 1R from actual fill, sizes from actual fill-to-stop
  risk, and requires spread <= 10% plus a clean original stop/target path.
  Rollback is `live_send.market_recovery_mode="disabled"`.
- Market-recovery implementation verification on 2026-05-04:
  focused live/notification tests passed (`38` tests), full LPFS discovery
  passed (`186` tests), and `scripts/run_core_coverage.py` passed at
  `100.00%` total coverage. Deployment requires updating the VPS repo and
  intentionally restarting `LPFS_Live`; an already running VPS process will not
  pick up this code automatically.
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
- Last verified tracked/MT5 strategy pending orders after that cycle:
  `EURNZD H8 SHORT SELL_LIMIT #257048012` and
  `GBPJPY H12 SHORT SELL_LIMIT #257048014`.
- Tracked strategy positions at that time: none.
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
- 2026-05-05 market-recovery retry alignment: after a pending entry is touched
  before placement, `market_recovery_not_better` is now retryable WAITING
  instead of a permanent skip. The runner does not mark the signal processed
  and does not call `order_check`/`order_send` while current executable price
  is worse than the original entry. It can recover later if price returns
  same-or-better, spread is acceptable, the actual 6-bar window remains open,
  and the stop/target path after the first entry touch remains clean. Existing
  historical skipped keys remain processed; do not edit VPS live state to
  rearm them without a separate operator plan. Verification passed the focused
  live executor/notification tests, full LPFS test discovery (`215` tests), and
  core coverage at `100.00%`.
- 2026-05-05 market-recovery filling-mode fix: live evidence showed MT5
  rejected an otherwise valid EURCHF D1 market recovery with retcode `10030`
  and comment `Unsupported filling mode`. Market recovery now selects
  broker-supported market `type_filling` modes, retries another filling mode
  when `order_check` fails specifically for invalid/unsupported filling, and
  sends using the exact request that passed `order_check`. This changes only
  market-recovery request plumbing; it does not alter LPFS signals, risk
  buckets, pending-limit behavior, VPS runtime state, or TradingView scripts.
  Verification passed focused live executor tests, full LPFS test discovery
  (`260` tests), and core coverage at `100.00%`.
- After a pending order is placed, spread widening does not auto-cancel it and
  does not currently trigger a dedicated Telegram alert.
- V16 closed the first execution-realism gap. The no-buffer bid/ask model did
  not materially weaken the baseline: `12,917` trades versus `13,012` V15 OHLC
  trades, `1,535.2R` versus `1,512.3R`, and PF `1.270` versus `1.265`.
- V16 stop-buffer variants were mixed. The `1.5x` signal-candle-spread buffer
  had the strongest raw R (`1,587.1R`) and a strong high-return bucket row, but
  it changed `722` exit reasons and `493` win/loss signs. Keep live FS
  structure stops unchanged until a focused buffer-specific follow-up is
  reviewed.
- V17 tested LP-FS proximity filters against the canonical V15 OHLC baseline.
  Strict touch raised PF slightly (`1.272` versus `1.265`) but cut `654` trades,
  gave up about `41R`, and did not beat current V15 on efficient
  return-to-reserved-drawdown. Farther-than-1ATR setups were a small positive
  bucket (`110` trades, `17.6R`, PF `1.391`). Keep current V15 unchanged and do
  not require FS structure touch.
- The live runner now sends best-effort Telegram process notifications on
  start and stop. The stop alert is emitted for completed cycle runs, Ctrl+C,
  and uncaught runtime errors after state save is attempted.
- Phase 2 local production controls are implemented:
  `../../scripts/run_lpfs_live_forever.ps1`,
  `../../scripts/Set-LpfsKillSwitch.ps1`, and
  `../../scripts/Get-LpfsLiveStatus.ps1`.
- The default production runtime root is `C:\TradeAutomationRuntime`, with
  state, journal, heartbeat, kill switch, and logs under
  `C:\TradeAutomationRuntime\data\live`.
- The kill switch is checked before MT5 initialization, before each live cycle,
  and during sleeps between cycles. It stops new cycles but does not close open
  positions or delete broker pending orders by itself.
- Runtime-root migration is fail-closed by default: when the old configured
  live state exists and the new runtime-root state is missing, the runner exits
  until state is copied or a clean state is explicitly allowed after
  broker-state verification.

Expected next scope:

1. Keep the Amazon Lightsail VPS runner under observation with
   `../../scripts/Get-LpfsLiveStatus.ps1`, MT5 open orders/positions,
   `C:\TradeAutomationRuntime\data\live\lpfs_live_state.json`,
   `lpfs_live_journal.jsonl`, Telegram lifecycle cards, and the latest log.
   MT5 remains broker truth; Telegram is only a monitoring channel.
2. Verify the VPS repo is on `main` and fast-forwarded to `origin/main` before
   assuming the latest local docs or live-runner behavior are present in
   production. Use `ssh lpfs-vps hostname`, `whoami`, VPS `git status`, and
   the LPFS status packet before drawing operational conclusions.
3. Do not run a local PC live runner against the same account while
   `LPFS_Live` is running on the VPS.
4. If a user manually deletes a pending order, let the next reconciliation
   record it as cancelled/missing; do not clear state unless intentionally
   re-arming the current latest-candle setups.
5. Keep low-risk live validation running long enough to collect real broker
   lifecycle evidence before scaling risk or changing strategy rules.
6. For any new MT5 account or broker feed, use the local-only validation path
   in `../../docs/lpfs_new_mt5_account_validation.md`: audit account/symbol
   specs, pull a separate dataset, rerun V22, compare to the current V22
   baseline, then run dry-run/order-check only if the broker-data comparison is
   acceptable. Do not change the VPS MT5 login for this work.
7. Local Phase 2 rehearsal passed on 2026-05-03. Amazon Lightsail VPS
   deployment passed staged verification on 2026-05-04: repo at
   `C:\TradeAutomation`, runtime at `C:\TradeAutomationRuntime`, MT5 Python
   attach to the FTMO terminal works, state/journal match the two LPFS pending
   orders, direct one-cycle and watchdog one-cycle tests passed, temporary Task
   Scheduler smoke/live tests passed, Telegram works after the `certifi` HTTPS
   fix, and final at-logon task `LPFS_Live` is installed. By 2026-05-05 it is
   expected to run under `C:\TradeAutomationRuntime` when the kill switch is
   absent.
8. If stop robustness becomes a priority, run a focused spread-buffer
   validation by timeframe and symbol group. Do not change the live stop
   placement from no-buffer based on V16 alone.
9. If discretionary review needs more context, surface LP-FS proximity as a
   setup-quality label in dashboards/Telegram, not as a live trade filter.

## Phase 2 Production Hardening

Phase 2 is an operations project, not a strategy project. The purpose is to make
the existing real-order-capable runner observable and restart-safe under normal
production failures: Python crash, MT5 disconnect, Windows restart, Telegram
failure, state-file lock, or operator emergency stop.

Canonical plan:

```text
../../docs/phase2_production_hardening.md
```

Implemented controls:

1. `../../scripts/run_lpfs_live_forever.ps1`: PowerShell watchdog launcher.
2. `../../scripts/Set-LpfsKillSwitch.ps1`: file-based kill switch helper.
3. `../../scripts/Get-LpfsLiveStatus.ps1`: pasteable status packet.
4. Timestamped stdout/stderr logs under the production runtime root.
5. `--runtime-root` support so production state and journal can live outside
   OneDrive.
6. Heartbeat JSON updated at start, every completed cycle, and shutdown.
7. Kill-switch checks before MT5 initialization, before live cycles, and during
   sleeps.
8. Amazon Lightsail runbook at `../../docs/lpfs_lightsail_vps_runbook.md`.

Local rehearsal result:

1. `C:\TradeAutomationRuntime` was staged with copied live state and journal.
2. `KILL_SWITCH` is active for post-rehearsal operator review.
3. Direct one-cycle production-runtime run completed with 140 frames and no new
   orders.
4. Watchdog one-cycle run completed, updated heartbeat, and wrote a log.
5. Temporary Task Scheduler smoke run returned kill-switch exit code `3`.
6. Temporary Task Scheduler one-cycle live rehearsal returned result `0`.
7. Temporary scheduled tasks were removed after rehearsal; no persistent local
   auto-start task is installed.

Recommended next path:

1. Leave `LPFS_Live` running only if the status packet shows a fresh heartbeat,
   the expected parent/child Python process shape, `kill_switch_active=False`,
   and MT5 state matches local live state.
2. For deployment or emergency pause, set the VPS kill switch first, wait for
   graceful stop, then verify process table, heartbeat, latest log, MT5, and
   Telegram lifecycle cards before changing code or config.
3. Do not edit `lpfs_live_state.json` or `lpfs_live_journal.jsonl` to rearm old
   processed signals. Historical skipped keys remain skipped unless a separate
   live operator plan explicitly approves state surgery.
4. The next research/ops evidence task is live gate attribution: quantify
   spread waits, market-recovery price waits, later recoveries, expiries,
   symbols/timeframes affected, and whether blocks cluster around weekly open
   before changing the spread gate or recovery rules.

Acceptance criteria include single-runner protection, no duplicate orders after
restart, kill-switch stop before order send, state/journal/log survival across
reboot, Telegram process alerts, and MT5 reconciliation before new signal
scanning.

Do not change signal rules, risk buckets, spread gate, order geometry, or
expiration behavior while implementing Phase 2.

## Experiment V16 Bid/Ask Execution Realism

Experiment V16 is configured by:

```text
../../configs/strategies/lp_force_strike_experiment_v16_execution_realism.json
```

Run command:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_v16_execution_realism.py --config configs\strategies\lp_force_strike_experiment_v16_execution_realism.json --docs-output docs\v16.html
```

Latest local run:

- report folder:
  `reports/strategies/lp_force_strike_experiment_v16_execution_realism/20260501_060205`
- dashboard: `../../docs/v16.html`
- scope: 28 major/cross pairs x H4/H8/H12/D1/W1
- model: LP3, 0.5 signal-candle pullback, FS structure stop, 1R target,
  fixed 6-bar pullback wait
- execution realism: OHLC as Bid, Ask approximated as Bid plus each candle's
  `spread_points * point`
- buffer variants: `0.0x`, `0.5x`, `1.0x`, `1.5x`, and `2.0x` signal-candle
  spread

Key result:

- V15 OHLC baseline: `13,012` trades, `1,512.3R`, PF `1.265`.
- V16 no-buffer bid/ask: `12,917` trades, `1,535.2R`, PF `1.270`.
- No-buffer missed only `95` baseline trades and passed V15 practical bucket
  filters.
- V16 `1.5x` buffer: `12,917` trades, `1,587.1R`, PF `1.280`, but changed
  `722` exit reasons and `493` win/loss signs versus baseline.

Decision:

- Bid/ask realism is not a material regression.
- Keep current live FS structure stops unchanged for now.
- Treat spread buffers as promising follow-up research because buffer behavior
  is more invasive than bid/ask realism itself.

## Experiment V17 LP-FS Proximity Tightening

Experiment V17 is configured by:

```text
../../configs/strategies/lp_force_strike_experiment_v17_lp_fs_proximity.json
```

Run command:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_v17_lp_fs_proximity.py --config configs\strategies\lp_force_strike_experiment_v17_lp_fs_proximity.json --docs-output docs\v17.html
```

Latest local run:

- report folder:
  `reports/strategies/lp_force_strike_experiment_v17_lp_fs_proximity/20260501_122711`
- dashboard: `../../docs/v17.html`
- scope: 28 major/cross pairs x H4/H8/H12/D1/W1
- baseline: current canonical V15 OHLC trade model
- variants: `current_v15`, `strict_touch`, `gap_0p25_atr`,
  `gap_0p50_atr`, and `gap_1p00_atr`

Key result:

- Current V15: `13,012` trades, `1,512.3R`, PF `1.265`.
- Strict touch: `12,358` trades, `1,471.3R`, PF `1.272`.
- Gap up to 0.25 ATR: `12,588` trades, `1,485.9R`, PF `1.269`.
- Gap up to 0.50 ATR: `12,750` trades, `1,495.7R`, PF `1.267`.
- Gap up to 1.00 ATR: `12,902` trades, `1,494.7R`, PF `1.264`.
- Farther-than-1ATR quality bucket: `110` trades, `17.6R`, PF `1.391`.

Decision:

- Keep current V15 unchanged.
- Do not require the Force Strike structure to touch/cross the selected LP.
- Strict touch and near-touch filters improve average quality slightly but do
  not beat the current V15 row on efficient return-to-reserved-drawdown and
  remove too much useful edge.
- LP-FS proximity can become a future setup-quality label for trader context,
  but it is not a live execution rule.

## Experiment V18 TP-Near Exit Research

Experiment V18 is configured by:

```text
../../configs/strategies/lp_force_strike_experiment_v18_tp_near_exit.json
```

Run command:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_v18_tp_near_exit.py --config configs\strategies\lp_force_strike_experiment_v18_tp_near_exit.json --docs-output docs\v18.html
```

Smoke verification run:

- report folder:
  `reports/strategies/lp_force_strike_experiment_v18_tp_near_exit/smoke`
- scope: `GBPCAD H4`
- result rows: `320` signals and `2,510` variant trade rows
- artifacts include `trades.csv`, `summary_by_variant.csv`,
  `old_vs_new_trade_delta.csv`, `tp_near_outcome_breakdown.csv`,
  `run_summary.json`, and `dashboard.html`

V18 is not the strategy baseline. The current strategy baseline remains V13
mechanics with V15 risk buckets. V18 uses the V16 no-buffer bid/ask simulator
as the control environment because TP-near behavior depends on bid/ask side and
spread-aware near-miss detection.

Decision status:

- Research-only implementation exists.
- No live executor, VPS task, MT5 order, live state, live journal, or live
  Telegram behavior has been changed.
- Full-universe results must be reviewed before any live TP-near close/protect
  behavior is considered.

## Experiment V19 TP-Near Robustness Backtest

Experiment V19 is configured by:

```text
../../configs/strategies/lp_force_strike_experiment_v19_tp_near_robustness.json
```

Run command:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_v19_tp_near_robustness.py --config configs\strategies\lp_force_strike_experiment_v19_tp_near_robustness.json --docs-output docs\v19.html
```

Full-universe run:

- report folder:
  `reports/strategies/lp_force_strike_experiment_v19_tp_near_robustness/20260504_194519`
- dashboard: `docs/v19.html`
- scope: all `H4/H8/H12/D1/W1` LPFS datasets from
  `configs/datasets/forex_major_crosses_10y.json`
- result rows: `16,061` signals, `12,917` control trades, and `245,423`
  variant trade rows
- artifacts include `trades.csv`, `summary_by_variant.csv`,
  `old_vs_new_trade_delta.csv`, `tp_near_outcome_breakdown.csv`,
  `symbol_timeframe_breakdown.csv`, `year_breakdown.csv`,
  `stress_sensitivity.csv`, `changed_trade_samples.csv`,
  `variant_decision_matrix.csv`, `run_summary.json`, and `dashboard.html`

V19 keeps the V15 LPFS strategy baseline and uses the V16 no-buffer bid/ask
simulator as the control. The rerun corrected close variants to hard reduced-TP
semantics: `close_pct_90` exits at `0.9R` once touched and does not get upgraded
to full `1R` later. It also tests spread-haircut closes, one-bar delayed
closes, breakeven protection, locked-profit protection, symbol/timeframe
concentration, year stability, saved/sacrificed R, same-bar reliance, and V15
bucket guardrails.

Decision status:

- `lock_0p50r_pct_90` is the strongest V19 live-design candidate.
- V16 no-buffer control: `12,917` trades, `1,535.2R`, PF about `1.270`.
- Hard `close_pct_90`: `12,917` trades, `1,594.0R`, PF about `1.302`, only
  `+58.8R` versus control. It is not a live candidate because reducing every
  target to `0.9R` sacrifices too much full-TP profit.
- `lock_0p50r_pct_90`: `12,917` trades, `1,878.7R`, PF about `1.356`, a
  `+343.5R` delta versus control.
- `lock_0p50r_pct_90` saved `390` trades from later stops for about `+585.0R`,
  sacrificed `259` later full TPs for about `-129.5R`, and had `308`
  same-bar-conflict rows for about `-112.0R`.
- The generated decision matrix marks `lock_0p50r_pct_90` as passing raw R, PF,
  return/DD, practical bucket, saved/sacrificed, concentration, year-stability,
  and same-bar gates.
- No live executor, VPS task, MT5 order, live state, live journal, or live
  Telegram behavior has been changed.

Recommended follow-up:

```text
Do not implement live TP-near protection from V19 alone. V20 must be reviewed
first because it brackets live stop-modification timing with M30 replay.
```

## Experiment V20 Protection Realism

Experiment V20 is configured by:

```text
../../configs/strategies/lp_force_strike_experiment_v20_protection_realism.json
```

Run command:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_v20_protection_realism.py --config configs\strategies\lp_force_strike_experiment_v20_protection_realism.json --docs-output docs\v20.html
```

Full-universe run:

- report folder:
  `reports/strategies/lp_force_strike_experiment_v20_protection_realism/20260505_043723`
- dashboard: `docs/v20.html`
- scope: all `H4/H8/H12/D1/W1` LPFS datasets from
  `configs/datasets/forex_major_crosses_10y.json`
- replay timeframe: `M30`
- result rows: `16,061` signals, `12,022` M30 replay control trades, and
  `96,176` variant trade rows
- artifacts include `trades.csv`, `summary_by_variant.csv`,
  `old_vs_new_trade_delta.csv`, `protection_outcome_breakdown.csv`,
  `protection_funnel.csv`, `symbol_timeframe_breakdown.csv`,
  `year_breakdown.csv`, `changed_trade_samples.csv`,
  `variant_decision_matrix.csv`, `run_summary.json`, and `dashboard.html`

V20 keeps the V15 LPFS signal baseline but replays entries, exits, and
stop-protection on M30 bid/ask candles. This matters because live checks every
30 seconds, while historical backtest data only shows candle OHLC. V20 therefore
brackets live behavior:

- conservative stress: a `0.9R` touch can only lock the `0.5R` stop on a later
  M30 candle; fast snapbacks are counted as missed protection and the trade
  remains on the original baseline bracket;
- optimistic upper bound: `lock_0p50r_pct_90_m30_same_assumed` assumes the live
  30-second loop could modify the stop inside the same M30 candle after the
  `0.9R` touch. This is not direct live evidence because intra-M30 ordering is
  unknown.

Decision status:

- M30 replay control: `12,022` trades, `336.9R`, PF about `1.058`.
- Same-M30 upper bound: `lock_0p50r_pct_90_m30_same_assumed` reached `512.9R`,
  PF about `1.095`, and `+176.0R` versus control. It had `2,561` trigger
  touches, `2,561` assumed activations, `427` saved-from-stop trades,
  `747` sacrificed full-TP trades, and `206` same-bar-conflict rows.
- Conservative later-M30 variants did not beat control:
  `lock_0p50r_pct_90_m30_next` was `-53.0R` and
  `lock_0p50r_pct_90_m30_delay1` was `-5.5R` versus control.
- The correct live interpretation is bounded: missed modifications are
  baseline-equivalent, but successful modifications can still sacrifice later
  full TPs. Real 30-second live behavior is likely between the conservative and
  optimistic V20 cases.
- No live executor, VPS task, MT5 order, live state, live journal, Telegram
  lifecycle behavior, or TradingView indicator has been changed.

Recommended follow-up:

```text
Do not change live TP/SL handling yet. If TP-near protection remains a priority,
collect M1/tick data or forward live attribution for 0.9R touches, stop-modify
success, too-fast misses, and later trade outcomes. Only then design the live
stop-modification lifecycle.
```

## Experiment V21 Crypto BTC/ETH Broker-History

Experiment V21 is configured by:

```text
../../configs/strategies/lp_force_strike_experiment_v21_crypto_btc_eth.json
```

Dataset config:

```text
../../configs/datasets/crypto_btc_eth_sol_broker_history.json
```

Run command:

```powershell
.\venv\Scripts\python scripts\pull_mt5_dataset.py --config configs\datasets\crypto_btc_eth_sol_broker_history.json --output reports\data\crypto_btc_eth_sol_pull.json
.\venv\Scripts\python scripts\run_lp_force_strike_v21_crypto_btc_eth.py --account-equity <current_equity>
```

Current local run:

- report folder:
  `reports/strategies/lp_force_strike_experiment_v21_crypto_btc_eth/20260505_062556`
- dashboard: `docs/v21.html`
- decision set: `BTCUSD` and `ETHUSD`
- exploratory only: `SOLUSD`, because current broker history starts much later
- broker-history starts observed on 2026-05-05:
  `BTCUSD` from 2017-10-23, `ETHUSD` from 2020-11-11, and `SOLUSD` from
  2025-04-17
- dataset pull: 18/18 symbol-timeframe datasets saved for
  `M30/H4/H8/H12/D1/W1`
- data quality: no failures, warnings for large crypto moves and incomplete
  latest bars from the live-ended pull
- BTC/ETH decision-population result: `701` trades, `49.0R`, PF about `1.150`,
  max drawdown about `21.0R`, return/DD about `2.33`, worst month about `-7.0R`
- explicit baseline comparison now appears in `docs/v21.html` and
  `baseline_comparison.csv`:
  - V15 canonical FX baseline: `13,012` trades, about `1,512.3R`, PF `1.265`
  - V16 FX bid/ask control: `12,917` trades, about `1,535.2R`, PF `1.270`
  - V21 BTC/ETH crypto transfer: `701` trades, about `49.0R`, PF `1.150`
- execution feasibility at the supplied current account equity:
  `66.5%` live-feasible, with spread-fail rate about `13.3%`

Decision status:

- V21 marks crypto as `research_only`, not a live candidate.
- The raw BTC/ETH result is positive, but one or more execution gates failed.
  The key blocker is current-account tradeability after min-lot and spread
  gates, not just raw R.
- SOL is not part of the decision because its broker history is too short.
- No live FX executor, VPS task, MT5 order, live state, live journal, Telegram
  lifecycle behavior, or TradingView indicator has been changed.

Recommended follow-up:

```text
Do not add crypto to live yet. Inspect V21 symbol/timeframe and feasibility
rows first. If crypto remains a priority, the next step is not a live deploy;
it is a focused BTC-only or ETH-only refinement with explicit sizeability and
spread gates.
```

## Dashboard Interpretation UX

The dashboard interpretation metadata lives in:

```text
../../configs/dashboards/lp_force_strike_pages.json
```

On 2026-04-30, V6-V15 were given a `decision_brief` section in that metadata.
V16-V21 also have decision briefs for execution realism, LP-FS proximity,
TP-near research, TP-near robustness, protection realism, and crypto expansion.
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
