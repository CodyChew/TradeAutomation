# Force Strike Pattern Specification

This document is the canonical behavior reference for the raw Force Strike
pattern concept. Python is the intended source of truth for MT5-data backtests
and future live strategy logic. TradingView Pine is a visual reference only.

## Definition

A Force Strike pattern is a short mother-range formation where price makes a
one-sided stop-run outside the mother candle and then closes back inside the
mother range with a directional signal candle.

The raw pattern is a reusable concept, not a complete trading strategy.

## Formation Window

Default formation length is 3 to 6 total bars, counted from mother candle
through signal candle.

- Bar 1 is the mother candle.
- Bar 2 is the first baby candle.
- The signal candle can be any candle from total bar 3 through total bar 6.

## Mother And Baby Requirement

The first baby candle must be inside or equal to the mother candle range:

- `baby_high <= mother_high`
- `baby_low >= mother_low`

If this condition fails, the mother candle cannot produce a Force Strike
pattern.

## Bullish Pattern

A bullish Force Strike requires:

- price breaches below the mother low at least once after the mother candle;
- price does not also breach above the mother high before the valid signal;
- the signal candle closes back inside the mother range;
- the signal candle is bullish by close location.

Bullish close location means the close is in or above the upper third of the
candle range:

- `(close - low) / (high - low) >= 2/3`

Zero-range candles do not qualify as bullish signal candles.

## Bearish Pattern

A bearish Force Strike requires:

- price breaches above the mother high at least once after the mother candle;
- price does not also breach below the mother low before the valid signal;
- the signal candle closes back inside the mother range;
- the signal candle is bearish by close location.

Bearish close location means the close is in or below the lower third of the
candle range:

- `(close - low) / (high - low) <= 1/3`

Zero-range candles do not qualify as bearish signal candles.

## Two-Sided Break Rejection

If both the mother high and mother low are breached before a valid signal, the
formation is rejected.

## Backtesting Rule

Detection must use no future data beyond the signal candle being evaluated.
Later bars must not invalidate an already valid signal.

The Python detector sorts input by `time_utc` and resets indexes internally so
results are deterministic for MT5-data research.

## Strategy Boundary

This spec intentionally excludes SMA retracement, trend filters, ATR, risk,
entries, exits, and execution. Those are strategy-layer decisions.
