# LPFS Amazon Lightsail VPS Runbook

Last updated: 2026-05-03.

This runbook moves the existing Python + MT5 live runner to Amazon Lightsail
without rewriting strategy logic. The exact strategy behavior remains owned by
the Python runner and MT5 terminal; Lightsail only supplies an always-on
Windows host.

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
- Restrict inbound RDP TCP 3389 to your current public IP where possible.
- Do not open web-server ports unless needed.
- Create a Lightsail snapshot after MT5, Python, repo, and config are working.
- Optional: attach a static IP for stable RDP addressing. The live runner does
  not need inbound public traffic for trading, but static IP can make support
  and monitoring simpler.

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
   Use the browser RDP client first, then your normal RDP client after the
   password and firewall are set.

3. Lock down firewall.

   In Lightsail networking, restrict RDP to your current public IP or a small
   trusted CIDR. AWS warns that allowing all IPs to RDP is a security risk.

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
   .\venv\Scripts\python -m pip install pandas MetaTrader5 certifi coverage[toml]
   ```

   `coverage[toml]` is needed for verification. `certifi` provides a stable CA
   bundle for Telegram HTTPS delivery from Windows Server. For pure live
   runtime, pandas, MetaTrader5, and certifi are the key external packages.

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
because signing out can close the interactive MT5 session.

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

Run these from the VPS in PowerShell after RDP login:

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

- RDP in;
- open MT5 if it is not already open;
- confirm account/server;
- run status command;
- let Task Scheduler or the watchdog start the runner.

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
- manual deletion semantics;
- Telegram wording except for operational clarity.
