[CmdletBinding()]
param(
    [string]$RuntimeRoot = "C:\TradeAutomationRuntime",
    [string]$Reason = "operator stop",
    [switch]$Clear
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$LiveDir = Join-Path $RuntimeRoot "data\live"
$KillSwitchPath = Join-Path $LiveDir "KILL_SWITCH"

New-Item -ItemType Directory -Force -Path $LiveDir | Out-Null

if ($Clear) {
    if (Test-Path -LiteralPath $KillSwitchPath) {
        Remove-Item -LiteralPath $KillSwitchPath
        Write-Host "LPFS kill switch cleared: $KillSwitchPath"
    } else {
        Write-Host "LPFS kill switch was already clear: $KillSwitchPath"
    }
    exit 0
}

$Content = @(
    "reason=$Reason",
    "created_at=$((Get-Date).ToString("o"))",
    "user=$env:USERNAME",
    "machine=$env:COMPUTERNAME"
)
$Content | Set-Content -LiteralPath $KillSwitchPath -Encoding UTF8
Write-Host "LPFS kill switch set: $KillSwitchPath"
