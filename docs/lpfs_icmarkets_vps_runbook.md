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

Last verified on 2026-05-23 after the LPFS weekly-report incident, runner
recovery, diagnostic-logging upgrade, and journal-read safety update.

Latest local dual-VPS packet before the IC scale-down plan:
`reports/live_ops/lpfs_dual_vps_status_20260530_224231.md`. It showed IC
`LPFS_IC_Live` running, kill switch clear, heartbeat fresh, MT5 connected and
trade allowed, `live_send.risk_bucket_scale=2`,
`max_risk_pct_per_trade=1.5`, and `max_open_risk_pct=12`. Treat that packet as
a historical snapshot; capture a fresh pre-change packet before maintenance.

Latest local dual-VPS packet after the IC scale-down maintenance:
`reports/live_ops/lpfs_dual_vps_status_20260531_001603.md`. It showed FTMO
unchanged and running at scale `0.05`, and IC running at
`live_send.risk_bucket_scale=1`, `max_risk_pct_per_trade=0.75`, and
`max_open_risk_pct=6`, with kill switch clear, fresh heartbeat, MT5 connected
and trade allowed, and broker/state counts reconciled.

- Active local operations PC: `LAPTOP-BOHDIO8I`, Tailscale IP
  `100.118.29.124`, repo
  `C:\Users\Cody\OneDrive\Desktop\TradeAutomation`.
- SSH alias: `lpfs-ic-vps`.
- Hostname: `EC2AMAZ-DT73P0T`.
- Tailscale IP: `100.98.12.113`.
- SSH user: `Administrator`.
- Repo checkout: `C:\TradeAutomation`, clean `main...origin/main` at
  `32a71d9` in the 2026-05-23 recovery packet. Pull latest `main` before any
  maintenance.
- Python venv: `C:\TradeAutomation\venv` with `pandas`, `pyarrow`,
  `MetaTrader5`, `certifi`, `pytest`, and `coverage[toml]` installed.
- Public Lightsail RDP has been removed. Use Tailscale RDP to `100.98.12.113`
  when MT5 desktop review is needed.
- Tailscale unattended mode is enabled on the IC VPS. Verify with
  `tailscale debug prefs` and confirm `ForceDaemon=true`. This keeps tailnet
  SSH/RDP available after Windows boots, before an `Administrator` desktop
  login.
- The old PC `cy-desktop` has been removed from Tailscale, and its old IC VPS
  SSH key entry was removed from `administrators_authorized_keys`.
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
- Reboot recovery checkpoint: on 2026-05-14 Windows Update restarted the IC VPS.
  `LPFS_IC_Startup_Alert` fired, but `LPFS_IC_Live` did not become durable
  until an interactive `Administrator` RDP logon recreated the desktop session.
  After logging in and then disconnecting, not signing out, `LPFS_IC_Live`
  stayed running with fresh heartbeat, IC MT5 connected to
  `ICMarketsSC-MT5-2`, and broker/state counts reconciled.
- Latest spot check on 2026-05-23:
  `reports/live_ops/lpfs_dual_vps_status_20260523_140154.md` showed
  `LPFS_IC_Live` running with kill switch clear, fresh `running`
  `lpfs_ic_live_heartbeat.json`, parent/child Python runner shape, MT5
  connected/trade allowed, `6` IC strategy pending orders, and `5` IC strategy
  positions matching runtime state. This packet was taken after restarting the
  runner from the weekly-report incident.
- Journal read safety: do not run unbounded `Select-String`,
  `Get-Content -Raw`, or `[System.IO.File]::OpenText()` scans against
  `C:\TradeAutomationRuntimeIC\data\live\lpfs_ic_live_journal.jsonl` while the
  runner is live. If a full scan is explicitly approved, use a streaming
  `FileStream` opened with `FileShare.ReadWrite`, then run
  `.\scripts\Get-LpfsDualVpsStatus.ps1 -JournalLines 5 -LogLines 5` from the
  local repo to verify both production lanes afterward.
- Diagnostic logging: current code can write additive versioned `diagnostics`
  payloads on sparse lifecycle rows. These fields are for future
  live-vs-backtest analysis only and do not change IC strategy behavior.
  Production IC journals only show them after the VPS checkout is pulled and
  `LPFS_IC_Live` is intentionally restarted. See
  `docs/lpfs_diagnostic_logging.md`.

## Live Sizing Policy Ledger

Tracked live sizing-policy epochs are recorded in
`configs/live_policy_ledger.csv`. Use that ledger for handoff and performance
analysis instead of repeating full sizing history across docs.

- FTMO remains unchanged at `risk_bucket_scale=0.05`,
  `max_risk_pct_per_trade=0.75`, and `max_open_risk_pct=0.65`.
- IC historical production used the IC growth-practical bucket shape
  `0.25% / 0.30% / 0.75%` with `risk_bucket_scale=2.0`,
  `max_risk_pct_per_trade=1.5`, and `max_open_risk_pct=12.0`.
- The active IC scale-down keeps the IC bucket shape but changes future
  live-send order sizing to `risk_bucket_scale=1.0`,
  `max_risk_pct_per_trade=0.75`, and `max_open_risk_pct=6.0`.
- This policy does not resize or cancel existing IC pending orders or active
  positions and does not edit live state, journals, or `dry_run` settings.

## IC Scale-Down Maintenance Procedure

Use this procedure for IC live sizing changes. It is IC-only; do not change
FTMO commands, config, runtime files, state, journals, orders, or positions.

1. Capture fresh pre-change status from the local repo:

```powershell
.\scripts\Get-LpfsDualVpsStatus.ps1 -JournalLines 20 -LogLines 40
```

2. Set the IC kill switch:

```powershell
ssh lpfs-ic-vps "powershell -NoProfile -ExecutionPolicy Bypass -File C:\TradeAutomation\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntimeIC -Reason 'IC scale-down maintenance'"
```

3. Poll IC status until it is paused:

```powershell
ssh lpfs-ic-vps "powershell -NoProfile -ExecutionPolicy Bypass -File C:\TradeAutomation\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntimeIC -StateFileName lpfs_ic_live_state.json -JournalFileName lpfs_ic_live_journal.jsonl -HeartbeatFileName lpfs_ic_live_heartbeat.json -LogFilter 'lpfs_ic_live_*.log' -JournalLines 10 -LogLines 20"
```

Required before editing the ignored config:

- `kill_switch_active=True`
- `processes=0`
- heartbeat status is `kill_switch`, `stopped`, or otherwise no longer
  `running`
- FTMO was not touched

If IC still shows running processes after a few minutes, stop and inspect. Do
not force-kill or edit config without a separate decision.

4. Back up and edit only the IC VPS ignored config:

```powershell
ssh lpfs-ic-vps "powershell -NoProfile -ExecutionPolicy Bypass -Command `$path='C:\TradeAutomation\config.lpfs_icmarkets_raw_spread.local.json'; `$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'; Copy-Item -LiteralPath `$path -Destination (`$path + '.bak_' + `$stamp + '_scale_down'); `$cfg=Get-Content -LiteralPath `$path -Raw | ConvertFrom-Json; `$cfg.live_send.risk_bucket_scale=1.0; `$cfg.live_send.max_risk_pct_per_trade=0.75; `$cfg.live_send.max_open_risk_pct=6.0; `$cfg | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath `$path -Encoding UTF8"
```

5. Validate config load and effective buckets without sending orders:

```powershell
ssh lpfs-ic-vps "powershell -NoProfile -ExecutionPolicy Bypass -Command Set-Location C:\TradeAutomation; `$env:PYTHONPATH='C:\TradeAutomation\strategies\lp_force_strike_strategy_lab\src;C:\TradeAutomation\concepts\lp_levels_lab\src;C:\TradeAutomation\concepts\force_strike_pattern_lab\src;C:\TradeAutomation\shared\backtest_engine_lab\src'; .\venv\Scripts\python -c `"from lp_force_strike_strategy_lab import load_live_send_settings, live_risk_buckets_from_config; s=load_live_send_settings('config.lpfs_icmarkets_raw_spread.local.json'); b=live_risk_buckets_from_config(s.executor); print('scale', s.executor.risk_bucket_scale); print('max_trade', s.executor.max_risk_pct_per_trade); print('max_open', s.executor.max_open_risk_pct); print('buckets', b)`""
```

Expected output includes `scale 1.0`, `max_trade 0.75`, `max_open 6.0`, and
effective buckets H4/H8 `0.25`, H12/D1 `0.30`, W1 `0.75`.

6. Clear the IC kill switch:

```powershell
ssh lpfs-ic-vps "powershell -NoProfile -ExecutionPolicy Bypass -File C:\TradeAutomation\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntimeIC -Clear"
```

7. Start the scheduled IC task, not a second manual runner:

```powershell
ssh lpfs-ic-vps "powershell -NoProfile -Command Start-ScheduledTask -TaskName LPFS_IC_Live"
```

8. Wait one to two minutes, then capture post-change status:

```powershell
.\scripts\Get-LpfsDualVpsStatus.ps1 -JournalLines 20 -LogLines 40
```

The post-change packet must show IC scale `1.0`, max trade `0.75`, max open
`6.0`, fresh IC `running` heartbeat, IC MT5 connected/trade allowed,
broker/state count reconciliation, and FTMO unchanged.

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

3. RDP over Tailscale only for MT5 login/visual review. Disconnect instead of
   signing out.
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
.\venv\Scripts\python scripts\summarize_lpfs_live_gate_attribution.py --ssh-journal "FTMO=lpfs-vps:C:\TradeAutomationRuntime\data\live\lpfs_live_journal.jsonl" --ssh-journal "IC=lpfs-ic-vps:C:\TradeAutomationRuntimeIC\data\live\lpfs_ic_live_journal.jsonl" --tail-lines 200000 --detail-limit 60 --output reports\live_ops\lpfs_gate_attribution_latest.md
```

`summarize_lpfs_live_gate_attribution.py` defaults remote journal reads to a
bounded shared-read stream. Use `--allow-full-scan` only when an explicit full
historical scan is approved, then capture a fresh dual-VPS status packet.

The status packet includes C: drive free-space fields. Treat
`disk_status=warn` as a cleanup or sizing-review trigger, and
`disk_status=action_required` as a blocker for heavy report scans, deploys, or
large data collection until free space is addressed. Current policy is warn
below `15 GB` or `25%` free, and action below `10 GB` or `15%` free.

Compact IC performance summary from a safely collected local journal copy:

```powershell
cd C:\TradeAutomation
$journalCopy = "reports\live_ops\lpfs_journal_snapshots\<snapshot>\lpfs_ic_live_journal.jsonl"
.\venv\Scripts\python scripts\summarize_lpfs_live_trades.py --config config.lpfs_icmarkets_raw_spread.local.json --journal $journalCopy --weeks 1 --post-telegram
```

Routine IC summaries should omit `--include-trades`. Add that flag only when
an explicit trade-by-trade list is requested. Do not point the compact summary
reader at the active IC runtime journal; use the shared-read collection
procedure in `docs/system_troubleshooting.md`.

## Reboot Recovery And Phone RDP

The current IC live runner is intentionally an interactive at-logon task.
Tailscale unattended mode should restore tailnet access after Windows boots,
but the live runner and MT5 desktop session still require an `Administrator`
logon after a full Windows reboot.

Operational interpretation:

- `LPFS IC LIVE | VPS STARTED` means Windows booted. It does not prove MT5,
  `LPFS_IC_Live`, heartbeat freshness, or broker connectivity.
- After any IC reboot alert, RDP in once over Tailscale, wait for MT5 and the
  runner to start, then disconnect. Do not sign out. If Tailscale is
  unexpectedly unavailable, temporarily whitelist the current operator public
  IP for Lightsail RDP, recover, then remove the public RDP rule again.
- A disconnected RDP session is healthy for this design. A signed-out session
  can close MT5 and the runner.
- Do not convert `LPFS_IC_Live` to a `SYSTEM` boot task without a separate
  staged redesign. A 2026-05-14 temporary SYSTEM/headless MT5 probe did not
  complete cleanly; the durable recovery path was the interactive
  `Administrator` logon trigger.

Phone RDP setup, using Microsoft Windows App or Microsoft Remote Desktop:

```text
PC name: 100.98.12.113
Username: EC2AMAZ-DT73P0T\Administrator
Fallback username: .\Administrator
Gateway: none
Admin mode: on
Friendly name: LPFS IC VPS
```

Phone recovery steps:

1. Connect the phone to Tailscale.
2. Open the saved IC VPS RDP entry.
3. Log in as `Administrator`.
4. Wait one to two minutes for MT5 and `LPFS_IC_Live`.
5. Disconnect the RDP session. Do not sign out.
6. Confirm with Telegram runner cards or, when available from the operations
   PC, the IC status command in this runbook.

## Setup Order

1. Create a new Windows Server Lightsail instance.
2. Install and sign into Tailscale.
3. Enable OpenSSH and restrict inbound SSH to Tailscale.
4. Add local SSH alias `lpfs-ic-vps`.
5. Install IC Markets MT5 on the IC VPS.
6. Log into the IC account in MT5 and keep the terminal open.
7. Create the IC Telegram channel/group and add the bot.
8. Clone/pull `TradeAutomation` into `C:\TradeAutomation`.
9. Create the venv and install dependencies from `requirements-dev.txt`.
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
    the sizing policy recorded in `configs/live_policy_ledger.csv`.
13. Create runtime folders and start with the kill switch active.

Dependency install command:

```powershell
py -3.12 -m venv venv
.\venv\Scripts\python -m pip install --upgrade pip
.\venv\Scripts\python -m pip install -r requirements-dev.txt
```

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

If the task is already running: do not start a new instance. Configure Task
Scheduler with `MultipleInstances=IgnoreNew`.

`LPFS_IC_Live` is now installed. Do not replace it or start a second manual
runner while the scheduled task is running. Use `Get-LpfsDualVpsStatus.ps1`,
the gate-attribution report, or the IC status command above before maintenance.

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

Current Windows Update posture observed on 2026-05-14: Windows automatic
scheduled install is enabled (`AUOptions=4`) and no pending reboot registry key
was present after the recovery. Planned update restarts are not fully random,
but the exact next restart time should not be relied on. Treat any startup
alert as a login-required signal until an unattended MT5 design is intentionally
implemented and tested.

## Guardrails

- Do not change the existing FTMO VPS, MT5 login, scheduled task, or runtime
  root while setting up IC.
- Do not reuse FTMO state or journal files for IC.
- Do not reuse FTMO Telegram channel for IC.
- Do not run IC and FTMO from the same MT5 terminal.
- Do not enable a second IC live-send process while `LPFS_IC_Live` is running.
- Do not change IC live sizing without a kill-switch-first pause, config-load
  validation, restart through `LPFS_IC_Live`, and fresh post-change dual-VPS
  status packet.
- Telegram is an alert channel only. MT5 orders/positions plus the JSONL journal
  remain the audit source of truth.
