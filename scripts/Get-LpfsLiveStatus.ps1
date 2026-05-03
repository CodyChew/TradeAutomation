[CmdletBinding()]
param(
    [string]$RuntimeRoot = "C:\TradeAutomationRuntime",
    [int]$JournalLines = 10,
    [int]$LogLines = 20
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$LiveDir = Join-Path $RuntimeRoot "data\live"
$StatePath = Join-Path $LiveDir "lpfs_live_state.json"
$JournalPath = Join-Path $LiveDir "lpfs_live_journal.jsonl"
$HeartbeatPath = Join-Path $LiveDir "lpfs_live_heartbeat.json"
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
Write-Host ""
Write-Host "processes=$($Processes.Count)"
foreach ($Process in $Processes) {
    Write-Host "pid=$($Process.ProcessId)"
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
            Write-Host "$($Row.occurred_at_utc) event=$($Row.event) symbol=$($Row.symbol) timeframe=$($Row.timeframe) status=$($Row.status)"
        } catch {
            Write-Host $Line
        }
    }
} else {
    Write-Host "journal=missing"
}

Write-Host ""
Write-Host "latest_log_dir=$LogDir"
if (Test-Path -LiteralPath $LogDir) {
    $LatestLog = Get-ChildItem -LiteralPath $LogDir -Filter "*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -ne $LatestLog) {
        Write-Host "latest_log=$($LatestLog.FullName)"
        Get-Content -LiteralPath $LatestLog.FullName -Tail $LogLines
    } else {
        Write-Host "latest_log=missing"
    }
} else {
    Write-Host "latest_log_dir=missing"
}
