# TradeAutomation Session Handoff

Last updated: 2026-05-01 SGT after the LPFS active-window LP selector patch,
V9-to-V15 revalidation, live-send runner start/stop notifications, and
handoff cleanup.

This is the canonical context-transfer file for the next AI/Codex session.
Use it as a map, then verify live MT5 state from MT5, the ignored live state
file, and the JSONL journal before making operational decisions.

## Read First

1. `SESSION_HANDOFF.md` for this latest operational snapshot.
2. `PROJECT_STATE.md` for workspace context.
3. `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md` for LPFS detail.
4. `docs/mt5_execution_contract.md`, `docs/telegram_notifications.md`, and
   `docs/dry_run_executor.md` before touching execution code.
5. `docs/live_ops.html` for dashboard-level live-run behavior and scenarios.

## Current Project Focus

The active work is the LP + Force Strike strategy lab. The strategy baseline is
V13 mechanics with V15 risk buckets:

- LP3, `take_all`, H4/H8/H12/D1/W1.
- 0.5 signal-candle pullback entry.
- Force Strike structure stop.
- 1R target.
- Fixed 6-bar pullback wait.
- V15 unscaled risk buckets: H4/H8 `0.20%`, H12/D1 `0.30%`, W1 `0.75%`.

Live broker testing scales that ladder with `live_send.risk_bucket_scale=0.05`,
so H4/H8 are `0.01%`, H12/D1 are `0.015%`, and W1 is `0.0375%`.

## Architecture Map

- Signal concepts:
  `concepts/lp_levels_lab/src/lp_levels_lab/levels.py` and
  `concepts/force_strike_pattern_lab/src/force_strike_pattern_lab/patterns.py`.
- Strategy signal selector:
  `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/signals.py`.
- Research/backtest model:
  `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/experiment.py`
  plus `shared/backtest_engine_lab`.
- Portfolio and sizing research:
  `portfolio.py`, `stability.py`, V13-V15 scripts, and generated `docs/v13.html`
  through `docs/v15.html`.
- Broker boundary:
  `execution_contract.py` is pure Python and must not import MetaTrader5.
- Live MT5 behavior:
  `live_executor.py` owns live-send checks, order_send, reconciliation, state,
  fill/close handling, and lifecycle events.
- Runner CLI:
  `scripts/run_lp_force_strike_live_executor.py` owns cycle count, sleep,
  process start/stop notifications, final state save, and MT5 shutdown.
- Telegram UX:
  `notifications.py`, `docs/telegram_notifications.md`, and
  `scripts/summarize_lpfs_live_trades.py`.
- Runtime files:
  `data/live/lpfs_live_state.json` and `data/live/lpfs_live_journal.jsonl` are
  ignored local truth for continuity and audit; do not commit them.

## Safety Status

The user confirmed the connected MT5 account is real. Treat live-send as a
real-order path.

Do not run this casually:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_live_executor.py --config config.local.json --cycles 1
```

The runner is a finite-cycle CLI, not an OS service. For a manual long run, use
a very large cycle count and stop with Ctrl+C:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_live_executor.py --config config.local.json --cycles 100000000 --sleep-seconds 30
```

Do not clear `data/live/lpfs_live_state.json` unless the user explicitly wants
to re-arm already processed latest-candle signals. Clearing live state can
place duplicate pending orders if the same setup still passes all checks.

## Last Verified Live-Test Snapshot

This is a historical snapshot from the fresh 2026-05-01 live test, not a
guarantee of the broker's current state. Always inspect MT5, state, and journal
before acting.

Before the fresh test cycle, old local live files were archived:

```text
data/live/lpfs_live_state.json.bak_20260501_034805
data/live/lpfs_live_journal.jsonl.bak_20260501_034805
```

Fresh live-send cycle result:

- Frames processed: `140`.
- Orders sent: `2`.
- Setups rejected: `2`.
- Tracked strategy positions at that time: none.

Last verified strategy pending orders in MT5 and local state:

```text
EURNZD H8 SHORT | SELL_LIMIT #257048012
Entry 1.99622 | SL 2.00515 | TP 1.98728
Size 0.01 | Expires 2026-05-02 21:00 SGT
Telegram order card message_id 127
```

```text
GBPJPY H12 SHORT | SELL_LIMIT #257048014
Entry 215.802 | SL 216.591 | TP 215.013
Size 0.02 | Expires 2026-05-03 17:00 SGT
Telegram order card message_id 128
```

Skipped in that fresh cycle:

- `AUDJPY D1 SHORT`: entry was already touched before placement.
- `NZDCHF H4 LONG`: spread was too wide, about `11.5%` of risk versus the
  `10.0%` gate.

## Execution Behavior To Preserve

- The live runner processes closed candles only.
- It only acts when the LPFS signal candle is the latest closed candle.
- LPFS selector rule: if multiple LP-break windows match one FS signal,
  bullish uses the lowest valid support LP and bearish uses the highest valid
  resistance LP. Equal-price ties use the latest valid break.
- Signal idempotency key:
  `lpfs:{SYMBOL}:{TIMEFRAME}:{SIGNAL_INDEX}:{SIDE}:{CANDIDATE_ID}:{FS_SIGNAL_TIME}`.
- A new signal candle creates a new key.
- Manual deletion of a pending MT5 order does not re-arm the signal. If local
  state still tracks the order, the next reconciliation should emit a
  cancelled/missing lifecycle alert and remove it from pending tracking.
- MT5 broker state is the source of truth for orders, positions, and deals.
- Telegram is best-effort UX only and must never decide trade validity.

## Notification UX

Telegram now sends compact plain-text trader cards:

- `LPFS LIVE | ORDER PLACED`
- `LPFS LIVE | ENTERED`
- `LPFS LIVE | TAKE PROFIT`
- `LPFS LIVE | STOP LOSS`
- `LPFS LIVE | WAITING`
- `LPFS LIVE | SKIPPED`
- `LPFS LIVE | REJECTED`
- `LPFS LIVE | CANCELLED`
- `LPFS LIVE | RUNNER STARTED`
- `LPFS LIVE | RUNNER STOPPED`

Fill, close, expiry, and cancellation alerts reply to the original order-card
message when Telegram returns a `message_id`. Raw broker comments, retcodes,
exact floats, and diagnostics stay in JSONL.

Runner start/stop alerts are process heartbeat cards. They show cadence,
requested/completed cycles, runtime, state-save status, and SGT start/stop
time. They are best-effort Telegram UX and are also journaled.

Manual summary:

```powershell
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --limit 5
```

Post summary:

```powershell
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --limit 5 --post-telegram
```

## Spread Gate

Current live setting: `max_spread_risk_fraction=0.1`.

A spread-too-wide setup is now a retryable WAITING event, not a permanent
rejection. The live runner does not mark the signal processed for spread-only
blocks, so a future cycle can place the order if spread improves before the
entry touches or the pending window expires. The one old NZDCHF spread skip was
cleaned from local live state explicitly instead of keeping compatibility code.

After an order is pending, spread widening does not auto-cancel it and does not
currently trigger a dedicated Telegram alert. Reconciliation keeps the order
until fill, expiry, or broker/user removal.

A read-only sanity check over 720 recent detected setups showed:

- `5%` gate: 607/720 pass (`84.3%`).
- `10%` gate: 714/720 pass (`99.2%`).
- `15%` gate: 720/720 pass (`100.0%`).

Current recommendation: keep `10%`. Consider an H4-only relaxation to `15%`
only if live evidence shows too many good H4 setups are skipped.

## Verification Commands

Targeted tests:

```powershell
.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_notifications strategies.lp_force_strike_strategy_lab.tests.test_live_executor strategies.lp_force_strike_strategy_lab.tests.test_live_trade_summary -v
```

Runner/process notification tests:

```powershell
.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_live_runner -v
```

Full strict gate:

```powershell
.\venv\Scripts\python scripts\run_core_coverage.py
```

Latest full strict result on 2026-05-01:

- `211` unittest cases across core labs.
- `100.00%` line and branch coverage.

Latest selector revalidation on 2026-05-01:

- Patched LPFS from latest matching LP break to most-extreme valid LP across the
  active trap window.
- Regenerated V9 into
  `reports/strategies/lp_force_strike_experiment_v9_lp_pivot_strength/20260501_032404`.
- Old/new V9 `signals.csv` and `trades.csv` were byte-identical, so V10-V15
  metrics stayed unchanged.
- V15 efficient row remains H4/H8 `0.20%`, H12/D1 `0.30%`, W1 `0.75%`.

## Current Code Additions

- `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/live_executor.py`
- `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/live_trade_summary.py`
- `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/notifications.py`
- `scripts/run_lp_force_strike_live_executor.py`
- `scripts/summarize_lpfs_live_trades.py`
- `scripts/build_lp_force_strike_live_ops_page.py`
- `strategies/lp_force_strike_strategy_lab/tests/test_live_executor.py`
- `strategies/lp_force_strike_strategy_lab/tests/test_live_runner.py`
- `strategies/lp_force_strike_strategy_lab/tests/test_live_trade_summary.py`

The tracked code also includes the execution contract, dry-run executor,
dashboard docs, and notification UX changes. Do not revert unrelated user/local
changes or ignored runtime files.
