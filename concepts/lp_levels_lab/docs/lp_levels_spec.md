# LP Levels Specification

This document is the canonical behavior reference for Left Precedence (LP)
levels in this workspace. TradingView Pine is the visual reference. Python is
the intended source of truth for MT5-data backtesting and future live trading.

## Definition

LP levels are active, unbreached horizontal support/resistance levels derived
from strict local market extremes.

- Resistance LP: a confirmed strict swing high.
- Support LP: a confirmed strict swing low.

LP levels are a reusable indicator/concept, not a complete trading strategy.

## Pivot Geometry

Default pivot strength is `3`.

For a pivot strength of `N`:

- A swing high at bar `i` is valid only when `high[i]` is strictly greater than
  every high from `i - N` through `i - 1` and from `i + 1` through `i + N`.
- A swing low at bar `i` is valid only when `low[i]` is strictly lower than
  every low from `i - N` through `i - 1` and from `i + 1` through `i + N`.
- Equality does not qualify. The pivot must be distinct.

## Confirmation Delay

A pivot is not known until the right-side confirmation bars exist.

For pivot strength `N`, a pivot at bar `i` becomes available at bar `i + N`.
Backtests and live logic must not use that LP level before its confirmation
bar.

## Timeframe Lookback Windows

Only levels whose pivot candle remains inside the active rolling lookback
window are kept.

- 30 minute charts: 5 days.
- 4 hour charts: 30 days.
- Daily or 2 day charts: 1 year.
- Weekly charts: 4 years.

Unsupported timeframes use nearest-duration buckets:

- Up to 135 minutes: 5 days.
- Above 135 minutes through 14 hours: 30 days.
- Above 14 hours through 4.5 days: 1 year.
- Above 4.5 days: 4 years.

## Breach And Deletion

Breaches use wick touch.

- Resistance LP breaches when a later candle high reaches or exceeds the level:
  `high >= level`.
- Support LP breaches when a later candle low reaches or falls below the level:
  `low <= level`.

Breached LPs are deleted from active state immediately. They are not retained as
inactive levels in the Python strategy engine.

Python strategies that need trap timing can use the break-event helper to read
which active LP levels were breached on each bar before those levels are removed
from active state.

## Backtesting Rule

LP state must be calculated bar by bar with no future leakage.

At each historical bar `T`, active LP levels are only those that:

- have already been confirmed by bar `T`;
- have a pivot time inside the rolling lookback window at `T`;
- have not been breached by wick touch after becoming active.

Do not precompute future pivots and attach them backward to earlier bars.

## Data Source Boundary

TradingView evaluates TradingView candles. Python/MT5 logic should evaluate MT5
broker candles. Both can be internally correct even if individual LP levels
differ because of feed, broker, timezone, or session construction differences.
