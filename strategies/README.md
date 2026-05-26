# Strategy Labs

Strategy labs combine reusable concepts, shared market data, and the shared
backtest engine into complete research candidates.

## Current Labs

- `lp_force_strike_strategy_lab`: active LP + Force Strike strategy research
  plus the current guarded MT5 dry-run/live-send implementation.
- `majority_flush_strategy_lab`: research-only V1 baseline strategy based on
  `concepts/majority_flush_lab`, with tested Python signal/trade logic,
  config-driven 10-year reports, and a dashboard. It has no live execution
  path yet.

## Lab Rules

- Keep strategy-specific signal, experiment, portfolio, and execution-contract
  code inside the strategy lab.
- Import reusable concepts from `concepts/` instead of copying their logic.
- Use `shared/market_data_lab` for MT5 candle schema, dataset loading,
  validation, and fingerprints.
- Use `shared/backtest_engine_lab` for strategy-neutral bracket simulation.
- Put versioned strategy configs in `configs/strategies/`.
- Put generated experiment outputs in `reports/strategies/<strategy_name>/`.
- Edit dashboard builders, then regenerate static HTML. Do not make HTML-only
  dashboard changes unless the HTML is intentionally hand-authored.
- Add new core strategy packages to the strict coverage gate only when the
  strategy has real source code and tests.
- Keep live execution out of new strategy labs until research, dashboard review,
  dry-run design, and deployment boundaries are separately approved.
