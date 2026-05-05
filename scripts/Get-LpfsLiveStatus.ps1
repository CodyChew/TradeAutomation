[CmdletBinding()]
param(
    [string]$RuntimeRoot = "C:\TradeAutomationRuntime",
    [string]$StateFileName = "lpfs_live_state.json",
    [string]$JournalFileName = "lpfs_live_journal.jsonl",
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

Write-Host "LPFS live status"
Write-Host "checked_at=$((Get-Date).ToString("o"))"
Write-Host "runtime_root=$RuntimeRoot"
Write-Host "kill_switch_active=$((Test-Path -LiteralPath $KillSwitchPath))"
if (Test-Path -LiteralPath $KillSwitchPath) {
    Write-Host "kill_switch_path=$KillSwitchPath"
    Write-Host "kill_switch_note=$((Get-Content -LiteralPath $KillSwitchPath -Raw).Trim())"
}

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
    Write-Host "heartbeat_status=$($Heartbeat.status)"
    Write-Host "heartbeat_updated_at_utc=$($Heartbeat.updated_at_utc)"
    Write-Host "heartbeat_pid=$($Heartbeat.pid)"
    Write-Host "heartbeat_completed_cycles=$($Heartbeat.completed_cycles)"
    Write-Host "heartbeat_requested_cycles=$($Heartbeat.requested_cycles)"
    if ($Heartbeat.PSObject.Properties.Name -contains "last_cycle") {
        Write-Host "last_cycle=$($Heartbeat.last_cycle | ConvertTo-Json -Compress)"
    }
}

$State = Read-JsonFile -Path $StatePath
Write-Host ""
Write-Host "state_path=$StatePath"
if ($null -eq $State) {
    Write-Host "state=missing"
} else {
    $Processed = @($State.processed_signal_keys).Count
    $Pending = @($State.pending_orders).Count
    $Positions = @($State.active_positions).Count
    Write-Host "processed_signal_keys=$Processed"
    Write-Host "pending_orders=$Pending"
    Write-Host "active_positions=$Positions"
}

Write-Host ""
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
