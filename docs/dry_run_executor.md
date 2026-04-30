# LP + Force Strike Dry-Run Executor

This is the first MT5 execution adapter for the current LP + Force Strike
baseline. It is intentionally dry-run only:

- it connects to MT5;
- it pulls recent closed candles;
- it detects LP + Force Strike setups;
- it converts tested setups through `execution_contract.py`;
- it calls MT5 `order_check`;
- it writes local audit/state files;
- it may send best-effort Telegram reports;
- it does not send orders.

`order_send` is intentionally deferred until the dry-run journal, broker
metadata, spread behavior, and Telegram reporting are reviewed.

## Local Config

Copy the example file and keep the copy ignored:

```powershell
Copy-Item config.local.example.json config.local.json
```

`config.local.json` is ignored by git. Do not commit real credentials, broker
account details, Telegram tokens, API keys, or live trading config.

Recommended MT5 mode:

- `mt5.use_existing_terminal_session=true`
- open MT5 manually and log in first;
- set `mt5.expected_login`;
- set `mt5.expected_server`;
- leave `mt5.password` blank.

This avoids storing an MT5 password locally while still preventing accidental
connection to the wrong account.

Required local MT5 fields in existing-session mode:

- `mt5.expected_login`
- `mt5.expected_server`

Optional explicit-login mode:

- set `mt5.use_existing_terminal_session=false`;
- set `mt5.login`;
- set `mt5.password`;
- set `mt5.server`.

Optional local fields:

- `mt5.path`
- `telegram.enabled`
- `telegram.bot_token`
- `telegram.chat_id`
- `telegram.dry_run`
- `dry_run.symbols`
- `dry_run.timeframes`
- `dry_run.broker_timezone`
- `dry_run.history_bars`
- `dry_run.max_spread_points`
- `dry_run.max_lots_per_order`
- `dry_run.max_open_risk_pct`
- `dry_run.max_same_symbol_stack`
- `dry_run.max_concurrent_strategy_trades`

Environment fallback is supported for:

```powershell
$env:MT5_USE_EXISTING_TERMINAL_SESSION = "true"
$env:MT5_EXPECTED_LOGIN = "your_demo_login"
$env:MT5_EXPECTED_SERVER = "your_demo_server"
$env:MT5_PATH = "optional_terminal_path"
$env:TELEGRAM_BOT_TOKEN = "optional_bot_token"
$env:TELEGRAM_CHAT_ID = "optional_chat_id"
```

Explicit-login mode also supports:

```powershell
$env:MT5_LOGIN = "your_demo_login"
$env:MT5_PASSWORD = "your_demo_password"
$env:MT5_SERVER = "your_demo_server"
```

Missing MT5 account-check values or explicit-login credentials fail before
order checks with a local setup message. Missing Telegram credentials do not
stop the dry-run; Telegram is disabled and the journal records the warning.

## Run

Run one dry-run cycle:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_dry_run_executor.py --config config.local.json
```

Run multiple finite cycles:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_dry_run_executor.py --config config.local.json --cycles 3 --sleep-seconds 30
```

## Behavior

The runner processes closed candles only. For every configured symbol/timeframe
it fetches recent MT5 rates, normalizes broker-time fields into canonical UTC,
sorts the candles, and drops the newest still-forming candle.

For detected setups, the runner:

- builds the V15 candidate setup: 0.5 signal-candle pullback, Force Strike
  structure stop, 1R target, fixed 6-bar wait;
- uses V15 risk buckets from `execution_contract.py`;
- rejects duplicate signal keys using local state;
- logs live `bid`, `ask`, and `spread_points`;
- translates ready intents to MT5 `order_check` requests;
- records pass/fail retcodes and comments.

Telegram is reporting only. Telegram delivery failure does not change signal
validity, risk sizing, idempotency, or order-check behavior.

## Journal And State

Default local files:

- journal: `data/live/lpfs_dry_run_journal.jsonl`
- state: `data/live/lpfs_dry_run_state.json`

Both are ignored because `data/` is local. The journal is append-only JSONL and
redacts sensitive fields before writing. The state file stores processed and
order-checked signal keys so restarts do not repeat the same order check.

Sensitive values must never appear in these files:

- Telegram bot token;
- Telegram chat ID;
- MT5 login;
- MT5 password;
- MT5 server;
- broker/account details;
- API keys;
- live trading config.

## Current Limits

- No `order_send`.
- No production live-account execution.
- No position/fill reconciliation yet.
- No pending-order cancellation or expiry management yet.
- No MT5 retry policy yet.
- No kill-switch implementation beyond notification event support.
