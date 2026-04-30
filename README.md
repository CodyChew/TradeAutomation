# TradeAutomation

Trading research workspace organized around reusable concepts and future
strategies.

Start a new handover or Codex session with `PROJECT_STATE.md`.

## Structure

- `concepts/`: reusable indicators, signals, and market-structure modules.
- `shared/`: reusable market data, backtest, and research infrastructure.
- `strategies/`: future strategy labs that combine reusable concepts.
- `data/`: local generated datasets, ignored by git.
- `reports/`: local generated research outputs, ignored by git.

`TradeAutomation` is the active Git repo. Preserved local side labs that are
not part of this repo live beside it in `../TradingResearchLabs/`. Keep
generated datasets, reports, virtual environments, and archives local/ignored
unless they are intentionally promoted into tracked project assets.

## Current Concepts

- `concepts/lp_levels_lab`: Left Precedence support/resistance concept with
  TradingView visualization and Python strategy/backtest logic.
- `concepts/force_strike_pattern_lab`: raw Force Strike pattern concept with
  TradingView visualization and Python strategy/backtest logic.

## Current Strategies

- `strategies/lp_force_strike_strategy_lab`: signal study combining LP level
  traps with raw Force Strike patterns.

## Dashboards

Static research dashboards are published from `docs/`:

- Local entry point: `docs/index.html`
- GitHub Pages: `https://codychew.github.io/TradeAutomation/`

The current LP + Force Strike research baseline is V13: LP3 take-all across
H4/H8/H12/D1/W1, using the 0.5 signal-candle pullback, full Force Strike
structure stop, single 1R target, and fixed 6-bar pullback wait. V15 is the
current risk-sizing read: the first account-constraint candidate is H4/H8
`0.20%`, H12/D1 `0.30%`, and W1 `0.75%`; the growth contrast is H4/H8
`0.25%`, H12/D1 `0.30%`, and W1 `0.60%`. Open `docs/index.html` or the GitHub
Pages link for the latest dashboard.

## Testing

Core strategy, concept, market-data, and backtest logic is protected by a
strict branch-coverage gate:

```powershell
.\venv\Scripts\python scripts\run_core_coverage.py
```

See `docs/testing_strategy.md` for the scoped rules and edge-case expectations.

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
