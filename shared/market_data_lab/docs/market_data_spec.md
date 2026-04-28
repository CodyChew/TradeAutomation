# Market Data Specification

This document defines the shared data contract for TradeAutomation research.

## Source Of Truth

Python backtests and future MT5 execution research should use this shared
market-data layer as the candle source of truth. TradingView scripts are for
inspection and may differ from MT5 broker data.

## Forex Universe

For the first FTMO FOREX dataset, "all FOREX" means majors and cross pairs built
from these eight currencies only:

- AUD
- CAD
- CHF
- EUR
- GBP
- JPY
- NZD
- USD

This produces 28 pairs and intentionally excludes exotics, metals, indices,
commodities, crypto, and synthetic broker symbols.

## Required Candle Schema

Every stored rates dataset must use these columns:

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

`time_utc` is UTC. `symbol` is uppercase. `timeframe` is the normalized internal
label, for example `M30`, `H4`, `H8`, `D1`, or `W1`.

## Validation Rules

Stored candles must pass these checks:

- required columns exist;
- dataset is not empty;
- all rows belong to the requested symbol and timeframe;
- timestamps are unique and increasing;
- OHLC fields are numeric;
- `high >= low`, `high >= open`, `high >= close`;
- `low <= open`, `low <= close`;
- known volume and spread fields are non-negative;
- median bar spacing matches the normalized timeframe.

The median spacing rule allows normal market closures and weekend gaps while
still catching the wrong timeframe.

## Storage Format

Parquet is the primary candle storage format. It is smaller than CSV, faster to
load with pandas, preserves datatypes more reliably, and can be queried directly
by tools such as DuckDB later.

CSV is allowed only as an export/debug format, not the default research store.

## Storage Layout

The default file-backed layout is:

```text
data/
  raw/
    ftmo/
      forex/
        SYMBOL/
          TIMEFRAME/
            SYMBOL_TIMEFRAME.parquet
            manifest.json
```

Generated data is intentionally ignored by git. Code, specs, configs, and tests
are versioned; broker candle history is local research data.

## Dataset Configs

Dataset pulls should be driven by JSON configs in `configs/datasets/`.

The first FOREX config is:

```text
configs/datasets/forex_major_crosses_10y.json
```

It requests:

- `symbol_universe`: `forex_major_cross_pairs`
- `timeframes`: `M30`, `H4`, `D1`, `W1`
- `history_years`: `10`
- `data_root`: `data/raw/ftmo/forex`

Native MT5 H8 is available as a separate add-on pull config:

```text
configs/datasets/forex_major_crosses_10y_h8.json
```

It requests the same 28-symbol universe on `H8` only. Use this config when the
research needs H8 without repulling the original M30/H4/D1/W1 dataset.

If `date_end_utc` is null, the pull resolves the end to the current UTC time.
If `date_start_utc` is null, the start is resolved from `history_years`.

## Bulk Pull And Coverage Workflow

Check exact MT5 symbol availability:

```powershell
.\venv\Scripts\python scripts\check_mt5_symbol_availability.py --config configs\datasets\forex_major_crosses_10y.json --output reports\datasets\forex_major_crosses_10y_availability.json
```

Pull the configured dataset:

```powershell
.\venv\Scripts\python scripts\pull_mt5_dataset.py --config configs\datasets\forex_major_crosses_10y.json --output reports\datasets\forex_major_crosses_10y_pull.json
```

Pull the native MT5 H8 add-on dataset:

```powershell
.\venv\Scripts\python scripts\pull_mt5_dataset.py --config configs\datasets\forex_major_crosses_10y_h8.json --output reports\datasets\forex_major_crosses_10y_h8_pull.json
```

Report availability and consistency:

```powershell
.\venv\Scripts\python scripts\report_dataset_coverage.py --config configs\datasets\forex_major_crosses_10y.json --output reports\datasets\forex_major_crosses_10y_coverage.json
```

Run deeper quality checks:

```powershell
.\venv\Scripts\python scripts\report_data_quality.py --config configs\datasets\forex_major_crosses_10y.json --output-dir reports\datasets\data_quality
```

The pull script validates each symbol/timeframe as it goes. Failures are
reported per dataset instead of silently producing unusable files. The coverage
report marks whether each dataset has data, a manifest, requested start
coverage, requested end coverage, and `backtest_ready`.

Coverage readiness allows normal market-closure boundary gaps. For M30, H4, and
D1 this tolerance is 72 hours; for W1 it is one weekly bar. The report includes
the actual start/end gap in hours so true missing history remains visible.

## Visual Verification

Build a static weekly candlestick webpage from local Parquet data:

```powershell
.\venv\Scripts\python scripts\build_weekly_chart_page.py --config configs\datasets\forex_major_crosses_10y.json --output reports\datasets\forex_weekly_charts.html
```

The page is self-contained and can be opened directly in a browser. It is
intended for fast human inspection of the broker candle history before running
strategy backtests.

## Current Quality Interpretation

The data-quality report should be read as follows:

- `FAIL`: do not use the dataset until failures are fixed.
- `OK`: usable without known warnings.
- `OK_WITH_WARNINGS`: usable, but inspect the warning files before deciding
  which symbols/time ranges to include.

For the current 10-year FTMO FOREX pull, the automated verdict was
`OK_WITH_WARNINGS`:

- no validation/load failures;
- no duplicate timestamps;
- complete W1 candles match M30 aggregation exactly;
- long historical gaps exist in `GBPAUD`, `GBPNZD`, `NZDCAD`, and `NZDCHF`;
- large one-bar moves are present around known high-volatility periods and are
  reported for manual review;
- the latest bar in each dataset is incomplete because the pull ended at the
  live current time.

Initial strategy backtests should either exclude the four gap symbols or treat
their results separately, and should ignore the current incomplete tail bar.

For the native H8 add-on pull, 28/28 pairs were pulled successfully and 28/28
coverage rows were backtest-ready. Its quality verdict was also
`OK_WITH_WARNINGS`, with the same known gap-symbol profile and incomplete
live-tail warning.

## Manifest

Each dataset should have a manifest containing:

- symbol and timeframe;
- source, usually `mt5`;
- requested start/end;
- coverage start/end;
- row count;
- data path;
- storage format;
- pulled timestamp;
- symbol metadata when available;
- account and terminal metadata when available.

## Candle Data Sufficiency

Candle data is enough for bar-close indicators, swing logic, candle patterns,
and conservative OHLC backtests.

Additional MT5 data may be needed for:

- tick-level spread changes;
- bid/ask accurate intrabar testing;
- same-bar stop/target sequencing beyond conservative assumptions;
- partial fills and slippage modelling;
- market depth;
- latency-sensitive execution behavior.

Strategies should state which assumptions they make before PnL backtesting.
