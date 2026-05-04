# Majority Flush Spec

Majority Flush is an LP-based displacement concept. It describes a full steep
movement leg from a later origin area toward one or more active Left Precedence
levels. The concept produces flush moves and the LPs forced by those moves. It
does not produce trade entries, exits, sizing, or live execution decisions.

## Source Of Truth

The Python module `src/majority_flush_lab/flush.py` is the source of truth for
research and future strategy work. TradingView Pine is visual-only because
TradingView candles can differ from MT5 broker candles.

## Inputs

The detector expects an OHLC frame with:

- `time_utc`
- `open`
- `high`
- `low`
- `close`

Rows are sorted by `time_utc` before detection. LP levels are imported from the
repo-local LP Levels concept using the same timeframe and pivot strength.

## LP Dependency

Majority Flush v1 is LP-based. A level can only be forced when it was active
entering the force candle. The detector therefore checks active LP levels from
the prior processed bar before evaluating the current wick breach.

## Downside Flush

A downside flush:

- starts from a later high/origin area;
- moves sharply downward;
- can force one or more active support LPs below the origin;
- forces a support LP when the wick low reaches or breaches the LP price.

The full flush leg runs from the origin area to the final forced LP in that
same displacement leg.

## Upside Flush

An upside flush:

- starts from a later low/origin area;
- moves sharply upward;
- can force one or more active resistance LPs above the origin;
- forces a resistance LP when the wick high reaches or breaches the LP price.

The full flush leg runs from the origin area to the final forced LP in that
same displacement leg.

## Per-LP 50% Rule

The 50% rule is evaluated separately for each forced LP.

For a downside flush, the midpoint is:

```text
(origin_high + support_lp_price) / 2
```

The flush start must be above that midpoint. This allows a deeper support LP to
pass while a nearer support LP fails, or the reverse in other geometries.

For an upside flush, the midpoint is:

```text
(origin_low + resistance_lp_price) / 2
```

The flush start must be below that midpoint.

## Stagnation And Congestion

A flush leg is invalidated before the next LP is forced if either hard
stagnation condition appears:

- two consecutive candles fail to make directional high/low progress toward the
  LP;
- two consecutive inside bars appear.

Downside progress requires a lower low than the best low already printed in the
leg. Upside progress requires a higher high than the best high already printed
in the leg. An inside bar has `high <= previous high` and `low >= previous low`.

The concept also measures whether a leg is too congested for its size. Each bar
in the leg is counted as congested when it fails to make directional progress,
prints as an inside bar, or closes with a counter-direction body. A forced LP is
accepted only when:

```text
congested_bar_count / duration_bars <= max_constipated_bar_ratio
```

The default maximum congested bar ratio is `0.35`. This lets a long clean leg
tolerate occasional awkward bars while rejecting small flushes where the awkward
bars take up too much of the move.

## No Duration Limit

The concept has no fixed maximum candle duration. A future strategy can add its
own timing filter if research shows that it improves results.

## Exclusions

Majority Flush excludes:

- execution candle confirmation;
- order placement;
- order sizing;
- broker state;
- messaging or operational lifecycle logic.

UR1/DR1 or other future strategy labs decide how to use the concept output.
