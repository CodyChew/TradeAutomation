# Market Data Lab Project State

Last updated: 2026-04-28 after creating the first shared market-data foundation.

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

## Local Availability Check

On 2026-04-28, the local MetaTrader5 Python package initialized successfully
against `FTMO-Server`, and all 28 configured major/cross FOREX symbols were
available by exact symbol name. Candle history coverage has not been pulled yet;
use `scripts/pull_mt5_dataset.py` followed by
`scripts/report_dataset_coverage.py` to validate the actual 10-year history.
