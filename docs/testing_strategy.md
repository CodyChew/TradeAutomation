# Core Strategy Testing Strategy

This repo treats Python core logic as the source of truth for LP + Force Strike
research. Dashboards and generated reports explain results, but the strict
coverage gate protects reusable strategy rules, market-data normalization, and
portfolio/risk calculations.

## Strict Coverage Scope

Run the core gate from the repo root:

```powershell
.\venv\Scripts\python scripts\run_core_coverage.py
```

The gate covers:

- `concepts/lp_levels_lab/src`
- `concepts/force_strike_pattern_lab/src`
- `shared/backtest_engine_lab/src`
- `shared/market_data_lab/src`
- `strategies/lp_force_strike_strategy_lab/src`

Generated dashboards, local data, local reports, and one-off research runners
are outside the strict 100% core gate. If a runner grows reusable behavior, move
that behavior into a core package and cover it there.

## Trading Rule Invariants

- LP levels are sorted by candle time internally, confirmed only after the
  configured pivot strength, expired by timeframe lookback, and removed after a
  wick-touch breach.
- LP + Force Strike signals require a wick break, a raw Force Strike signal
  inside the configured break window, and a close back beyond the broken LP
  level. Bullish closes may equal support; bearish closes may equal resistance.
- When multiple support break windows are valid, the bullish trap uses the
  lowest support. When multiple resistance break windows are valid, the bearish
  trap uses the highest resistance. Equal-price ties use the latest break.
- The current research baseline keeps the fixed 6-bar pullback wait. The V7/V8
  1R-cancel wait is a tested alternative, not the default.
- Pullback entries are invalid when the signal candle range is zero or inverted,
  when no next candle exists, when entry is not reached during the wait, or when
  stop distance is not positive.
- Bracket simulation is conservative on same-bar conflicts: if stop and target
  are both touched in the same candle, the stop is recorded first.
- Realized drawdown measures closed-trade equity only. Risk-reserved drawdown
  subtracts open reserved risk while trades are active and is the safer account
  stress metric.

## Edge-Case Expectations

Tests should make boundary behavior explicit for exact LP closes, expired
windows, same-timestamp portfolio ordering, max-open-risk equality, malformed
OHLC data, missing ATR, invalid stops, same-bar trade conflicts, and empty
result frames. A change to these rules should update the test first so the
research assumptions remain visible.
