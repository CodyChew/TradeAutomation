# Backtest Engine Specification

This document defines the shared V1 backtest mechanics.

## Inputs

The engine expects a pandas frame with:

- `time_utc`
- `open`
- `high`
- `low`
- `close`

Optional columns:

- `spread_points`
- `point`

Input is sorted by `time_utc` internally and indexes are reset. Trade setup
indexes must refer to this sorted frame.

Large batch experiments can normalize once and then call
`simulate_bracket_trade_on_normalized_frame`. That fast path uses the same
stop-first and cost rules as `simulate_bracket_trade`, but it assumes the caller
has already prepared the frame.

## Trade Setup

Each setup defines:

- side: `long` or `short`
- entry candle index
- entry reference price
- stop price
- target price

The engine validates that:

- long: `stop < entry < target`
- short: `target < entry < stop`

## Stop And Target Simulation

For a long trade:

- stop is hit when `low <= stop`
- target is hit when `high >= target`

For a short trade:

- stop is hit when `high >= stop`
- target is hit when `low <= target`

If both stop and target are hit on the same candle, the engine exits at the
stop. This is the conservative same-bar rule.

If neither is hit before the dataset ends, the trade exits at the final close
with reason `end_of_data`.

## Spread And Costs

Reference prices are strategy prices. Fill prices include costs:

Long:

- entry fill = reference entry + half spread + entry slippage
- exit fill = reference exit - half spread - exit slippage

Short:

- entry fill = reference entry - half spread - entry slippage
- exit fill = reference exit + half spread + exit slippage

Spread is read from the candle `spread_points` column when enabled. If unavailable,
the engine uses `fallback_spread_points`. Point value comes from the candle
`point` column when available, otherwise from `CostConfig.point`.

Round-turn commission can be supplied in points and is subtracted from final R.

## R Metrics

- `reference_r`: R using reference entry and exit prices without costs.
- `fill_r`: R after spread and slippage.
- `commission_r`: round-turn commission converted to R.
- `net_r`: `fill_r - commission_r`.

## Incomplete Latest Candle

Live-ended datasets often contain the currently forming candle. Use
`drop_incomplete_last_bar(frame, timeframe, as_of_time_utc)` before backtesting.

If the latest candle's expected close time is after `as_of_time_utc`, it is
removed.
