# LPFS IC Markets VPS Runbook

This runbook is for bringing up a second LP + Force Strike production runner
for IC Markets Raw Spread while leaving the existing FTMO VPS runner untouched.

The current FTMO production task remains `LPFS_Live` on the existing VPS. The IC
runner must use its own VPS, MT5 terminal, Telegram channel, ignored config,
runtime root, state, journal, heartbeat, kill switch, and scheduled task.

## Target Shape

| Area | FTMO Existing Production | IC Markets Production |
|---|---|---|
| VPS alias | `lpfs-vps` | `lpfs-ic-vps` |
| Scheduled task | `LPFS_Live` | `LPFS_IC_Live` |
| Startup alert task | `LPFS_FTMO_Startup_Alert` | `LPFS_IC_Startup_Alert` |
| Repo path | `C:\TradeAutomation` | `C:\TradeAutomation` |
| Runtime root | `C:\TradeAutomationRuntime` | `C:\TradeAutomationRuntimeIC` |
| Config | ignored `config.local.json` | ignored `config.lpfs_icmarkets_raw_spread.local.json` |
| MT5 terminal | FTMO terminal/account | IC Markets terminal/account |
| Telegram | FTMO LPFS channel/chat | separate IC LPFS channel/chat |
| Magic | `131500` | `231500` |
| Broker comment prefix | `LPFS` | `LPFSIC` |
| State | `lpfs_live_state.json` | `lpfs_ic_live_state.json` |
| Journal | `lpfs_live_journal.jsonl` | `lpfs_ic_live_journal.jsonl` |
| Heartbeat | `lpfs_live_heartbeat.json` | `lpfs_ic_live_heartbeat.json` |
| Logs | `lpfs_live_*.log` | `lpfs_ic_live_*.log` |

## Current Verified IC VPS State

Last verified on 2026-05-06 after the dedicated IC VPS was promoted from
staging to its own live runner.

- SSH alias: `lpfs-ic-vps`.
- Hostname: `EC2AMAZ-DT73P0T`.
- Tailscale IP: `100.98.12.113`.
- SSH user: `Administrator`.
- Repo checkout: `C:\TradeAutomation`, clean `main...origin/main`. Pull latest
  `main` before any maintenance.
- Python venv: `C:\TradeAutomation\venv` with `pandas`, `certifi`,
  `MetaTrader5`, and `pytest` installed.
- Focused IC-lane tests: `91 passed`.
- MT5 terminal: `C:\Program Files\MetaTrader 5 IC Markets Global`.
- MT5 account check: expected login matched, server `ICMarketsSC-MT5-2`,
  company `Raw Trading Ltd`, currency `USD`, terminal connected, trading
  allowed.
- Symbol check: all `28` configured FX symbols selected, none missing.
- Candle check: `140` probes across H4/H8/H12/D1/W1 returned `20` rows each
  in the quick availability probe.
- IC runtime: `C:\TradeAutomationRuntimeIC` exists with the kill switch clear.
- Telegram: IC VPS Telegram-only smoke delivered to the separate IC channel.
- IC dry-run/order-check: one VPS dry-run cycle processed `140` frames, found
  `3` current setups, created `3` pending intents, and all `3` MT5
  `order_check` calls passed.
- Broker state after dry-run: `0` orders, `0` positions, `0` IC-strategy orders,
  and `0` IC-strategy positions.
- IC one-cycle live-send smoke: completed from the IC VPS against
  `config.lpfs_icmarkets_raw_spread.local.json`; it placed `1` tracked pending
  order, left `0` active positions, and wrote `lpfs_ic_live_state.json` plus
  `lpfs_ic_live_journal.jsonl`.
- Continuous live state: `LPFS_IC_Live` is installed and running through
  `scripts\run_lpfs_live_forever.ps1` with `Cycles 100000000`,
  `SleepSeconds 30`, runtime root `C:\TradeAutomationRuntimeIC`, and log prefix
  `lpfs_ic_live`.
- Boot/restart alert: `LPFS_IC_Startup_Alert` is installed as an at-startup
  `SYSTEM` task. It sends IC Telegram `VPS STARTED` cards and journals
  `vps_startup_alert` into `lpfs_ic_live_journal.jsonl` without touching MT5 or
  live trading state.

## Files Needed On The IC VPS

Repo checkout:

- `C:\TradeAutomation`
- current `main` branch from GitHub
- Python venv under `C:\TradeAutomation\venv`
- all repo scripts under `scripts\`
- strategy source under `strategies\lp_force_strike_strategy_lab\src`
- concept/shared source folders imported by the runner

Ignored local files created on the IC VPS:

- `C:\TradeAutomation\config.lpfs_icmarkets_raw_spread.local.json`
- no MT5 password is required if `use_existing_terminal_session=true`
- Telegram bot token and IC chat ID stay only in this ignored local config or
  environment variables

Runtime files created outside the repo:

- `C:\TradeAutomationRuntimeIC\data\live\KILL_SWITCH` only when intentionally
  paused
- `C:\TradeAutomationRuntimeIC\data\live\lpfs_ic_live_state.json`
- `C:\TradeAutomationRuntimeIC\data\live\lpfs_ic_live_journal.jsonl`
- `C:\TradeAutomationRuntimeIC\data\live\lpfs_ic_live_heartbeat.json`
- `C:\TradeAutomationRuntimeIC\data\live\logs\lpfs_ic_live_*.log`

## Communication Channels

Use the same operator channels as the FTMO VPS, but with IC-specific names:

1. Tailscale device for the new VPS.
2. SSH alias on the local PC:

```sshconfig
Host lpfs-ic-vps
  HostName 100.98.12.113
  User Administrator
  IdentityFile ~/.ssh/lpfs_ic_vps_ed25519
```

3. RDP only for MT5 login/visual review. Disconnect instead of signing out.
4. Separate Telegram channel or group for IC LPFS notifications.
5. Separate bot/chat ID in `config.lpfs_icmarkets_raw_spread.local.json`.
6. GitHub remains the code migration channel. Local changes must be committed
   and pushed, then pulled on the IC VPS.

This gives future agents the same analysis access pattern:

```powershell
ssh lpfs-ic-vps hostname
ssh lpfs-ic-vps whoami
ssh lpfs-ic-vps "powershell -NoProfile -Command Set-Location C:\TradeAutomation; git status --short --branch"
ssh lpfs-ic-vps "powershell -NoProfile -ExecutionPolicy Bypass -File C:\TradeAutomation\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntimeIC -StateFileName lpfs_ic_live_state.json -JournalFileName lpfs_ic_live_journal.jsonl -HeartbeatFileName lpfs_ic_live_heartbeat.json -LogFilter 'lpfs_ic_live_*.log' -JournalLines 40 -LogLines 80"
.\scripts\Get-LpfsDualVpsStatus.ps1 -JournalLines 20 -LogLines 40
```

## Setup Order

1. Create a new Windows Server Lightsail instance.
2. Install and sign into Tailscale.
3. Enable OpenSSH and restrict inbound SSH to Tailscale.
4. Add local SSH alias `lpfs-ic-vps`.
5. Install IC Markets MT5 on the IC VPS.
6. Log into the IC account in MT5 and keep the terminal open.
7. Create the IC Telegram channel/group and add the bot.
8. Clone/pull `TradeAutomation` into `C:\TradeAutomation`.
9. Create the venv and install dependencies.
10. Copy `config.lpfs_icmarkets_raw_spread.example.json` to ignored
    `config.lpfs_icmarkets_raw_spread.local.json`.
11. Fill only the IC-specific local values:
    - `mt5.expected_login`
    - `mt5.expected_server`
    - Telegram bot token and IC chat ID
    - `telegram.enabled=true`
    - `telegram.dry_run=false` only after test delivery is confirmed
12. Keep `live_send.execution_mode="DRY_RUN"` and
    `live_send.live_send_enabled=false` until the staged checks pass. The
    promoted IC VPS now uses `live_send.execution_mode="LIVE_SEND"`,
    `live_send.live_send_enabled=true`, 28 explicit live symbols, and
    `risk_bucket_scale=2.0`.
13. Create runtime folders and start with the kill switch active.

```powershell
New-Item -ItemType Directory -Force -Path C:\TradeAutomationRuntimeIC\data\live\logs
.\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntimeIC -Reason "IC maintenance pause"
```

## Staged Verification

Run all commands from `C:\TradeAutomation` on the IC VPS unless noted.

1. Prove identity and repo:

```powershell
hostname
whoami
git status --short --branch
```

2. Prove MT5 account/server and symbol metadata with a read-only audit.

3. Run one-cycle order-check only:

```powershell
.\venv\Scripts\python scripts\run_lp_force_strike_dry_run_executor.py `
  --config config.lpfs_icmarkets_raw_spread.local.json `
  --cycles 1 `
  --sleep-seconds 1
```

4. Inspect status:

```powershell
.\scripts\Get-LpfsLiveStatus.ps1 `
  -RuntimeRoot C:\TradeAutomationRuntimeIC `
  -StateFileName lpfs_ic_live_state.json `
  -JournalFileName lpfs_ic_live_journal.jsonl `
  -HeartbeatFileName lpfs_ic_live_heartbeat.json `
  -LogFilter "lpfs_ic_live_*.log" `
  -JournalLines 40 `
  -LogLines 80
```

5. Only after explicit approval, change the ignored local config to
   `LIVE_SEND`, clear the kill switch, and run a one-cycle live-send smoke test.

6. After the smoke test, reconcile MT5 orders/positions against the IC state
   and journal before any continuous runner is installed.

Current promoted state: the one-cycle live-send smoke completed and
`LPFS_IC_Live` is installed/running. Future agents should still repeat the same
reconciliation after any config change or restart.

## Watchdog And Scheduled Task

Manual watchdog command:

```powershell
.\scripts\run_lpfs_live_forever.ps1 `
  -RepoRoot C:\TradeAutomation `
  -ConfigPath C:\TradeAutomation\config.lpfs_icmarkets_raw_spread.local.json `
  -RuntimeRoot C:\TradeAutomationRuntimeIC `
  -StateFileName lpfs_ic_live_state.json `
  -JournalFileName lpfs_ic_live_journal.jsonl `
  -HeartbeatFileName lpfs_ic_live_heartbeat.json `
  -LogPrefix lpfs_ic_live `
  -Cycles 100000000 `
  -SleepSeconds 30
```

Task Scheduler action for `LPFS_IC_Live`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\TradeAutomation\scripts\run_lpfs_live_forever.ps1" -RepoRoot "C:\TradeAutomation" -ConfigPath "C:\TradeAutomation\config.lpfs_icmarkets_raw_spread.local.json" -RuntimeRoot "C:\TradeAutomationRuntimeIC" -StateFileName "lpfs_ic_live_state.json" -JournalFileName "lpfs_ic_live_journal.jsonl" -HeartbeatFileName "lpfs_ic_live_heartbeat.json" -LogPrefix "lpfs_ic_live" -Cycles 100000000 -SleepSeconds 30
```

`LPFS_IC_Live` is now installed. Do not replace it or start a second manual
runner while the scheduled task is running. Use `Get-LpfsDualVpsStatus.ps1` or
the IC status command above before maintenance.

Startup alert task for `LPFS_IC_Startup_Alert`:

```powershell
.\scripts\Install-LpfsStartupAlertTask.ps1 `
  -TaskName LPFS_IC_Startup_Alert `
  -ConfigPath C:\TradeAutomation\config.lpfs_icmarkets_raw_spread.local.json `
  -RuntimeRoot C:\TradeAutomationRuntimeIC `
  -RuntimeJournalFileName lpfs_ic_live_journal.jsonl `
  -InstanceLabel "LPFS IC LIVE" `
  -RunnerTaskName LPFS_IC_Live
```

This is an alert-only task. It does not import MT5, does not place orders, and
does not start the live runner. It exists so the operator gets a Telegram signal
when Windows has rebooted, even before the RDP/logon-dependent MT5 session is
restored.

## Guardrails

- Do not change the existing FTMO VPS, MT5 login, scheduled task, or runtime
  root while setting up IC.
- Do not reuse FTMO state or journal files for IC.
- Do not reuse FTMO Telegram channel for IC.
- Do not run IC and FTMO from the same MT5 terminal.
- Do not enable a second IC live-send process while `LPFS_IC_Live` is running.
- Do not change IC live sizing without rerunning a one-cycle reconciliation.
- Telegram is an alert channel only. MT5 orders/positions plus the JSONL journal
  remain the audit source of truth.
