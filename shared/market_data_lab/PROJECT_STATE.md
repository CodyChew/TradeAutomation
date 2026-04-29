# Market Data Lab Project State

Last updated: 2026-04-29 after adding and quality-checking the native MT5 H12
FOREX add-on dataset and reviewing the four long-gap symbols.

## Purpose

This shared lab owns canonical MT5 candle data for all concepts and strategies
in `TradeAutomation`. It is strategy-neutral. Concepts and strategies should
load their OHLC data from this shared layer instead of pulling, cleaning, or
validating candles differently.

## Current Scope

- Normalize MT5-style rates into one canonical candle schema.
- Validate timestamp order, duplicate bars, OHLC integrity, symbol, timeframe,
  and median bar spacing.
- Define the first FOREX universe as major/cross pairs only, using AUD, CAD,
  CHF, EUR, GBP, JPY, NZD, and USD.
- Store datasets in a file-backed local data store.
- Write manifests with coverage, source, symbol metadata, account metadata, and
  pull timing.
- Provide MT5 pull helpers that are injectable and testable without a live MT5
  terminal.
- Provide config-driven bulk MT5 dataset pulls with per-symbol/timeframe
  failures and coverage reporting.
- Provide a preflight MT5 symbol availability script for configured datasets.

## Current Storage Model

V1 uses Parquet files plus JSON manifests. Parquet is the primary dataset format
because it is smaller, faster for pandas reads, and preserves column types more
reliably than CSV. CSV helpers remain available for exports and debugging.

Future versions can add DuckDB or SQLite indexing if dataset size or query
complexity makes that worthwhile. Strategy logic should not depend on the
physical storage format.

## Canonical Candle Columns

- `time_utc`
- `symbol`
- `timeframe`
- `open`
- `high`
- `low`
- `close`
- `tick_volume`
- `spread_points`
- `real_volume`

## Boundary

This lab does not define indicators, strategies, entries, exits, risk, PnL, or
live execution.

Candle data is sufficient for bar-based strategy research. It is not sufficient
for tick-level spread behavior, intrabar order sequencing, partial fills, market
depth, or latency-sensitive execution unless additional MT5 data is captured.

## Current Dataset Config

`configs/datasets/forex_major_crosses_10y.json` requests the 28 major/cross
FOREX pairs on `M30`, `H4`, `D1`, and `W1` for 10 years into
`data/raw/ftmo/forex`.

`configs/datasets/forex_major_crosses_10y_h8.json` requests the same 28-symbol
universe on native MT5 `H8` only. H8 is stored alongside the other timeframes
under `data/raw/ftmo/forex/SYMBOL/H8`.

`configs/datasets/forex_major_crosses_10y_h12.json` requests the same 28-symbol
universe on native MT5 `H12` only. H12 is stored alongside the other timeframes
under `data/raw/ftmo/forex/SYMBOL/H12`.

## Local Availability Check

On 2026-04-28, the local MetaTrader5 Python package initialized successfully
against `FTMO-Server`, and all 28 configured major/cross FOREX symbols were
available by exact symbol name.

## Current Pulled Dataset

The 10-year FTMO FOREX dataset has been pulled locally into
`data/raw/ftmo/forex` as Parquet files. Generated data is ignored by git.

- 28 symbols.
- 4 timeframes: `M30`, `H4`, `D1`, `W1`.
- 112 symbol/timeframe datasets.
- 3,984,435 candle rows.
- 112/112 coverage rows marked backtest-ready after market-closure boundary
  tolerance.

The native MT5 H8 add-on dataset has also been pulled locally:

- 28 symbols.
- 1 timeframe: `H8`.
- 28 symbol/timeframe datasets.
- 28/28 coverage rows marked backtest-ready after market-closure boundary
  tolerance.

The native MT5 H12 add-on dataset has also been pulled locally:

- 28 symbols.
- 1 timeframe: `H12`.
- 28 symbol/timeframe datasets.
- 28/28 coverage rows marked backtest-ready after market-closure boundary
  tolerance.

## Current Quality Verdict

`scripts/report_data_quality.py` produced `OK_WITH_WARNINGS`.

- No dataset validation/load failures.
- No duplicate timestamps.
- Complete W1 candles match M30 aggregation exactly.
- Long historical gaps exist in `GBPAUD`, `GBPNZD`, `NZDCAD`, and `NZDCHF`.
- Large one-bar moves were flagged for manual review, mostly around known
  high-volatility periods.
- All datasets end with an incomplete latest bar because the pull was live-ended.

Early clean baseline backtests may exclude `GBPAUD`, `GBPNZD`, `NZDCAD`, and
`NZDCHF`, but the data is loadable and an LP + Force Strike ad hoc run found
that those four symbols were not obvious performance outliers. Future strategy
research can include all 28 major/cross FOREX pairs, while keeping the gap
caveat visible. Backtests should also ignore the latest incomplete tail bar
unless the strategy explicitly supports live in-progress candles.

The current backtest runner can test the available candles as-is. It does not
yet automatically split around large gaps, so production-grade research should
eventually add gap segmentation to prevent indicators, signals, and trades from
spanning missing broker-history periods.

The H8 and H12 add-on datasets produced the same overall quality class,
`OK_WITH_WARNINGS`: no validation/load failures, the same known long-gap
symbols, several large one-bar moves for manual review, and incomplete latest
bars from the live-ended pulls.
