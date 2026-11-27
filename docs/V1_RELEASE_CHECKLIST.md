# V1.0 release checklist — physical hardware

This is the list that turns "built" into "verified". Nothing here has been run on a real Windows
machine or a real phone by the person who wrote the code — that is the whole point of the page.

Status words used in `docs/V1_STATUS.md` and below:

| Word | Means |
|---|---|
| **Implemented** | The code exists and is wired in |
| **Tests passed** | Automated tests cover it and passed in this container |
| **Built** | It compiled into an artifact (APK, wheel, installer) |
| **Emulator** | Verified on an emulator — **MIMO has had no emulator run** (no KVM in the build container) |
| **Hardware** | Verified on the real device — **nothing has reached this level** |
| **Pending** | Needs your laptop or phone |

---

## A. Windows laptop (16 GB) — install and first run

| # | Step | Expected | Status |
|---|---|---|---|
| A1 | `powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -WithVoice -WithDesktop` | Ends with "Installed." and no red text | Pending |
| A2 | Desktop and Start Menu show *MIMO*, *MIMO — Stop*, *MIMO Desktop* | Three shortcuts | Pending |
| A3 | `ollama pull qwen3:4b` then start MIMO | Start script reaches `/health` and opens the browser | Pending |
| A4 | Browser at `http://127.0.0.1:8000` — ask "what time is it" | An answer, in time | Pending |
| A5 | Desktop shell opens; Settings shows "Connected"; pair it (A6) | Five tabs, status pill green | Pending |
| A6 | `python -m backend.main pair desktop` → code → desktop Pair | "Paired as …" with a scope list | Pending |

## B. Windows laptop — capability checks

| # | Step | Expected | Status |
|---|---|---|---|
| B1 | Ask MIMO to list files in Documents | File names, no permission error | Pending |
| B2 | Ask it to create a folder in Documents | Folder appears; appears again in Activity with `verified` | Pending |
| B3 | Start `notepad` through it | Notepad opens | Pending |
| B4 | `run_powershell` with `Get-Process` | A process list | Pending |
| B5 | Screenshot + OCR: ask what is on screen | Text from the window matches | Pending |
| B6 | Mouse/keyboard: ask it to type into a scratch file | Text appears | Pending |
| B7 | Browser: "search for the weather in Indore and read me the first result" | A real page summary | Pending |
| B8 | Browser click that looks consequential (e.g. "Add to cart") | It **stops and asks** — level 3 | Pending |
| B9 | Memory: "remember that I prefer tea over coffee" then, in a new conversation, "what do I prefer?" | It recalls tea | Pending |
| B10 | Voice in: hold mic in the browser, say a sentence | Text appears and is answered | Pending |
| B11 | Voice out: spoken answer plays; say "stop" mid-answer | Speech stops within a sentence | Pending |
| B12 | Emergency stop in the desktop toolbar with 2 tasks running | Both reach `cancelled` | Pending |
| B13 | Restart the backend; reopen the browser | History and memory are still there | Pending |
| B14 | `stop-mimo.ps1`, then `start-mimo.ps1` twice | Second start says "already running" | Pending |
| B15 | `uninstall.ps1 -KeepData` then reinstall | Data survived in `%LOCALAPPDATA%\MIMO-data` | Pending |

## C. Samsung Galaxy A27 5G — install and pair

| # | Step | Expected | Status |
|---|---|---|---|
| C1 | `adb install -r app-debug.apk` (or sideload) | "Success" | Pending |
| C2 | First launch | Chat screen, no crash, notification permission prompt | Pending |
| C3 | Settings → address `http://<PC-LAN-IP>:8000` → Save | Status pill turns Connected in ≤ 6 s | Pending |
| C4 | Pair with the PC's code | "Paired as …"; the PC lists the phone | Pending |
| C5 | Send "hello" | Answer appears; timestamp shown | Pending |
| C6 | Force-stop the app, reopen | Same conversation and messages | Pending |
| C7 | Same conversation from the laptop | Both turns present on both devices | Pending |

## D. Samsung Galaxy A27 5G — behaviour

| # | Step | Expected | Status |
|---|---|---|---|
| D1 | Airplane mode → send → airplane mode off | "queued", then delivered by itself | Pending |
| D2 | Two messages queued offline, then reconnect | Both delivered, in order | Pending |
| D3 | Start a task on the PC; wait | "MIMO finished a task" notification | Pending |
| D4 | Task that needs approval | "MIMO is waiting for you"; Approve continues it | Pending |
| D5 | Switch conversations, delete one | Correct messages; server-side delete too | Pending |
| D6 | Memory screen: search, correct importance, forget | Each change is visible on the PC | Pending |
| D7 | Activity → Start a goal | It appears with its specialist and steps | Pending |
| D8 | Activity → Stop all with two running | Both cancelled, count reported | Pending |
| D9 | Rotate the phone on the chat screen | No crash, draft text preserved | Pending |

## E. Samsung Galaxy A27 5G — operator (needs the accessibility permission)

| # | Step | Expected | Status |
|---|---|---|---|
| E1 | Android Settings → Accessibility → MIMO on | Operator tab shows "Reading … N elements" | Pending |
| E2 | In the phone's Settings app, Operator → Read screen | Element list + OCR text of that screen | Pending |
| E3 | Tap "Wi-Fi" by name | Settings opens the Wi-Fi page; report says verified | Pending |
| E4 | Type into a field (e.g. a search box in Chrome) | Text appears; report verified | Pending |
| E5 | Scroll down | Page scrolls | Pending |
| E6 | A screen with an error dialog → Read | "Possible problems" names the error line | Pending |
| E7 | Settings → Screen capture → accept Android's dialog | Permanent "MIMO can see the screen" notification | Pending |
| E8 | Turn accessibility off, return to the app | Operator says Off and refuses to act | Pending |
| E9 | Deny the microphone permission, press the mic | A readable message, no crash | Pending |

## F. Cross-device

| # | Step | Expected | Status |
|---|---|---|---|
| F1 | Laptop, phone and desktop all open; send from each in turn | One history, order preserved | Pending |
| F2 | Revoke the phone on the PC (`DELETE /devices/{id}`) then use the phone | "Re-pair needed", not a crash | Pending |
| F3 | Rotate the desktop token | Desktop works, old token dead | Pending |
| F4 | Backend restart while the phone is idle | The phone reconnects by itself (pill green) | Pending |

---

## What to send back

For anything that fails: the step number, what you saw, and — where you can — the output of

```
GET /health
GET /llm/status
GET /agent/tasks?limit=20
```

plus the last 30 lines of `run\mimo.err.log` (Windows) or `adb logcat -s AndroidRuntime` (phone).
A failing step number is enough; I can find the cause from there faster than from a description.
