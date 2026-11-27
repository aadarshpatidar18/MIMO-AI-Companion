<#
.SYNOPSIS
    Remove MIMO from this PC.

.DESCRIPTION
    Stops the backend, removes the shortcuts and the scheduled task, then deletes the install
    folder. Your data lives inside that folder (data\ holds the memory and conversation databases,
    .env holds your keys and port), so deleting it deletes your history. Pass -KeepData to copy
    .env, data\ and your voice models to %LOCALAPPDATA%\MIMO-data first.

.PARAMETER InstallDir
    Where MIMO was installed. Default: %LOCALAPPDATA%\MIMO

.PARAMETER KeepData
    Keep .env, data\ and voice settings — remove only the program and the environment.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\windows\uninstall.ps1 -KeepData
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'MIMO'),
    [switch]$KeepData
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $InstallDir)) {
    Write-Host "Nothing to remove: $InstallDir does not exist." -ForegroundColor Yellow
    exit 0
}

Write-Host 'Stopping MIMO…' -ForegroundColor Cyan
$stopScript = Join-Path $InstallDir 'scripts\windows\stop-mimo.ps1'
if (Test-Path $stopScript) {
    try { & $stopScript -Force } catch { Write-Host "  (stop reported: $_)" -ForegroundColor DarkGray }
}

Write-Host 'Removing the scheduled task…' -ForegroundColor Cyan
$task = Get-ScheduledTask -TaskName 'MIMO' -ErrorAction SilentlyContinue
if ($task) { Unregister-ScheduledTask -TaskName 'MIMO' -Confirm:$false }

Write-Host 'Removing shortcuts…' -ForegroundColor Cyan
$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$desktop = [Environment]::GetFolderPath('Desktop')
foreach ($shortcut in @((Join-Path $startMenu 'MIMO.lnk'),
                        (Join-Path $startMenu 'MIMO — Stop.lnk'),
                        (Join-Path $desktop 'MIMO.lnk'))) {
    if (Test-Path $shortcut) { Remove-Item $shortcut -Force }
}

if ($KeepData) {
    Write-Host 'Keeping your data (.env, data, voice settings)…' -ForegroundColor Cyan
    $keep = Join-Path $env:LOCALAPPDATA 'MIMO-data'
    if (-not (Test-Path $keep)) { New-Item -ItemType Directory -Path $keep | Out-Null }
    foreach ($item in @('.env', 'data')) {
        $source = Join-Path $InstallDir $item
        if (Test-Path $source) { Copy-Item $source -Destination $keep -Recurse -Force }
    }
    $voice = Join-Path $env:USERPROFILE '.mimo'
    if (Test-Path $voice) { Copy-Item $voice -Destination $keep -Recurse -Force }
    Write-Host "  Your data is at $keep — put it back before reinstalling to keep your memory." -ForegroundColor DarkGray
}

Write-Host "Deleting $InstallDir…" -ForegroundColor Cyan
Remove-Item -Path $InstallDir -Recurse -Force
Write-Host ''
Write-Host 'MIMO has been removed.' -ForegroundColor Green
if ($KeepData) {
    Write-Host 'Your data was copied out first; delete it yourself when you are sure you do not want it.' -ForegroundColor DarkGray
} else {
    Write-Host 'Your memory database and conversations were deleted with the folder.' -ForegroundColor Yellow
}
