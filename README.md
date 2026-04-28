# TradeAutomation

Trading research workspace organized around reusable concepts and future
strategies.

## Structure

- `concepts/`: reusable indicators, signals, and market-structure modules.
- `shared/`: reusable market data, backtest, and research infrastructure.
- `strategies/`: future strategy labs that combine reusable concepts.
- `data/`: local generated datasets, ignored by git.
- `reports/`: local generated research outputs, ignored by git.

## Current Concepts

- `concepts/lp_levels_lab`: Left Precedence support/resistance concept with
  TradingView visualization and Python strategy/backtest logic.
- `concepts/force_strike_pattern_lab`: raw Force Strike pattern concept with
  TradingView visualization and Python strategy/backtest logic.

## Current Strategies

- `strategies/lp_force_strike_strategy_lab`: signal study combining LP level
  traps with raw Force Strike patterns.

## Current Shared Labs

- `shared/market_data_lab`: canonical MT5 candle schema, validation, Parquet
  dataset storage, manifests, and MT5 pull helpers for all future backtests.
- `shared/backtest_engine_lab`: strategy-neutral OHLC bracket-trade simulation
  with spread, slippage, commission, same-bar stop-first handling, and incomplete
  latest-candle removal.

## Dataset Workflow

- `configs/datasets/forex_major_crosses_10y.json`: first FTMO FOREX dataset
  config, covering the 28 major/cross pairs on M30, H4, D1, and W1.
- `scripts/check_mt5_symbol_availability.py`: checks exact MT5 symbol
  availability before a large pull.
- `scripts/pull_mt5_dataset.py`: pulls configured MT5 candles into Parquet
  datasets and writes manifests.
- `scripts/report_dataset_coverage.py`: reports availability, coverage, and
  backtest readiness for configured datasets.
- `scripts/report_data_quality.py`: checks timestamp gaps, duplicate timestamps,
  suspicious bars, and M30-vs-W1 aggregation consistency.
- `scripts/build_weekly_chart_page.py`: builds a static weekly candlestick
  webpage from local Parquet data for visual verification.
