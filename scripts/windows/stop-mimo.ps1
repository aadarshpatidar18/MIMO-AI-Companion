<#
.SYNOPSIS
    Stop the MIMO backend started by start-mimo.ps1.

.DESCRIPTION
    Stops the process named in run\mimo.pid, and any uvicorn child it started. If the pid file is
    missing, it says so instead of killing something else that happens to be python.

.PARAMETER Force
    Also stop a MIMO process found by command line when the pid file is gone.
#>
[CmdletBinding()]
param([switch]$Force)

$ErrorActionPreference = 'Stop'
$installDir = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pidFile = Join-Path $installDir 'run\mimo.pid'
$stopped = $false

if (Test-Path $pidFile) {
    $pidValue = (Get-Content $pidFile | Select-Object -First 1)
    if ($pidValue) {
        $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($process) {
            # Kill the tree: uvicorn may have spawned a reloader or worker child.
            Get-CimInstance Win32_Process -Filter "ParentProcessId = $pidValue" |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
            Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 400
            Write-Host "MIMO stopped (pid $pidValue)." -ForegroundColor Green
            $stopped = $true
        }
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}

if (-not $stopped -and $Force) {
    $candidates = Get-CimInstance Win32_Process |
        Where-Object { $_.CommandLine -like '*uvicorn*backend.api:app*' }
    foreach ($candidate in $candidates) {
        Stop-Process -Id $candidate.ProcessId -Force -ErrorAction SilentlyContinue
        $stopped = $true
    }
    if ($stopped) { Write-Host 'Stopped a MIMO process found by its command line.' -ForegroundColor Green }
}

if (-not $stopped) {
    Write-Host 'MIMO does not appear to be running (no pid file, no matching process).' -ForegroundColor Yellow
}
