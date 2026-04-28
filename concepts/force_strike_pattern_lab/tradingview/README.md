# Force Strike Pattern TradingView Indicator

Copy `force_strike_pattern.pine` into TradingView's Pine Editor and add it to a
chart.

This is a visual-only indicator for the raw Force Strike pattern. It does not
include SMA retracement, trend filters, ATR, entries, exits, risk, or strategy
backtesting logic.

For future development, use `../docs/force_strike_pattern_spec.md` as the
canonical rule reference. Python/MT5 strategy work should use
`../src/force_strike_pattern_lab/patterns.py` rather than treating this Pine
script as the trading source of truth.

## Defaults

- Minimum formation length: 3 total bars.
- Maximum formation length: 6 total bars.
- First baby candle must be inside or equal to the mother candle range.
- Bullish pattern: one-sided break below mother low, then bullish signal candle
  closes back inside mother range.
- Bearish pattern: one-sided break above mother high, then bearish signal
  candle closes back inside mother range.
- Two-sided breaks are rejected.

TradingView uses the chart's visible candle stream. Future Python/MT5 logic
should apply the same raw pattern rules to the MT5 candle data being traded.
