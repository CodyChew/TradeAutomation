# Force Strike Pattern Lab Project State

Last updated: 2026-04-28 local time after creating the raw pattern concept.

## Purpose

Force Strike Pattern Lab defines the raw Force Strike bar pattern as a reusable
concept. It is not the full researched Force Strike strategy.

The existing `force_strike_lab` project remains the strategy/research lab with
SMA context, ATR/risk logic, candidate grids, backtests, configs, and reports.
This concept package exists so future strategies can import the raw pattern
without copying strategy-specific code.

## Current State

- Canonical rules/spec: `docs/force_strike_pattern_spec.md`
- Python strategy/backtest module: `src/force_strike_pattern_lab/patterns.py`
- TradingView visual indicator: `tradingview/force_strike_pattern.pine`
- TradingView usage notes: `tradingview/README.md`

Python is the source of truth for future MT5-data strategy work. The
TradingView indicator is for visual inspection on TradingView candles only.

## Current Pattern Defaults

- Minimum formation length: 3 total bars.
- Maximum formation length: 6 total bars.
- First baby candle must be inside or equal to the mother candle range.
- Bullish Force Strike: one-sided break below mother low, then bullish signal
  candle closes back inside the mother range.
- Bearish Force Strike: one-sided break above mother high, then bearish signal
  candle closes back inside the mother range.
- If both sides of the mother range are breached before a valid signal, the
  formation is rejected.

## Boundaries

This concept does not include:

- SMA retracement or trend context.
- ATR calculations.
- Entry, stop, target, position sizing, or execution rules.
- Backtest candidate grids or symbol selection.

Those belong in strategy labs that import this concept.
