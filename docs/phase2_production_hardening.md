# LPFS Phase 2 Production Hardening

Last updated: 2026-05-06 after adding boot-level Telegram startup alerts.

This is the operations layer for LP + Force Strike live execution. It does not
change signal rules, risk buckets, spread gates, stop/target geometry, order
lifecycle logic, or pending-order expiry.

## Current Stage

LPFS is in controlled live validation on a real MT5 account with low-risk
scaled V15 sizing.

The live strategy remains:

- V13 mechanics with V15 efficient risk buckets.
- LP3, `take_all`, H4/H8/H12/D1/W1.
- 0.5 signal-candle pullback entry.
- Force Strike structure stop.
- 1R target.
- Fixed 6-bar pullback wait.
- Strategy expiry after 6 actual MT5 bars from the signal candle.
- Conservative broker expiration only as an emergency backstop.
- Live test scale: `live_send.risk_bucket_scale=0.05`.

## What Phase 2 Adds

Implemented operational controls:

- `scripts/run_lpfs_live_forever.ps1`: production watchdog launcher.
- `scripts/Get-LpfsLiveStatus.ps1`: local/VPS status snapshot for operator and
  Codex review.
- `scripts/Set-LpfsKillSwitch.ps1`: file-based emergency stop helper.
- `scripts/run_lp_force_strike_live_executor.py --runtime-root`: runtime path
  override so state, journal, logs, heartbeat, and kill switch can live outside
  OneDrive.
- `scripts/run_lp_force_strike_live_executor.py --kill-switch-path`: kill
  switch checked before MT5 initialization, before each live cycle, and during
  sleeps between cycles.
- `scripts/run_lp_force_strike_live_executor.py --heartbeat-path`: JSON
  heartbeat updated at start, every completed cycle, and shutdown.
- `scripts/send_lpfs_vps_startup_alert.py`: boot/restart Telegram alert and
  `vps_startup_alert` journal row without importing MT5 or touching live state.
- `scripts/Install-LpfsStartupAlertTask.ps1`: installs the at-startup SYSTEM
  task used by the FTMO and IC VPS lanes.

Default production runtime root:

```text
C:\TradeAutomationRuntime
```

Runtime files under that root:

```text
C:\TradeAutomationRuntime\data\live\lpfs_live_state.json
C:\TradeAutomationRuntime\data\live\lpfs_live_journal.jsonl
C:\TradeAutomationRuntime\data\live\lpfs_live_heartbeat.json
C:\TradeAutomationRuntime\data\live\KILL_SWITCH
C:\TradeAutomationRuntime\data\live\logs\lpfs_live_YYYYMMDD_HHMMSS.log
```

## Runtime State Migration

Before switching from the repo default `data/live` path to
`C:\TradeAutomationRuntime`, copy the current live state and journal if they
exist:

```powershell
New-Item -ItemType Directory -Force -Path C:\TradeAutomationRuntime\data\live
Copy-Item data\live\lpfs_live_state.json C:\TradeAutomationRuntime\data\live\lpfs_live_state.json
Copy-Item data\live\lpfs_live_journal.jsonl C:\TradeAutomationRuntime\data\live\lpfs_live_journal.jsonl
```

The runner fails closed when `--runtime-root` is used, the old configured state
file exists, and the new runtime state is missing. This prevents accidentally
starting with an empty state and re-arming already processed latest-candle
signals. Use `--allow-empty-runtime-state` only when a clean production state is
intentional and broker state has been checked first.

## Local Rehearsal Commands

Run these from the repository root. Do not start the live runner unless
`config.local.json`, MT5 account/server, and risk settings have been reviewed.

Set the kill switch before staging:

```powershell
.\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Reason "staging"
```

Check status:

```powershell
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime
```

Clear the kill switch only when ready to allow new cycles:

```powershell
.\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Clear
```

Start the watchdog launcher:

```powershell
.\scripts\run_lpfs_live_forever.ps1 -ConfigPath config.local.json -RuntimeRoot C:\TradeAutomationRuntime -Cycles 100000000 -SleepSeconds 30
```

Use the status command as the copy/paste packet for review:

```powershell
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 20 -LogLines 40
```

Emergency stop:

```powershell
.\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Reason "operator emergency stop"
```

The kill switch prevents new live cycles. It does not forcibly close MT5
positions and it does not delete existing broker pending orders by itself.
Existing broker state remains managed by MT5 and the next online reconciliation
cycle.

## Watchdog Behavior

`run_lpfs_live_forever.ps1`:

- creates the runtime and log folders;
- refuses to start when `KILL_SWITCH` exists;
- starts `scripts/run_lp_force_strike_live_executor.py`;
- redirects stdout/stderr to timestamped log files;
- passes `--runtime-root`, `--kill-switch-path`, and `--heartbeat-path`;
- restarts after unexpected non-zero crashes;
- does not restart after normal completion, Ctrl+C, or kill-switch exit.

Expected exit codes:

| Code | Meaning | Watchdog action |
|---:|---|---|
| 0 | requested cycles completed | stop |
| 2 | another runner already holds the state lock | stop |
| 3 | kill switch active | stop |
| 4 | runtime state migration required | stop |
| 130 | Ctrl+C / user stop | stop |
| other | unexpected crash | restart unless `-MaxRestarts` is exceeded |

The live runner still keeps the existing single-runner lock beside the resolved
state file. A watchdog restart should not duplicate orders because the live
cycle reconciles MT5 before scanning new signals and persists broker-affecting
state immediately.

## Heartbeat Contract

The heartbeat is local JSON intended for operator review:

- `status`: `starting`, `running`, `completed`, `stopped_by_user`, `error`, or
  `kill_switch`.
- `pid`: current Python process ID.
- `requested_cycles` and `completed_cycles`.
- `state_path`, `journal_path`, `kill_switch_path`.
- `account_login`, `account_server`, and `account_currency` when MT5 account
  info is available.
- `last_cycle` with cycle index, frames processed, orders sent, rejected
  setups, and blocked setups.
- `runtime_seconds`, `state_saved`, and stop detail on shutdown.

The heartbeat is not a trading source of truth. Broker truth is still MT5
orders, positions, and deal history. Restart continuity is still the state file.
Audit truth is still the JSONL journal.

## Task Scheduler Rehearsal

Create a Windows Task Scheduler task after local manual rehearsal passes.

Recommended task settings:

- Trigger: at user logon, or on startup after automatic login is deliberately
  configured.
- Run only when the user is logged on, because MT5 is a GUI terminal and the
  Python API attaches to that user session.
- Program:

```text
powershell.exe
```

- Arguments:

```text
-NoProfile -ExecutionPolicy Bypass -File "C:\Users\chewc\OneDrive\Desktop\TradeAutomation\scripts\run_lpfs_live_forever.ps1" -RepoRoot "C:\Users\chewc\OneDrive\Desktop\TradeAutomation" -ConfigPath "C:\Users\chewc\OneDrive\Desktop\TradeAutomation\config.local.json" -RuntimeRoot "C:\TradeAutomationRuntime" -Cycles 100000000 -SleepSeconds 30
```

- Start in:

```text
C:\Users\chewc\OneDrive\Desktop\TradeAutomation
```

For VPS use, disconnect the RDP session instead of signing out, so MT5 remains
open in the user session.

## Startup Alert Task

The boot alert is intentionally separate from the MT5 live runner. It can run as
`SYSTEM` at Windows startup because it only reads the ignored local config for
Telegram, collects Windows boot/restart evidence, retries Telegram while
networking starts, and appends one `vps_startup_alert` row to the runtime
journal.

FTMO:

```powershell
.\scripts\Install-LpfsStartupAlertTask.ps1 `
  -TaskName LPFS_FTMO_Startup_Alert `
  -ConfigPath C:\TradeAutomation\config.local.json `
  -RuntimeRoot C:\TradeAutomationRuntime `
  -RuntimeJournalFileName lpfs_live_journal.jsonl `
  -InstanceLabel "LPFS FTMO LIVE" `
  -RunnerTaskName LPFS_Live
```

IC:

```powershell
.\scripts\Install-LpfsStartupAlertTask.ps1 `
  -TaskName LPFS_IC_Startup_Alert `
  -ConfigPath C:\TradeAutomation\config.lpfs_icmarkets_raw_spread.local.json `
  -RuntimeRoot C:\TradeAutomationRuntimeIC `
  -RuntimeJournalFileName lpfs_ic_live_journal.jsonl `
  -InstanceLabel "LPFS IC LIVE" `
  -RunnerTaskName LPFS_IC_Live
```

Limit: a `VPS STARTED` card means Windows booted. It is not proof that MT5 is
logged in, trading is allowed, or the at-logon runner is healthy. Follow it
with the normal heartbeat, journal, and MT5 broker-state checks.

## Acceptance Criteria

Phase 2 is ready for VPS migration when these pass locally:

- The status command reports no unexpected second logical runner. On Windows,
  one venv-launched logical runner can appear as two process entries when
  `venv\Scripts\python.exe` is the parent of the real child interpreter.
- The watchdog refuses to start while `KILL_SWITCH` exists.
- The runner exits before MT5 initialization when `KILL_SWITCH` exists.
- A kill switch created during sleep stops before the next live cycle.
- Heartbeat updates after every completed cycle.
- Logs are written under `C:\TradeAutomationRuntime\data\live\logs`.
- Existing live state and journal are copied before switching runtime roots, or
  a clean state is explicitly allowed after broker-state verification.
- A crash produces a timestamped log and the watchdog restarts.
- A watchdog restart reconciles MT5 before scanning new signals.
- State and journal are written under `C:\TradeAutomationRuntime`, not
  OneDrive.
- Telegram failure does not change trade validity.
- Existing MT5 pending orders and positions are reconciled before any new
  signal send.
- Weekly-open spread WAITING and market-recovery price WAITING behavior is
  reviewed with live gate attribution before changing the `0.10` spread/risk
  gate.
- Better-than-entry market recovery is default-on for missed pending touches:
  long ask must be at or below original entry, short bid must be at or above
  original entry, spread must still be <= 10% of actual fill-to-stop risk, and
  the original stop/target path after the first entry touch must remain clean.
  Worse-than-entry quotes wait/retry until same-or-better price, path
  invalidation, or actual-bar expiry.
- Rollback is explicit and local: set `live_send.market_recovery_mode` to
  `"disabled"` and restart the runner intentionally.
- Verification on 2026-05-04: focused live executor/notification tests passed
  (`38` tests), full LPFS discovery passed (`186` tests), and
  `scripts/run_core_coverage.py` passed with `100.00%` total coverage.

## Amazon Lightsail Next Step

Local rehearsal passed on 2026-05-03:

- production runtime staged at `C:\TradeAutomationRuntime`;
- current live state and journal copied into that runtime;
- read-only MT5 preflight matched the expected account/server from local config;
- MT5 showed two LPFS pending orders and zero LPFS positions, matching staged
  runtime state;
- direct one-cycle run completed with `frames_processed=140`, `orders_sent=0`,
  `setups_rejected=0`, and `setups_blocked=0`;
- watchdog one-cycle run completed and wrote a timestamped log;
- temporary Task Scheduler smoke run returned kill-switch exit code `3`;
- temporary Task Scheduler one-cycle live rehearsal returned result `0`;
- all temporary scheduled tasks were removed after rehearsal;
- `KILL_SWITCH` was re-enabled afterward for operator review.

Use `docs/lpfs_lightsail_vps_runbook.md` for the next move. The recommended
VPS target is a Windows Lightsail instance running MT5, Python, and the same
Phase 2 wrapper.

Do not increase risk during the VPS migration. Keep `KILL_SWITCH` active while
staging, and only clear it for controlled one-cycle verification after MT5,
config, state, journal, and broker state are checked.
