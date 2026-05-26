# Majority Flush Strategy Spec

Last updated: 2026-05-22 for the V1 baseline and M30/all-timeframe comparison.

## Purpose

This strategy lab tests whether the reusable Majority Flush concept has a
tradeable baseline edge before optimizing entries, stops, targets, filters, or
portfolio rules.

The strategy is research-only. It has no MT5 dry-run executor, live-send path,
MQL5 EA, VPS scheduled task, runtime state, journal, or broker order lifecycle.

## Concept Dependency

Majority Flush detection comes from:

```text
concepts/majority_flush_lab/src/majority_flush_lab/flush.py
```

The strategy does not copy concept rules. It imports detected
`MajorityFlushMove` objects and decides whether a final forced LP becomes a
trade signal.

## V1 Fixed Signal Rule

Inputs:

- OHLC candles with `time_utc`, `open`, `high`, `low`, and `close`.
- Timeframe supplied by the experiment runner.
- Majority Flush pivot strength `3`.
- Execution window of `6` bars.

For each accepted Majority Flush move:

- Use only the final forced LP in the move.
- For an upside flush, the final LP is the highest forced resistance reached by
  the flush. This creates a short candidate.
- For a downside flush, the final LP is the lowest forced support reached by
  the flush. This creates a long candidate.
- The candle that first forces the selected LP is bar `1`.
- Search bars `1` through `6`, inclusive, for the first valid execution bar.

Short execution confirmation:

- The move is an upside flush into a resistance LP.
- The execution bar closes in the lower third of its own range.
- The execution bar close is strictly below the LP price.

Long execution confirmation:

- The move is a downside flush into a support LP.
- The execution bar closes in the upper third of its own range.
- The execution bar close is strictly above the LP price.

Equality at the LP is not confirmation in V1. The close must be beyond the LP.

## V1 Baseline Trade Model

The first backtest intentionally uses one simple model:

- Entry: next candle open after the execution bar.
- Stop:
  - short: highest high from the flush origin through the execution bar;
  - long: lowest low from the flush origin through the execution bar.
- Target: fixed `1R`.
- Costs: candle spread enabled by the shared backtest engine.
- Latest incomplete candle: dropped by the runner when the dataset manifest has
  a requested end timestamp.

No portfolio selection, risk sizing, timeframe selection, symbol filtering, ATR
filtering, trailing stop, partial exit, or live execution behavior is part of
V1.

## First Research Question

V1 answers:

```text
Does the raw Majority Flush execution signal show enough baseline quality over
the 10-year MT5 dataset to justify optimized follow-up tests?
```

Metrics to review:

- signal count;
- trade count;
- total net R;
- average net R;
- win rate;
- profit factor;
- closed-trade drawdown;
- skipped setup reasons;
- symbol and timeframe concentration.

## Executed V1 Lanes

The original baseline config is:

```text
configs/strategies/majority_flush_strategy_baseline_v1.json
```

It tests `H4`, `H8`, `H12`, `D1`, and `W1`.

The M30/all-timeframe comparison config is:

```text
configs/strategies/majority_flush_strategy_all_timeframes_v1.json
```

It tests `M30`, `H4`, `H8`, `H12`, `D1`, and `W1` using the same fixed V1
rules. This lane exists only to compare timeframes; it does not change the
signal, entry, stop, target, cost, or incomplete-bar rules.

## Future Iteration Candidates

Only test these after V1 is understood:

- entry models: execution-bar pullback, flush-leg pullback, LP retest;
- stop models: execution-bar stop, ATR-capped structure stop;
- target models: `1R`, `1.5R`, `2R`, partial exits;
- execution window variants: `4`, `6`, `8` bars;
- pivot strength variants: `2`, `3`, `4`;
- timeframe and symbol selection;
- cost and gap-symbol sensitivity;
- portfolio and account-risk rules.

## LPFS Separation

This strategy must remain separate from LPFS live execution. Do not reuse or
modify LPFS live configs, magic numbers, broker comments, runtime roots, state
files, journals, Telegram channels, scheduled tasks, or MQL5 EA files.
