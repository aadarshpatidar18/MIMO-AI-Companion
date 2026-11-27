# MIMO — a personal AI operating system

MIMO runs on your own computer, remembers what matters to you, and can act — on files, applications,
a browser, a Windows desktop and an Android phone — with your permission. It is not a chatbot with
extras: the backend is a small operating layer (models, memory, tools, approvals, devices) and this
repository contains three ways to talk to it: the browser interface, a Windows desktop shell, and an
Android app.

Nothing leaves your machine unless you choose a cloud model. Conversations, memory and device
tokens live in SQLite files in `data/`.

---

## What it can do

- **Talk and remember.** Chat with a local model (Ollama) or a cloud one (Gemini). Facts you tell it
  — preferences, projects, people — are stored with an importance score and recalled by relevance,
  not by keyword alone. You can correct or forget any fact from any device.
- **Plan and act.** An agent engine turns a goal into steps, checks each step against a permission
  policy, runs it, verifies the result and replans once if it fails. Six specialists (Research,
  Coding, Computer, Files, Browser, Memory) plus a generalist each get their own tool set.
- **Operate the computer.** Files inside a sandbox, an allowlisted PowerShell runner, application
  launch/close, screenshots with OCR, mouse and keyboard, and a real Playwright browser.
- **Operate the phone.** An Android app with an accessibility-based operator: it reads the screen
  you are looking at, taps elements by name, types, scrolls — and re-reads the screen afterwards to
  check it actually worked. Everything needs a permission you grant, and you can revoke it.
- **Speak and listen.** Local Whisper for speech in and Kokoro for speech out on the PC; the phone
  and browser use their own engines.
- **Work from three devices at once.** The PC, the desktop app and the phone share one conversation
  history and one memory. A message sent on the phone appears on the laptop.

## Architecture

```
      Android app (Kotlin/Compose)   Desktop (PySide6)   Browser app
                    \                     |                 /
                     \--------- HTTP/JSON + bearer token -/
                                        |
                          FastAPI  (backend/api.py)
                                        |
     +-------------+-------------+-------------+--------------+
     |             |             |             |              |
  /chat        /agent/*      /memory       /voice/*      /conversations
  intent +     plan →        SQLite +       Whisper +     shared history,
  model call   policy →      FTS5, ranked   Kokoro        device-tagged
               execute →     recall
               verify
     |             |             |             |
  ModelRouter   ToolRegistry  memory.db     models on disk
  Ollama/Gemini 36 tools
```

Every client is a thin layer over the same REST API. There is no second implementation of memory,
policy or conversation storage in any client — that is what keeps three interfaces honest with each
other.

## Technology

Python 3.11+ · FastAPI · SQLite (WAL) with FTS5 · Ollama and Gemini providers behind one router ·
faster-whisper (CTranslate2) and Kokoro-ONNX for voice · Playwright for the browser ·
Kotlin + Jetpack Compose + Room + OkHttp for Android · PySide6 for the desktop shell ·
pytest, a load harness and JVM unit tests for verification.

## Installation

**Windows (recommended):** see [`docs/INSTALL_WINDOWS.md`](docs/INSTALL_WINDOWS.md).

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -WithVoice -WithDesktop
```

**Linux / macOS / development:**

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn backend.api:app --host 0.0.0.0 --port 8000
```

Open <http://127.0.0.1:8000>. Full details, including optional extras and the reverse-proxy note,
are in [`docs/INSTALL.md`](docs/INSTALL.md).

## Configuration

Configuration is environment variables in `.env` at the repository root (never committed) plus
`config/*.json` for model routing and application aliases.

| Variable | Purpose | Default |
|---|---|---|
| `GEMINI_API_KEY` | Cloud model key, optional | unset (local only) |
| `MIMO_LLM_PROVIDER` | `ollama`, `gemini` or `auto` | `auto` |
| `MIMO_OLLAMA_URL` | Where Ollama listens | `http://127.0.0.1:11434` |
| `MIMO_OLLAMA_MODEL` | Local model name | `qwen2.5:1.5b` |
| `MIMO_REQUIRE_AUTH` | Refuse unpaired callers on every route | unset |
| `MIMO_DATA_DIR` | Where the SQLite files live | `./data` |
| `MIMO_ALLOW_MEMORY_TO_CLOUD` | Let memory text reach a cloud model | unset |
| `MIMO_CORS_ORIGINS` | Extra browser origins | localhost only |

Voice settings live in `~/.mimo/voice.json` and can be changed from the API; see
[`docs/VOICE.md`](docs/VOICE.md).

## Running it on Windows

- **Backend:** `scripts\windows\start-mimo.ps1` starts uvicorn, waits for `/health`, prints the LAN
  address for your phone, and opens the browser. `stop-mimo.ps1` stops it.
- **Desktop shell:** `python desktop\run.py`, or the *MIMO Desktop* shortcut if you installed with
  `-WithDesktop`.
- **Emergency stop** is the red button in the desktop toolbar; on the phone it is *Stop all* on the
  Activity screen. Both cancel every queued or running task on the backend.

## Android

Build: `cd android && ./gradlew :app:assembleDebug` (see
[`docs/ANDROID_OPERATOR.md`](docs/ANDROID_OPERATOR.md) for signing and a 17-step verification
checklist). Install the APK, open Settings, enter `http://<PC-LAN-IP>:8000`, pair with the code from
`python -m backend.main pair android` (the kind is part of the code), then grant notifications.
Accessibility and screen capture are
optional and off until you turn them on.

## Local AI models

Local is the default. Install [Ollama](https://ollama.com) and pull a model:

```bash
ollama pull qwen3:4b        # ~2.5 GB, the documented default for a 16 GB laptop
ollama pull qwen3:1.7b      # smaller, for a machine that is also running a browser
```

Routing, fallback and per-task model choice are in [`docs/MODEL_ROUTING.md`](docs/MODEL_ROUTING.md).
The phone never runs a model of its own; it talks to the PC.

## Voice

```bash
pip install faster-whisper kokoro-onnx numpy
```

Whisper downloads its model on first use; the two Kokoro files go in `~/.mimo/models`. Measured on a
4-core machine: speech in at 0.45× real time, first spoken chunk 0.4 s warm, ~1.25 GB resident for
both. Numbers and the memory trade-offs are in [`docs/VOICE.md`](docs/VOICE.md).

## Security and permissions

- Devices are paired with a single-use, expiring code; each device gets a hashed bearer token with
  its own scopes. Revoking a device takes effect on its next request.
- The agent's tools are gated by a policy: levels 1–2 can be automatic, level 3 always needs your
  confirmation, and a device without a scope cannot invoke the tool at all.
- The phone's operator only works while you have enabled the accessibility service, and every action
  is verified by re-reading the screen.
- Files are confined to a sandbox; PowerShell runs an allowlist, not arbitrary command lines.

Details, including what is intentionally *not* protected, are in [`docs/SECURITY.md`](docs/SECURITY.md).

## Project layout

```
backend/          FastAPI app, agent engine, memory, security, tools, voice
android/          Kotlin/Compose app (the phone operator)
desktop/          PySide6 desktop shell
config/           model routing, application aliases (.example files)
scripts/          install/start/stop (windows/), load harness, voice benchmark, evals
docs/             architecture, operators, security, API reference, per-module notes
```

## Known limitations

- Nothing in this repository has been run on a physical Windows machine or a physical phone by the
  person who built it; every hardware step is a checklist, not a claim. See
  [`docs/V1_STATUS.md`](docs/V1_STATUS.md) for exactly what is verified and what is not.
- The browser operator and the Windows operators are tested on Linux and through mocks; Windows
  behaviour is unverified.
- One backend process, one SQLite database: right for one person, not for a team.
- The phone polls for task updates every 20 s rather than using push notifications.
- Local models need RAM; the voice models need about 1.25 GB resident.

## Docs

[Architecture](docs/ARCHITECTURE.md) · [Install (Linux/macOS)](docs/INSTALL.md) ·
[Install (Windows)](docs/INSTALL_WINDOWS.md) · [Android](docs/ANDROID_OPERATOR.md) ·
[Desktop](docs/DESKTOP.md) · [Voice](docs/VOICE.md) · [Operators](docs/OPERATORS.md) ·
[Agent engine](docs/AGENT_ENGINE.md) · [Memory](docs/MEMORY.md) · [Roster](docs/ROSTER.md) ·
[Model routing](docs/MODEL_ROUTING.md) · [API reference](docs/API_REFERENCE.md) ·
[Security](docs/SECURITY.md) · [Performance](docs/PERFORMANCE.md) ·
[Troubleshooting](docs/TROUBLESHOOTING.md) · [V1 status](docs/V1_STATUS.md)
