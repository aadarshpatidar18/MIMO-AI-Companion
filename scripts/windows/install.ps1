<#
.SYNOPSIS
    Install MIMO on this Windows PC.

.DESCRIPTION
    Creates a private virtual environment, installs the backend's dependencies, writes a starter
    .env, and creates Start Menu / Desktop shortcuts. Nothing is installed system-wide, nothing is
    written to the registry, and no service is registered unless you pass -Autostart (which uses a
    Scheduled Task, not a Windows service).

    Run it from the repository folder:  powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1

.PARAMETER InstallDir
    Where MIMO lives. Default: %LOCALAPPDATA%\MIMO

.PARAMETER Python
    The Python launcher to use. Default: tries `py -3.12`, then `py -3`, then `python`.

.PARAMETER WithVoice
    Also install faster-whisper and kokoro-onnx (about 1.5 GB of wheels and models).

.PARAMETER WithDesktop
    Also install the PySide6 desktop shell and create a "MIMO Desktop" shortcut.

.PARAMETER LocalOnly
    Serve this PC only (127.0.0.1). Without it MIMO listens on the LAN so your phone can reach it,
    which requires device authentication — the installer turns that on for you.

.PARAMETER Autostart
    Start MIMO when you log in (Scheduled Task, current user, no admin rights needed).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -WithVoice -Autostart
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'MIMO'),
    [string]$Python,
    [switch]$WithVoice,
    [switch]$WithDesktop,
    [switch]$LocalOnly,
    [switch]$Autostart
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$port = 8000

function Write-Step($text) { Write-Host "  $text" -ForegroundColor Cyan }
function Write-Ok($text)   { Write-Host "  OK  $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "  !   $text" -ForegroundColor Yellow }

Write-Host ''
Write-Host 'MIMO — Windows installer' -ForegroundColor White
Write-Host "Installing to $InstallDir" -ForegroundColor DarkGray
Write-Host ''

# ---------------------------------------------------------------- 1. Python
Write-Step 'Looking for Python 3.11 or newer…'
if (-not $Python) {
    foreach ($candidate in @('py -3.12', 'py -3.11', 'py -3', 'python')) {
        $parts = $candidate.Split(' ')
        $exe = $parts[0]
        if (Get-Command $exe -ErrorAction SilentlyContinue) {
            $Python = $candidate
            break
        }
    }
}
if (-not $Python) {
    throw 'Python was not found. Install it from https://www.python.org/downloads/windows/ (tick "Add python.exe to PATH"), then run this script again.'
}
$pythonCmd = $Python.Split(' ')
$pythonExe = $pythonCmd[0]
$pythonArgs = @()
if ($pythonCmd.Length -gt 1) { $pythonArgs += $pythonCmd[1..($pythonCmd.Length - 1)] }
$version = (& $pythonExe @pythonArgs -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
$major, $minor = $version.Split('.')
if ([int]$major -lt 3 -or ([int]$major -eq 3 -and [int]$minor -lt 11)) {
    throw "Python $version is too old. MIMO needs 3.11 or newer."
}
Write-Ok "Python $version ($Python)"

# --------------------------------------------------------------- 2. files
Write-Step 'Copying the application…'
if (-not (Test-Path $InstallDir)) { New-Item -ItemType Directory -Path $InstallDir | Out-Null }
foreach ($item in @('backend', 'config', 'scripts', 'docs', 'desktop', 'requirements.txt',
                    'requirements-dev.txt', 'requirements-optional.txt', 'README.md')) {
    $source = Join-Path $repo $item
    if (Test-Path $source) {
        Copy-Item -Path $source -Destination $InstallDir -Recurse -Force
    }
}
Write-Ok 'Application files copied'

# ------------------------------------------------------------ 3. virtualenv
Write-Step 'Creating a private virtual environment…'
$venv = Join-Path $InstallDir '.venv'
if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) {
    & $pythonExe @pythonArgs -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Python could not create a virtual environment (venv).' }
}
$venvPython = Join-Path $venv 'Scripts\python.exe'
Write-Ok 'Virtual environment ready'

Write-Step 'Installing the backend (this downloads packages once)…'
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r (Join-Path $InstallDir 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Scroll up for the first error.' }
Write-Ok 'Backend dependencies installed'

if ($WithVoice) {
    Write-Step 'Installing local voice (Whisper + Kokoro, about 1.5 GB)…'
    & $venvPython -m pip install --quiet faster-whisper kokoro-onnx numpy
    if ($LASTEXITCODE -ne 0) {
        Write-Warn 'Voice packages failed to install; MIMO still works with text and the browser microphone.'
    } else {
        Write-Ok 'Voice packages installed (models download on first use)'
    }
}

if ($WithDesktop) {
    Write-Step 'Installing the desktop shell (PySide6, about 250 MB once)…'
    & $venvPython -m pip install --quiet "PySide6>=6.6"
    if ($LASTEXITCODE -ne 0) {
        Write-Warn 'PySide6 failed to install; the browser interface still works.'
    } else {
        Write-Ok 'Desktop shell installed'
    }
}

# ------------------------------------------------------------- 4. settings
Write-Step 'Writing the configuration file…'
$envFile = Join-Path $InstallDir '.env'
if (Test-Path $envFile) {
    Write-Ok '.env already exists — left untouched'
} else {
    $example = Join-Path $InstallDir '.env.example'
    if (Test-Path $example) { Copy-Item $example $envFile } else {
        New-Item -ItemType File -Path $envFile | Out-Null
    }
    $listenHost = if ($LocalOnly) { '127.0.0.1' } else { '0.0.0.0' }
    # A LAN-reachable backend requires device authentication; the backend refuses to start
    # otherwise. Pairing itself stays open, so a new phone can still enroll.
    $requireAuth = if ($LocalOnly) { '0' } else { '1' }
    Add-Content -Path $envFile -Value @"
# Written by install.ps1. Secrets stay in this file; it is never committed.
# Local model (recommended): install Ollama from https://ollama.com and run:  ollama pull qwen3:4b
# Cloud model (optional): put a key here and MIMO will use it only when local is unavailable.
# GEMINI_API_KEY=
# Listen on the LAN so the phone can reach MIMO. Use 127.0.0.1 for this PC only.
MIMO_HOST=$listenHost
MIMO_PORT=$port
# Every request except pairing and /health needs a paired device token. Required for LAN access.
MIMO_REQUIRE_AUTH=$requireAuth
"@
    Write-Ok 'Created .env'
}

# ------------------------------------------------------------ 5. shortcuts
Write-Step 'Creating shortcuts…'
$shell = New-Object -ComObject WScript.Shell
function New-Shortcut($path, $target, $arguments, $description) {
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = $target
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $InstallDir
    $shortcut.Description = $description
    $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
    $shortcut.Save()
}
$startScript = Join-Path $InstallDir 'scripts\windows\start-mimo.ps1'
$stopScript = Join-Path $InstallDir 'scripts\windows\stop-mimo.ps1'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
New-Shortcut (Join-Path $startMenu 'MIMO.lnk') $powershell `
    "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`"" 'Start MIMO'
New-Shortcut (Join-Path $startMenu 'MIMO — Stop.lnk') $powershell `
    "-NoProfile -ExecutionPolicy Bypass -File `"$stopScript`"" 'Stop MIMO'
$desktopFolder = [Environment]::GetFolderPath('Desktop')
New-Shortcut (Join-Path $desktopFolder 'MIMO.lnk') $powershell `
    "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`"" 'Start MIMO'
if ($WithDesktop) {
    $pythonw = Join-Path $InstallDir '.venv\Scripts\pythonw.exe'
    $desktopEntry = Join-Path $InstallDir 'desktop\run.py'
    New-Shortcut (Join-Path $startMenu 'MIMO Desktop.lnk') $pythonw `
        "`"$desktopEntry`"" 'MIMO desktop shell'
    New-Shortcut (Join-Path $desktopFolder 'MIMO Desktop.lnk') $pythonw `
        "`"$desktopEntry`"" 'MIMO desktop shell'
}
Write-Ok 'Shortcuts created (Start Menu and Desktop)'

# ------------------------------------------------------------ 6. autostart
if ($Autostart) {
    Write-Step 'Registering MIMO to start when you log in…'
    $action = New-ScheduledTaskAction -Execute $powershell `
        -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$startScript`" -NoBrowser"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
    Register-ScheduledTask -TaskName 'MIMO' -Action $action -Trigger $trigger -Settings $settings `
        -Description 'Starts the MIMO personal AI backend at logon.' -Force | Out-Null
    Write-Ok 'Scheduled task "MIMO" registered'
}

# --------------------------------------------------------------- 7. finish
Write-Host ''
Write-Host 'Installed.' -ForegroundColor Green
Write-Host ''
Write-Host '  Next steps:' -ForegroundColor White
Write-Host '    1. Install a local model: https://ollama.com  then   ollama pull qwen3:4b'
Write-Host '    2. Start MIMO: the MIMO shortcut, or  scripts\windows\start-mimo.ps1'
Write-Host '    3. Open http://127.0.0.1:8000 in your browser.'
Write-Host "    4. Pair your phone:  .venv\Scripts\python.exe -m backend.main pair"
Write-Host ''
if (-not $WithVoice) {
    Write-Host '  Voice is not installed. Re-run with -WithVoice to add Whisper and Kokoro.' -ForegroundColor DarkGray
}
Write-Host "  If Windows Firewall asks, allow MIMO on private networks only (needed for the phone)." -ForegroundColor DarkGray
Write-Host ''
