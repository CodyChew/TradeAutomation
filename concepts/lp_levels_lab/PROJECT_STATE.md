# LP Levels Lab Project State

Last updated: 2026-04-29 local time after adding H8 and H12 LP lookback
overrides.

## Purpose

LP Levels Lab defines Left Precedence levels as a reusable support/resistance
concept. LP is not a trading strategy by itself. It is intended to be combined
with other entry, filter, risk, and exit concepts in future strategy labs.

## Current State

- TradingView visual indicator: `tradingview/lp_levels.pine`
- TradingView usage notes: `tradingview/README.md`
- Canonical rules/spec: `docs/lp_levels_spec.md`
- Python strategy/backtest module: `src/lp_levels_lab/levels.py`
- Python break-event helper: `lp_break_events_by_bar(...)`

The Pine script is for TradingView chart inspection and publication. It should
not be treated as the live trading source of truth because TradingView candles
can differ from MT5 broker candles.

## Architecture Guidance

Future strategy development should use this order:

1. Use the LP spec to understand the behavior.
2. Use the Python LP module for backtests and MT5 live-trading logic.
3. Keep TradingView scripts visual-only unless explicitly building a visual
   strategy inspection layer.
4. Port the Python-tested behavior into MQL5 only after the strategy rules are
   stable.

An MT5 indicator is optional later. It is not required for Python execution and
not required for a future EA. If an MT5 indicator is created, it should reuse or
mirror the same LP rules rather than becoming a separate source of truth.

## Current LP Defaults

- Pivot strength: `3`
- Resistance breach: wick touch, `high >= level`
- Support breach: wick touch, `low <= level`
- Breached LPs: deleted from active state
- LP break events are exposed before deletion for strategy signal studies.
- Timeframe windows:
  - 30 minute: 5 days
  - 4 hour: 30 days
  - 8 hour: 60 days
  - 12 hour: 180 days
  - Daily or 2 day: 1 year
  - Weekly: 4 years

## Next Best Work

1. Maintain the Python LP module as the strategy/backtest reference.
2. Add future strategies in separate projects/modules that import LP behavior.
3. Avoid copying LP logic into each strategy.
4. Only create an EA/MQL5 port once the combined strategy rules are stable.
