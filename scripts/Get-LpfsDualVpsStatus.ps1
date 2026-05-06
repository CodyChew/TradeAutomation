[CmdletBinding()]
param(
    [string]$OutputDir = "reports\live_ops",
    [int]$JournalLines = 12,
    [int]$LogLines = 30,
    [switch]$NoReport
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Quote-PowerShellString {
    param([string]$Value)
    return "'" + ($Value -replace "'", "''") + "'"
}

function Invoke-RemotePowerShell {
    param(
        [string]$Alias,
        [string]$Script
    )

    $RunId = [Guid]::NewGuid().ToString("N")
    $LocalTemp = Join-Path ([IO.Path]::GetTempPath()) "lpfs_dual_status_$RunId.ps1"
    $RemoteTempWin = "C:\Windows\Temp\lpfs_dual_status_$RunId.ps1"
    $RemoteTempScp = "C:/Windows/Temp/lpfs_dual_status_$RunId.ps1"

    $Script | Set-Content -LiteralPath $LocalTemp -Encoding UTF8
    try {
        & scp $LocalTemp "${Alias}:$RemoteTempScp" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "scp failed for $Alias"
        }
        & ssh $Alias powershell -NoProfile -ExecutionPolicy Bypass -File $RemoteTempWin
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "remote status script exited with code $LASTEXITCODE on $Alias"
        }
    } finally {
        Remove-Item -LiteralPath $LocalTemp -ErrorAction SilentlyContinue
        & ssh $Alias powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item -LiteralPath '$RemoteTempWin' -ErrorAction SilentlyContinue" | Out-Null
    }
}

function New-RemoteStatusScript {
    param(
        [hashtable]$Spec,
        [int]$JournalLines,
        [int]$LogLines
    )

    $Name = Quote-PowerShellString $Spec.Name
    $Alias = Quote-PowerShellString $Spec.Alias
    $RepoRoot = Quote-PowerShellString $Spec.RepoRoot
    $RuntimeRoot = Quote-PowerShellString $Spec.RuntimeRoot
    $ConfigPath = Quote-PowerShellString $Spec.ConfigPath
    $TaskName = Quote-PowerShellString $Spec.TaskName
    $StartupAlertTaskName = Quote-PowerShellString $Spec.StartupAlertTaskName
    $StateFileName = Quote-PowerShellString $Spec.StateFileName
    $JournalFileName = Quote-PowerShellString $Spec.JournalFileName
    $HeartbeatFileName = Quote-PowerShellString $Spec.HeartbeatFileName
    $LogFilter = Quote-PowerShellString $Spec.LogFilter
    $Magic = [int]$Spec.Magic
    $CommentPrefix = Quote-PowerShellString $Spec.CommentPrefix

    return @"
`$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest
`$Name = $Name
`$Alias = $Alias
`$RepoRoot = $RepoRoot
`$RuntimeRoot = $RuntimeRoot
`$ConfigPath = $ConfigPath
`$TaskName = $TaskName
`$StartupAlertTaskName = $StartupAlertTaskName
`$StateFileName = $StateFileName
`$JournalFileName = $JournalFileName
`$HeartbeatFileName = $HeartbeatFileName
`$LogFilter = $LogFilter
`$Magic = $Magic
`$CommentPrefix = $CommentPrefix

Write-Output "## `$Name"
Write-Output "checked_at=$((Get-Date).ToString("o"))"
Write-Output "ssh_alias=`$Alias"
Write-Output "hostname=`$(hostname)"
Write-Output "whoami=`$(whoami)"
Write-Output "repo_root=`$RepoRoot"
Write-Output "runtime_root=`$RuntimeRoot"
Write-Output "config_path=`$ConfigPath"
Write-Output "task_name=`$TaskName"
Write-Output "startup_alert_task_name=`$StartupAlertTaskName"
Write-Output "strategy_magic=`$Magic"
Write-Output "comment_prefix=`$CommentPrefix"

if (Test-Path -LiteralPath `$RepoRoot) {
    Set-Location `$RepoRoot
    Write-Output ""
    Write-Output "### Repo"
    `$GitExe = "git"
    if (-not (Get-Command `$GitExe -ErrorAction SilentlyContinue)) {
        foreach (`$Candidate in @("C:\Program Files\Git\cmd\git.exe", "C:\Program Files\Git\bin\git.exe")) {
            if (Test-Path -LiteralPath `$Candidate) {
                `$GitExe = `$Candidate
                break
            }
        }
    }
    try { Write-Output "git_head=`$((& `$GitExe rev-parse --short HEAD).Trim())" } catch { Write-Output "git_head=error `$(`$_.Exception.Message)" }
    try { Write-Output "git_branch=`$((& `$GitExe branch --show-current).Trim())" } catch { Write-Output "git_branch=error `$(`$_.Exception.Message)" }
    try { Write-Output "git_status=`$(((& `$GitExe status --short --branch) -join ' | ').Trim())" } catch { Write-Output "git_status=error `$(`$_.Exception.Message)" }
} else {
    Write-Output ""
    Write-Output "### Repo"
    Write-Output "repo=missing"
}

Write-Output ""
Write-Output "### Scheduled Task"
`$Task = Get-ScheduledTask -TaskName `$TaskName -ErrorAction SilentlyContinue
if (`$null -eq `$Task) {
    Write-Output "task_state=missing"
} else {
    Write-Output "task_state=`$(`$Task.State)"
    `$TaskInfo = Get-ScheduledTaskInfo -TaskName `$TaskName -ErrorAction SilentlyContinue
    if (`$null -ne `$TaskInfo) {
        Write-Output "task_last_run_time=`$(`$TaskInfo.LastRunTime.ToString("o"))"
        if (`$null -ne `$TaskInfo.NextRunTime) {
            Write-Output "task_next_run_time=`$(`$TaskInfo.NextRunTime.ToString("o"))"
        } else {
            Write-Output "task_next_run_time="
        }
        Write-Output "task_last_result=`$(`$TaskInfo.LastTaskResult)"
    }
}

Write-Output ""
Write-Output "### Startup Alert Task"
`$StartupTask = Get-ScheduledTask -TaskName `$StartupAlertTaskName -ErrorAction SilentlyContinue
if (`$null -eq `$StartupTask) {
    Write-Output "startup_alert_task_state=missing"
} else {
    Write-Output "startup_alert_task_state=`$(`$StartupTask.State)"
    `$StartupTaskInfo = Get-ScheduledTaskInfo -TaskName `$StartupAlertTaskName -ErrorAction SilentlyContinue
    if (`$null -ne `$StartupTaskInfo) {
        Write-Output "startup_alert_last_run_time=`$(`$StartupTaskInfo.LastRunTime.ToString("o"))"
        Write-Output "startup_alert_last_result=`$(`$StartupTaskInfo.LastTaskResult)"
    }
}

if (Test-Path -LiteralPath `$ConfigPath) {
    Write-Output ""
    Write-Output "### Sanitized Config"
    try {
        `$Config = Get-Content -LiteralPath `$ConfigPath -Raw | ConvertFrom-Json
        foreach (`$SectionName in @("dry_run", "live_send")) {
            if (`$Config.PSObject.Properties.Name -contains `$SectionName) {
                `$Section = `$Config.`$SectionName
                foreach (`$PropertyName in @("execution_mode", "live_send_enabled", "risk_bucket_scale", "max_risk_pct_per_trade", "max_open_risk_pct", "strategy_magic", "order_comment_prefix")) {
                    if (`$Section.PSObject.Properties.Name -contains `$PropertyName) {
                        Write-Output "`$SectionName.`$PropertyName=`$(`$Section.`$PropertyName)"
                    }
                }
                if (`$Section.PSObject.Properties.Name -contains "symbols") {
                    Write-Output "`$SectionName.symbol_count=`$(@(`$Section.symbols).Count)"
                }
            }
        }
        if (`$Config.PSObject.Properties.Name -contains "mt5") {
            Write-Output "mt5.expected_server=`$(`$Config.mt5.expected_server)"
        }
    } catch {
        Write-Output "config_parse_error=`$(`$_.Exception.Message)"
    }
} else {
    Write-Output ""
    Write-Output "### Sanitized Config"
    Write-Output "config=missing"
}

Write-Output ""
Write-Output "### Runtime Status"
if (Test-Path -LiteralPath (Join-Path `$RepoRoot "scripts\Get-LpfsLiveStatus.ps1")) {
    `$StatusParams = @{
        RuntimeRoot = `$RuntimeRoot
        StateFileName = `$StateFileName
        JournalFileName = `$JournalFileName
        HeartbeatFileName = `$HeartbeatFileName
        LogFilter = `$LogFilter
        JournalLines = $JournalLines
        LogLines = $LogLines
    }
    & (Join-Path `$RepoRoot "scripts\Get-LpfsLiveStatus.ps1") @StatusParams
} else {
    Write-Output "status_script=missing"
}

Write-Output ""
Write-Output "### Broker And State Snapshot"
`$SnapshotScript = @'
import json
from pathlib import Path

name = r"""$($Spec.Name)"""
runtime_root = Path(r"""$($Spec.RuntimeRoot)""")
state_name = r"""$($Spec.StateFileName)"""
journal_name = r"""$($Spec.JournalFileName)"""
config_path = Path(r"""$($Spec.ConfigPath)""")
magic = int(r"""$($Spec.Magic)""")
comment_prefix = r"""$($Spec.CommentPrefix)"""

def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"_error": str(exc), "_path": str(path)}

def tail_jsonl(path, limit=300):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    except Exception:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows

def mask_login(value):
    if value is None:
        return None
    text = str(value)
    if len(text) <= 4:
        return "***" + text
    return "***" + text[-4:]

live_dir = runtime_root / "data" / "live"
state_path = live_dir / state_name
journal_path = live_dir / journal_name
state = read_json(state_path)
journal_rows = tail_jsonl(journal_path)

open_state_items = []
if isinstance(state, dict):
    for bucket in ("pending_orders", "active_positions"):
        for item in state.get(bucket, []) or []:
            if not isinstance(item, dict):
                continue
            open_state_items.append({
                "bucket": bucket,
                "symbol": item.get("symbol"),
                "timeframe": item.get("timeframe"),
                "side": item.get("side"),
                "signal_key": item.get("signal_key"),
                "setup_id": item.get("setup_id"),
                "volume": item.get("volume"),
                "target_risk_pct": item.get("target_risk_pct"),
                "actual_risk_pct": item.get("actual_risk_pct"),
                "order_ticket": item.get("order_ticket"),
                "position_id": item.get("position_id"),
                "comment": item.get("comment"),
            })

recent_signal_rows = []
for row in journal_rows:
    if not isinstance(row, dict):
        continue
    if row.get("signal_key") or row.get("symbol") or row.get("timeframe"):
        recent_signal_rows.append({
            "event": row.get("event"),
            "status": row.get("status"),
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "signal_key": row.get("signal_key"),
            "order_ticket": row.get("order_ticket"),
            "order_send_retcode": row.get("order_send_retcode"),
            "occurred_at_utc": row.get("occurred_at_utc"),
        })
recent_signal_rows = recent_signal_rows[-20:]

broker = {"available": False}
try:
    import MetaTrader5 as mt5

    if mt5.initialize():
        account = mt5.account_info()
        terminal = mt5.terminal_info()
        orders = mt5.orders_get() or ()
        positions = mt5.positions_get() or ()

        def keep(item):
            item_magic = int(getattr(item, "magic", 0) or 0)
            item_comment = str(getattr(item, "comment", "") or "")
            return item_magic == magic or item_comment.startswith(comment_prefix)

        def normalize_order(item):
            return {
                "ticket": int(getattr(item, "ticket", 0) or 0),
                "symbol": getattr(item, "symbol", ""),
                "type": int(getattr(item, "type", 0) or 0),
                "volume_current": float(getattr(item, "volume_current", 0.0) or 0.0),
                "price_open": float(getattr(item, "price_open", 0.0) or 0.0),
                "sl": float(getattr(item, "sl", 0.0) or 0.0),
                "tp": float(getattr(item, "tp", 0.0) or 0.0),
                "magic": int(getattr(item, "magic", 0) or 0),
                "comment": str(getattr(item, "comment", "") or ""),
            }

        def normalize_position(item):
            return {
                "ticket": int(getattr(item, "ticket", 0) or 0),
                "identifier": int(getattr(item, "identifier", 0) or 0),
                "symbol": getattr(item, "symbol", ""),
                "type": int(getattr(item, "type", 0) or 0),
                "volume": float(getattr(item, "volume", 0.0) or 0.0),
                "price_open": float(getattr(item, "price_open", 0.0) or 0.0),
                "sl": float(getattr(item, "sl", 0.0) or 0.0),
                "tp": float(getattr(item, "tp", 0.0) or 0.0),
                "profit": float(getattr(item, "profit", 0.0) or 0.0),
                "magic": int(getattr(item, "magic", 0) or 0),
                "comment": str(getattr(item, "comment", "") or ""),
            }

        broker = {
            "available": True,
            "account_login_tail": mask_login(getattr(account, "login", None)) if account else None,
            "server": getattr(account, "server", None) if account else None,
            "company": getattr(account, "company", None) if account else None,
            "currency": getattr(account, "currency", None) if account else None,
            "trade_allowed": bool(getattr(account, "trade_allowed", False)) if account else None,
            "terminal_connected": bool(getattr(terminal, "connected", False)) if terminal else None,
            "terminal_trade_allowed": bool(getattr(terminal, "trade_allowed", False)) if terminal else None,
            "strategy_orders": [normalize_order(item) for item in orders if keep(item)],
            "strategy_positions": [normalize_position(item) for item in positions if keep(item)],
        }
    else:
        broker = {"available": False, "error": str(mt5.last_error())}
except Exception as exc:
    broker = {"available": False, "error": str(exc)}

snapshot = {
    "name": name,
    "state_path": str(state_path),
    "journal_path": str(journal_path),
    "state_error": state.get("_error") if isinstance(state, dict) else "state_not_dict",
    "processed_signal_keys": len(state.get("processed_signal_keys", []) or []) if isinstance(state, dict) else 0,
    "order_checked_signal_keys": len(state.get("order_checked_signal_keys", []) or []) if isinstance(state, dict) else 0,
    "open_state_items": open_state_items,
    "recent_signal_rows": recent_signal_rows,
    "broker": broker,
}
print("LPFS_SNAPSHOT_JSON=" + json.dumps(snapshot, separators=(",", ":"), sort_keys=True))
print(json.dumps(snapshot, indent=2, sort_keys=True))
'@

`$PythonPath = Join-Path `$RepoRoot "venv\Scripts\python.exe"
if (Test-Path -LiteralPath `$PythonPath) {
    `$SnapshotTemp = Join-Path `$env:TEMP "lpfs_snapshot_`$PID.py"
    `$SnapshotScript | Set-Content -LiteralPath `$SnapshotTemp -Encoding UTF8
    try {
        & `$PythonPath `$SnapshotTemp
    } finally {
        Remove-Item -LiteralPath `$SnapshotTemp -ErrorAction SilentlyContinue
    }
} else {
    Write-Output "broker_snapshot=python_missing"
}
"@
}

function ConvertFrom-SnapshotLine {
    param([string[]]$Lines)

    foreach ($Line in $Lines) {
        if ($Line.StartsWith("LPFS_SNAPSHOT_JSON=")) {
            try {
                return ($Line.Substring("LPFS_SNAPSHOT_JSON=".Length) | ConvertFrom-Json)
            } catch {
                return $null
            }
        }
    }
    return $null
}

function Get-OpenSignalKeySet {
    param([object]$Snapshot)

    $Keys = New-Object System.Collections.Generic.HashSet[string]
    if ($null -eq $Snapshot) {
        return ,$Keys
    }
    foreach ($Item in @($Snapshot.open_state_items)) {
        if ($null -ne $Item.signal_key -and -not [string]::IsNullOrWhiteSpace([string]$Item.signal_key)) {
            [void]$Keys.Add([string]$Item.signal_key)
        }
    }
    return ,$Keys
}

$Specs = @(
    @{
        Name = "FTMO VPS"
        Alias = "lpfs-vps"
        RepoRoot = "C:\TradeAutomation"
        RuntimeRoot = "C:\TradeAutomationRuntime"
        ConfigPath = "C:\TradeAutomation\config.local.json"
        TaskName = "LPFS_Live"
        StartupAlertTaskName = "LPFS_FTMO_Startup_Alert"
        StateFileName = "lpfs_live_state.json"
        JournalFileName = "lpfs_live_journal.jsonl"
        HeartbeatFileName = "lpfs_live_heartbeat.json"
        LogFilter = "lpfs_live_*.log"
        Magic = 131500
        CommentPrefix = "LPFS"
    },
    @{
        Name = "IC Markets VPS"
        Alias = "lpfs-ic-vps"
        RepoRoot = "C:\TradeAutomation"
        RuntimeRoot = "C:\TradeAutomationRuntimeIC"
        ConfigPath = "C:\TradeAutomation\config.lpfs_icmarkets_raw_spread.local.json"
        TaskName = "LPFS_IC_Live"
        StartupAlertTaskName = "LPFS_IC_Startup_Alert"
        StateFileName = "lpfs_ic_live_state.json"
        JournalFileName = "lpfs_ic_live_journal.jsonl"
        HeartbeatFileName = "lpfs_ic_live_heartbeat.json"
        LogFilter = "lpfs_ic_live_*.log"
        Magic = 231500
        CommentPrefix = "LPFSIC"
    }
)

$CheckedAt = Get-Date
$Sections = New-Object System.Collections.Generic.List[string]
$Snapshots = @{}

foreach ($Spec in $Specs) {
    $Script = New-RemoteStatusScript -Spec $Spec -JournalLines $JournalLines -LogLines $LogLines
    $Lines = @(Invoke-RemotePowerShell -Alias $Spec.Alias -Script $Script)
    $Sections.Add(($Lines -join [Environment]::NewLine))
    $Snapshots[$Spec.Name] = ConvertFrom-SnapshotLine -Lines $Lines
}

$Ftmo = $Snapshots["FTMO VPS"]
$Ic = $Snapshots["IC Markets VPS"]
$ComparisonLines = New-Object System.Collections.Generic.List[string]
$ComparisonLines.Add("## Cross-Account Comparison")
$ComparisonLines.Add("checked_at=$($CheckedAt.ToString("o"))")
$ComparisonLines.Add("expected_relationship=same_strategy_signal_family_different_broker_data_and_sizing")

if ($null -ne $Ftmo -and $null -ne $Ic) {
    $FtmoKeys = Get-OpenSignalKeySet -Snapshot $Ftmo
    $IcKeys = Get-OpenSignalKeySet -Snapshot $Ic
    $Shared = @($FtmoKeys | Where-Object { $IcKeys.Contains($_) } | Sort-Object)
    $OnlyFtmo = @($FtmoKeys | Where-Object { -not $IcKeys.Contains($_) } | Sort-Object)
    $OnlyIc = @($IcKeys | Where-Object { -not $FtmoKeys.Contains($_) } | Sort-Object)

    $ComparisonLines.Add("ftmo_open_state_items=$(@($Ftmo.open_state_items).Count)")
    $ComparisonLines.Add("ic_open_state_items=$(@($Ic.open_state_items).Count)")
    $ComparisonLines.Add("shared_open_signal_keys=$($Shared.Count)")
    $ComparisonLines.Add("ftmo_only_open_signal_keys=$($OnlyFtmo.Count)")
    $ComparisonLines.Add("ic_only_open_signal_keys=$($OnlyIc.Count)")
    if ($OnlyFtmo.Count -gt 0) {
        $ComparisonLines.Add("ftmo_only=$($OnlyFtmo -join ',')")
    }
    if ($OnlyIc.Count -gt 0) {
        $ComparisonLines.Add("ic_only=$($OnlyIc -join ',')")
    }
    $ComparisonLines.Add("note=Signal keys may differ while IC is newly started or when broker candle feeds differ; inspect journals before treating a delta as a defect.")
} else {
    $ComparisonLines.Add("comparison=unavailable_snapshot_missing")
}

$Report = @(
    "# LPFS Dual VPS Status",
    "",
    "Generated: $($CheckedAt.ToString("o"))",
    "",
    ($ComparisonLines -join [Environment]::NewLine),
    "",
    ($Sections -join ([Environment]::NewLine + [Environment]::NewLine + "---" + [Environment]::NewLine + [Environment]::NewLine))
) -join [Environment]::NewLine

Write-Output $Report

if (-not $NoReport) {
    $ResolvedOutputDir = if ([System.IO.Path]::IsPathRooted($OutputDir)) {
        $OutputDir
    } else {
        Join-Path (Get-Location) $OutputDir
    }
    New-Item -ItemType Directory -Force -Path $ResolvedOutputDir | Out-Null
    $FileName = "lpfs_dual_vps_status_$($CheckedAt.ToString("yyyyMMdd_HHmmss")).md"
    $OutputPath = Join-Path $ResolvedOutputDir $FileName
    $Report | Set-Content -LiteralPath $OutputPath -Encoding UTF8
    Write-Output ""
    Write-Output "report_path=$OutputPath"
}
