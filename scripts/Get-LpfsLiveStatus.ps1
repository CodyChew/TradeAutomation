[CmdletBinding()]
param(
    [string]$RuntimeRoot = "C:\TradeAutomationRuntime",
    [string]$StateFileName = "lpfs_live_state.json",
    [string]$JournalFileName = "lpfs_live_journal.jsonl",
    [string]$MarketSnapshotJournalFileName = "",
    [string]$HeartbeatFileName = "lpfs_live_heartbeat.json",
    [string]$LogFilter = "*.log",
    [int]$JournalLines = 10,
    [int]$LogLines = 20
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$LiveDir = Join-Path $RuntimeRoot "data\live"
$StatePath = Join-Path $LiveDir $StateFileName
$JournalPath = Join-Path $LiveDir $JournalFileName
if ([string]::IsNullOrWhiteSpace($MarketSnapshotJournalFileName)) {
    if ($JournalFileName -eq "lpfs_live_journal.jsonl") {
        $MarketSnapshotJournalFileName = "lpfs_live_market_snapshots.jsonl"
    } elseif ($JournalFileName.EndsWith("_journal.jsonl")) {
        $MarketSnapshotJournalFileName = $JournalFileName.Substring(0, $JournalFileName.Length - "_journal.jsonl".Length) + "_market_snapshots.jsonl"
    } elseif ($JournalFileName.EndsWith(".jsonl")) {
        $MarketSnapshotJournalFileName = $JournalFileName.Substring(0, $JournalFileName.Length - ".jsonl".Length) + "_market_snapshots.jsonl"
    } else {
        $MarketSnapshotJournalFileName = "$($JournalFileName)_market_snapshots.jsonl"
    }
}
$MarketSnapshotJournalPath = Join-Path $LiveDir $MarketSnapshotJournalFileName
$HeartbeatPath = Join-Path $LiveDir $HeartbeatFileName
$KillSwitchPath = Join-Path $LiveDir "KILL_SWITCH"
$LogDir = Join-Path $LiveDir "logs"

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    try {
        return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    } catch {
        Write-Host "Could not parse JSON: $Path"
        Write-Host $_.Exception.Message
        return $null
    }
}

function Get-JsonField {
    param(
        [object]$Object,
        [string]$Name,
        [string]$Default = ""
    )
    if ($null -eq $Object) {
        return $Default
    }
    if ($Object.PSObject.Properties.Name -contains $Name) {
        $Value = $Object.$Name
        if ($null -eq $Value) {
            return $Default
        }
        return "$Value"
    }
    return $Default
}

function Convert-ToOptionalInt {
    param([object]$Value)
    try {
        if ($null -eq $Value -or [string]::IsNullOrWhiteSpace("$Value")) {
            return $null
        }
        $Integer = [int64]$Value
        if ($Integer -eq 0) {
            return $null
        }
        return $Integer
    } catch {
        return $null
    }
}

function Write-FileMetadata {
    param(
        [string]$Prefix,
        [string]$Path
    )

    Write-Host "$($Prefix)_path=$Path"
    if (Test-Path -LiteralPath $Path) {
        $Item = Get-Item -LiteralPath $Path
        Write-Host "$($Prefix)_size_bytes=$($Item.Length)"
        Write-Host "$($Prefix)_mtime=$($Item.LastWriteTimeUtc.ToString("o"))"
    } else {
        Write-Host "$($Prefix)_size_bytes=0"
        Write-Host "$($Prefix)_mtime="
    }
}

function Write-DiskStatus {
    param([string]$Path)

    $Drive = Split-Path -Path $Path -Qualifier
    if ([string]::IsNullOrWhiteSpace($Drive)) {
        $Drive = Split-Path -Path (Get-Location).Path -Qualifier
    }
    if ([string]::IsNullOrWhiteSpace($Drive)) {
        Write-Host "disk_status=unknown"
        Write-Host "disk_error=could_not_resolve_drive"
        return
    }

    try {
        $Disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$Drive'"
        if ($null -eq $Disk -or $null -eq $Disk.Size -or $Disk.Size -le 0) {
            Write-Host "disk_drive=$Drive"
            Write-Host "disk_status=unknown"
            Write-Host "disk_error=drive_not_found"
            return
        }

        $FreeGb = [Math]::Round($Disk.FreeSpace / 1GB, 2)
        $SizeGb = [Math]::Round($Disk.Size / 1GB, 2)
        $FreePct = [Math]::Round(($Disk.FreeSpace / $Disk.Size) * 100, 1)
        $Status = "ok"
        if ($FreeGb -lt 10 -or $FreePct -lt 15) {
            $Status = "action_required"
        } elseif ($FreeGb -lt 15 -or $FreePct -lt 25) {
            $Status = "warn"
        }

        Write-Host "disk_drive=$Drive"
        Write-Host "disk_size_gb=$SizeGb"
        Write-Host "disk_free_gb=$FreeGb"
        Write-Host "disk_free_pct=$FreePct"
        Write-Host "disk_status=$Status"
        Write-Host "disk_policy=warn_below_15gb_or_25pct_action_below_10gb_or_15pct"
    } catch {
        Write-Host "disk_drive=$Drive"
        Write-Host "disk_status=unknown"
        Write-Host "disk_error=$($_.Exception.Message)"
    }
}

Write-Host "LPFS live status"
Write-Host "checked_at=$((Get-Date).ToString("o"))"
Write-Host "runtime_root=$RuntimeRoot"
Write-Host "kill_switch_active=$((Test-Path -LiteralPath $KillSwitchPath))"
if (Test-Path -LiteralPath $KillSwitchPath) {
    Write-Host "kill_switch_path=$KillSwitchPath"
    Write-Host "kill_switch_note=$((Get-Content -LiteralPath $KillSwitchPath -Raw).Trim())"
}

Write-Host ""
Write-DiskStatus -Path $RuntimeRoot

$Processes = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*run_lp_force_strike_live_executor.py*"
})
$ProcessById = @{}
foreach ($Process in $Processes) {
    $ProcessById[$Process.ProcessId] = $Process
}
$ChildEntries = @($Processes | Where-Object { $ProcessById.ContainsKey($_.ParentProcessId) })
Write-Host ""
Write-Host "processes=$($Processes.Count)"
if ($Processes.Count -eq 2 -and $ChildEntries.Count -ge 1) {
    Write-Host "process_note=two_entries_parent_child_windows_venv_launcher"
} elseif ($Processes.Count -gt 1) {
    Write-Host "process_note=multiple_entries_verify_parent_pid_exe_config_runtime"
}
foreach ($Process in $Processes) {
    Write-Host "pid=$($Process.ProcessId)"
    Write-Host "parent_pid=$($Process.ParentProcessId)"
    Write-Host "exe=$($Process.ExecutablePath)"
    Write-Host "command=$($Process.CommandLine)"
}

$Heartbeat = Read-JsonFile -Path $HeartbeatPath
Write-Host ""
Write-Host "heartbeat_path=$HeartbeatPath"
if ($null -eq $Heartbeat) {
    Write-Host "heartbeat=missing"
} else {
    foreach ($Field in @(
        "status",
        "updated_at_utc",
        "pid",
        "completed_cycles",
        "requested_cycles",
        "reconciliation_operation_id",
        "journal_rows_backfilled",
        "detail"
    )) {
        $Value = Get-JsonField -Object $Heartbeat -Name $Field
        if (-not [string]::IsNullOrWhiteSpace($Value)) {
            Write-Host "heartbeat_$Field=$Value"
        }
    }
    if ($Heartbeat.PSObject.Properties.Name -contains "last_cycle") {
        Write-Host "last_cycle=$($Heartbeat.last_cycle | ConvertTo-Json -Compress)"
    }
}

$State = Read-JsonFile -Path $StatePath
Write-Host ""
Write-Host "state_path=$StatePath"
if ($null -eq $State) {
    Write-Host "state=missing"
    Write-Host "state_active_position_ids="
    Write-Host "broker_active_position_ids=unavailable_single_lane_status"
    Write-Host "state_not_in_broker=unavailable_single_lane_status"
    Write-Host "broker_not_in_state=unavailable_single_lane_status"
    Write-Host "active_position_state_broker_mismatch_count=unavailable_single_lane_status"
} else {
    $StatePayload = $State
    if (($State.PSObject.Properties.Name -contains "state_schema_version") -and $State.state_schema_version -eq 2) {
        $StatePayload = $State.state
        Write-Host "state_schema_version=2"
    } else {
        Write-Host "state_schema_version=1"
    }
    $Processed = @($StatePayload.processed_signal_keys).Count
    $Pending = @($StatePayload.pending_orders).Count
    $Positions = @($StatePayload.active_positions).Count
    Write-Host "processed_signal_keys=$Processed"
    Write-Host "pending_orders=$Pending"
    Write-Host "active_positions=$Positions"
    $StateActivePositionIds = @()
    foreach ($Item in @($StatePayload.active_positions)) {
        $PositionId = Convert-ToOptionalInt -Value $Item.position_id
        if ($null -ne $PositionId) {
            $StateActivePositionIds += $PositionId
        }
    }
    $StateActivePositionIds = @($StateActivePositionIds | Sort-Object -Unique)
    Write-Host "state_active_position_ids=$($StateActivePositionIds -join ',')"
    Write-Host "broker_active_position_ids=unavailable_single_lane_status"
    Write-Host "state_not_in_broker=unavailable_single_lane_status"
    Write-Host "broker_not_in_state=unavailable_single_lane_status"
    Write-Host "active_position_state_broker_mismatch_count=unavailable_single_lane_status"
}

Write-Host ""
Write-Host "lifecycle_journal_path=$JournalPath"
if (Test-Path -LiteralPath $JournalPath) {
    $LifecycleJournalItem = Get-Item -LiteralPath $JournalPath
    Write-Host "lifecycle_journal_size_bytes=$($LifecycleJournalItem.Length)"
    Write-Host "lifecycle_journal_mtime=$($LifecycleJournalItem.LastWriteTimeUtc.ToString("o"))"
} else {
    Write-Host "lifecycle_journal_size_bytes=0"
    Write-Host "lifecycle_journal_mtime="
}
Write-Host "market_snapshot_journal_path=$MarketSnapshotJournalPath"
if (Test-Path -LiteralPath $MarketSnapshotJournalPath) {
    $MarketSnapshotJournalItem = Get-Item -LiteralPath $MarketSnapshotJournalPath
    Write-Host "market_snapshot_journal_size_bytes=$($MarketSnapshotJournalItem.Length)"
    Write-Host "market_snapshot_journal_mtime=$($MarketSnapshotJournalItem.LastWriteTimeUtc.ToString("o"))"
} else {
    Write-Host "market_snapshot_journal_size_bytes=0"
    Write-Host "market_snapshot_journal_mtime="
}
$MarketSnapshotMaxBytes = Get-JsonField -Object $Heartbeat -Name "market_snapshot_journal_max_bytes" -Default "536870912"
Write-Host "market_snapshot_journal_max_bytes=$MarketSnapshotMaxBytes"
$LastCycle = $null
if ($null -ne $Heartbeat -and $Heartbeat.PSObject.Properties.Name -contains "last_cycle") {
    $LastCycle = $Heartbeat.last_cycle
}
Write-Host "market_data_frames_skipped=$(Get-JsonField -Object $LastCycle -Name 'frames_skipped' -Default '0')"
Write-Host "market_data_fetch_failure_count=$(Get-JsonField -Object $LastCycle -Name 'market_data_fetch_failures' -Default '0')"
Write-Host "cycle_degraded=$(Get-JsonField -Object $LastCycle -Name 'cycle_degraded' -Default 'False')"
Write-Host "cycle_degraded_reason=$(Get-JsonField -Object $LastCycle -Name 'cycle_degraded_reason')"
Write-Host "latest_market_data_fetch_error=$(Get-JsonField -Object $LastCycle -Name 'latest_market_data_fetch_error')"
Write-Host "market_snapshot_telemetry_write_failure_count=$(Get-JsonField -Object $LastCycle -Name 'market_snapshot_telemetry_write_failures' -Default '0')"
Write-Host "market_snapshot_telemetry_retention_failure_count=$(Get-JsonField -Object $LastCycle -Name 'market_snapshot_telemetry_retention_failures' -Default '0')"
Write-Host "latest_market_snapshot_telemetry_write_error=$(Get-JsonField -Object $LastCycle -Name 'latest_market_snapshot_telemetry_write_error')"
Write-Host "latest_market_snapshot_telemetry_retention_error=$(Get-JsonField -Object $LastCycle -Name 'latest_market_snapshot_telemetry_retention_error')"
Write-Host "journal_path=$JournalPath"
if (Test-Path -LiteralPath $JournalPath) {
    $Rows = @(Get-Content -LiteralPath $JournalPath -Tail $JournalLines)
    foreach ($Line in $Rows) {
        try {
            $Row = $Line | ConvertFrom-Json
            $OccurredAt = Get-JsonField -Object $Row -Name "occurred_at_utc"
            $Event = Get-JsonField -Object $Row -Name "event"
            $Symbol = Get-JsonField -Object $Row -Name "symbol"
            $Timeframe = Get-JsonField -Object $Row -Name "timeframe"
            $Status = Get-JsonField -Object $Row -Name "status"
            $Ticket = Get-JsonField -Object $Row -Name "order_ticket"
            $Retcode = Get-JsonField -Object $Row -Name "order_send_retcode"
            $Parts = @($OccurredAt, "event=$Event")
            if (-not [string]::IsNullOrWhiteSpace($Symbol)) { $Parts += "symbol=$Symbol" }
            if (-not [string]::IsNullOrWhiteSpace($Timeframe)) { $Parts += "timeframe=$Timeframe" }
            if (-not [string]::IsNullOrWhiteSpace($Status)) { $Parts += "status=$Status" }
            if (-not [string]::IsNullOrWhiteSpace($Ticket)) { $Parts += "order_ticket=$Ticket" }
            if (-not [string]::IsNullOrWhiteSpace($Retcode)) { $Parts += "order_send_retcode=$Retcode" }
            Write-Host ($Parts -join " ")
        } catch {
            $Preview = $Line
            if ($Preview.Length -gt 240) {
                $Preview = $Preview.Substring(0, 237) + "..."
            }
            Write-Host "unparsed_journal_row=$Preview"
        }
    }
} else {
    Write-Host "journal=missing"
}

Write-Host ""
Write-Host "latest_log_dir=$LogDir"
if (Test-Path -LiteralPath $LogDir) {
    $LatestLog = Get-ChildItem -LiteralPath $LogDir -Filter $LogFilter | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -ne $LatestLog) {
        Write-Host "latest_log=$($LatestLog.FullName)"
        Get-Content -LiteralPath $LatestLog.FullName -Tail $LogLines
    } else {
        Write-Host "latest_log=missing"
    }
} else {
    Write-Host "latest_log_dir=missing"
}
