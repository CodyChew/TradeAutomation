# MT5 Execution Contract

This contract defines the first live-execution boundary for the current LP +
Force Strike baseline. It is intentionally broker-safe: Phase 1 creates a
validated order intent only. It does not call `order_send`.

Current basis:

- Strategy mechanics: V13 LP3 take-all.
- Trade model: 0.5 signal-candle pullback, Force Strike structure stop, 1R
  target, fixed 6-bar pullback wait.
- Risk buckets: V15 most-efficient practical row.
  - H4/H8: 0.20% account risk.
  - H12/D1: 0.30% account risk.
  - W1: 0.75% account risk.

## Order Intent

A valid setup becomes one pending order intent:

- Long setup: `BUY_LIMIT` only, with entry below current ask.
- Short setup: `SELL_LIMIT` only, with entry above current bid.
- Entry: tested 0.5 signal-candle pullback price.
- Stop loss: full Force Strike structure stop.
- Take profit: 1R target from entry to stop distance.
- Expiration: open of the first candle after the fixed pullback wait.

Because stored candle timestamps are bar opens, a signal at time `T` with
timeframe duration `D` and a 6-bar pullback wait expires at:

```text
T + D * (6 + 1)
```

The signal is known after its candle closes. The next six candles can fill the
pending pullback order. The order expires at the open of the seventh candle
after the signal candle.

## Risk Sizing

The contract sizes lots from account equity and symbol tick metadata:

```text
target_risk_money = equity * risk_pct / 100
risk_per_lot = abs(entry - stop) / trade_tick_size * trade_tick_value
raw_volume = target_risk_money / risk_per_lot
```

Volume is capped by:

- symbol `volume_max`;
- optional executor `max_lots_per_order`;
- symbol `volume_step`, rounded down.

If rounded volume is below `volume_min`, the setup is rejected. If capped volume
is lower than the target volume, the order may risk less than the V15 bucket;
the intent records both target and actual risk percentages.

## Required Rejections

The executor must reject before sending if any of these are true:

- setup symbol does not match broker symbol metadata;
- side is not long or short;
- symbol is not visible or not tradeable;
- account equity is non-positive;
- entry, stop, target, bid, or ask is non-finite;
- bid is greater than or equal to ask;
- spread exceeds the configured cap;
- trade geometry is invalid:
  - long requires `stop < entry < target`;
  - short requires `target < entry < stop`;
- signal key already exists in the local/MT5 reconciliation state;
- same-symbol stack is at or above the configured limit;
- total strategy positions are at or above the configured limit;
- entry is already marketable instead of a pending pullback;
- pending price, stop, or target is inside broker stop/freeze distance;
- timeframe has no configured risk bucket;
- target risk is zero, negative, or above the configured per-trade cap;
- symbol tick value or tick size is invalid;
- volume metadata is invalid;
- rounded volume is below broker minimum;
- open risk plus new actual risk would exceed the configured max open risk.

Equality at the max-open-risk boundary is allowed. Exceeding it is rejected.

## Idempotency

Every order intent carries a deterministic signal key:

```text
lpfs:{SYMBOL}:{TIMEFRAME}:{SIGNAL_INDEX}:{SIDE}:{CANDIDATE_ID}:{FS_SIGNAL_TIME}
```

The future MT5 adapter must reconcile open orders, positions, and the local
journal before sending. If this key already exists, the setup is rejected as a
duplicate.

## Live Status

This contract is not the final live executor. The next phase should build a
dry-run MT5 adapter that:

- pulls broker symbol/account metadata;
- checks current bid/ask and spread;
- runs `order_check` against the generated intent;
- logs whether the order would be accepted or rejected;
- never sends an order unless an explicit live flag is later added.
