[CmdletBinding()]
param(
    [string]$TaskName = "LPFS_VPS_Startup_Alert",
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$ConfigPath = "config.local.json",
    [string]$RuntimeRoot = "C:\TradeAutomationRuntime",
    [string]$RuntimeJournalFileName = "lpfs_live_journal.jsonl",
    [string]$InstanceLabel = "LPFS LIVE",
    [string]$RunnerTaskName = "LPFS_Live",
    [string]$PythonPath = "",
    [int]$InitialDelaySeconds = 60,
    [int]$MaxAttempts = 20,
    [int]$RetrySeconds = 30,
    [switch]$StartNow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $PythonPath = Join-Path $RepoRoot "venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python executable not found: $PythonPath"
}

if ([System.IO.Path]::IsPathRooted($ConfigPath)) {
    $ResolvedConfigPath = $ConfigPath
} else {
    $ResolvedConfigPath = Join-Path $RepoRoot $ConfigPath
}
if (-not (Test-Path -LiteralPath $ResolvedConfigPath)) {
    throw "Config file not found: $ResolvedConfigPath"
}

$ScriptPath = Join-Path $RepoRoot "scripts\send_lpfs_vps_startup_alert.py"
if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw "Startup alert script not found: $ScriptPath"
}

$ArgumentList = @(
    "`"$ScriptPath`"",
    "--config", "`"$ResolvedConfigPath`"",
    "--runtime-root", "`"$RuntimeRoot`"",
    "--runtime-journal-file-name", "`"$RuntimeJournalFileName`"",
    "--instance-label", "`"$InstanceLabel`"",
    "--runner-task-name", "`"$RunnerTaskName`"",
    "--initial-delay-seconds", "$InitialDelaySeconds",
    "--max-attempts", "$MaxAttempts",
    "--retry-seconds", "$RetrySeconds"
) -join " "

$Action = New-ScheduledTaskAction -Execute $PythonPath -Argument $ArgumentList -WorkingDirectory $RepoRoot
$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "LPFS boot/restart Telegram alert. Does not touch MT5 or trading state." `
    -Force | Out-Null

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
}

Get-ScheduledTask -TaskName $TaskName
