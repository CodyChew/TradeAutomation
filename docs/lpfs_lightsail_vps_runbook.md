# LPFS Amazon Lightsail VPS Runbook

Last updated: 2026-05-14 after verifying post-reboot phone RDP recovery for
the IC lane and confirming both FTMO and IC runners stay healthy after RDP
disconnect.

This runbook moves the existing Python + MT5 live runner to Amazon Lightsail
without rewriting strategy logic. The exact strategy behavior remains owned by
the Python runner and MT5 terminal; Lightsail only supplies an always-on
Windows host.

## Current Live Environment

The live production environment is the Amazon Lightsail Windows VPS, not the
local OneDrive workspace.

- VPS repo path: `C:\TradeAutomation`.
- VPS runtime root: `C:\TradeAutomationRuntime`.
- VPS scheduled task: `LPFS_Live`.
- VPS startup alert task: `LPFS_FTMO_Startup_Alert`.
- VPS MT5 terminal: FTMO Global Markets MT5 terminal attached through the local
  MetaTrader5 Python package.

Future live-operation checks, deployment verification, and incident debugging
should be performed from the VPS first. The local repo remains the development
workspace unless changes are explicitly pushed/pulled to the VPS and
`LPFS_Live` is intentionally restarted.

## Remote Maintenance Access

The preferred remote-maintenance path is Tailscale plus OpenSSH over the
private tailnet, not public SSH/RDP exposure. Use Tailscale RDP when MT5 or
desktop review is needed.

Current proven access model:

- Active local development PC: `LAPTOP-BOHDIO8I`, Tailscale IP
  `100.118.29.124`.
- Local repo path: `C:\Users\Cody\OneDrive\Desktop\TradeAutomation`.
- VPS host: `EC2AMAZ-ON6FOF2`, Tailscale IP `100.115.34.38`.
- VPS SSH user: `Administrator`.
- Local SSH alias: `lpfs-vps`.
- Local SSH key: `C:\Users\Cody\.ssh\lpfs_vps_ed25519`.
- VPS OpenSSH service: `sshd`.
- VPS firewall rule: `OpenSSH-Tailscale-Only`, inbound TCP `22` from
  `100.64.0.0/10`.
- Public Lightsail RDP has been removed. RDP to `100.115.34.38` over Tailscale
  was verified from this PC after removal.
- The old PC `cy-desktop` has been removed from Tailscale, and its old FTMO
  VPS SSH key entry was removed from `administrators_authorized_keys`.

Use the alias for read-only operator checks:

```powershell
ssh lpfs-vps hostname
ssh lpfs-vps whoami
ssh lpfs-vps "powershell -NoProfile -ExecutionPolicy Bypass -File C:\TradeAutomation\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 40 -LogLines 80"
ssh lpfs-vps "powershell -NoProfile -Command Set-Location C:\TradeAutomation; git status --short --branch"
```

The remote access path has been verified from the local PC to the VPS over
Tailscale. The status script returned a running heartbeat and the expected
Windows parent/child process shape.

## Windows Restart Alerting

`LPFS_FTMO_Startup_Alert` is an at-startup Windows Scheduled Task that runs as
`SYSTEM`. It sends a Telegram `VPS STARTED` card and appends
`vps_startup_alert` to the live journal after Windows boots. This alert is
ops-only:

- it reads ignored local config only for Telegram credentials;
- it writes only the runtime JSONL journal;
- it does not import MT5;
- it does not read or mutate live state;
- it cannot place, cancel, or modify broker orders.

The alert includes hostname, Windows boot time, the latest Windows restart
event/reason when available, runner task name, runtime root, and journal path.
It retries while networking/Tailscale/Telegram connectivity comes up.

Install or refresh it on the FTMO VPS from `C:\TradeAutomation`:

```powershell
.\scripts\Install-LpfsStartupAlertTask.ps1 `
  -TaskName LPFS_FTMO_Startup_Alert `
  -ConfigPath C:\TradeAutomation\config.local.json `
  -RuntimeRoot C:\TradeAutomationRuntime `
  -RuntimeJournalFileName lpfs_live_journal.jsonl `
  -InstanceLabel "LPFS FTMO LIVE" `
  -RunnerTaskName LPFS_Live
```

Smoke-test without rebooting:

```powershell
Start-ScheduledTask -TaskName LPFS_FTMO_Startup_Alert
Start-Sleep -Seconds 90
Get-ScheduledTaskInfo -TaskName LPFS_FTMO_Startup_Alert
Select-String -Path C:\TradeAutomationRuntime\data\live\lpfs_live_journal.jsonl -Pattern "vps_startup_alert" |
  Select-Object -Last 1
```

Important limit: this task alerts that Windows came back. It does not make MT5
or the live runner fully unattended. With the current at-logon runner design,
RDP/logon is still required after a reboot to restore the interactive MT5
session and start `LPFS_Live`.

Mobile RDP recovery is valid for this failure mode. Install Tailscale and
Microsoft Windows App or Microsoft Remote Desktop on the phone, connect the
phone to the tailnet, then use:

```text
PC name: 100.115.34.38
Username: EC2AMAZ-ON6FOF2\Administrator
Fallback username: .\Administrator
Gateway: none
Admin mode: on
Friendly name: LPFS FTMO VPS
```

After a `VPS STARTED` alert, log in once, wait for MT5 and `LPFS_Live`, then
disconnect. Do not sign out. The same pattern applies to IC with PC name
`100.98.12.113` and username `EC2AMAZ-DT73P0T\Administrator`; see
`docs/lpfs_icmarkets_vps_runbook.md` for IC-specific paths and task names.

### Environment Boundaries

Future agents and operators must differentiate environments explicitly:

- Local commands are run from the OneDrive workspace and are for development,
  tests, commits, pushes, docs, and local inspection.
- VPS commands are run through `ssh lpfs-vps ...` and affect the production
  checkout or production runtime only when the command targets
  `C:\TradeAutomation` or `C:\TradeAutomationRuntime`.
- The VPS runtime root is the production source for live heartbeat, state,
  journal, logs, kill switch, and scheduled task behavior.
- MT5 on the VPS remains the broker source of truth for orders and positions.
- Do not run a local LPFS live runner while the VPS runner is active.
- Do not mutate the VPS kill switch, scheduled task, repo checkout, live state,
  journal, MT5 orders, or MT5 positions unless the user has explicitly approved
  that operation.

### First Commands Before Touching VPS

Start any remote session by proving identity before analysis:

```powershell
ssh lpfs-vps hostname
ssh lpfs-vps whoami
ssh lpfs-vps "powershell -NoProfile -Command Set-Location C:\TradeAutomation; git status --short --branch"
```

Then gather the production status packet:

```powershell
ssh lpfs-vps "powershell -NoProfile -ExecutionPolicy Bypass -File C:\TradeAutomation\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 40 -LogLines 80"
```

### Remote Access Setup

Local setup:

1. Install and log into Tailscale on the local PC.
2. Confirm local Tailscale identity:

   ```powershell
   & "$env:ProgramFiles\Tailscale\tailscale.exe" status
   & "$env:ProgramFiles\Tailscale\tailscale.exe" ip -4
   ```

3. Create or keep the local SSH key at `~\.ssh\lpfs_vps_ed25519`.
4. Add this local SSH config entry:

   ```sshconfig
   Host lpfs-vps
     HostName 100.115.34.38
     User Administrator
     IdentityFile ~/.ssh/lpfs_vps_ed25519
     IdentitiesOnly yes
     StrictHostKeyChecking accept-new
   ```

VPS setup:

1. Install and log into Tailscale on the VPS with the same tailnet account.
2. Confirm VPS Tailscale identity:

   ```powershell
   & "$env:ProgramFiles\Tailscale\tailscale.exe" status
   & "$env:ProgramFiles\Tailscale\tailscale.exe" ip -4
   hostname
   ```

3. Enable OpenSSH Server:

   ```powershell
   Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
   Start-Service sshd
   Set-Service sshd -StartupType Automatic
   ```

4. Restrict SSH to Tailscale:

   ```powershell
   New-NetFirewallRule `
     -Name "OpenSSH-Tailscale-Only" `
     -DisplayName "OpenSSH Server - Tailscale Only" `
     -Enabled True `
     -Direction Inbound `
     -Protocol TCP `
     -Action Allow `
     -LocalPort 22 `
     -RemoteAddress 100.64.0.0/10
   ```

5. Install the local public key into
   `C:\ProgramData\ssh\administrators_authorized_keys` because the SSH user is
   an Administrator.

### Remote Access Teardown

Normal end-of-session teardown is simply to exit SSH sessions. Leave Tailscale
and `sshd` running if future remote audits are desired.

For a stricter teardown:

```powershell
Stop-Service sshd
Set-Service sshd -StartupType Manual
Disable-NetFirewallRule -Name "OpenSSH-Tailscale-Only"
```

For complete access revocation, also remove or rotate
`C:\ProgramData\ssh\administrators_authorized_keys` and disable/remove the VPS
device from the Tailscale admin console. If using RDP for MT5 review, disconnect
the RDP session instead of signing out so the interactive MT5 terminal remains
open.

Official references:

- Create Windows Server instances:
  <https://docs.aws.amazon.com/lightsail/latest/userguide/get-started-with-windows-based-instances-in-lightsail.html>
- Connect to Windows with RDP:
  <https://docs.aws.amazon.com/lightsail/latest/userguide/connect-to-your-windows-based-instance-using-amazon-lightsail.html>
- Lightsail firewall behavior:
  <https://docs.aws.amazon.com/lightsail/latest/userguide/understanding-firewall-and-port-mappings-in-amazon-lightsail.html>
- Secure Windows Server instances:
  <https://docs.aws.amazon.com/lightsail/latest/userguide/best-practices-for-securing-windows-based-lightsail-instances.html>
- Instance bundle pricing:
  <https://docs.aws.amazon.com/lightsail/latest/userguide/amazon-lightsail-bundles.html>

## Recommendation

Start with a Windows Server Lightsail instance, not MetaTrader built-in VPS and
not a Linux VPS.

Reason:

- The current runner uses the MetaTrader5 Python package, which attaches to a
  local Windows MT5 terminal.
- Keeping Python + MT5 avoids a risky MQL5 rewrite while forward live evidence
  is still being collected.
- The new Phase 2 wrapper already provides the process controls needed for a
  Windows VPS: watchdog, kill switch, logs, heartbeat, status command, and
  runtime files outside OneDrive.

## Instance Size

Practical starting point:

- Windows Small 2GB if keeping only MT5, Python, Git, and the LPFS runner open.
- Windows Medium 4GB if Windows Update, MT5, browser, and logs make the 2GB
  instance sluggish.

Avoid 0.5GB and 1GB Windows bundles for live trading. They are cheaper, but
Windows plus MT5 can become unstable or slow under updates and terminal restarts.

AWS currently documents Windows public-IPv4 bundle prices starting at 0.5GB,
with 2GB and 4GB bundles also listed. Recheck the official Lightsail pricing
page before creating the instance because pricing, free-tier eligibility, and
IPv4 charges can change.

## Security Baseline

Before funding the instance:

- Enable MFA on the AWS account.
- Add an AWS billing alert.
- Use a strong AWS root password and do daily work from an IAM user where
  possible.
- Keep `config.local.json`, MT5 credentials, and Telegram tokens out of Git.
- Do not paste tokens or broker passwords into chat.

On the Lightsail instance:

- Change or rotate Windows credentials after first setup.
- Keep Windows Update enabled.
- Keep public inbound RDP TCP 3389 disabled once Tailscale RDP is verified.
  If Tailscale is unavailable during emergency recovery, temporarily restrict
  public RDP to the current public IP and remove the rule again after access is
  restored.
- Do not open web-server ports unless needed.
- Create a Lightsail snapshot after MT5, Python, repo, and config are working.
- Optional: attach a static IP for recovery/support workflows. The live runner
  does not need inbound public traffic for trading, and normal RDP should use
  the VPS Tailscale IP.

## Build Steps

1. Create the instance:

   - Platform: Windows.
   - Blueprint: Windows Server 2022 unless your MT5 broker installer requires
     an older Windows version.
   - Region: closest practical region to the broker server. For Singapore/Asia
     broker servers, start with Singapore if available. Otherwise test ping
     from the terminal after install.
   - Bundle: Windows 2GB first, 4GB if it feels slow.

2. Connect with RDP.

   AWS says Windows instances can take several minutes before RDP is ready.
   Use the browser RDP client for first provisioning if needed. After
   Tailscale is installed and connected, use normal RDP to the VPS Tailscale
   IP instead of public Lightsail RDP.

3. Lock down firewall.

   In Lightsail networking, remove public RDP after Tailscale RDP is verified.
   If public RDP is temporarily needed during setup or emergency recovery,
   restrict it to the current public IP or a small trusted CIDR and remove it
   again afterward. AWS warns that allowing all IPs to RDP is a security risk.

4. Install MT5.

   - Download MT5 from the broker's official portal.
   - Log into the intended account.
   - Confirm account login/server match `config.local.json`.
   - Leave MT5 open.

5. Install Python and Git.

   Recommended:

   - Python 3.11 or 3.12, 64-bit.
   - Git for Windows.

6. Clone the repo.

   Example:

   ```powershell
   mkdir C:\TradeAutomation
   cd C:\TradeAutomation
   git clone https://github.com/codychew/TradeAutomation.git .
   ```

7. Create the venv.

   ```powershell
   py -3.12 -m venv venv
   .\venv\Scripts\python -m pip install --upgrade pip
   .\venv\Scripts\python -m pip install -r requirements-dev.txt
   ```

   `requirements-dev.txt` includes the operational and verification packages:
   `pandas`, `pyarrow`, `MetaTrader5`, `certifi`, `pytest`, and
   `coverage[toml]`. `certifi` provides a stable CA bundle for Telegram HTTPS
   delivery from Windows Server.

8. Create local config.

   ```powershell
   Copy-Item config.local.example.json config.local.json
   notepad config.local.json
   ```

   Required live safety fields still apply:

   - `mt5.use_existing_terminal_session=true`
   - `mt5.expected_login`
   - `mt5.expected_server`
   - `live_send.execution_mode="LIVE_SEND"`
   - `live_send.live_send_enabled=true`
   - `live_send.real_money_ack="I_UNDERSTAND_THIS_SENDS_REAL_ORDERS"`
   - `live_send.risk_bucket_scale=0.05` for controlled validation

9. Keep runtime outside the repo.

   ```powershell
   mkdir C:\TradeAutomationRuntime\data\live
   ```

   If this VPS is taking over from the local PC, copy the current live state
   and journal into this runtime folder before allowing a live cycle. Starting
   with an empty state can re-arm already processed latest-candle signals if no
   matching broker item exists for adoption.

10. Start with the kill switch set.

    ```powershell
    .\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Reason "initial VPS staging"
    .\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime
    ```

11. Clear kill switch only when ready.

    ```powershell
    .\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Clear
    ```

12. Run one controlled cycle first.

    ```powershell
    .\venv\Scripts\python scripts\run_lp_force_strike_live_executor.py --config config.local.json --cycles 1 --runtime-root C:\TradeAutomationRuntime
    ```

13. Inspect status.

    ```powershell
    .\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 30 -LogLines 40
    ```

14. Start the watchdog only after the one-cycle check is correct.

    ```powershell
    .\scripts\run_lpfs_live_forever.ps1 -RepoRoot C:\TradeAutomation -ConfigPath C:\TradeAutomation\config.local.json -RuntimeRoot C:\TradeAutomationRuntime -Cycles 100000000 -SleepSeconds 30
    ```

## Task Scheduler On Lightsail

Use Task Scheduler only after manual watchdog launch works.

Recommended settings:

- General: run only when user is logged on.
- Trigger: at logon.
- Action program: `powershell.exe`
- Arguments:

```text
-NoProfile -ExecutionPolicy Bypass -File "C:\TradeAutomation\scripts\run_lpfs_live_forever.ps1" -RepoRoot "C:\TradeAutomation" -ConfigPath "C:\TradeAutomation\config.local.json" -RuntimeRoot "C:\TradeAutomationRuntime" -Cycles 100000000 -SleepSeconds 30
```

- Start in:

```text
C:\TradeAutomation
```

After confirming the task starts the runner, disconnect RDP. Do not sign out,
because signing out can close the interactive MT5 session. Prefer Tailscale RDP
to `100.115.34.38`; public Lightsail RDP is not required for normal operation.

Validated 2026-05-04 VPS checkpoint:

- Final task name: `LPFS_Live`.
- Trigger: at logon.
- Wrapper command: `run_lpfs_live_forever.ps1` with `Cycles 100000000` and
  `SleepSeconds 30`.
- Production runtime: `C:\TradeAutomationRuntime`.
- Safe paused state: `KILL_SWITCH` exists, `LPFS_Live` is `Ready`, no runner
  process is active, and `Get-LpfsLiveStatus.ps1` reports two tracked pending
  LPFS orders and zero LPFS positions.
- Telegram delivery on Windows Server requires `certifi`; if Telegram fails
  with `CERTIFICATE_VERIFY_FAILED`, run `git pull` and
  `.\venv\Scripts\python -m pip install certifi`.

When intentionally going live from the paused state:

```powershell
cd C:\TradeAutomation
Remove-Item "C:\TradeAutomationRuntime\data\live\KILL_SWITCH" -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName "LPFS_Live"
Start-Sleep -Seconds 60
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 30 -LogLines 60
```

Expected first check: one logical runner active, heartbeat `running`, latest
log updated, and Telegram `RUNNER STARTED` received. On Windows, the status
packet can show `processes=2` for one logical runner because the venv launcher
`C:\TradeAutomation\venv\Scripts\python.exe` starts the child interpreter
`C:\Program Files\Python312\python.exe`. Confirm this by checking that one
listed `parent_pid` points to the other listed `pid`, and that both command
lines use the same config and runtime root. Do not run a local PC runner at the
same time.

## Operator Quick Reference

Run these from the VPS in PowerShell after Tailscale RDP login:

```powershell
cd C:\TradeAutomation
```

Primary status packet for Codex/operator review:

```powershell
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 30 -LogLines 60
```

Check whether the production scheduled task exists and what Windows thinks
happened last:

```powershell
Get-ScheduledTask -TaskName "LPFS_Live"
Get-ScheduledTaskInfo -TaskName "LPFS_Live"
```

Check for live runner processes directly:

```powershell
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match "run_lp_force_strike_live_executor|run_lpfs_live_forever" } |
    Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine
```

Interpretation: `processes=2` is normal only when it is the Windows venv
launcher plus its child Python interpreter for the same LPFS command. Treat it
as suspicious if the parent/child relationship is absent, configs/runtime roots
differ, the heartbeat is stale, or there are more than two runner entries.

Read the heartbeat:

```powershell
Get-Content C:\TradeAutomationRuntime\data\live\lpfs_live_heartbeat.json -Raw |
    ConvertFrom-Json |
    ConvertTo-Json -Depth 20
```

Read the latest wrapper log:

```powershell
$LatestLog = Get-ChildItem C:\TradeAutomationRuntime\data\live\logs -Filter "lpfs_live_*.log" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
Get-Content $LatestLog.FullName -Tail 80
```

Pause/stop new live cycles:

```powershell
.\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Reason "operator stop"
```

Resume intentionally:

```powershell
Remove-Item "C:\TradeAutomationRuntime\data\live\KILL_SWITCH" -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName "LPFS_Live"
```

After any resume, verify with the status packet, MT5 open orders/positions, and
Telegram runner lifecycle cards. Telegram confirms notifications only; MT5 is
the broker source of truth for orders and positions.

Market-recovery operator note:

- default live config is `live_send.market_recovery_mode="better_than_entry_only"`;
- if a pending entry was touched before placement, the runner may send a
  `MARKET RECOVERY` market order instead of a late pending order;
- long recovery requires current ask at or below the original entry; short
  recovery requires current bid at or above the original entry;
- if current executable price is worse than the original entry, the setup is a
  retryable `WAITING` event while the actual 6-bar window is still open. The
  signal key is not marked processed and no MT5 order is sent;
- the original structure stop is kept, TP is recalculated to 1R from the actual
  fill, and spread must still be no more than 10% of actual fill-to-stop risk;
- market recovery uses a market `TRADE_ACTION_DEAL` request, not a new pending
  limit. It selects broker-supported `type_filling` modes from symbol metadata;
  if MT5 returns invalid/unsupported filling mode on `order_check`, the runner
  tries the next fill mode and sends with the exact request that passed
  `order_check`;
- path safety is checked from the first actual entry touch onward. Stop/target
  movement after that touch makes late recovery ineligible; same-bar ambiguity
  remains conservative;
- `WAITING` can mean pending spread wait, market-recovery spread wait, or
  market-recovery price wait. Check the Telegram reason and JSONL
  `notification_event.fields`;
- `SKIPPED` after a missed entry means recovery was disabled or a final gate
  failed, such as stop/target after the first entry touch, expired 6-bar
  window, unavailable path, invalid stop distance, or broker rejection;
- historical processed skips remain processed after deployment. Do not edit
  `lpfs_live_state.json` to rearm them unless there is a separate live
  operator plan;
- rollback is local config only: set `live_send.market_recovery_mode` to
  `"disabled"` and restart the runner intentionally.

Deployment note: market recovery retry and the broker filling-mode fallback
were verified locally on 2026-05-05 with focused live executor tests, full LPFS
discovery (`260` tests), and core coverage at `100.00%`. The VPS repo must be
on `main` and fast-forwarded to the deployed commit, and `LPFS_Live` must be
intentionally restarted before code behavior changes are active; an already
running process keeps the old code.

LP/FS separation deployment note:

- current signal baseline requires `lp_pivot_index < fs_mother_index`;
- the rule is controlled by `require_lp_pivot_before_fs_mother`, defaulting to
  `true` for research, dry-run, and live-send paths;
- V22 control remains reproducible by explicitly setting the flag `false`;
- existing pending orders, active positions, live state, and journal files must
  not be edited for this deployment;
- existing historical processed/skipped signals remain processed because live
  `processed_signal_keys` do not include LP pivot index.

Use this exact VPS update sequence for the LP/FS separation baseline:

```powershell
cd C:\TradeAutomation
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 30 -LogLines 60
git status --short

.\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Reason "deploy LPFS V22 hard LP-FS separation"
Start-Sleep -Seconds 90
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 30 -LogLines 60
```

Expected paused state:

- `kill_switch_active=True`;
- `processes=0`;
- existing MT5 pending orders and positions are not edited.

If a runner remains active after the graceful wait:

```powershell
Stop-ScheduledTask -TaskName "LPFS_Live" -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match "run_lp_force_strike_live_executor" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 30 -LogLines 60
```

Then pull and run deployment checks:

```powershell
git pull
.\venv\Scripts\python -m unittest strategies.lp_force_strike_strategy_lab.tests.test_signals strategies.lp_force_strike_strategy_lab.tests.test_dry_run_executor strategies.lp_force_strike_strategy_lab.tests.test_live_executor -v
```

Do not edit:

```text
C:\TradeAutomationRuntime\data\live\lpfs_live_state.json
C:\TradeAutomationRuntime\data\live\lpfs_live_journal.jsonl
MT5 orders
MT5 positions
```

Resume only when ready:

```powershell
Remove-Item "C:\TradeAutomationRuntime\data\live\KILL_SWITCH" -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName "LPFS_Live"
Start-Sleep -Seconds 60
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 30 -LogLines 60
```

Expected resumed state:

- one logical LPFS live runner;
- heartbeat updated after restart;
- new future signals use hard LP/FS separation;
- existing historical skipped/processed signals remain processed.

If status shows suspicious duplicate runner entries, pause first and
investigate afterward:

```powershell
.\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Reason "duplicate runner check"
Start-Sleep -Seconds 90
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 30 -LogLines 60
```

Expected recovery state is `kill_switch_active=True` and `processes=0` after a
graceful stop. If any LPFS runner process remains, stop the scheduled task and
only then kill the runner process:

```powershell
Stop-ScheduledTask -TaskName "LPFS_Live" -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match "run_lp_force_strike_live_executor" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 30 -LogLines 60
```

A hard stop can prevent the Python runner from sending `RUNNER STOPPED` to
Telegram. In that case, trust the process table, heartbeat, latest log, and
journal over the absence of a Telegram stop card.

## Liaison Packet For Codex

When asking Codex to inspect the live process, paste:

```powershell
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime -JournalLines 30 -LogLines 60
```

Also include screenshots from MT5 open orders/positions if the question is
about broker truth. Telegram alone is not broker truth.

## Failure Handling

Use kill switch for operator stop:

```powershell
.\scripts\Set-LpfsKillSwitch.ps1 -RuntimeRoot C:\TradeAutomationRuntime -Reason "operator stop"
```

Then verify:

```powershell
.\scripts\Get-LpfsLiveStatus.ps1 -RuntimeRoot C:\TradeAutomationRuntime
```

If MT5 is disconnected:

- set kill switch;
- reconnect MT5;
- verify account login/server;
- clear kill switch;
- start one controlled cycle;
- only then return to watchdog mode.

If the VPS reboots:

- RDP in over Tailscale from the operations PC or phone;
- open MT5 if it is not already open;
- confirm account/server;
- run status command;
- let Task Scheduler or the watchdog start the runner.
- disconnect RDP after verification; do not sign out.

If suspicious duplicate runner processes appear after starting `LPFS_Live`:

- first confirm it is not the normal two-entry Windows venv launcher/child
  interpreter shape;
- if suspicious, set kill switch immediately;
- wait at least 90 seconds so the runner can exit gracefully;
- verify `processes=0`;
- if still active, use `Stop-ScheduledTask` and then stop only processes whose
  command line contains `run_lp_force_strike_live_executor`;
- do not interpret a missing Telegram `RUNNER STOPPED` card as proof the
  runner is still active after a hard stop;
- before restarting, verify only one `LPFS_Live` task exists and no manual
  PowerShell live runner is still open.

## Non-Goals

Do not use this migration to change:

- strategy signal rules;
- risk bucket values;
- spread threshold;
- stop or target placement;
- pending expiry behavior;
- market-recovery rollback/default behavior without a documented operator
  reason;
- manual deletion semantics;
- Telegram wording except for operational clarity.
