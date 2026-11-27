# Troubleshooting

Symptom → cause → fix. Every message quoted here is the one the code actually produces, so you can
search this file by what you see.

## Starting and connecting

**`No AI model is available. Make sure Ollama is running (or configure a cloud model).`**
Nothing answered. Check `ollama list` — if it errors, Ollama is not running (`ollama serve`, or start
the Ollama app). If the model name is unknown, `ollama pull qwen3:4b`. `GET /llm/status` shows each
provider's state, and `GET /llm/usage` shows what has been tried.

**`Can't reach MIMO at http://…`** (desktop or app)
The address is wrong, the backend is not running, or a firewall is blocking it. On the PC:
`curl http://127.0.0.1:8000/health` must return `{"status":"healthy",…}`. On the phone, use the LAN
address the start script prints — `127.0.0.1` on a phone means the phone itself.

**`MIMO is already running (pid …)`**
A previous start is still alive. Use *MIMO — Stop*, or `stop-mimo.ps1 -Force`. Deleting
`run\mimo.pid` alone does not stop the process.

**Port 8000 already in use**
Set `MIMO_PORT=8010` in `.env` and start again; every client uses the address you give it, so update
it there too.

**`A valid device token is required. Pair this device first.`**
`MIMO_REQUIRE_AUTH=1` is set and the caller has no token, or its token was revoked/rotated. Pair
again: `python -m backend.main pair android` (or `desktop`). `python -m backend.main devices`
lists what is paired. If the code was issued for a different kind, the error says so.

**`This device is not allowed to 'device:manage'.`**
Correct behaviour: an Android device has no `device:manage` scope. Issue pairing codes and revoke
devices from the PC or the desktop shell.

**Pairing code refused**
Codes are single-use, expire, and are burned after repeated wrong guesses. A new code invalidates
the old one. Issue a fresh code and type it within the window; codes are upper-case.

## Chat and memory

**`'conversation_id' is required for a paired device.`**
A paired client must name a conversation, so two devices never share an implicit history. The phone
and desktop create one automatically; a hand-written `curl` must create one first.

**A message shows "queued" on the phone and never sends**
The phone could not reach the PC when you pressed send. It retries in order when the link returns;
the Chat screen's connection pill tells you which. If the token was revoked meanwhile, re-pair.

**`That memory could not be updated: it is empty or duplicates another one.`**
Correcting a fact to the same wording as another fact is refused. Change the wording slightly or
forget the duplicate.

**Answers feel generic / memory is not used**
Memory is only sent to the model when relevant, and never to a cloud model without
`MIMO_ALLOW_MEMORY_TO_CLOUD=1`. `GET /memory` shows what is stored; a fact that is never recalled
may have a low importance — correct it and raise the score.

## The agent

**A task sits in `awaiting_confirmation`**
A level-3 (consequential) step is waiting for you: approve it in Activity on the phone, in the
desktop Activity tab, or `POST /agent/tasks/{id}/confirm` with `{"approve": true}`. Denying cancels
the task.

**`A MIMO task failed` notification**
Open the task: `error` says what the step returned and `steps` lists each action with its decision.
A killed subprocess shows as a timeout.

**A task cancelled but its tool kept running**
Cancellation is cooperative between steps; a running subprocess is killed with its process group.
If Windows itself refuses (a protected process), the task reports `failed` with that message.

**`PowerShell is only available on Windows; this machine is Linux.`**
Expected on Linux/macOS. On Windows, `run_powershell` takes a cmdlet from a fixed list — it is not a
shell.

## Voice

**`faster-whisper is not installed. Run 'pip install faster-whisper'`**
Follow it. The model downloads on first use (about 480 MB for `small.en`).

**`Kokoro model files are missing from …: kokoro-v1.0.onnx and voices-v1.0.bin.`**
Download the two files into `~/.mimo/models` (commands in `docs/VOICE.md`), or point
`model_dir` at where you put them in `~/.mimo/voice.json`.

**`Kokoro could not speak this: language "en" is not supported…`**
An unsupported language code. Set `language` to a code the model knows (`en-us`, `en-gb`, `es`,
`fr-fr`, `hi`, `it`, `ja`, `pt-br`, `cmn`) — the manager maps the short forms it recognises.

**Speech starts late on the first sentence**
Cold model load: about 4 s for both models. Keep the backend running; warm turns start in ~0.4 s.

**`Cloud speech recognition is off. Turn on 'allow_cloud'…`**
Two switches are required by design: `stt_provider: "cloud"` **and** `allow_cloud: true`, plus the
key in `.env`. Both are in `PUT /voice/settings`.

## The phone

**The app shows "Not paired" after working before**
The token was revoked on the PC, or the app's data was cleared. Pair again.

**Notifications never arrive**
Android 13+ needs the notification permission (granted on first launch; re-grant in app settings if
declined), and the app polls every 20 s — a task that finished one second ago appears a little later.

**"Turn on MIMO in Settings → Accessibility first."**
The operator needs the accessibility service enabled by you, in Android's own settings. That is
deliberate; the app cannot enable it for you.

**Tapping an element does nothing and the report says "screen looks unchanged"**
The action ran but the screen did not change — often the element was a label inside a clickable
row. Try the row's own text, or the accessibility label. Games and canvas-drawn apps expose nothing
tappable; only OCR text is visible to MIMO there.

**"Screen capture is not enabled. Grant it in Permissions."**
Screen capture needs the system consent dialog once per app run; Settings → Screen capture re-opens
it. While armed, Android shows a permanent notification.

**The app cannot be installed**
It is a debug-signed sideload APK: allow installation from the file manager, or
`adb install -r app-debug.apk`. Android may warn about an unknown developer — expected for a
personal build.

## Windows operator

**`File access is switched off: no allowed folders are configured.`**
Set `MIMO_ALLOWED_ROOTS` (a `;`-separated list on Windows) or use the defaults, which are your home
directory and a few subfolders.

**`That path is outside the folders I am allowed to touch.`**
The sandbox refused the path, including through a symlink. Move the file inside an allowed root or
add the root.

**`Close … is not supported on Linux yet` / `Computer control is not supported…`**
Those operators are Windows-only.

**Browser tools fail with a Playwright error**
`pip install playwright` and `playwright install chromium`; set `MIMO_CHROME_PATH` if you want a
specific Chrome.

## Performance

- Idle: the backend idles at tens of megabytes; voice models are only loaded when first used, and
  stay loaded (about 1.25 GB for both) until the backend restarts.
- If RAM is tight, use `small.en` → `base.en` and keep the browser closed during long tasks.
- The phone polls every 20 s; the desktop every 4 s while its window is open. Neither runs when the
  app is closed — the phone has no background service for this.

## Collecting evidence for a bug report

```
GET /health          # is it up
GET /llm/status      # which providers are usable
GET /agent/tasks?limit=20   # what failed, with its error and steps
GET /security/events # recent rejected requests, rotations, revocations
```

Logs: the backend logs to stdout (the Windows start script writes `run\mimo.log` and
`run\mimo.err.log`). The phone's stack traces are in `adb logcat -s AndroidRuntime`.
