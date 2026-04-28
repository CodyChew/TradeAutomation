# LP Force Strike Strategy Lab Project State

Last updated: 2026-04-28 local time after creating the first signal-study engine.

## Purpose

This lab studies the combination of active LP level traps and raw Force Strike
patterns. It is a signal study only. It does not contain PnL backtesting,
entries, stops, targets, risk, position sizing, live execution, or a combined
TradingView indicator yet.

## Concept Dependencies

- LP levels: `../../concepts/lp_levels_lab`
- Raw Force Strike pattern: `../../concepts/force_strike_pattern_lab`

Python remains the source of truth for MT5-data strategy development.
TradingView combined visuals should be built after this signal contract is
stable.

Future PnL backtests should load candles through
`../../shared/market_data_lab` so this strategy uses the same broker data and
validation contract as other strategies.

Future trade simulation should use `../../shared/backtest_engine_lab` so entry,
stop, target, spread, slippage, commission, and same-bar assumptions stay
consistent across strategy labs.

## Current Signal Rules

- Bullish force bottom starts when price wick-breaks active support LP.
- Bearish force top starts when price wick-breaks active resistance LP.
- If a candle breaks multiple support LPs, bullish uses the lowest broken
  support.
- If a candle breaks multiple resistance LPs, bearish uses the highest broken
  resistance.
- A valid raw Force Strike signal must occur within 6 bars from the LP break.
- The LP break candle is counted as bar 1.
- Bullish FS execution candle must close at or above the selected support LP.
- Bearish FS execution candle must close at or below the selected resistance LP.
- If multiple LP-break windows match one FS signal, the most recent valid break
  window is used.

## Boundary

This lab intentionally excludes SMA context, ATR, risk, entries, exits, PnL,
and order execution.
