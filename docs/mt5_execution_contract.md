# MT5 Execution Contract

This contract defines the broker boundary for the current LP + Force Strike
baseline. The pure contract still only creates a validated order intent. The
live executor translates that intent to MT5 `order_check` and, only when
explicit live-send config is enabled, `order_send`.

Current basis:

- Strategy mechanics: V13 LP3 take-all.
- Trade model: 0.5 signal-candle pullback, Force Strike structure stop, 1R
  target, fixed 6-bar pullback wait.
- Risk buckets: V15 most-efficient practical row.
  - H4/H8: 0.20% account risk.
  - H12/D1: 0.30% account risk.
  - W1: 0.75% account risk.

The dry-run and live-send executors can scale this ladder for broker testing with
`risk_bucket_scale`. A scale of `0.1` keeps the same V15 proportions while
sizing `H4/H8` at `0.02%`, `H12/D1` at `0.03%`, and `W1` at `0.075%`.
The current real-account live-test default is `0.05`, sizing `H4/H8` at
`0.01%`, `H12/D1` at `0.015%`, and `W1` at `0.0375%`.

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

The contract can size lots from account equity and symbol tick metadata:

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

The live executor overrides the tick-value formula with broker-calculated risk:

```text
risk_per_lot = abs(mt5.order_calc_profit(side, symbol, 1.0, entry, stop))
```

That keeps sizing in the account currency according to the connected broker's
current symbol contract. The final volume is still floored to broker
`volume_step`, capped, and rejected if below `volume_min`.

## Required Rejections

The executor must reject before sending if any of these are true:

- setup symbol does not match broker symbol metadata;
- side is not long or short;
- symbol is not visible or not tradeable;
- account equity is non-positive;
- entry, stop, target, bid, or ask is non-finite;
- bid is greater than or equal to ask;
- spread exceeds the configured cap or live dynamic spread gate;
- trade geometry is invalid:
  - long requires `stop < entry < target`;
  - short requires `target < entry < stop`;
- signal key already exists in the local/MT5 reconciliation state;
- same-symbol stack is at or above the configured limit;
- total strategy positions are at or above the configured limit;
- entry is already marketable instead of a pending pullback;
- live-send is starting late and MT5 bars since the signal candle show the
  planned pullback entry was already touched before the order could be placed;
- pending price, stop, or target is inside broker stop/freeze distance;
- timeframe has no configured risk bucket;
- target risk is zero, negative, or above the configured per-trade cap;
- symbol tick value or tick size is invalid;
- volume metadata is invalid;
- rounded volume is below broker minimum;
- open risk plus new actual risk would exceed the configured max open risk.
- the pending order expiration time is already at or before the current broker
  market time.

Equality at the max-open-risk boundary is allowed. Exceeding it is rejected.

## Idempotency

Every order intent carries a deterministic signal key:

```text
lpfs:{SYMBOL}:{TIMEFRAME}:{SIGNAL_INDEX}:{SIDE}:{CANDIDATE_ID}:{FS_SIGNAL_TIME}
```

The MT5 adapters use this key for idempotency. The live-send adapter reconciles
open orders, positions, historical orders, and local state before scanning for
new signals. If this key already exists in processed/tracked state, the setup is
skipped as already processed.

Manual deletion of a pending order in MT5 does not create a new signal. If the
local live state still tracks the order, the next reconciliation emits a
cancelled/missing lifecycle alert and removes the pending item from local
tracking. The original signal key remains processed so the bot does not place a
duplicate order unless state is intentionally reset or a future re-arm command
is added.

## Live Status

The dry-run MT5 adapter builds around this contract and:

- pulls broker symbol/account metadata;
- pulls recent closed candles;
- normalizes MT5 broker-time fields to UTC;
- checks current bid/ask and spread;
- runs `order_check` against the generated intent;
- logs whether the order would be accepted or rejected;
- emits Telegram notification events for signal, rejection, order-check, and
  executor-error states;
- never sends an order.

The live-send adapter lives at:

```text
strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/live_executor.py
scripts/run_lp_force_strike_live_executor.py
```

It adds:

- explicit fail-closed config: `live_send.execution_mode="LIVE_SEND"`,
  `live_send.live_send_enabled=true`, and
  `live_send.real_money_ack="I_UNDERSTAND_THIS_SENDS_REAL_ORDERS"`;
- MT5 account login/server validation before any cycle;
- dynamic spread gate: current spread must be no more than
  `live_send.max_spread_risk_fraction` of entry-to-stop distance, default
  `0.10`;
- current live-send implementation treats a spread-gate failure as a retryable
  block. It sends/logs a WAITING event once, does not mark the signal processed,
  and can place the order on a later cycle if spread improves before entry
  touch or expiry;
- late-start missed-entry guard: after the signal candle, if the current or
  later MT5 bars already traded through the planned limit entry, the setup is
  rejected instead of placing a stale order;
- `order_check` before every live send;
- a final quote refresh and second dynamic spread gate immediately before
  `order_send`;
- spread is a placement gate only. After a pending order is placed, spread
  widening does not auto-cancel it and does not currently emit a dedicated
  Telegram alert;
- broker-side SL, TP, expiration, magic number, and compact comment on every
  pending order;
- restart-safe local state for processed signals, pending orders, active
  positions, sent notification keys, and last seen close deal;
- reconciliation through MT5 open orders, open positions, historical orders,
  and deal history.

Telegram is reporting only. It must not decide whether a trade is valid.

Operational setup for the adapter is documented in `docs/dry_run_executor.md`.
