# Installing MIMO on Windows

Tested steps are marked ✅ (verified on Linux here); steps that need your PC are marked ⚠️ — I could
not run them, so treat them as instructions rather than proof.

## 1. What you need

* Windows 10 or 11, 8 GB RAM or more.
* Python 3.11 or 3.12 from python.org (tick "Add Python to PATH").
* Ollama from ollama.com (local models, free) — or a Gemini API key for cloud models.
* Optional: Android Studio, if you want to build the phone app yourself.

## 2. Get the code and install ✅

Unzip `MIMO-*.zip` anywhere you keep projects, open PowerShell in that folder:

```powershell
cd MIMO
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pytest                       # 262 tests should pass
```

## 3. Give it a brain

Local, private, free:

```powershell
ollama pull qwen2.5:1.5b     # small and quick; qwen3:4b is better at planning if you have the room
ollama serve                 # already running if the Ollama app is open
```

Cloud, if you prefer (keys stay on this PC, never in the app):

```powershell
copy .env.example .env
notepad .env                 # set GEMINI_API_KEY=...
```

`config/models.example.json` shows how to route different tasks to different models.

## 4. Start it ✅

```powershell
uvicorn backend.api:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. MIMO's interface appears; it is the same page on your phone.

## 5. Pair your phone ⚠️

1. Find your PC's address: `ipconfig` → IPv4 address, e.g. `192.168.1.20`.
2. On the PC, allow the port once:
   `New-NetFirewallRule -DisplayName "MIMO" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow`
3. Restart the backend with `--host 0.0.0.0` so the phone can reach it.
4. On the PC: `python -m backend.main pair android` (or `desktop`) → an 8-character code.
5. On the phone (same Wi-Fi): open `http://192.168.1.20:8000`, type the **code** into the pairing
   field, give the device a name, press Connect.

After pairing, both devices read the same conversations. `python -m backend.main devices` lists them.

**Lock it down once your PC is paired:** Settings → Security → "Require a paired device", or start
with `MIMO_REQUIRE_AUTH=1`. Before that, anything on your network can call the API.

## 6. Turn on the abilities you want ⚠️

```powershell
pip install -r requirements-optional.txt
playwright install chromium
```

| Ability | Needs | Then |
|---|---|---|
| Browser control | `playwright` + `playwright install chromium` | "open YouTube and find robotics channels" |
| Screen reading | `pillow`, `pytesseract` + [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) | "what does this error say?" |
| Mouse and keyboard | `pyautogui` | "click the Save button" (asks first) |
| Applications | nothing extra on Windows | "open VS Code" |
| Files | nothing extra; set `MIMO_FILE_ROOTS` to widen the sandbox | "read my robotics notes" |

Check what your machine actually supports: <http://127.0.0.1:8000/system/capabilities>.

## 7. Android app (optional) ⚠️

The native app is chat-only today and needs Android Studio to build:

1. Open the `android/` folder in Android Studio, let Gradle sync.
2. In `android/app/src/main/java/.../data/remote/ApiService.kt`, set the base URL to your PC
   (`http://192.168.1.20:8000`).
3. Run on a device, or **Build → Build Bundle(s)/APK(s) → Build APK(s)** for a sideloadable APK.

Until it gains pairing, the phone browser is the fuller experience — it has history, memory,
devices and voice.

## 8. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| "No AI model is available" (503) | Ollama is not running, or no model is pulled, and no cloud key is set. `ollama list`, then `ollama serve`. |
| Answers are slow | First call loads the model into memory. `qwen2.5:1.5b` is faster; 4B models need the GPU. |
| Phone shows "This site can't be reached" | Backend bound to 127.0.0.1 — restart with `--host 0.0.0.0`; check the firewall rule and that both are on the same Wi-Fi. |
| Phone says the pairing code is invalid | Codes are single-use, expire in 10 minutes, and are burned after 5 wrong guesses. Run `pair` again on the PC. |
| "That path is outside the folders MIMO may touch" | Add the folder to `MIMO_FILE_ROOTS` (separate several with `;`). |
| Browser tools say Playwright is missing | `pip install playwright` then `playwright install chromium`. |
| Screenshot says mss/pillow missing | `pip install pillow` (Windows uses pillow for capture). |
| Dashboard loads but every request is 401 | Authentication is on and this device is not paired. Pair it, or set `require_auth` off from a paired PC. |
| Port 8000 already in use | `--port 8001`, then open that address. |
| Tests fail after editing | `pytest -q` shows which contract broke; every tool has its own test file. |

## 9. Running it without thinking about it

Task Scheduler → Create Task → "Run whether user is logged on or not" → action:

```
C:\MIMO\.venv\Scripts\uvicorn.exe backend.api:app --host 0.0.0.0 --port 8000
```

Start in `C:\MIMO`. Ollama has its own start-at-login setting.
