# TradeAutomation Project State

Last updated: 2026-04-29 after the native H12 bridge experiment and responsive
dashboard update.

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

Known data-quality interpretation:

- Current verdict is `OK_WITH_WARNINGS`, not failed.
- Known long-gap symbols: `GBPAUD`, `GBPNZD`, `NZDCAD`, `NZDCHF`.
- Strategy experiments currently exclude those four symbols.
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

The dashboard generator is:

```text
scripts/build_lp_force_strike_dashboard.py
```

The pages were made responsive on 2026-04-29. Future dashboard changes should
update the generator first, then regenerate the versioned pages.

## Current Recommendation

Next useful research should not keep widening timeframe tests blindly. The
highest-value next step is to test portfolio-realistic behavior for the current
candidate family:

- one-position-at-a-time or max-concurrent-position rules;
- symbol/timeframe exposure limits;
- closed-trade and equity drawdown by timeframe;
- FTMO-style daily/max loss constraints;
- candidate comparison on H12/D1/W1 first, with H4/H8 as lower-quality
  context.

## Git State Notes

Latest pushed commits at the time of this handover:

- `fd4e7cb Add native H12 bridge experiment`
- `da6f999 Improve dashboard responsiveness`

Untracked folders such as `CryptoBot_test/`, `FOREX/`, `force_strike_lab/`,
`forex_experiment/`, `mt5_strategy_lab/`, and `xauusd_m1_research/` are outside
the active TradeAutomation research path and should not be staged unless the
user explicitly asks.

## Suggested Prompt For Next Session

```text
Continue from TradeAutomation/PROJECT_STATE.md. Focus on the LP + Force Strike
strategy lab. Review V6 H12 bridge results and propose the next controlled
portfolio/backtest experiment without changing concept behavior unless needed.
```
