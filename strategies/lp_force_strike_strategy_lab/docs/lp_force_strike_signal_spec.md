# LP Force Strike Signal Specification

This document defines the first LP + raw Force Strike signal-study contract.

## Inputs

The signal detector expects MT5-style OHLC candles with at least:

- `time_utc`
- `open`
- `high`
- `low`
- `close`

Input is sorted by `time_utc` internally.

For backtests, candles should come from `../../shared/market_data_lab` so all
strategies share the same dataset storage, validation, and broker metadata.

## Force Bottom

A bullish force bottom setup starts when a candle wick-breaks one or more active
support LP levels.

If multiple support LPs break on the same candle, the selected LP is the lowest
broken support price.

A bullish raw Force Strike signal is valid when:

- its signal/EXE candle occurs within 6 bars of the selected LP break;
- the LP break candle counts as bar 1;
- the FS signal candle closes at or above the selected LP price.

## Force Top

A bearish force top setup starts when a candle wick-breaks one or more active
resistance LP levels.

If multiple resistance LPs break on the same candle, the selected LP is the
highest broken resistance price.

A bearish raw Force Strike signal is valid when:

- its signal/EXE candle occurs within 6 bars of the selected LP break;
- the LP break candle counts as bar 1;
- the FS signal candle closes at or below the selected LP price.

## Scope

This is a signal study. It does not define trade entry price, stop loss, target,
position sizing, costs, PnL, or execution.
