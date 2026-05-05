# TradeAutomation

Trading research workspace organized around reusable concepts and future
strategies.

Start a new handover or Codex session with `SESSION_HANDOFF.md`, then
`strategies/lp_force_strike_strategy_lab/START_HERE.md`, then
`PROJECT_STATE.md`.

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
  traps with raw Force Strike patterns, plus the current MT5 execution and
  Telegram notification contracts.

## Dashboards

Static research dashboards are published from `docs/`:

- Local entry point: `docs/index.html`
- GitHub Pages: `https://codychew.github.io/TradeAutomation/`

The current LP + Force Strike research baseline is V13 mechanics plus V15 risk
buckets plus V22 LP/FS separation: LP3 take-all across H4/H8/H12/D1/W1, with
the selected LP pivot required before the Force Strike mother bar, using the
0.5 signal-candle pullback, full Force Strike structure stop, single 1R target,
and fixed 6-bar pullback wait. V15 is the current risk-sizing read: the first
account-constraint candidate is H4/H8
`0.20%`, H12/D1 `0.30%`, and W1 `0.75%`; the growth contrast is H4/H8
`0.25%`, H12/D1 `0.30%`, and W1 `0.60%`. Open `docs/index.html` or the GitHub
Pages link for the latest dashboard.

The current strategy guide and execution-readiness docs are:

- `SESSION_HANDOFF.md`
- `strategies/lp_force_strike_strategy_lab/START_HERE.md`
- `docs/strategy.html`
- `docs/live_ops.html`
- `docs/lpfs_lightsail_vps_runbook.md`
- `docs/mt5_execution_contract.md`
- `docs/telegram_notifications.md`
- `docs/dry_run_executor.md`

The dry-run path attaches to an already-open MT5 terminal by default, verifies
the expected account, pulls recent closed candles, builds order intents, calls
`order_check`, writes JSONL audit/state files, emits optional best-effort
Telegram reports, and never calls `order_send`.

A guarded live-send path now exists at
`scripts/run_lp_force_strike_live_executor.py`. It can place real MT5 pending
orders only when ignored local config explicitly sets
`live_send.execution_mode="LIVE_SEND"`, `live_send.live_send_enabled=true`, and
`live_send.real_money_ack="I_UNDERSTAND_THIS_SENDS_REAL_ORDERS"`. Treat this
path as real-account capable. Open `docs/live_ops.html` for cycle cadence,
spread behavior, pending-order lifecycle, Telegram alerts, and operator
commands.

Copy `config.local.example.json` to ignored `config.local.json` before running
the executors. Real MT5 passwords, Telegram credentials, broker/account
details, API keys, and live trading config stay local only.

## Testing

Core strategy, concept, market-data, and backtest logic is protected by a
strict branch-coverage gate:

```powershell
.\venv\Scripts\python scripts\run_core_coverage.py
```

See `docs/testing_strategy.md` for the scoped rules and edge-case expectations.

The exact test count changes as LPFS grows. Treat the command output as the
current authority; before changing strategy or execution behavior, rerun the
gate and record the fresh result in the relevant handoff/state file.

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
