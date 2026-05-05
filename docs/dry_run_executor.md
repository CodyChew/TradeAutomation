# LP + Force Strike MT5 Executors

This document covers the MT5 dry-run executor and the guarded live-send
executor for the current LP + Force Strike baseline.

The current baseline is V13 mechanics plus V15 risk buckets plus V22 hard
LP/FS separation. New dry-run and live-send detections require the selected LP
pivot to be before the Force Strike mother bar by default
(`require_lp_pivot_before_fs_mother=true`). Set that flag `false` only for a
controlled legacy comparison.

The dry-run executor:

- it connects to MT5;
- it pulls recent closed candles;
- it detects LP + Force Strike setups under the hard LP-before-FS baseline;
- it converts tested setups through `execution_contract.py`;
- it calls MT5 `order_check`;
- it writes local audit/state files;
- it may send best-effort Telegram reports;
- it does not send orders.

The live-send executor uses the same setup and execution contract, then calls
MT5 `order_send` only when the explicit live config is enabled. Treat it as
real-account capable.

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
- `dry_run.max_risk_pct_per_trade`
- `dry_run.risk_buckets_pct`
- `dry_run.risk_bucket_scale`
- `dry_run.max_open_risk_pct`
- `dry_run.max_same_symbol_stack`
- `dry_run.max_concurrent_strategy_trades`

For the current FTMO-style MT5 terminal, use:

```json
"broker_timezone": "Europe/Helsinki"
```

This converts the broker's EET/EEST candle and tick times back to canonical
UTC. If this is set incorrectly, signal timestamps, bar-count expiry checks,
and broker backstop timestamps will be shifted.

For low-risk broker testing, use:

```json
"risk_bucket_scale": 0.1
```

This keeps V15's relative risk ladder but sizes each bucket at one tenth:

- `H4/H8`: `0.02%`
- `H12/D1`: `0.03%`
- `W1`: `0.075%`

Broker volume steps and minimum lot rules can make actual risk slightly lower
than the scaled target, or reject very wide setups if rounded volume falls
below broker minimum.

For account-specific analysis, `risk_buckets_pct` can override the base bucket
shape before `risk_bucket_scale` is applied. The IC Markets Raw Spread
validation uses:

```json
"risk_buckets_pct": {
  "H4": 0.25,
  "H8": 0.25,
  "H12": 0.30,
  "D1": 0.30,
  "W1": 0.75
}
```

That is a separate IC analysis recommendation. The current FTMO live/default
bucket remains `H4/H8 0.20%`, `H12/D1 0.30%`, and `W1 0.75%`.

`dry_run.max_risk_pct_per_trade` defaults to `0.75`. It is an execution
guardrail only. Raising it in an ignored account-specific local config lets a
new broker account test higher scaled buckets without changing the strategy
detector or the FTMO/VPS live defaults.

The live-send adapter has a separate `live_send` config block. It is fail-closed
unless all explicit live flags are set:

```json
"live_send": {
  "execution_mode": "LIVE_SEND",
  "live_send_enabled": true,
  "real_money_ack": "I_UNDERSTAND_THIS_SENDS_REAL_ORDERS",
  "risk_buckets_pct": {
    "H4": 0.20,
    "H8": 0.20,
    "H12": 0.30,
    "D1": 0.30,
    "W1": 0.75
  },
  "risk_bucket_scale": 0.05,
  "max_risk_pct_per_trade": 0.75,
  "max_open_risk_pct": 0.65,
  "max_spread_risk_fraction": 0.1
}
```

With `risk_bucket_scale=0.05`, the V15 ladder is reduced to:

- `H4/H8`: `0.01%`
- `H12/D1`: `0.015%`
- `W1`: `0.0375%`

`max_spread_risk_fraction=0.1` means the live executor only sends a pending
order if the current bid/ask spread is no more than 10% of the setup's
entry-to-stop distance. It checks this before `order_check` and again
immediately before `order_send`.

Live-send also checks the MT5 bars between the signal candle and placement
time. If the 50% pullback entry was already touched before the bot could place
the pending order, the setup is rejected as a stale late-start signal. This
keeps live behavior aligned with the V15 assumption that the pending order was
available immediately after the signal candle closed.

Pending order expiry is hybrid:

- Strategy expiry is after `max_entry_wait_bars` actual MT5 bars from the signal
  candle. For the current config this is 6 bars.
- Friday bars after the signal count normally. Weekend time does not count
  because no broker candles form. Monday continues the remaining count.
- The MT5 order also carries a conservative `ORDER_TIME_SPECIFIED` broker
  backstop. This protects against a stopped runner but is not the strategy
  expiry rule.
- If the runner is offline after the 6-bar window but before the broker
  backstop, exact strategy cancellation cannot be guaranteed until the runner is
  online again.

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

Run finite live-send cycles only after the `live_send` block is explicitly
enabled and reviewed:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_live_executor.py --config config.local.json --cycles 3 --sleep-seconds 30
```

For a manual long run that you will stop with Ctrl+C:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_live_executor.py --config config.local.json --cycles 100000000 --sleep-seconds 30
```

This is still a finite-cycle CLI, not a Windows service. MT5 closure, network
loss, machine sleep, terminal crash, or shutdown can still stop operation.

## Phase 2 Production Wrapper

The production wrapper keeps runtime files away from OneDrive and adds a kill
switch, heartbeat, logs, and watchdog restart behavior. It does not change
strategy mechanics or live order logic.

Default production runtime root:

```text
C:\TradeAutomationRuntime
```

Set the kill switch before staging:

```powershell
.\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Reason "staging"
```

Check process, heartbeat, state, journal, and latest log:

```powershell
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 20 -LogLines 40
```

Start the watchdog only after the config and MT5 account are reviewed:

```powershell
.\scripts\run_lpfs_live_forever.ps1 -ConfigPath config.local.json -RuntimeRoot C:\TradeAutomationRuntime -Cycles 100000000 -SleepSeconds 30
```

The live runner also accepts operational path overrides directly:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_live_executor.py --config config.local.json --cycles 1 --runtime-root C:\TradeAutomationRuntime
```

With `--runtime-root C:\TradeAutomationRuntime`, live state and journal resolve
to `C:\TradeAutomationRuntime\data\live`. The default kill switch is
`KILL_SWITCH` beside the live state file, and the default heartbeat is
`lpfs_live_heartbeat.json` beside the live state file.

Before switching runtime roots, copy existing live state and journal if they
exist:

```powershell
New-Item -ItemType Directory -Force -Path C:\TradeAutomationRuntime\data\live
Copy-Item data\live\lpfs_live_state.json C:\TradeAutomationRuntime\data\live\lpfs_live_state.json
Copy-Item data\live\lpfs_live_journal.jsonl C:\TradeAutomationRuntime\data\live\lpfs_live_journal.jsonl
```

If the old configured live state exists and the new runtime-root state is
missing, the runner refuses to start unless
`--allow-empty-runtime-state` is passed. Use that bypass only after confirming
MT5 broker state and intentionally choosing a clean production state.

The kill switch is checked before MT5 initialization, before each live cycle,
and during sleeps between cycles. It stops new cycles; it does not close open
positions or delete broker pending orders by itself.

## Behavior

The runner processes closed candles only. For every configured symbol/timeframe
it fetches recent MT5 rates, normalizes broker-time fields into canonical UTC,
sorts the candles, and drops the newest still-forming candle.

For detected setups, the runner:

- builds a pending setup directly from the latest closed signal candle, without
  requiring the future pullback candle to exist yet;
- builds the V15 candidate setup: 0.5 signal-candle pullback, Force Strike
  structure stop, 1R target, fixed 6-bar wait;
- uses V15 risk buckets from `execution_contract.py`, unless the local config
  provides a per-timeframe `risk_buckets_pct` override;
- applies optional `risk_bucket_scale` to the selected bucket shape before lot
  sizing;
- live-send blocks a setup when current spread is more than
  `max_spread_risk_fraction` of the entry-to-stop distance. This spread-only
  block does not mark the exact signal as processed, so a later cycle can place
  the order if spread improves before entry touch or expiry;
- rejects already-expired pending windows before calling `order_check`;
- rejects duplicate signal keys using local state;
- logs live `bid`, `ask`, and `spread_points`;
- translates ready intents to MT5 `order_check` requests;
- immediately before live `order_send`, refreshes quotes and checks MT5 for an
  exact matching strategy pending order or already-open matching position. A
  match is adopted into local state instead of sending a duplicate;
- records pass/fail retcodes and comments.

The local journal records each lifecycle event. Telegram is intentionally
trader-facing and less noisy: it sends final broker-check results for accepted
intents and setup-rejection alerts, while intermediate signal and intent rows
stay in the journal.

Live-send Telegram cards are compact and trader-oriented:

- `ORDER PLACED`: market, order type/ticket, entry, SL, TP, risk, size,
  signal-close time, placement time, placement lag, spread, bar-count window,
  broker backstop, setup reason, and ref.
- `ORDER ADOPTED`: a matching MT5 order/position was found and tracked locally;
  no new order was sent.
- `ENTERED`: market, position/order IDs, fill, size, risk, SL, TP, open time,
  and ref.
- `TAKE PROFIT` / `STOP LOSS`: market, position ID, exit, PnL, R, entry, size,
  hold time, close time, deal ticket, and ref.
- `TRADE CLOSED`: manual or unknown close using real MT5 PnL/R, without
  mislabeling the exit as SL.
- `SKIPPED` / `REJECTED` / `CANCELLED`: human reason, action taken, key metric,
  and ref.
- `RUNNER STARTED` / `RUNNER STOPPED`: live process status, cadence, cycle
  counts, runtime, state-save result, and SGT start/stop time.

Fill, close, expiry, and cancellation cards reply to the original
`ORDER PLACED` Telegram message when Telegram returns a message ID. Raw broker
comments, retcodes, exact floats, and diagnostics stay in the JSONL journal.

Print a manual performance summary. The default output is metric-only and does
not list exact trades; add `--include-trades` only when the old detailed trade
list is needed:

```powershell
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --days 7
```

Post that same summary to Telegram:

```powershell
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --weeks 4 --post-telegram
```

On the VPS, include the runtime root because production live state and journal
files live outside the repo:

```powershell
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --runtime-root C:\TradeAutomationRuntime --days 7
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --runtime-root C:\TradeAutomationRuntime --weeks 4 --post-telegram
```

The full V15 dry-run universe is the 28 AUD/CAD/CHF/EUR/GBP/JPY/NZD/USD
major/cross pairs across `H4`, `H8`, `H12`, `D1`, and `W1`. That is 140
symbol/timeframe checks per cycle; use a multi-minute sleep interval for
longer observation windows.

Telegram is reporting only. Telegram delivery failure does not change signal
validity, risk sizing, idempotency, or order-check behavior.

## Journal And State

Default local files:

- dry-run journal: `data/live/lpfs_dry_run_journal.jsonl`
- dry-run state: `data/live/lpfs_dry_run_state.json`
- live-send journal: `data/live/lpfs_live_journal.jsonl`
- live-send state: `data/live/lpfs_live_state.json`

Both are ignored because `data/` is local. The journal is append-only JSONL and
redacts sensitive fields before writing. The state files store processed
signal keys, checked signal keys, tracked pending orders, tracked active
positions, notification idempotency keys, and Telegram order-card message IDs.
Live-send state is written atomically and saved immediately after
broker-affecting safety mutations. Restarts reconcile MT5 first, then continue
from the local state.

Do not clear live-send state casually. Clearing it intentionally re-arms
already processed latest-candle signals and can place the same pending orders
again if the setups still pass live checks.

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

- The dry-run runner has no `order_send`.
- The live-send runner can call `order_send` when explicitly enabled.
- Live-send uses MT5 as source of truth for pending orders, positions, and
  close deals.
- The live runner holds a single-runner lock beside the state file. A second
  runner against the same state exits fail-closed before MT5 initialization.
- Live-send skips stale late-start setups when the planned entry already traded
  before the pending order was placed.
- Live-send treats spread-too-wide setups as retryable WAITING events. It can
  retry that same signal on a future cycle until entry touch or expiry.
- Spread is only a placement gate. After an order is pending, spread widening
  does not auto-cancel it and does not currently trigger a dedicated Telegram
  alert.
- Manual deletion of an MT5 pending order does not re-arm the signal. On the
  next reconciliation, the tracked pending order is treated as cancelled/missing
  and the original signal remains processed.
- Live-send tracks order placement/adoption, fill, TP/SL/manual close,
  cancellation, and expiry notifications in local state so restarts do not
  replay alerts. It also stores Telegram order-card message IDs for best-effort
  lifecycle replies.
- The live runner sends and journals start/stop process notifications when
  Telegram is configured. Stop cards are emitted for completed cycles, Ctrl+C,
  and uncaught runtime errors after state save is attempted.
- No MT5 retry policy yet.
- No kill-switch implementation beyond notification event support.
