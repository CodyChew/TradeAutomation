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

    $SshOptions = @("-o", "BatchMode=yes", "-o", "ConnectTimeout=15")
    $RunId = [Guid]::NewGuid().ToString("N")
    $LocalTemp = Join-Path ([IO.Path]::GetTempPath()) "lpfs_dual_status_$RunId.ps1"
    $RemoteTempWin = "C:\Windows\Temp\lpfs_dual_status_$RunId.ps1"
    $RemoteTempScp = "C:/Windows/Temp/lpfs_dual_status_$RunId.ps1"

    $Script | Set-Content -LiteralPath $LocalTemp -Encoding UTF8
    try {
        & scp @SshOptions $LocalTemp "${Alias}:$RemoteTempScp" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "scp failed for $Alias"
        }
        & ssh @SshOptions $Alias powershell -NoProfile -ExecutionPolicy Bypass -File $RemoteTempWin
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "remote status script exited with code $LASTEXITCODE on $Alias"
        }
    } finally {
        Remove-Item -LiteralPath $LocalTemp -ErrorAction SilentlyContinue
        & ssh @SshOptions $Alias powershell -NoProfile -ExecutionPolicy Bypass -Command "Remove-Item -LiteralPath '$RemoteTempWin' -ErrorAction SilentlyContinue" | Out-Null
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
    Write-Output "task_multiple_instances=`$(`$Task.Settings.MultipleInstances)"
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
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_MARKET_SNAPSHOT_JOURNAL_MAX_BYTES = 536870912
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

def tail_lines(path, limit):
    try:
        limit = max(0, int(limit))
    except Exception:
        limit = 0
    if limit <= 0:
        return []
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            position = handle.tell()
            if position <= 0:
                return []
            chunks = []
            newline_count = 0
            block_size = 64 * 1024
            while position > 0 and newline_count <= limit:
                read_size = min(block_size, position)
                position -= read_size
                handle.seek(position)
                chunk = handle.read(read_size)
                chunks.append(chunk)
                newline_count += chunk.count(b"\n")
        data = b"".join(reversed(chunks))
        return data.decode("utf-8", errors="replace").splitlines()[-limit:]
    except Exception:
        return []

def tail_jsonl(path, limit=300):
    lines = tail_lines(path, limit)
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

def file_sha256(path):
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception as exc:
        return "ERROR:" + str(exc)

def market_snapshot_journal_name(journal_file_name):
    value = str(journal_file_name or "lpfs_live_journal.jsonl")
    if value == "lpfs_live_journal.jsonl":
        return "lpfs_live_market_snapshots.jsonl"
    if value.endswith("_journal.jsonl"):
        return value[: -len("_journal.jsonl")] + "_market_snapshots.jsonl"
    if value.endswith(".jsonl"):
        return value[: -len(".jsonl")] + "_market_snapshots.jsonl"
    return value + "_market_snapshots.jsonl"

def file_metadata(path):
    path = Path(path)
    if not path.exists():
        return {"path": str(path), "size_bytes": 0, "mtime": ""}
    stat = path.stat()
    return {
        "path": str(path),
        "size_bytes": int(stat.st_size),
        "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }

def run_command(args, timeout=20):
    try:
        completed = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
        return {
            "args": args,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except Exception as exc:
        return {"args": args, "error": str(exc), "stdout": "", "stderr": ""}

def read_config_summary(path):
    summary = {
        "exists": path.exists(),
        "sha256": file_sha256(path) if path.exists() else None,
        "live_send_market_recovery_mode": None,
        "market_snapshot_journal_max_bytes": DEFAULT_MARKET_SNAPSHOT_JOURNAL_MAX_BYTES,
    }
    if not path.exists():
        return summary
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        live_send = payload.get("live_send") if isinstance(payload, dict) else None
        if isinstance(live_send, dict):
            summary["live_send_market_recovery_mode"] = live_send.get("market_recovery_mode")
            summary["market_snapshot_journal_max_bytes"] = int(
                live_send.get("market_snapshot_journal_max_bytes", DEFAULT_MARKET_SNAPSHOT_JOURNAL_MAX_BYTES)
            )
    except Exception as exc:
        summary["parse_error"] = str(exc)
    return summary

def task_summary(task_name):
    completed = run_command(["schtasks.exe", "/Query", "/TN", task_name, "/FO", "LIST", "/V"])
    parsed = {}
    for line in completed.get("stdout", "").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            parsed[key.strip()] = value.strip()
    return {
        "returncode": completed.get("returncode"),
        "stderr": completed.get("stderr"),
        "status": parsed.get("Status"),
        "scheduled_state": parsed.get("Scheduled Task State"),
        "last_result": parsed.get("Last Result"),
    }

def process_summary():
    completed = run_command(["wmic", "process", "get", "ProcessId,ParentProcessId,CommandLine", "/format:csv"])
    probe_trusted = (
        completed.get("returncode") == 0
        and not completed.get("error")
        and bool(str(completed.get("stdout") or "").strip())
        and not bool(str(completed.get("stderr") or "").strip())
    )
    if not probe_trusted:
        return {
            "returncode": completed.get("returncode"),
            "stderr": completed.get("stderr"),
            "error": completed.get("error"),
            "probe_trusted": False,
            "watchdog_process_rows": None,
            "runner_process_rows": None,
            "logical_runner_paths": None,
            "process_shape": "probe_untrusted",
        }
    watchdog_rows = []
    runner_rows = []
    for line in completed.get("stdout", "").splitlines():
        lowered = line.lower()
        if "run_lpfs_live_forever.ps1" in lowered and str(runtime_root).lower() in lowered:
            watchdog_rows.append(line)
        if "run_lp_force_strike_live_executor.py" in lowered and str(runtime_root).lower() in lowered:
            runner_rows.append(line)
    watchdog_count = len(watchdog_rows)
    runner_count = len(runner_rows)
    if watchdog_count == 1 and 1 <= runner_count <= 2:
        logical_runner_paths = 1
        shape = "watchdog_with_runner_chain"
    elif watchdog_count == 0 and 1 <= runner_count <= 2:
        logical_runner_paths = 1
        shape = "direct_runner_chain"
    elif watchdog_count == 0 and runner_count == 0:
        logical_runner_paths = 0
        shape = "stopped"
    else:
        logical_runner_paths = max(watchdog_count, runner_count)
        shape = "ambiguous"
    return {
        "returncode": completed.get("returncode"),
        "stderr": completed.get("stderr"),
        "error": completed.get("error"),
        "probe_trusted": True,
        "watchdog_process_rows": watchdog_count,
        "runner_process_rows": runner_count,
        "logical_runner_paths": logical_runner_paths,
        "process_shape": shape,
    }

def parse_utc(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None

def heartbeat_summary(path):
    summary = {"exists": path.exists(), "status": None, "updated_at_utc": None, "age_seconds": None, "fresh": False, "last_cycle": {}}
    if not path.exists():
        return summary
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        summary["status"] = payload.get("status")
        summary["updated_at_utc"] = payload.get("updated_at_utc")
        summary["last_cycle"] = payload.get("last_cycle") if isinstance(payload.get("last_cycle"), dict) else {}
        summary["market_snapshot_journal_path"] = payload.get("market_snapshot_journal_path")
        summary["market_snapshot_journal_max_bytes"] = payload.get("market_snapshot_journal_max_bytes")
        updated = parse_utc(summary["updated_at_utc"])
        if updated is not None:
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds()
            summary["age_seconds"] = round(age, 3)
            summary["fresh"] = age <= 300
    except Exception as exc:
        summary["parse_error"] = str(exc)
    return summary

def classify_lane(kill_switch_active, task, processes, heartbeat, broker):
    broker_available = bool(broker.get("available"))
    broker_status = "OK" if broker_available else "ERROR/UNKNOWN"
    task_status = task.get("status")
    task_state = task.get("scheduled_state")
    process_probe_trusted = bool(processes.get("probe_trusted"))
    logical_paths = processes.get("logical_runner_paths") if process_probe_trusted else None
    pending_order_count = len(broker.get("strategy_orders") or []) if broker_available else None
    position_count = len(broker.get("strategy_positions") or []) if broker_available else None

    if not process_probe_trusted:
        state = "AMBIGUOUS"
        reason = "process_probe_untrusted"
    elif (
        not kill_switch_active
        and task_status == "Running"
        and task_state == "Enabled"
        and logical_paths == 1
        and heartbeat.get("status") == "running"
        and bool(heartbeat.get("fresh"))
        and broker_available
    ):
        state = "RUNNING"
        reason = "task_running_kill_clear_one_logical_runner_fresh_heartbeat_broker_ok"
    elif kill_switch_active and task_state == "Disabled" and logical_paths == 0:
        state = "PAUSED"
        reason = "kill_switch_active_task_disabled_no_runner"
    else:
        state = "AMBIGUOUS"
        reason = "state_signals_conflict_or_incomplete"

    return {
        "lane_state_summary": state,
        "lane_state_reason": reason,
        "kill_switch_active": kill_switch_active,
        "task_status": task_status,
        "task_scheduled_state": task_state,
        "task_last_result": task.get("last_result"),
        "runner_process_rows": processes.get("runner_process_rows"),
        "watchdog_process_rows": processes.get("watchdog_process_rows"),
        "logical_runner_paths": logical_paths,
        "process_shape": processes.get("process_shape"),
        "process_probe_trusted": process_probe_trusted,
        "process_probe_error": processes.get("error"),
        "heartbeat_status": heartbeat.get("status"),
        "heartbeat_age_seconds": heartbeat.get("age_seconds"),
        "heartbeat_fresh": heartbeat.get("fresh"),
        "broker_status": broker_status,
        "pending_strategy_order_count": pending_order_count,
        "strategy_position_count": position_count,
    }

live_dir = runtime_root / "data" / "live"
state_path = live_dir / state_name
journal_path = live_dir / journal_name
market_snapshot_journal_path = live_dir / market_snapshot_journal_name(journal_name)
kill_switch_path = live_dir / "KILL_SWITCH"
heartbeat_path = live_dir / r"""$($Spec.HeartbeatFileName)"""
config_summary = read_config_summary(config_path)
task = task_summary(r"""$($Spec.TaskName)""")
processes = process_summary()
heartbeat = heartbeat_summary(heartbeat_path)
state_document = read_json(state_path)
if isinstance(state_document, dict) and state_document.get("state_schema_version") == 2:
    state = state_document.get("state", {})
else:
    state = state_document
journal_rows = tail_jsonl(journal_path)
lifecycle_journal = file_metadata(journal_path)
market_snapshot_journal = file_metadata(market_snapshot_journal_path)

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
        if account is None:
            raise RuntimeError("account_info=ERROR/UNKNOWN last_error=" + repr(mt5.last_error()))
        if terminal is None:
            raise RuntimeError("terminal_info=ERROR/UNKNOWN last_error=" + repr(mt5.last_error()))
        orders = mt5.orders_get()
        if orders is None:
            raise RuntimeError("orders_get=ERROR/UNKNOWN last_error=" + repr(mt5.last_error()))
        positions = mt5.positions_get()
        if positions is None:
            raise RuntimeError("positions_get=ERROR/UNKNOWN last_error=" + repr(mt5.last_error()))

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

operational_summary = classify_lane(kill_switch_path.exists(), task, processes, heartbeat, broker)

snapshot = {
    "name": name,
    "state_path": str(state_path),
    "journal_path": str(journal_path),
    "lifecycle_journal": lifecycle_journal,
    "market_snapshot_journal": market_snapshot_journal,
    "market_snapshot_journal_max_bytes": heartbeat.get("market_snapshot_journal_max_bytes") or config_summary.get("market_snapshot_journal_max_bytes"),
    "config_path": str(config_path),
    "config": config_summary,
    "task": task,
    "processes": processes,
    "heartbeat": heartbeat,
    "operational_summary": operational_summary,
    "state_schema_version": state_document.get("state_schema_version", 1) if isinstance(state_document, dict) else None,
    "state_error": state_document.get("_error") if isinstance(state_document, dict) else "state_not_dict",
    "processed_signal_keys": len(state.get("processed_signal_keys", []) or []) if isinstance(state, dict) else 0,
    "order_checked_signal_keys": len(state.get("order_checked_signal_keys", []) or []) if isinstance(state, dict) else 0,
    "open_state_items": open_state_items,
    "recent_signal_rows": recent_signal_rows,
    "broker": broker,
}
print("### Lane State Summary")
print("lane_state_summary=" + str(operational_summary["lane_state_summary"]))
print("lane_state_reason=" + str(operational_summary["lane_state_reason"]))
print("kill_switch_active=" + str(operational_summary["kill_switch_active"]))
print("task_status=" + str(operational_summary["task_status"]))
print("task_scheduled_state=" + str(operational_summary["task_scheduled_state"]))
print("runner_process_rows=" + str(operational_summary["runner_process_rows"]))
print("watchdog_process_rows=" + str(operational_summary["watchdog_process_rows"]))
print("logical_runner_paths=" + str(operational_summary["logical_runner_paths"]))
print("process_shape=" + str(operational_summary["process_shape"]))
print("process_probe_trusted=" + str(operational_summary["process_probe_trusted"]))
print("process_probe_error=" + str(operational_summary["process_probe_error"]))
print("heartbeat_status=" + str(operational_summary["heartbeat_status"]))
print("heartbeat_age_seconds=" + str(operational_summary["heartbeat_age_seconds"]))
print("heartbeat_fresh=" + str(operational_summary["heartbeat_fresh"]))
print("broker_status=" + str(operational_summary["broker_status"]))
print("pending_strategy_order_count=" + str(operational_summary["pending_strategy_order_count"]))
print("strategy_position_count=" + str(operational_summary["strategy_position_count"]))
print("lifecycle_journal_path=" + str(lifecycle_journal["path"]))
print("lifecycle_journal_size_bytes=" + str(lifecycle_journal["size_bytes"]))
print("lifecycle_journal_mtime=" + str(lifecycle_journal["mtime"]))
print("market_snapshot_journal_path=" + str(market_snapshot_journal["path"]))
print("market_snapshot_journal_size_bytes=" + str(market_snapshot_journal["size_bytes"]))
print("market_snapshot_journal_mtime=" + str(market_snapshot_journal["mtime"]))
print("market_snapshot_journal_max_bytes=" + str(snapshot["market_snapshot_journal_max_bytes"]))
print("market_snapshot_telemetry_write_failure_count=" + str(heartbeat.get("last_cycle", {}).get("market_snapshot_telemetry_write_failures", 0)))
print("market_snapshot_telemetry_retention_failure_count=" + str(heartbeat.get("last_cycle", {}).get("market_snapshot_telemetry_retention_failures", 0)))
print("latest_market_snapshot_telemetry_write_error=" + str(heartbeat.get("last_cycle", {}).get("latest_market_snapshot_telemetry_write_error", "")))
print("latest_market_snapshot_telemetry_retention_error=" + str(heartbeat.get("last_cycle", {}).get("latest_market_snapshot_telemetry_retention_error", "")))
print("config_sha256=" + str(config_summary.get("sha256")))
print("live_send.market_recovery_mode=" + str(config_summary.get("live_send_market_recovery_mode")))
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
