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
label, for example `M30`, `H4`, `D1`, or `W1`.

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

Report availability and consistency:

```powershell
.\venv\Scripts\python scripts\report_dataset_coverage.py --config configs\datasets\forex_major_crosses_10y.json --output reports\datasets\forex_major_crosses_10y_coverage.json
```

The pull script validates each symbol/timeframe as it goes. Failures are
reported per dataset instead of silently producing unusable files. The coverage
report marks whether each dataset has data, a manifest, requested start
coverage, requested end coverage, and `backtest_ready`.

Coverage readiness allows normal market-closure boundary gaps. For M30, H4, and
D1 this tolerance is 72 hours; for W1 it is one weekly bar. The report includes
the actual start/end gap in hours so true missing history remains visible.

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
