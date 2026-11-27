<#
.SYNOPSIS
    Start the MIMO backend and open the interface.

.DESCRIPTION
    Starts uvicorn from the installed virtual environment, waits until /health answers, then opens
    the browser. The process id is written to run\mimo.pid so stop-mimo.ps1 can find it again.
    Refuses to start a second copy if one is already running.

.PARAMETER NoBrowser
    Start the backend only (used by the logon task).

.PARAMETER Port
    Override the port from .env.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\windows\start-mimo.ps1
#>
[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [int]$Port
)

$ErrorActionPreference = 'Stop'
$installDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$venvPython = Join-Path $installDir '.venv\Scripts\python.exe'
$runDir = Join-Path $installDir 'run'
$pidFile = Join-Path $runDir 'mimo.pid'
$logFile = Join-Path $runDir 'mimo.log'

function Read-EnvValue($name, $fallback) {
    $envFile = Join-Path $installDir '.env'
    if (-not (Test-Path $envFile)) { return $fallback }
    foreach ($line in Get-Content $envFile) {
        if ($line -match "^\s*$name\s*=\s*(.+?)\s*$") { return $Matches[1].Trim('"', "'") }
    }
    return $fallback
}

if (-not (Test-Path $venvPython)) {
    Write-Host 'MIMO is not installed here. Run scripts\windows\install.ps1 first.' -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $runDir)) { New-Item -ItemType Directory -Path $runDir | Out-Null }

if (Test-Path $pidFile) {
    $existing = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($existing) {
        $process = Get-Process -Id $existing -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "MIMO is already running (pid $existing)." -ForegroundColor Yellow
            if (-not $NoBrowser) {
                Start-Process ("http://127.0.0.1:" + (Read-EnvValue 'MIMO_PORT' '8000'))
            }
            exit 0
        }
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}

if (-not $Port) { $Port = [int](Read-EnvValue 'MIMO_PORT' '8000') }
$hostAddress = Read-EnvValue 'MIMO_HOST' '0.0.0.0'
$requireAuth = Read-EnvValue 'MIMO_REQUIRE_AUTH' '0'
if ($hostAddress -ne '127.0.0.1' -and $hostAddress -ne 'localhost' -and $requireAuth -ne '1') {
    Write-Host 'Refusing to start: MIMO would be reachable from your network without device authentication.' -ForegroundColor Red
    Write-Host '  Either set MIMO_REQUIRE_AUTH=1 in .env (recommended), or MIMO_HOST=127.0.0.1 for this PC only.' -ForegroundColor Yellow
    exit 1
}

Write-Host "Starting MIMO on ${hostAddress}:${Port}…" -ForegroundColor Cyan
$arguments = @('-m', 'uvicorn', 'backend.api:app', '--host', $hostAddress, '--port', "$Port")
$process = Start-Process -FilePath $venvPython -ArgumentList $arguments `
    -WorkingDirectory $installDir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $logFile -RedirectStandardError (Join-Path $runDir 'mimo.err.log')
Set-Content -Path $pidFile -Value $process.Id

$deadline = (Get-Date).AddSeconds(45)
$ready = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 400
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch { }
    if ($process.HasExited) { break }
}

if (-not $ready) {
    Write-Host 'MIMO did not answer. The last lines of the log:' -ForegroundColor Red
    if (Test-Path $logFile) { Get-Content $logFile -Tail 20 }
    Write-Host ''
    Write-Host "Full log: $logFile" -ForegroundColor DarkGray
    exit 1
}

Write-Host "MIMO is running (pid $($process.Id))." -ForegroundColor Green
Write-Host "  Interface: http://127.0.0.1:$Port" -ForegroundColor DarkGray
Write-Host "  Log:       $logFile" -ForegroundColor DarkGray
if ($hostAddress -ne '127.0.0.1') {
    try {
        $ip = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
            Select-Object -First 1).IPAddress
        if ($ip) {
            Write-Host "  From your phone: http://${ip}:$Port  (allow it through the firewall on private networks)" -ForegroundColor DarkGray
        }
    } catch {
        Write-Host "  Run ipconfig to find this PC's LAN address for the phone." -ForegroundColor DarkGray
    }
}
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port" }
