# Telegram Notification Contract

Telegram is an observability layer for the LP + Force Strike executor. It must
report decisions made by tested strategy and execution-contract code. It must
not decide whether to trade.

## Credentials

Credentials stay outside the repo:

```powershell
$env:TELEGRAM_BOT_TOKEN = "<bot token>"
$env:TELEGRAM_CHAT_ID = "<chat id>"
```

No bot token, chat ID, or sent-message payload should be committed.

## Modes

Every message includes an execution mode:

- `DRY_RUN`: no Telegram HTTP request is sent by default; the message is
  rendered and returned for logs.
- `DEMO_LIVE`: intended for a demo account after the dry-run adapter is proven.
- `LIVE`: real-order capable and intended only after explicit local enablement.

The notifier defaults to dry-run behavior. Live Telegram delivery must be
enabled explicitly by configuration.

## Event Types

The contract supports these event names:

- `signal_detected`
- `setup_rejected`
- `order_intent_created`
- `order_check_passed`
- `order_check_failed`
- `order_sent`
- `market_recovery_sent`
- `order_adopted`
- `order_rejected`
- `pending_expired`
- `pending_cancelled`
- `position_opened`
- `stop_loss_hit`
- `take_profit_hit`
- `position_closed`
- `runner_started`
- `runner_stopped`
- `kill_switch_activated`
- `executor_error`
- `kill_switch_activated`

The dry-run MT5 adapter emits at least:

- `signal_detected`
- `setup_rejected`
- `order_intent_created`
- `order_check_passed`
- `order_check_failed`
- `executor_error`
- `kill_switch_activated`

The current dry-run implementation writes signal, order intent, setup rejection,
order-check pass/fail, and local warning events through the audit journal.
Telegram is intentionally less noisy: it sends only final broker-check results
for accepted intents and setup-rejection alerts. Signal and intermediate intent
details remain in the local journal.

Live order management adds:

- `order_sent`
- `market_recovery_sent`
- `order_adopted`
- `order_rejected`
- `pending_expired`
- `pending_cancelled`
- `position_opened`
- `stop_loss_hit`
- `take_profit_hit`
- `position_closed`
- `runner_started`
- `runner_stopped`

## Message Content

Messages are plain text and trader-facing. There is no Markdown parse mode and
no emoji dependency. A normal dry-run broker-check message
should show:

- symbol, timeframe, and side;
- a clear dry-run status: no order sent and not filled;
- whether MT5 would accept or reject the pending request;
- retcode/comment when available;
- signal ID for traceability.

The local journal keeps fuller order-intent detail:

- pending order type;
- pending entry;
- stop loss;
- take profit;
- volume;
- target and actual risk percentage;
- strategy expiry mode and bar count;
- broker backstop expiration time.

Rejection messages should show:

- rejection reason;
- checks completed before rejection;
- concise detail from the execution contract.

Live lifecycle messages are compact trader cards. Raw retcodes, broker
comments, exact floats, and diagnostic fields stay in the JSONL journal.

- `order_sent`: `LPFS LIVE | ORDER PLACED`, market, order type/ticket,
  signal-close time, order-placement time, placement lag, entry/SL/TP,
  actual/target risk, lot size, spread as percent of risk, SGT strategy bar
  window, broker backstop, setup reason, and signal ref.
- `market_recovery_sent`: `LPFS LIVE | MARKET RECOVERY`, market, position/deal
  ID, original pending entry, actual executable fill, original structure SL,
  recalculated 1R TP, actual/target risk, lot size, spread as percent of
  actual fill-to-stop risk, first-touch high/low/time, and signal ref.
- `order_adopted`: `LPFS LIVE | ORDER ADOPTED`, matching broker order/position
  details, recovery note, and signal ref. It means no duplicate `order_send`
  was made.
- `position_opened`: `LPFS LIVE | ENTERED`, market, position/order IDs, fill,
  size, risk, broker SL/TP, SGT open time, and signal ref.
- `take_profit_hit` / `stop_loss_hit`: `LPFS LIVE | TAKE PROFIT` or
  `LPFS LIVE | STOP LOSS`, market, position ID, exit, PnL, R, entry, size,
  hold time, SGT close time, deal ticket, and signal ref.
- `position_closed`: `LPFS LIVE | TRADE CLOSED` for manual or unknown broker
  close reasons, still using MT5 PnL/R and deal details.
- retryable `setup_rejected`: `WAITING`, human reason, key metric, retry
  action, and signal ref. This includes pending-order spread waits,
  market-recovery spread waits, and market-recovery price waits where current
  executable price is worse than the original entry.
- other `setup_rejected` / `order_check_failed` / `order_rejected`: `SKIPPED`
  or `REJECTED`, human reason, key metric such as touched time, action taken,
  and signal ref.
- `pending_expired` / `pending_cancelled`: `CANCELLED`, human reason, order
  ticket, action taken, and signal ref. If MT5 rejects the cancellation, the
  card says cancellation failed and the local pending item is kept for retry.
- `runner_started` / `runner_stopped`: process heartbeat cards showing the
  sleep-after-cycle setting, cycle counts, runtime, state-save status, and SGT
  start/stop time.
- `kill_switch_activated`: `LPFS LIVE | KILL SWITCH`, human reason, stage, and
  action stating that no new live cycles will run.

Live fill, close, expiry, and cancellation cards reply to the original
`ORDER PLACED` or `ORDER ADOPTED` Telegram message when Telegram returns a
`message_id`. Missing message IDs or Telegram failures do not affect trading or
reconciliation.

Manual performance summaries can be printed or posted. The default output is
metric-only and does not list exact trades; add `--include-trades` only for the
older per-trade detail list.

```powershell
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --days 7
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --weeks 4 --post-telegram
```

On the VPS, live state and journal files are under `C:\TradeAutomationRuntime`,
so include the runtime root:

```powershell
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --runtime-root C:\TradeAutomationRuntime --days 7
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --runtime-root C:\TradeAutomationRuntime --weeks 4 --post-telegram
```

The summary pairs enriched `notification_event` rows from
`data/live/lpfs_live_journal.jsonl`; older sparse rows may be skipped.

## Safety Rules

- Telegram messages are best-effort reporting only.
- Telegram delivery failure must not crash the strategy loop unless the future
  runner explicitly chooses fail-closed behavior.
- Repeated signals must still be blocked by execution idempotency, not by
  Telegram state.
- Telegram reply threading is UX only. MT5 broker state and local idempotency
  state remain the source of truth.
- Notification text must not include account passwords, bot tokens, MT5 login
  passwords, or local filesystem secrets.
- The MT5 adapters log the rendered message and serialized notification event
  even when Telegram delivery is disabled or fails.

## Current Implementation

The current code provides:

- `NotificationEvent`: validated event contract.
- `format_notification_message`: deterministic plain-text renderer for dry-run
  and live lifecycle alerts.
- `notification_from_execution_decision`: converts MT5 execution-contract
  decisions into alert events.
- `TelegramConfig.from_env`: loads `TELEGRAM_BOT_TOKEN` and
  `TELEGRAM_CHAT_ID`.
- `NotificationDelivery`: stores Telegram `message_id` and
  `reply_to_message_id` when available.
- `TelegramNotifier`: sends through an injectable HTTP client, supports
  `reply_to_message_id`, or returns a dry-run delivery without making a
  network call.
- `live_trade_summary.py`: builds manual recent-trade summaries from the live
  JSONL journal.

Tests use fake clients only. They do not contact Telegram.
