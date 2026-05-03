[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$ConfigPath = "config.local.json",
    [string]$RuntimeRoot = "C:\TradeAutomationRuntime",
    [string]$PythonPath = "",
    [int]$Cycles = 100000000,
    [double]$SleepSeconds = 30,
    [int]$RestartDelaySeconds = 15,
    [int]$MaxRestarts = 0
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

$LiveDir = Join-Path $RuntimeRoot "data\live"
$LogDir = Join-Path $LiveDir "logs"
$KillSwitchPath = Join-Path $LiveDir "KILL_SWITCH"
$HeartbeatPath = Join-Path $LiveDir "lpfs_live_heartbeat.json"

New-Item -ItemType Directory -Force -Path $LiveDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$RestartCount = 0
while ($true) {
    if (Test-Path -LiteralPath $KillSwitchPath) {
        Write-Host "LPFS kill switch active. Runner will not start: $KillSwitchPath"
        exit 3
    }

    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $LogPath = Join-Path $LogDir "lpfs_live_$Timestamp.log"
    $RunnerArgs = @(
        "scripts\run_lp_force_strike_live_executor.py",
        "--config", $ResolvedConfigPath,
        "--cycles", "$Cycles",
        "--sleep-seconds", "$SleepSeconds",
        "--runtime-root", $RuntimeRoot,
        "--kill-switch-path", $KillSwitchPath,
        "--heartbeat-path", $HeartbeatPath
    )

    "[$(Get-Date -Format o)] starting LPFS live runner" | Tee-Object -FilePath $LogPath -Append | Out-Null
    "repo_root=$RepoRoot" | Tee-Object -FilePath $LogPath -Append | Out-Null
    "runtime_root=$RuntimeRoot" | Tee-Object -FilePath $LogPath -Append | Out-Null
    "heartbeat=$HeartbeatPath" | Tee-Object -FilePath $LogPath -Append | Out-Null
    "kill_switch=$KillSwitchPath" | Tee-Object -FilePath $LogPath -Append | Out-Null

    Push-Location $RepoRoot
    try {
        & $PythonPath @RunnerArgs *>> $LogPath
        $ExitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    "[$(Get-Date -Format o)] runner exited with code $ExitCode" | Tee-Object -FilePath $LogPath -Append | Out-Null

    if ($ExitCode -eq 0 -or $ExitCode -eq 130 -or $ExitCode -eq 3 -or $ExitCode -eq 4) {
        exit $ExitCode
    }
    if (Test-Path -LiteralPath $KillSwitchPath) {
        Write-Host "LPFS kill switch became active after runner exit. Watchdog will not restart."
        exit 3
    }

    $RestartCount += 1
    if ($MaxRestarts -gt 0 -and $RestartCount -gt $MaxRestarts) {
        "[$(Get-Date -Format o)] max restarts exceeded: $MaxRestarts" | Tee-Object -FilePath $LogPath -Append | Out-Null
        exit $ExitCode
    }

    "[$(Get-Date -Format o)] restart $RestartCount after ${RestartDelaySeconds}s" | Tee-Object -FilePath $LogPath -Append | Out-Null
    Start-Sleep -Seconds $RestartDelaySeconds
}
