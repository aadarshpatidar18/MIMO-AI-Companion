# Installing MIMO on Windows

Everything here is per-user: no admin rights, no registry keys, no Windows service. MIMO installs
into `%LOCALAPPDATA%\MIMO` with its own Python environment and is removed by deleting that folder
(plus the shortcuts an uninstall script removes for you).

**Status of these scripts:** written and reviewed against Windows PowerShell 5.1 and PowerShell 7
syntax rules, but **not executed on Windows** — this project was developed in a Linux container.
Treat the first run as a test, and if a step fails, `run\mimo.log` says why. Nothing in this folder
has been claimed as verified on Windows.

## Prerequisites

1. **Windows 10 or 11, 64-bit.**
2. **Python 3.11+** from <https://www.python.org/downloads/windows/> — tick *Add python.exe to PATH*.
3. **A model.** Local is the intended default: install [Ollama](https://ollama.com), then
   `ollama pull qwen3:4b` (about 2.5 GB; Qwen3 4B is the documented default in `docs/MODEL_ROUTING.md`).
   A cloud key (Gemini) in `.env` works too and needs no Ollama.
4. Optional: a microphone, for voice.

## Install

From the repository folder, in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1
```

Useful switches:

| Switch | Effect |
|---|---|
| `-WithVoice` | Also install faster-whisper + kokoro-onnx (~1.5 GB once models download) |
| `-Autostart` | Start MIMO at logon via a Scheduled Task (no admin rights) |
| `-InstallDir D:\MIMO` | Install somewhere else |
| `-Python 'py -3.12'` | Force a particular interpreter |

The installer copies the application, creates `.venv`, installs `requirements.txt`, writes a
starter `.env` (port 8000, binds `0.0.0.0` so your phone can reach it), and creates *MIMO* and
*MIMO — Stop* shortcuts in the Start Menu plus *MIMO* on the Desktop.

If Windows Firewall asks, allow **private networks only**. Public is never needed for a personal
LAN setup.

## Start, stop, use

- **Start:** the *MIMO* shortcut (or `scripts\windows\start-mimo.ps1`). It starts the backend,
  waits for `/health`, then opens <http://127.0.0.1:8000>.
- **Stop:** the *MIMO — Stop* shortcut (or `scripts\windows\stop-mimo.ps1 -Force`).
- **Logs:** `%LOCALAPPDATA%\MIMO\run\mimo.log` and `mimo.err.log`.
- **From your phone:** the start script prints the LAN address, e.g. `http://192.168.1.20:8000`.
  Type that into the Android app's settings.

## Pair your phone

```powershell
cd $env:LOCALAPPDATA\MIMO
.venv\Scripts\python.exe -m backend.main pair
```

Type the code it prints into the app (Settings → Pair). The code is single-use and expires; issue a
new one with the same command if it lapses.

## Voice models

`-WithVoice` installs the packages; the models download on first use:

- Whisper `small.en`: automatic, ~480 MB, into `~\.mimo\models`.
- Kokoro: two files, 338 MB total. Installer does not fetch them; download once:

```powershell
mkdir "$env:USERPROFILE\.mimo\models" -Force
curl.exe -L -o "$env:USERPROFILE\.mimo\models\kokoro-v1.0.onnx" `
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl.exe -L -o "$env:USERPROFILE\.mimo\models\voices-v1.0.bin" `
  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

Measured cost on a 4-core, no-GPU machine: about 1.25 GB resident for both models, speech in at
RTF ≈ 0.45, first spoken chunk ≈ 0.4 s warm. See `docs/VOICE.md` for the full table and the
memory trade-offs. On a 16 GB laptop this is comfortable; if it is not, set
`stt_model="base.en"` in `%USERPROFILE%\.mimo\voice.json`.

## Android app

Build and sign on this PC (needs Android Studio or the command-line SDK):

```powershell
cd android
.\gradlew :app:assembleDebug         # installable on the phone via adb or a copied file
.\gradlew :app:assembleRelease       # unsigned unless the MIMO_KEYSTORE env vars are set
```

Signing, without committing a key:

```powershell
keytool -genkeypair -v -keystore "$env:USERPROFILE\mimo-release.jks" -alias mimo `
  -keyalg RSA -keysize 2048 -validity 10000
$env:MIMO_KEYSTORE = "$env:USERPROFILE\mimo-release.jks"
$env:MIMO_KEYSTORE_PASSWORD = '…'
$env:MIMO_KEY_ALIAS = 'mimo'
$env:MIMO_KEY_PASSWORD = '…'
.\gradlew :app:assembleRelease
```

Install with `adb install -r app\build\outputs\apk\debug\app-debug.apk`, then follow the phone
checklist in `docs/ANDROID_OPERATOR.md`.

## Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\uninstall.ps1
```

Add `-KeepData` to copy `.env`, `data\` and your voice models to `%LOCALAPPDATA%\MIMO-data` before
the folder is deleted. Without it, your memory and conversation history go with the folder — that
is the whole point of them being local, and it is worth a moment's thought before running it.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Python was not found` | Python is not on PATH. Reinstall with *Add python.exe to PATH*, or pass `-Python 'C:\Python312\python.exe'` |
| `Python 3.10 is too old` | MIMO needs 3.11+. Install 3.12 and re-run with `-Python 'py -3.12'` |
| MIMO starts, replies with "No AI model is available" | Ollama is not running or the model is missing: `ollama serve`, `ollama pull qwen3:4b` |
| Phone cannot reach the PC | Firewall on private networks; both on the same Wi-Fi; use the LAN address the start script prints, not `127.0.0.1` |
| Phone says "Not paired" after working before | The token was revoked on the PC (`/devices`), or the data folder was moved. Pair again |
| Voice says `faster-whisper is not installed` | Re-run the installer with `-WithVoice`, or `.venv\Scripts\pip install faster-whisper` |
| Voice says the Kokoro files are missing | Download the two `.onnx`/`.bin` files into `%USERPROFILE%\.mimo\models` (above) |
| `MIMO is already running` | Use the *MIMO — Stop* shortcut, or `stop-mimo.ps1 -Force` if the pid file is stale |
| Port 8000 taken | Edit `MIMO_PORT` in `.env`, then start again |

## What is still missing on Windows

- The native PySide6 desktop shell (Module C) is not built yet, so the interface on the PC is the
  browser app. The installer is written so that adding it later is a matter of copying its files
  and adding a start shortcut — no change to the backend.
- No hardware verification on a real Windows machine has happened. The checklist for Aadarsh's
  laptop is in `docs/AUDIT.md` and the operators' own notes in `docs/OPERATORS.md`.
