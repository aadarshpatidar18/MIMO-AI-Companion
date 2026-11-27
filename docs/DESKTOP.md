# Desktop shell — PySide6 client for Windows

Date: 2026-11-27. Branch: `mimo/v2-continuation`.

A native desktop front end over the **same** backend the browser and the phone use. The browser
interface is untouched and still works; this is a second window onto one brain, not a replacement.

## Run it

```powershell
cd path\to\MIMO
.venv\Scripts\pip install PySide6
.venv\Scripts\python desktop\run.py
```

Or install with the desktop shortcut in one step: `scripts\windows\install.ps1 -WithDesktop`.

First run: **Settings → MIMO address** (default `http://127.0.0.1:8000`) → **Pair** with a code from
`python -m backend.main pair desktop` (the kind matters: a code issued for `android` will be
refused by this app). The token is written to `%USERPROFILE%\.mimo\desktop.json` with
owner-only permissions.

## What is in the window

| Screen | What it does |
|---|---|
| Chat | Conversation switcher, new/delete conversation, transcript, send, speak the last answer aloud |
| Activity | Live task list (polls every 4 s), start a goal, approve or deny a paused task, stop a task |
| Memory | Search, teach a fact, double-click to correct its wording or importance, forget |
| Devices | Every paired device with its scopes and last seen; revoke one |
| Settings | Backend address, pairing, spoken-reply toggle, identity and scopes |
| Toolbar | Connection state, this PC's device name, and **Emergency stop** |

**Emergency stop** is the red button in the toolbar: it cancels every task in
`queued/running/planning` through `POST /agent/tasks/{id}/cancel` and reports how many it stopped.
It does not just stop the UI — the backend sets the cancellation flags for the engine.

## How it is built

```
desktop/mimo_desktop/
  api.py       urllib client for every route used (no third-party HTTP dependency)
  worker.py    QRunnable + signals, so no HTTP call ever blocks the GUI thread
  settings.py  ~/.mimo/desktop.json, token written 0600
  theme.py     one dark stylesheet
  window.py    the five screens and the toolbar
  __main__.py  entry point
desktop/run.py the launcher
```

Decisions worth knowing:

- **No duplicated logic.** Every screen calls a backend route. Conversation storage, memory
  ranking, agent policy and permissions stay in one place, which is why a fact corrected on the
  phone shows up here after a refresh.
- **Threads for every call.** Qt widgets are single-threaded; a 20-second model turn on the GUI
  thread would freeze the window. Each call runs in `QThreadPool` and returns by signal.
- **The runnable is kept alive until it reports.** A `QRunnable`'s Python wrapper is collected when
  the last Python reference goes, and its signals then have no source — a real crash seen during
  development and fixed by holding each call until its result arrives.
- **Speech plays through QtMultimedia** from the WAV the backend's Kokoro model returns. If there is
  no audio device (headless), the app says so instead of pretending.
- **Errors are readable.** An unreachable backend is "Can't reach MIMO at …", a rejected token is
  "This PC's token is no longer valid — pair again", not a traceback.

## Verified here vs. not verified

**Verified in this container** (`QT_QPA_PLATFORM=offscreen`, real backend over real HTTP):

```
python -m pytest desktop/tests/test_desktop.py   →  7 passed
```

- pairing from a real code → device + token, `auth/me` returns `chat:write`
- create a conversation, chat in it, read back exactly `user, assistant`
- teach a memory and forget it, seeing the change in search
- emergency stop over four running tasks, every one ending in a terminal state
- a bad token is a `MimoError` with `is_auth`, an unreachable host is `is_offline` and `health()`
  returns False rather than raising
- the window constructs with all five tabs, renders two bubbles, and carries the stop button

**Not verified:** a real Windows session, a display, a sound card, and the shortcut the installer
creates. Those need Aadarsh's laptop. The Qt platform here is offscreen, so nothing about visual
layout, DPI scaling or audio output has been seen.

## Known limits

- No microphone capture in the desktop window yet: speech **out** works, and the browser handles
  speech **in**. A desktop mic would need `QAudioSource` plus WAV assembly, and the phone already
  covers push-to-talk.
- Polling, not events: the Activity screen refreshes every 4 s while the window is open.
- One window, no tray icon, no notifications on the PC (the phone has those).
