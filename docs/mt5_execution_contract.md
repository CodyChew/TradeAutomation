# MT5 Execution Contract

This contract defines the broker boundary for the current LP + Force Strike
baseline. The pure contract still only creates a validated order intent. The
live executor translates that intent to MT5 `order_check` and, only when
explicit live-send config is enabled, `order_send`.

Current basis:

- Strategy mechanics: V13 LP3 take-all.
- Signal-quality guard: V22 hard LP/FS separation, requiring the selected LP
  pivot index to be before the Force Strike mother index.
- Trade model: 0.5 signal-candle pullback, Force Strike structure stop, 1R
  target, fixed 6-bar pullback wait.
- Risk buckets: V15 most-efficient practical row.
  - H4/H8: 0.20% account risk.
  - H12/D1: 0.30% account risk.
  - W1: 0.75% account risk.

The dry-run and live-send executors can override this base ladder with
`risk_buckets_pct`, then scale the selected ladder with `risk_bucket_scale`. A
scale of `0.1` on the FTMO-style V15 ladder sizes `H4/H8` at `0.02%`,
`H12/D1` at `0.03%`, and `W1` at `0.075%`. The current real-account live-test
default is `0.05`, sizing the FTMO-style V15 ladder at `H4/H8 0.01%`,
`H12/D1 0.015%`, and `W1 0.0375%`.

Account-specific bucket overrides are analysis decisions, not signal-rule
changes. The ICMarketsSC-MT5-2 validation currently recommends
`H4/H8 0.25%`, `H12/D1 0.30%`, and `W1 0.75%` for growth-practical analysis,
but that remains dry-run/order-check only until a separate live-send plan is
approved.

`max_risk_pct_per_trade` is an execution guardrail, not a backtest signal rule.
It defaults to `0.75`, matching the highest current V15 W1 bucket. Separate
ignored account configs may raise it for validation, for example to allow an
IC scale-2 dry-run where W1 targets `1.50%`. Keep the FTMO/VPS live config at
its approved cap unless a separate live-send decision explicitly changes it.

`strategy_magic` and `order_comment_prefix` are account-bound identity fields.
The FTMO runner keeps magic `131500` and prefix `LPFS`. The IC Markets runner
uses magic `231500` and prefix `LPFSIC` so broker orders, local state, journal
rows, and Telegram cards cannot be confused across accounts.

The current detector default is `require_lp_pivot_before_fs_mother=true`. This
means new setups are emitted only when `lp_pivot_index < fs_mother_index`.
LP==mother and LP-inside-FS candidates are treated as invalid/self-referential
and are not sent. The legacy override `false` exists only for reproducible
research comparison. Deploying this rule does not edit existing pending orders,
active positions, historical journal rows, or processed signal keys.

## Order Intent

A valid setup becomes one pending order intent:

- Long setup: `BUY_LIMIT` only, with entry below current ask.
- Short setup: `SELL_LIMIT` only, with entry above current bid.
- Entry: tested 0.5 signal-candle pullback price.
- Stop loss: full Force Strike structure stop.
- Take profit: 1R target from entry to stop distance.
- Strategy expiry: after the fixed pullback wait, counted from actual MT5 bar
  opens after the signal candle.
- Broker backstop: a conservative time-based emergency expiration used only if
  the runner or MT5 terminal stops before it can enforce the bar-count rule.

Backtests fill only during the next six actual candles after the signal candle.
Live reconciliation now follows the same rule. If the signal is early Friday,
later Friday bars count. If the signal is on the final candle before the
weekend, no weekend time counts because no broker candles form. Monday continues
the remaining bar count; it does not restart the count.

The legacy continuous-calendar boundary for a signal at time `T` with timeframe
duration `D` and a 6-bar pullback wait is still useful for backstop sizing:

```text
T + D * (6 + 1)
```

The MT5 pending request uses `ORDER_TIME_SPECIFIED` with extra padding after
that boundary: 10 calendar days for H4/H8/H12, 14 days for D1, and 21 days for
W1. This broker timestamp is not the strategy expiry; it is a fail-safe.

## Default Live Market Recovery

The historical baseline assumes the pending pullback order exists after the
signal candle and can fill during the next six actual bars. Live trading can be
more conservative when spread is too wide at first check: the runner may wait,
then later discover the entry traded before the pending order could be placed.

Current live default:

- `live_send.market_recovery_mode="better_than_entry_only"`;
- rollback flag: `live_send.market_recovery_mode="disabled"`;
- `live_send.market_recovery_deviation_points=0` by default, so market recovery
  does not silently accept worse slippage.

If the planned entry was touched before placement, the live executor now
attempts market recovery before final skip. It sends `TRADE_ACTION_DEAL` only
when all of these are true:

- long recovery uses current broker `ask` and requires `ask <= original_entry`;
- short recovery uses current broker `bid` and requires `bid >= original_entry`;
- the executable price is still on the valid side of the original Force Strike
  structure stop;
- the setup is still inside the 6 actual MT5-bar entry window;
- the original structure stop has not traded after the signal;
- the original 1R target has not traded after the signal;
- spread is no more than `10%` of actual fill-to-stop risk.

Market recovery keeps the original structure stop, recalculates TP to 1R from
the actual market fill, and sizes volume from the actual fill-to-stop risk so
the configured account-risk bucket remains aligned. This is a live execution
enhancement only; it does not change signal generation or historical baseline
reports.

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
- bid is greater than ask;
- spread exceeds the configured cap or live dynamic spread gate;
- trade geometry is invalid:
  - long requires `stop < entry < target`;
  - short requires `target < entry < stop`;
- signal key already exists in the local/MT5 reconciliation state;
- same-symbol stack is at or above the configured limit;
- total strategy positions are at or above the configured limit;
- entry is already marketable instead of a pending pullback for the normal
  pending-order path;
- live-send is starting late and MT5 bars since the signal candle show the
  planned pullback entry was already touched before the order could be placed,
  unless default market recovery passes every better-than-entry recovery gate;
- pending price, stop, or target is inside broker stop/freeze distance;
- timeframe has no configured risk bucket;
- target risk is zero, negative, or above the configured per-trade cap;
- symbol tick value or tick size is invalid;
- volume metadata is invalid;
- rounded volume is below broker minimum;
- open risk plus new actual risk would exceed the configured max open risk.
- the conservative broker backstop expiration is already at or before the
  current broker market time.

Raw-spread zero quotes are valid at this contract boundary: `bid == ask` is a
zero-spread quote, not an invalid market. It still flows through the configured
spread gate, MT5 `order_check`, and the final pre-send quote refresh. Only an
inverted quote, where bid is greater than ask, is rejected locally as
`invalid_market`.

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

Live-send also checks MT5 one final time immediately before `order_send`. If an
exact matching strategy pending order already exists, or a matching open
position exists under the same strategy magic/comment, the runner adopts that
broker item into local state and does not send a duplicate order.

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
- a single-runner lock beside the live state file. A second runner exits
  fail-closed before MT5 initialization;
- operational path overrides for Phase 2 production use:
  `--runtime-root`, `--kill-switch-path`, and `--heartbeat-path`;
- a file-based kill switch that is checked before MT5 initialization, before
  each live cycle, and during sleeps between cycles. It stops new live cycles
  but does not close positions or delete pending broker orders by itself;
- heartbeat JSON updates at startup, every completed cycle, and shutdown, so
  operators can inspect process status without treating Telegram as broker
  truth;
- dynamic spread gate: current spread must be no more than
  `live_send.max_spread_risk_fraction` of entry-to-stop distance, default
  `0.10`;
- current live-send implementation treats a spread-gate failure as a retryable
  block. It sends/logs a WAITING event once, does not mark the signal processed,
  and can place the order on a later cycle if spread improves before entry
  touch or expiry;
- broker-session `Market closed` responses during pending-order or
  market-recovery `order_check`/`order_send` are retryable WAITING blocks. The
  signal is not marked processed, and true broker rejections remain permanent;
- live pending-order fills are broker Bid/Ask events, not chart-only candle
  touches. A `BUY_LIMIT` fills only when Ask is at or below the entry; a
  `SELL_LIMIT` fills only when Bid is at or above the entry. Most MT5 candle
  charts show Bid OHLC, so a buy-limit chart low below entry is not proof that
  the order should already be filled;
- late-start missed-entry recovery: after the signal candle, if the current or
  later MT5 bars already traded through the planned limit entry, the runner
  attempts default-on better-than-entry market recovery. If current executable
  price is temporarily worse than the original entry, the runner records a
  WAITING event, does not mark the signal processed, and retries while the
  actual 6-bar window remains open;
- market recovery uses `TRADE_ACTION_DEAL`, current ask for longs or current
  bid for shorts, the original structure stop, a recalculated 1R TP from the
  actual fill, actual fill-to-stop risk sizing, and
  `live_send.market_recovery_deviation_points` for slippage control;
- market recovery does not hardcode pending-order filling behavior. It selects
  broker-supported market `type_filling` modes from symbol metadata, retries
  another fill mode if MT5 returns invalid/unsupported filling on
  `order_check`, and sends with the exact request that passed `order_check`;
- market recovery path validation is evaluated from the first actual entry
  touch onward. Stop/target events after that touch make late recovery
  ineligible; pre-touch target/stop movement does not by itself permanently
  skip the setup because the backtest pending order would not have filled yet;
- actual-bar expiry guard: after the signal candle, only real MT5 bars count
  toward `max_entry_wait_bars`. Weekend and holiday gaps do not consume the
  window. Once the first bar after the allowed wait appears, a still-pending
  order is cancelled on the next reconciliation cycle;
- `order_check` before every live send;
- a final quote refresh and second dynamic spread gate immediately before
  `order_send`;
- exact broker duplicate/adoption guard immediately before `order_send`;
- spread is a placement gate only. After a pending order is placed, spread
  widening does not auto-cancel it and does not currently emit a dedicated
  Telegram alert;
- broker market-closed is a placement-session gate only. It does not change
  already placed pending orders, manual deletion behavior, or close
  classification;
- weekly-open spread behavior is expected to be more conservative than the
  historical V15/V22 baseline. If spread or not-better recovery WAITING cards
  cluster only around poor-liquidity windows, keep the current `0.10` gate. If
  they persist during normal liquid hours, measure the divergence with a live
  gate attribution report before changing the live rule;
- V16 closed the first bid/ask execution-realism gap. The no-buffer bid/ask
  model did not materially weaken the V15 baseline, so current live stop
  placement remains unchanged. Spread buffers are still research-only until a
  buffer-specific decision is made;
- V17 tested whether the Force Strike structure must touch the broken LP.
  Strict-touch and ATR-gap filters did not beat the current V15 row, so live
  order intent does not require FS structure touch;
- V22 accepted hard LP/FS separation. The selected LP pivot must be before the
  Force Strike mother bar for all new signals unless a legacy comparison config
  explicitly disables `require_lp_pivot_before_fs_mother`;
- broker-side SL, TP, expiration, magic number, and compact comment on every
  pending order;
- atomically written, restart-safe local state for processed signals, pending
  orders, active positions, sent notification keys, and last seen close deal.
  Broker-affecting state is persisted immediately after safety mutations;
- reconciliation through MT5 open orders, open positions, historical orders,
  and deal history. Pending-to-position matching requires broker comment or
  historical order/deal linkage, not volume alone;
- truthful close classification: TP and SL stay specific, while manual or
  ambiguous exits are reported as `TRADE CLOSED` with MT5 PnL/R;
- best-effort runner start/stop process notifications so the operator can see
  when the program starts, exits by completed cycles or Ctrl+C, or stops after
  an uncaught runtime error.

2026-05-09 IC EURCHF H12 case:

- IC live `EURCHF H12` `BUY_LIMIT` ticket `4420525163` had entry `0.91447`.
  It was placed promptly after the signal, but did not fill until
  `2026-05-08 18:50:01 UTC` / `2026-05-09 02:50 SGT`.
- The MT5 chart screenshot showed earlier candle lows below the entry zone,
  which is consistent with Bid lows crossing the level. The broker fill
  condition for a buy limit was Ask at or below `0.91447`.
- A read-only IC tick query showed the first available tick with
  `ask <= 0.91447` at the later live fill time, with approximately
  `bid=0.91442` and `ask=0.91447`. This supports expected broker fill
  mechanics, not a live runner bug.
- Backtest implication: candle-only fills can mark a buy entry earlier than
  live if they use Bid low without the exact intrabar Ask path. The V16-style
  candle-spread approximation helps, but it is not the same as true tick
  Bid/Ask replay.
- Data feasibility check: IC MT5 currently exposes 10-year M1/H4/D1 candles
  and non-zero M1 spread fields for all 28 LPFS FX pairs, but true tick
  Bid/Ask history returned only from around `2025-01` in the local terminal.
  A full 10-year true tick replay is therefore not currently feasible from
  this broker terminal; recent/live tick audits are feasible.

Telegram, heartbeat, logs, and the status command are reporting only. They must
not decide whether a trade is valid. MT5 broker state, local state, and journal
rows remain the operational truth.

Operational setup for the adapter is documented in `docs/dry_run_executor.md`.
