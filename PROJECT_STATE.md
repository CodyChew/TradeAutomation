# TradeAutomation Project State

Last updated: 2026-04-30 after running the V14 risk sizing and drawdown study
and regenerating V1-V14 dashboard navigation.

## Purpose

This repository is a Python-first trading research workspace. TradingView is
used for visual inspection, while Python modules and MT5 broker data are the
source of truth for strategy research and future live execution work.

## Read This First In A New Codex Session

1. `PROJECT_STATE.md` for the overall workspace state.
2. `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md` for the current
   LP + Force Strike strategy research.
3. `shared/market_data_lab/PROJECT_STATE.md` for dataset status.
4. `concepts/lp_levels_lab/PROJECT_STATE.md` and
   `concepts/force_strike_pattern_lab/PROJECT_STATE.md` only when changing
   concept behavior.

Useful dashboard entry point:

```text
docs/index.html
https://codychew.github.io/TradeAutomation/
```

## Current Structure

- `concepts/lp_levels_lab`: reusable LP levels concept.
- `concepts/force_strike_pattern_lab`: reusable raw Force Strike pattern
  concept.
- `shared/market_data_lab`: MT5 candle pulls, validation, Parquet storage, and
  dataset manifests.
- `shared/backtest_engine_lab`: strategy-neutral OHLC bracket-trade simulator.
- `strategies/lp_force_strike_strategy_lab`: active LP + Force Strike strategy
  research.
- `docs/`: static GitHub Pages dashboards.
- `data/` and `reports/`: generated local data/results, intentionally ignored by
  git.

## Current Dataset State

The FTMO FOREX major/cross dataset covers the 28 pairs built from AUD, CAD,
CHF, EUR, GBP, JPY, NZD, and USD.

Pulled locally:

- `M30`, `H4`, `D1`, `W1`: canonical 10-year dataset.
- `H8`: native MT5 add-on dataset.
- `H12`: native MT5 add-on dataset.

Dataset regression gate:

```powershell
.\venv\Scripts\python scripts\verify_dataset_fingerprint.py
```

Current result on 2026-04-29:

- `status=OK`
- `fingerprint_datasets=168`
- `aggregation_checks=140`

The gate compares the local Parquet files against
`configs/datasets/fingerprints/ftmo_forex_major_crosses_10y.json` and verifies
that settled `H4`, `H8`, `H12`, `D1`, and `W1` candles aggregate exactly from
`M30`. It skips the newest one day for aggregation checks because MT5 can have
small live-edge cache drift between native higher-timeframe candles and M30.

Known data-quality interpretation:

- Current verdict is `OK_WITH_WARNINGS`, not failed.
- Known long-gap symbols: `GBPAUD`, `GBPNZD`, `NZDCAD`, `NZDCHF`.
- V1 through V6 strategy experiments excluded those four symbols for a clean
  conservative baseline.
- A 2026-04-29 ad hoc run tested those four symbols with the current V6 model.
  They loaded successfully and were not obvious performance outliers. Future
  experiments can use all 28 pairs, while keeping the gap caveat visible.
- Latest live-ended bars are incomplete and are dropped in backtests.

## Current LP Rules

LP levels are implemented in:

```text
concepts/lp_levels_lab/src/lp_levels_lab/levels.py
```

Current lookback mapping:

- `M30`: 5 days.
- `H4`: 30 days.
- `H8`: 60 days.
- `H12`: 180 days.
- `D1` / `2D`: 1 year.
- `W1`: 4 years.

TradingView visual indicator is kept aligned at:

```text
concepts/lp_levels_lab/tradingview/lp_levels.pine
```

## Current Strategy Model Under Test

The current best model family is:

```text
0.5 signal-candle pullback
full Force Strike structure stop
single 1R target
```

The strategy combines:

- active LP wick-break trap;
- raw Force Strike confirmation within the configured window;
- pullback entry into the signal candle zone;
- OHLC bracket simulation with candle spread and conservative same-bar
  stop-first handling.

## Latest Timeframe Comparison

Latest completed comparison is V6:

```text
reports/strategies/lp_force_strike_experiment_v6_h12_bridge/20260428_191017
docs/v6.html
```

V6 results for `signal_zone_0p5_pullback__fs_structure__1r`:

| Timeframe | Trades | Avg R | PF | Win Rate |
|---|---:|---:|---:|---:|
| H4 | 5,642 | 0.084R | 1.185 | 56.9% |
| H8 | 2,674 | 0.099R | 1.221 | 56.7% |
| H12 | 1,844 | 0.157R | 1.375 | 59.2% |
| D1 | 855 | 0.208R | 1.527 | 61.2% |
| W1 | 170 | 0.252R | 1.678 | 62.9% |

Interpretation:

- H8 is only a modest improvement over H4.
- H12 is a meaningful bridge between H8 and D1.
- D1 and W1 remain the cleanest timeframes by quality.
- H12 should remain in the forward research set.

## Dashboard State

Static dashboards exist at:

- `docs/v1.html`: broad baseline.
- `docs/v2.html`: H4/D1/W1 midpoint focus.
- `docs/v3.html`: entry zones, ATR filters, partial exits.
- `docs/v4.html`: train/test stability filters.
- `docs/v5.html`: H8 bridge.
- `docs/v6.html`: H12 bridge.
- `docs/v7.html`: conservative 1R-cancel entry-wait test.
- `docs/v8.html`: entry-priority 1R-cancel entry-wait test.
- `docs/v9.html`: LP pivot strength sensitivity.
- `docs/v10.html`: portfolio exposure cap baseline.
- `docs/v11.html`: practical timeframe mix study.
- `docs/v12.html`: LP pivot finalization.
- `docs/v13.html`: relaxed portfolio rule selection.
- `docs/v14.html`: risk sizing and drawdown study.

The dashboard generator is:

```text
scripts/build_lp_force_strike_dashboard.py
```

Dashboard interpretation text is centralized in:

```text
configs/dashboards/lp_force_strike_pages.json
```

The home page generator is:

```text
scripts/build_lp_force_strike_index.py
```

The pages were made responsive and given explicit interpretation summaries on
2026-04-29. On 2026-04-30, V6-V14 gained a prominent `Decision Brief` block so
the important chat-style conclusions are visible before the metric tables.
Future dashboard changes should update the metadata and generators first, then
regenerate the versioned pages.

## Current Recommendation

The current research baseline after V13 is:

- LP pivot strength `3`.
- all `H4/H8/H12/D1/W1` timeframes.
- `take_all` portfolio handling: allow all trades, including same-symbol
  stacking.
- 0.5 signal-candle pullback, full Force Strike structure stop, single 1R
  target, and fixed 6-bar pullback wait.

V13 relaxed the older 30R max-drawdown / 180D underwater guardrails from hard
selection rules into context. Under that more trader-practical ranking,
`take_all` became the current research baseline:

| Portfolio | Trades | Total R | Max DD | Underwater | Negative years | Negative symbols |
|---|---:|---:|---:|---:|---:|---:|
| take_all | 13,012 | 1,512.3R | 33.4R | 111D | 0 | 0 |
| cap_4r | 10,037 | 1,100.9R | 26.7R | 162D | 0 | 0 |

Interpretation:

- `take_all` adds about `411R` over `cap_4r` and has shorter underwater.
- The higher drawdown is about `8.3%` at `0.25%` risk per trade, versus about
  `6.7%` for `cap_4r`.
- No negative years, no negative symbols, and no obvious year/ticker
  concentration skew were found in V13.
- The caveat is exposure: `take_all` reached 17 concurrent trades and max
  same-symbol stack of 4.

Next useful research:

- use V14's account-risk schedule as the starting point, then test daily/max
  loss constraints, same-symbol stacking limits, and max concurrent trade
  limits;
- add equity-curve diagnostics beyond closed-trade R;
- prepare an MT5 execution contract only after risk sizing is clear.

Latest V14 risk-sizing read:

- V14 did not rerun MT5 data or signals. It used the V13 baseline trade rows.
- Balanced equal-LTF is the practical starting schedule:
  H4 `0.15%`, H8 `0.15%`, H12 `0.25%`, D1 `0.40%`, W1 `0.60%`.
- Balanced equal-LTF result: `+332.6%` total return, `6.2%` realized max DD,
  `8.6%` risk-reserved max DD, and `5.7%` max reserved open risk.
- Fixed `0.25%` is the closest simple alternative: `+378.1%` total return,
  `8.3%` realized max DD, and `9.8%` risk-reserved max DD.
- Fixed `0.50%` is a high-return/high-stress diagnostic, not the first
  practical default: `+756.1%` total return and `19.5%` risk-reserved max DD.

Do not replace the fixed 6-bar pullback wait with the V7/V8 1R-cancel wait
rule. V8, the fairer entry-priority version, was positive but weaker than the
full-28 fixed 6-bar baseline on every timeframe.

## Git State Notes

Recent project commits:

- `Add V14 risk sizing study` (current HEAD)
- `0e55f70 Add V13 relaxed portfolio study`
- `2c8cf82 Improve dashboard decision briefs`
- `f2e448c Add V11 timeframe mix study`

Untracked folders such as `CryptoBot_test/`, `FOREX/`, `force_strike_lab/`,
`forex_experiment/`, `mt5_strategy_lab/`, and `xauusd_m1_research/` are outside
the active TradeAutomation research path and should not be staged unless the
user explicitly asks.

## Suggested Prompt For Next Session

```text
Continue from TradeAutomation/PROJECT_STATE.md. Focus on the LP + Force Strike
strategy lab. The current baseline is V13 `take_all` with LP3 across
H4/H8/H12/D1/W1. Review docs/v13.html and docs/v14.html. Use the V14 balanced
equal-LTF risk schedule as the first practical sizing candidate, then test
daily/max loss and same-symbol/concurrent execution constraints without
changing LP or Force Strike concept behavior unless needed.
```
