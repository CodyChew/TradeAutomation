# TradeAutomation Session Handoff

Last updated: 2026-05-05 SGT after proving Tailscale + SSH remote access to
the LPFS Windows VPS and documenting the environment boundaries.

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
6. `docs/phase2_production_hardening.md` before operating the watchdog, kill
   switch, heartbeat, status command, or Task Scheduler setup.
7. `docs/lpfs_lightsail_vps_runbook.md` before moving the runner to Amazon
   Lightsail.

## AI Agent Continuity Rules

- External Codex memory may be read-only. Treat this repo handoff plus
  `strategies/lp_force_strike_strategy_lab/PROJECT_STATE.md` as the durable
  continuity layer for future AI agents.
- For any LPFS live/runtime, Telegram, MT5 execution, scheduled-task, or VPS
  operations change, do not stop at a local patch. Carry the work to a clear
  completion state: focused tests, full relevant tests when practical, commit,
  push, and explicit VPS deploy/verification steps.
- By default, final answers for LPFS live/runtime work must include the VPS
  operator path: pause with kill switch, verify runner stopped, pull/deploy,
  run focused checks, resume `LPFS_Live`, and verify heartbeat, latest log,
  state, journal, MT5 orders/positions, and Telegram lifecycle cards.
- If the change is docs-only and does not need runtime activation, say that no
  VPS runner restart is required. Still give a minimal VPS pull step if the
  user wants the docs available on the VPS checkout.
- Never instruct future agents to edit VPS live state, journal, MT5 orders, or
  MT5 positions unless the user explicitly approves a separate operator plan.

## Remote VPS Access

Tailscale + OpenSSH is now the preferred remote-maintenance path for read-only
LPFS VPS audits and approved cleanup.

- Local development PC: `cy-desktop`, Tailscale IP `100.105.200.52`.
- Local repo path: `C:\Users\chewc\OneDrive\Desktop\TradeAutomation`.
- Local SSH alias: `lpfs-vps`.
- Local SSH key: `~\.ssh\lpfs_vps_ed25519`.
- VPS host: `EC2AMAZ-ON6FOF2`, Tailscale IP `100.115.34.38`.
- VPS SSH user: `Administrator`.
- VPS repo path: `C:\TradeAutomation`.
- VPS runtime root: `C:\TradeAutomationRuntime`.
- VPS OpenSSH service: `sshd`.
- VPS firewall rule: `OpenSSH-Tailscale-Only`, inbound TCP `22` from
  `100.64.0.0/10`.

Verified remote commands:

```powershell
ssh lpfs-vps hostname
ssh lpfs-vps whoami
ssh lpfs-vps "powershell -NoProfile -ExecutionPolicy Bypass -File C:\TradeAutomation\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 40 -LogLines 80"
ssh lpfs-vps "powershell -NoProfile -Command Set-Location C:\TradeAutomation; git status --short --branch"
```

The remote status packet verified a running heartbeat, the expected Windows
parent/child process shape, `C:\TradeAutomationRuntime` as runtime root, and
`main...origin/main` as the VPS repo state.

Environment boundary rule: local OneDrive is development; VPS
`C:\TradeAutomation` plus `C:\TradeAutomationRuntime` is production. Future
agents should start remote work with `ssh lpfs-vps hostname`, `ssh lpfs-vps
whoami`, VPS `git status`, and the LPFS status packet before drawing
operational conclusions.

## 2026-05-05 Wrap-Up / Git State

- The LPFS order-placement timing telemetry branch
  `lpfs-order-placed-timing-telemetry` has been fast-forward merged into
  `main` locally. After pushing this handoff, future local work should branch
  from `main`.
- The telemetry change is observability-only: Telegram `ORDER PLACED` cards and
  journal rows now expose signal-close time, placement time, and placement lag.
  It did not change LPFS signal selection, MT5 order-send semantics, sizing,
  spread gates, pending expiry, live state schema, or TradingView behavior.
- The VPS may still be checked out on `lpfs-order-placed-timing-telemetry`
  until the operator intentionally switches it back to `main`. Verify the VPS
  branch with `git branch` before assuming which checkout is live.
- Once the pushed `main` is available on the VPS, the preferred production
  baseline is `main`; do not continue new work from the old telemetry branch.
- Safe VPS switch-over path:

```powershell
cd C:\TradeAutomation

.\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Reason "switch VPS to main after LPFS telemetry merge"
Start-Sleep -Seconds 90

git fetch origin
git checkout main
git pull --ff-only origin main

.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_notifications strategies.lp_force_strike_strategy_lab.tests.test_live_executor -v

Remove-Item "C:\TradeAutomationRuntime\data\live\KILL_SWITCH" -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName "LPFS_Live"
Start-Sleep -Seconds 60

.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 40 -LogLines 80
```

## Current Project Focus

The active work is the LP + Force Strike strategy lab. The strategy baseline is
V13 mechanics with V15 risk buckets and V22 LP/FS separation:

- LP3, `take_all`, H4/H8/H12/D1/W1.
- Selected LP pivot must be before the Force Strike mother bar
  (`lp_pivot_index < fs_mother_index`).
- 0.5 signal-candle pullback entry.
- Force Strike structure stop.
- 1R target.
- Fixed 6-bar pullback wait.
- Live pending expiry is bar-counted from actual MT5 candles after the signal
  candle. Weekend time does not count; Friday bars after the signal do count.
  The MT5 order also carries a conservative broker backstop in case the runner
  stops.
- V15 unscaled risk buckets: H4/H8 `0.20%`, H12/D1 `0.30%`, W1 `0.75%`.

The legacy override `require_lp_pivot_before_fs_mother=false` exists only for
reproducible comparison such as V22 control. Do not edit live state or rearm
historical processed/skipped signals for this baseline change.

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
- Bid/ask execution realism:
  `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/execution_realism.py`
  and `scripts/run_lp_force_strike_v16_execution_realism.py`.
- LP-FS proximity research:
  `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/proximity.py`
  and `scripts/run_lp_force_strike_v17_lp_fs_proximity.py`.
- Portfolio and sizing research:
  `portfolio.py`, `stability.py`, V13-V15 scripts, and generated `docs/v13.html`
  through `docs/v17.html`.
- Broker boundary:
  `execution_contract.py` is pure Python and must not import MetaTrader5.
- Live MT5 behavior:
  `live_executor.py` owns live-send checks, order_send, reconciliation, state,
  duplicate/adoption recovery, fill/close handling, and lifecycle events.
- Runner CLI:
  `scripts/run_lp_force_strike_live_executor.py` owns cycle count, sleep,
  single-runner locking, runtime-root override, kill-switch checks, heartbeat,
  process start/stop notifications, final state save, and MT5 shutdown.
- Telegram UX:
  `notifications.py`, `docs/telegram_notifications.md`, and
  `scripts/summarize_lpfs_live_trades.py`.
- Runtime files:
  `data/live/lpfs_live_state.json` and `data/live/lpfs_live_journal.jsonl` are
  ignored local truth for continuity and audit; do not commit them.
- Phase 2 operations plan:
  `docs/phase2_production_hardening.md` captures the local launcher, kill
  switch, watchdog, runtime-folder, heartbeat, Task Scheduler path, and VPS
  readiness checks. `docs/lpfs_lightsail_vps_runbook.md` captures the Amazon
  Lightsail setup.

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

The runner now holds `data/live/lpfs_live_state.json.lock` while active. A
second runner against the same state exits fail-closed before MT5
initialization.

Phase 2 production wrapper commands:

```powershell
.\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Reason "staging"
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 20 -LogLines 40
.\scripts\run_lpfs_live_forever.ps1 -ConfigPath config.local.json -RuntimeRoot C:\TradeAutomationRuntime -Cycles 100000000 -SleepSeconds 30
```

With `--runtime-root C:\TradeAutomationRuntime`, live state, journal,
heartbeat, kill switch, and logs live outside OneDrive. The kill switch stops
new live cycles before MT5 initialization, before each cycle, and during sleeps;
it does not close open positions or delete pending broker orders by itself.
Before switching runtime roots, copy existing live state/journal when they
exist. The runner now fails closed if the old configured state exists but the
new runtime-root state is missing, unless `--allow-empty-runtime-state` is
passed intentionally after broker-state verification.

`save_live_state()` normally uses atomic temp-file replace. On Windows/OneDrive,
the state file can be a reparse-point placeholder and deny `os.replace()`.
The save path now retries and falls back to direct state-file writing on
`PermissionError` so the live runner does not crash during state persistence.

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
- Local live state is persisted immediately after broker-affecting safety
  mutations. It uses atomic replace when Windows allows it, with a OneDrive-safe
  fallback for replace-denied state files.
- Before live `order_send`, the runner checks for an exact matching strategy
  pending order or matching open position and adopts it instead of sending a
  duplicate.
- Pending-to-position fill matching requires broker comment or historical
  order/deal linkage; same volume alone is not enough.
- Manual or unknown broker exits are shown as `LPFS LIVE | TRADE CLOSED`, not
  as stop losses, while still using MT5 PnL/R.
- Telegram is best-effort UX only and must never decide trade validity.

## Notification UX

Telegram now sends compact plain-text trader cards:

- `LPFS LIVE | ORDER PLACED`
- `LPFS LIVE | ORDER ADOPTED`
- `LPFS LIVE | ENTERED`
- `LPFS LIVE | TAKE PROFIT`
- `LPFS LIVE | STOP LOSS`
- `LPFS LIVE | TRADE CLOSED`
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

Manual performance summary, metric-only by default:

```powershell
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --days 7
```

Post summary:

```powershell
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --weeks 4 --post-telegram
```

On the VPS, production journal/state live under `C:\TradeAutomationRuntime`, so
the summary commands must include `--runtime-root`:

```powershell
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --runtime-root C:\TradeAutomationRuntime --days 7
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.local.json --runtime-root C:\TradeAutomationRuntime --weeks 4 --post-telegram
```

## Spread Gate

Current live setting: `max_spread_risk_fraction=0.1`.

A spread-too-wide setup is now a retryable WAITING event, not a permanent
rejection. The live runner does not mark the signal processed for spread-only
blocks, so a future cycle can place the order if spread improves before the
entry touches or the pending window expires. The one old NZDCHF spread skip was
cleaned from local live state explicitly instead of keeping compatibility code.

Default-on market recovery is now the live path after a missed pending touch.
If spread was too wide first and the original entry later traded before the
pending order existed, the runner attempts `MARKET RECOVERY` before final skip.
It sends a `TRADE_ACTION_DEAL` only when current executable price is at least as
good as the original entry (`ask <= entry` for longs, `bid >= entry` for
shorts), spread is still no more than `10%` of actual fill-to-stop risk, the
setup is still inside the 6 actual-bar window, and the original stop/target
path after the first entry touch is clean. Worse-than-entry executable prices
are now retryable `WAITING` events, not permanent skips; the signal key is not
marked processed and no MT5 order is sent while waiting. It keeps the original
structure stop, recalculates TP to 1R from actual fill, and sizes volume from
actual fill-to-stop risk. Rollback is `live_send.market_recovery_mode="disabled"`.

Continuity note for VPS handoff: this change does not rearm historical skipped
signals already present in `lpfs_live_state.json`. Do not edit live state to
recover old skips unless a separate operator plan explicitly approves it.

Implementation verification:

- 2026-05-05 market-recovery retry focused tests:
  `.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_live_executor strategies.lp_force_strike_strategy_lab.tests.test_notifications -v`
  passed: 38 tests.
- `.\venv\Scripts\python -m unittest discover -s strategies\lp_force_strike_strategy_lab\tests`
  passed: 215 tests.
- `.\venv\Scripts\python scripts\run_core_coverage.py` passed with 100.00%
  total coverage.
- 2026-05-04 market-recovery initial verification:
- `.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_live_executor strategies.lp_force_strike_strategy_lab.tests.test_notifications -v`
  passed: 38 tests.
- `.\venv\Scripts\python -m unittest discover -s strategies\lp_force_strike_strategy_lab\tests`
  passed: 186 tests.
- `.\venv\Scripts\python scripts\run_core_coverage.py` passed with 100.00%
  total coverage.

Deployment note: the VPS live runner will not use this recovery behavior until
the VPS repo is updated and `LPFS_Live` is intentionally restarted after config
review. Existing running processes keep the code they started with.

After an order is pending, spread widening does not auto-cancel it and does not
currently trigger a dedicated Telegram alert. Reconciliation keeps the order
until fill, expiry, or broker/user removal.

First Lightsail weekly-open observation: the runner reconciled the two old
LPFS pending orders out of local state because MT5 no longer showed them, then
sent multiple spread-too-wide WAITING cards and one entry-already-touched
SKIPPED card. Treat this as expected conservative live behavior at poor
liquidity, but measure it before tuning because persistent spread blocks during
normal hours would make forward execution diverge from V15.

Next evidence task before changing the spread rule: build a live gate
attribution report from `lpfs_live_journal.jsonl` showing detected setups,
placed orders, spread waits, later placements after spread improves,
entry-touch skips, expiries, affected symbols/timeframes, and whether blocks
cluster around weekly open.

V16 execution-realism result:

- Report: `docs/v16.html`.
- Run folder:
  `reports/strategies/lp_force_strike_experiment_v16_execution_realism/20260501_060205`.
- No-buffer bid/ask model: `12,917` trades versus `13,012` V15 OHLC baseline
  trades, total `1,535.2R` versus `1,512.3R`, PF `1.270` versus `1.265`.
- No-buffer missed only `95` baseline trades, changed `284` exit reasons, and
  still passed V15 practical bucket filters.
- Best raw buffer was `1.5x` signal-candle spread: `1,587.1R`, but it changed
  `722` exit reasons and `493` win/loss signs.
- Decision: bid/ask realism is not a material regression. Keep current live FS
  structure stops unchanged for now. Treat spread buffers as promising follow-up
  research, not an immediate live-rule change.

V17 LP-FS proximity result:

- Report: `docs/v17.html`.
- Run folder:
  `reports/strategies/lp_force_strike_experiment_v17_lp_fs_proximity/20260501_122711`.
- Baseline V15 OHLC: `13,012` trades, `1,512.3R`, PF `1.265`.
- Strict touch only: `12,358` trades, `1,471.3R`, PF `1.272`.
  Quality improved slightly, but it cut `654` trades and gave up about `41R`.
- Farther-than-1ATR setups were a small but positive bucket:
  `110` trades, `17.6R`, PF `1.391`.
- V15 bucket sensitivity still favored current V15: return/DD `48.56`
  versus strict-touch `46.64`.
- Decision: keep current V15 unchanged. Do not require the Force Strike
  structure to touch the selected LP. A future dashboard/live label can show
  LP-FS proximity as setup quality, but it is not a trade filter.
- Staleness note after V22: V17 studied the old signal universe. Rerun it on
  the separated signal baseline before using it for any new live-design
  decision.

V18/V19/V20 TP-near research result:

- V18 report: `docs/v18.html`.
- V19 report: `docs/v19.html`.
- V20 report: `docs/v20.html`.
- V19 run folder:
  `reports/strategies/lp_force_strike_experiment_v19_tp_near_robustness/20260504_194519`.
- V19 keeps the old V15 LPFS strategy baseline and uses the V16 no-buffer
  bid/ask simulator as the control environment.
- V19 close variants now use hard reduced-TP semantics: `close_pct_90` exits at
  `0.9R` once touched and does not get upgraded to full `1R` later.
- V19 full-universe scope: all `H4/H8/H12/D1/W1` LPFS datasets from
  `configs/datasets/forex_major_crosses_10y.json`.
- V19 wrote `16,061` signals, `12,917` control trades, and `245,423` variant
  trade rows.
- V16 no-buffer control: `12,917` trades, `1,535.2R`, PF about `1.270`.
- Hard `close_pct_90`: `12,917` trades, `1,594.0R`, PF about `1.302`, only
  `+58.8R` versus control. It is not a live candidate.
- V19 best live-design candidate: `lock_0p50r_pct_90`, with `12,917` trades,
  `1,878.7R`, PF about `1.356`, and `+343.5R` versus the V16 control.
- `lock_0p50r_pct_90` saved `390` trades from later stops for about `+585.0R`,
  sacrificed `259` later full TPs for about `-129.5R`, and had `308`
  same-bar-conflict rows for about `-112.0R`.
- The V19 decision matrix marks `lock_0p50r_pct_90` as passing raw R, PF,
  return/DD, practical bucket, saved/sacrificed, concentration,
  year-stability, and same-bar gates.
- V19 is still research-only. It did not change live executor behavior, VPS
  runtime, MT5 orders/state, Telegram lifecycle behavior, or TradingView
  indicators.
- V20 run folder:
  `reports/strategies/lp_force_strike_experiment_v20_protection_realism/20260505_043723`.
- V20 keeps the same H4/H8/H12/D1/W1 LPFS signal baseline but replays entry,
  exit, and stop-protection behavior on M30 bid/ask candles.
- V20 intentionally brackets live stop-modification timing. Default stress
  variants do not assume instant stop modification: a `0.9R` touch only locks
  the stop on a later M30 candle, and fast snapbacks are counted as missed. It
  also includes `lock_0p50r_pct_90_m30_same_assumed` as an optimistic same-M30
  upper bound for the live 30-second loop.
- V20 M30 replay control: `12,022` trades, `336.9R`, PF about `1.058`.
- Same-M30 upper bound: `lock_0p50r_pct_90_m30_same_assumed` produced
  `512.9R`, PF about `1.095`, `+176.0R` versus control, `2,561` trigger
  touches, `2,561` assumed activations, `427` saved-from-stop trades,
  `747` sacrificed full-TP trades, and `206` same-bar conflicts. This is not
  direct live evidence because intra-M30 ordering is unknown.
- Conservative later-M30 variants were flat to negative. `m30_next` was
  `-53.0R` versus control. `m30_delay1` was `331.4R`, PF about `1.058`,
  `-5.5R` versus control, `1,043` activations, and `540` too-late rejections.
- V20 is still research-only. It did not change live executor behavior, VPS
  runtime, MT5 orders/state, Telegram lifecycle behavior, or TradingView
  indicators.
- Current TP-near conclusion: do not implement live stop protection from V19
  alone. Real 30-second live behavior is likely between V20's pessimistic
  later-M30 stress and its optimistic same-M30 upper bound. The next valid
  evidence step is M1/tick replay or forward live attribution of `0.9R` touches,
  modification success, and later outcome.
- Staleness note after V22: V18/V19/V20 used the old signal universe. Rerun
  TP-near/protection research on the separated baseline before using those
  dashboards for a live TP/SL design.

A read-only sanity check over 720 recent detected setups showed:

- `5%` gate: 607/720 pass (`84.3%`).
- `10%` gate: 714/720 pass (`99.2%`).
- `15%` gate: 720/720 pass (`100.0%`).

Current recommendation: keep `10%`. Consider an H4-only relaxation to `15%`
only if live evidence shows too many good H4 setups are skipped.

## Phase 2 Readiness

Current stage: controlled live validation on a real MT5 account with low-risk
scaled V15 sizing. The Lightsail VPS production wrapper is installed and
observable, and the operator has started the long-running VPS task. Current
state must be verified from the VPS status packet, MT5, heartbeat, latest log,
and journal rather than from this static handoff.

Phase 2 local production hardening is now implemented without changing strategy
rules:

- `scripts/run_lpfs_live_forever.ps1`: watchdog launcher and timestamped logs.
- `scripts/Set-LpfsKillSwitch.ps1`: creates/clears the emergency stop file.
- `scripts/Get-LpfsLiveStatus.ps1`: pasteable status packet for operator/Codex
  review.
- `scripts/run_lp_force_strike_live_executor.py --runtime-root`: moves
  production state/journal away from OneDrive.
- Runtime-root migration guard: refuses to start from an empty production state
  when the old configured live state exists, unless explicitly bypassed.
- `scripts/run_lp_force_strike_live_executor.py --heartbeat-path`: writes
  process/cycle heartbeat JSON.
- `scripts/run_lp_force_strike_live_executor.py --kill-switch-path`: stops
  before MT5 init, before live cycles, and during sleeps when `KILL_SWITCH`
  exists.

Local rehearsal passed on 2026-05-03:

- `C:\TradeAutomationRuntime\data\live` was staged with copied live state and
  journal.
- `KILL_SWITCH` is active at `C:\TradeAutomationRuntime\data\live\KILL_SWITCH`.
- Read-only MT5 preflight matched the expected account/server in local config.
- MT5 showed two LPFS pending orders and zero LPFS positions, matching staged
  runtime state.
- Direct one-cycle production-runtime run completed with `frames_processed=140`,
  `orders_sent=0`, `setups_rejected=0`, and `setups_blocked=0`.
- Watchdog one-cycle run completed and wrote a timestamped log under
  `C:\TradeAutomationRuntime\data\live\logs`.
- Temporary Task Scheduler smoke run with kill switch active returned result
  `3`, the expected kill-switch exit.
- Temporary Task Scheduler one-cycle live rehearsal returned result `0`.
- Temporary scheduled tasks were removed after rehearsal; no persistent
  auto-start task is installed locally.

The same wrapper has now been moved to Amazon Lightsail using
`docs/lpfs_lightsail_vps_runbook.md`. Keep risk unchanged; the VPS runner was
started only after explicit operator go-live checks.
Treat the Lightsail VPS as the production environment for future live
iteration: repo `C:\TradeAutomation`, runtime `C:\TradeAutomationRuntime`, task
`LPFS_Live`. Local OneDrive remains the development workspace until changes are
explicitly pushed/pulled to the VPS and the task is intentionally restarted.

Lightsail VPS deployment checkpoint passed on 2026-05-04 SGT:

- Instance path: Amazon Lightsail Windows Server 2022 in `ap-southeast-1`,
  2 GB plan, host `EC2AMAZ-ON6FOF2`.
- VPS repo path: `C:\TradeAutomation`.
- VPS runtime root: `C:\TradeAutomationRuntime`.
- MT5 path: `C:\Program Files\FTMO Global Markets MT5 Terminal\terminal64.exe`.
- MT5 Python attach succeeds against `FTMO-Server` and the expected account.
- MT5 API sees the two LPFS strategy pending orders, both with magic `131500`:
  `EURNZD H8 SHORT #257048012` and `GBPJPY H12 SHORT #257048014`.
- MT5 API also showed two non-LPFS open positions with `magic=0`; those are
  outside LPFS management but still consume account margin/risk.
- `config.local.json`, `lpfs_live_state.json`, and `lpfs_live_journal.jsonl`
  were copied to the VPS production paths.
- VPS direct one-cycle run completed with exit code `0`.
- VPS watchdog one-cycle run completed with exit code `0`, wrote a timestamped
  log, and delivered Telegram runner start/stop cards.
- Temporary VPS Task Scheduler smoke test with kill switch active returned
  result `3`, the expected kill-switch exit.
- Temporary VPS Task Scheduler one-cycle live test returned result `0`.
- Telegram initially failed on the VPS with an SSL certificate verification
  error. Commit `3a9cb0a` added `certifi` for Telegram HTTPS; after `git pull`
  and `pip install certifi`, explicit Telegram test delivery and runner
  lifecycle cards succeeded.
- Final at-logon scheduled task `LPFS_Live` is installed and `Ready`. It runs
  `scripts\run_lpfs_live_forever.ps1` with `Cycles 100000000` and
  `SleepSeconds 30`.
- The user cleared the VPS kill switch and started `LPFS_Live`. The latest
  pasted status showed `kill_switch_active=False`, heartbeat `running`,
  `pending_orders=2`, `active_positions=0`, and `processes=2`.
- `processes=2` is expected for one logical Windows venv-launched runner when
  one entry is `C:\TradeAutomation\venv\Scripts\python.exe` and the other is
  its child `C:\Program Files\Python312\python.exe` for the same LPFS command.
  Confirm with `parent_pid`, `exe`, heartbeat freshness, matching config/runtime
  root, and one advancing latest log. Treat it as duplicate only if that
  parent/child shape is absent, configs/runtime roots differ, heartbeat is
  stale, or there are more than two runner entries.

Next VPS decision: keep the VPS runner under observation with status packets,
MT5 open orders/positions, Telegram alerts, and the latest log. Do not run the
local PC runner at the same time.

Operator quick checks live in `docs/lpfs_lightsail_vps_runbook.md` under
`Operator Quick Reference`. The main packet to paste into Codex is:

```powershell
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 30 -LogLines 60
```

Also inspect MT5 open orders/positions on the VPS and compare against the state
file whenever Telegram reports a placement, cancellation, fill, stop, target,
or runner error. Telegram is useful for signal/runner monitoring, but MT5 is
the broker source of truth.

Do not change stops, targets, spread threshold, risk buckets, or pending
expiration as part of Phase 2. The one accepted signal-rule change is V22 hard
LP/FS separation. Corrected V19 marks `lock_0p50r_pct_90` as a research-only
live-design candidate, but no TP-near live behavior has been implemented or
deployed, and that branch is stale until rerun on the V22 signal universe.

## Verification Commands

Targeted tests:

```powershell
.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_notifications strategies.lp_force_strike_strategy_lab.tests.test_live_executor strategies.lp_force_strike_strategy_lab.tests.test_live_trade_summary -v
```

Runner/process notification tests:

```powershell
.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_live_runner -v
```

PowerShell syntax check:

```powershell
powershell -NoProfile -Command "$files = 'scripts\run_lpfs_live_forever.ps1','scripts\Get-LpfsLiveStatus.ps1','scripts\Set-LpfsKillSwitch.ps1'; foreach ($file in $files) { [scriptblock]::Create((Get-Content -Raw $file)) | Out-Null; Write-Host ""syntax ok $file"" }"
```

Full strict gate:

```powershell
.\venv\Scripts\python scripts\run_core_coverage.py
```

Latest full strict result on 2026-05-05 after V22 baseline implementation:

- `274` LPFS unittest discovery cases.
- Core coverage ran all scoped concept/shared/LPFS tests and reported
  `100.00%` line and branch coverage across the measured modules.

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
- `scripts/run_lpfs_live_forever.ps1`
- `scripts/Get-LpfsLiveStatus.ps1`
- `scripts/Set-LpfsKillSwitch.ps1`
- `scripts/summarize_lpfs_live_trades.py`
- `scripts/build_lp_force_strike_live_ops_page.py`
- `scripts/run_lp_force_strike_v17_lp_fs_proximity.py`
- `scripts/run_lp_force_strike_v19_tp_near_robustness.py`
- `docs/phase2_production_hardening.md`
- `docs/lpfs_lightsail_vps_runbook.md`
- `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/proximity.py`
- `strategies/lp_force_strike_strategy_lab/src/lp_force_strike_strategy_lab/tp_near_exit.py`
- `strategies/lp_force_strike_strategy_lab/tests/test_live_executor.py`
- `strategies/lp_force_strike_strategy_lab/tests/test_live_runner.py`
- `strategies/lp_force_strike_strategy_lab/tests/test_live_trade_summary.py`
- `strategies/lp_force_strike_strategy_lab/tests/test_proximity.py`
- `strategies/lp_force_strike_strategy_lab/tests/test_v17_lp_fs_proximity_report.py`
- `strategies/lp_force_strike_strategy_lab/tests/test_v19_tp_near_robustness_report.py`

The tracked code also includes the execution contract, dry-run executor,
dashboard docs, and notification UX changes. Do not revert unrelated user/local
changes or ignored runtime files.
