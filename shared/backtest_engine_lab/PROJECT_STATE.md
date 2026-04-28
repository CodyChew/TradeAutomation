# Backtest Engine Lab Project State

Last updated: 2026-04-28 after creating the first shared OHLC bracket-trade
engine.

## Purpose

This shared lab owns strategy-neutral backtest mechanics for TradeAutomation.
Strategies should generate trade setups; this engine simulates those setups on
OHLC candles.

## Current Scope

- Normalize and validate OHLC backtest frames.
- Simulate long/short bracket trades with fixed entry, stop, and target prices.
- Use OHLC high/low checks for stop and target touches.
- Apply a conservative same-bar rule: if stop and target are both touched in the
  same candle, the stop wins.
- Model candle-level spread, slippage, and round-turn commission in points.
- Provide a helper to drop the latest incomplete candle for live-ended datasets.

## Boundary

This lab does not detect signals, choose entries, choose stops/targets, size
positions, optimize parameters, or connect to MT5. Those belong in strategy labs
or execution modules.

## Data Assumptions

OHLC candles cannot reveal intrabar sequence. When both stop and target are hit
inside one candle, this engine assumes the worse result. That prevents optimistic
backtests when using candle data.

Spread is based on candle-level `spread_points` when available. For tighter or
latency-sensitive models, promising results should later be retested with tick
data.
