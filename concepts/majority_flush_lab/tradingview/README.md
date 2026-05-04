# Majority Flush TradingView Visual

`majority_flush.pine` is a visual-only Pine v6 indicator for reviewing the
Majority Flush concept on a TradingView chart.

## How To Use

1. Open `majority_flush.pine`.
2. Copy the full script into the TradingView Pine editor.
3. Add it to the current chart.
4. Use the same symbol and timeframe that you want to inspect in Python.

## Defaults

- Pivot strength: `3`
- Maximum congested bar ratio: `0.35`
- Maximum retained moves: `80`
- Midpoint guides: enabled
- Rejected diagnostics: disabled

## What It Shows

- The full flush leg from origin to the forced LP candle.
- LP levels forced by that leg.
- Per-LP midpoint guides when enabled.
- Upside and downside Majority Flush markers.
- Optional midpoint-failed diagnostics.

## Scope

This script is for chart-side review and alerts. Python remains the source of
truth for research because TradingView candles can differ from MT5 broker
candles. This visual excludes execution confirmation, order management, sizing,
messaging, and operational lifecycle logic.
