# LPFS TradingView Indicator

Copy `lp_force_strike.pine` into TradingView's Pine Editor and add it to a
chart.

This is a visual-only indicator for the current LP + Force Strike strategy
baseline. It combines the existing LP level and raw Force Strike visual rules
into one chart-side signal layer.

Python and MT5 remain the source of truth for research, live execution, broker
spread, order placement, market recovery, fills, and lifecycle state. This Pine
script is for visual review and TradingView alerts on the candle stream shown
in TradingView.

## Defaults

- LP pivot strength: `3`.
- Raw Force Strike formation: `3` to `6` total bars.
- LP/FS separation: selected LP pivot bar must be before the Force Strike
  mother bar.
- LP break-to-FS window: `6` bars.
- Entry: `0.5` signal-candle pullback.
- Stop: full Force Strike structure.
- Target: `1R`.
- Confirm on candle close: enabled.

## Visuals

The indicator can draw:

- active LP support/resistance levels;
- selected LPFS signal markers;
- Force Strike structure boxes;
- selected LP segment;
- theoretical entry, stop, and target lines;
- the 6-bar expiry projection.

## Alerts

Two TradingView alert conditions are exposed:

- Bullish LPFS signal.
- Bearish LPFS signal.

These alerts are chart-side notifications only. They do not imply that the MT5
live runner placed an order.

## Chart-Source Boundary

TradingView evaluates the active TradingView chart candles. The Python/MT5
runner evaluates MT5 broker candles. Signals can differ because of feed,
timezone, session, spread, and broker construction differences. Treat this
indicator as visual context; use Python reports and MT5 state for trading
truth. The visual now defaults to the V22 LP/FS separation rule, but
TradingView can still differ from MT5 because the candle feed can differ.
