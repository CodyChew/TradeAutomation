# LP Levels TradingView Indicator

Copy `lp_levels.pine` into TradingView's Pine Editor and add it to a chart.

This is a visual-only indicator for Left Precedence levels. It identifies strict
swing highs and swing lows, then keeps horizontal LP levels active until later
wick action breaches them.

For future development, use `../docs/lp_levels_spec.md` as the canonical LP
rule reference. Python/MT5 strategy work should use
`../src/lp_levels_lab/levels.py` rather than treating this Pine script as the
trading source of truth.

## Defaults

- Pivot strength: `3`, meaning 3 bars to the left and 3 bars to the right.
- Max retained levels: `150`.
- Resistance breach: current candle high reaches or exceeds the LP level.
- Support breach: current candle low reaches or falls below the LP level.
- Breached levels are deleted to keep the chart clean.

## Timeframe Windows

The indicator only keeps LP levels whose pivot candle is inside the active
lookback window:

- 30 minute charts: 5 days.
- 4 hour charts: 30 days.
- Daily or 2 day charts: 1 year.
- Weekly charts: 4 years.

Unsupported chart timeframes use nearest-duration buckets:

- Up to 135 minutes: 5 days.
- Above 135 minutes through 14 hours: 30 days.
- Above 14 hours through 4.5 days: 1 year.
- Above 4.5 days: 4 years.

## Pivot Confirmation

A new LP level appears only after the right-side confirmation bars exist. With
the default strength of 3, a pivot from 3 bars ago is confirmed on the current
bar, and the horizontal line starts from the original pivot candle.

TradingView uses the chart's visible candle stream. Future Python/MT5 execution
logic should apply the same rules to the MT5 candle data being traded.
