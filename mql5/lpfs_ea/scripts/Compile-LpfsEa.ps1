param(
    [string]$MetaEditorPath = "",
    [string]$SourcePath = "",
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..\..")
if ([string]::IsNullOrWhiteSpace($SourcePath)) {
    $SourcePath = Join-Path $RepoRoot "mql5\lpfs_ea\Experts\LPFS\LPFS_EA.mq5"
}
if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $LogPath = Join-Path $RepoRoot "mql5\lpfs_ea\compile_lpfs_ea.log"
}

if (-not (Test-Path -LiteralPath $SourcePath)) {
    throw "EA source not found: $SourcePath"
}

if ([string]::IsNullOrWhiteSpace($MetaEditorPath)) {
    $candidates = @(
        "${env:ProgramFiles}\MetaTrader 5\metaeditor64.exe",
        "${env:ProgramFiles(x86)}\MetaTrader 5\metaeditor64.exe",
        "${env:LOCALAPPDATA}\Programs\MetaTrader 5\metaeditor64.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            $MetaEditorPath = $candidate
            break
        }
    }
}

if ([string]::IsNullOrWhiteSpace($MetaEditorPath) -or -not (Test-Path -LiteralPath $MetaEditorPath)) {
    Write-Host "MetaEditor not found. Install MT5/MetaEditor or pass -MetaEditorPath."
    Write-Host "No live terminal, VPS runtime, config, state, journal, or broker order was touched."
    exit 2
}

Write-Host "Compiling LPFS EA with MetaEditor:"
Write-Host "  MetaEditor: $MetaEditorPath"
Write-Host "  Source:     $SourcePath"
Write-Host "  Log:        $LogPath"

$args = @(
    "/compile:`"$SourcePath`"",
    "/log:`"$LogPath`""
)
$process = Start-Process -FilePath $MetaEditorPath -ArgumentList $args -Wait -PassThru -WindowStyle Hidden

if (Test-Path -LiteralPath $LogPath) {
    $logContent = Get-Content -LiteralPath $LogPath
    $logContent | Select-Object -Last 80
    $errorLine = $logContent | Select-String -Pattern 'Result:\s+[1-9][0-9]*\s+errors?' | Select-Object -First 1
    if ($errorLine) {
        throw "MetaEditor reported compile errors. See $LogPath."
    }
}

if ($process.ExitCode -ne 0) {
    Write-Host "MetaEditor exited with code $($process.ExitCode), but the compile log reported zero errors."
}

Write-Host "LPFS EA compile command completed. Review the log for warnings/errors."
