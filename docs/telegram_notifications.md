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
- `LIVE`: intended only after demo execution is stable and explicitly enabled.

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
- `order_rejected`
- `pending_expired`
- `pending_cancelled`
- `position_opened`
- `stop_loss_hit`
- `take_profit_hit`
- `executor_error`
- `kill_switch_activated`

The first dry-run MT5 adapter should emit at least:

- `signal_detected`
- `setup_rejected`
- `order_intent_created`
- `order_check_passed`
- `order_check_failed`
- `executor_error`
- `kill_switch_activated`

Live/demo order management later adds:

- `order_sent`
- `order_rejected`
- `pending_expired`
- `pending_cancelled`
- `position_opened`
- `stop_loss_hit`
- `take_profit_hit`

## Message Content

Messages are plain text and concise. A normal order-intent message should show:

- mode;
- event type;
- severity;
- symbol, timeframe, and side;
- signal key;
- order type;
- entry;
- stop loss;
- take profit;
- volume;
- target and actual risk percentage;
- pending expiration time.

Rejection messages should show:

- rejection reason;
- checks completed before rejection;
- concise detail from the execution contract.

## Safety Rules

- Telegram messages are best-effort reporting only.
- Telegram delivery failure must not crash the strategy loop unless the future
  runner explicitly chooses fail-closed behavior.
- Repeated signals must still be blocked by execution idempotency, not by
  Telegram state.
- Notification text must not include account passwords, bot tokens, MT5 login
  passwords, or local filesystem secrets.
- The future MT5 adapter should log the rendered message even when Telegram
  delivery is disabled or fails.

## Current Implementation

The current code provides:

- `NotificationEvent`: validated event contract.
- `format_notification_message`: deterministic plain-text renderer.
- `notification_from_execution_decision`: converts MT5 execution-contract
  decisions into alert events.
- `TelegramConfig.from_env`: loads `TELEGRAM_BOT_TOKEN` and
  `TELEGRAM_CHAT_ID`.
- `TelegramNotifier`: sends through an injectable HTTP client, or returns a
  dry-run delivery without making a network call.

Tests use fake clients only. They do not contact Telegram.
