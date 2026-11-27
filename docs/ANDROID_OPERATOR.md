# Android operator — what is built, what is verified

Date: 2026-11-27. Branch: `mimo/v2-continuation`.

The previous Android client was a chat-only activity with a hardcoded address and no
authentication. It has been replaced by an application with four layers: a durable local store, a
device-identity layer, an operator that can read and act on the screen with the user's permission,
and the screens that drive them. The package name (`com.mimo.companion`) and the app's existing
data directory name are unchanged.

## What exists now

| Area | Implementation |
|---|---|
| Local store | Room 2.8.5, schema v1 exported to `app/schemas` (`data/local/`). Conversations, messages, and a table of notifications already shown. |
| Wire layer | OkHttp + kotlinx.serialization (`data/remote/MimoClient.kt`, `Dto.kt`). Bearer token on every call; `ignoreUnknownKeys` so a newer backend never crashes an older app. |
| Device identity | Pairing-code exchange, token stored only in DataStore, `GET /auth/me`, device list, token rotation, self-revocation (`data/repository/AuthRepository.kt`). |
| Connection | `device/ConnectionMonitor.kt`: `/health` probe, 2→30 s exponential backoff, distinct states for offline / unauthorised / unpaired. |
| Conversations | `data/repository/ChatRepository.kt`: server-authoritative ids, offline queue, retry in order, local→server id upgrade for a conversation created offline, delete-then-sync. |
| Notifications | `device/NotificationCenter.kt`: three channels (task finished, awaiting approval, activity), derived by polling `/agent/tasks` — no push service, because task state must not leave the user's own network. Remembers what it already announced. |
| Operator: reading | `operator/UiReader.kt` flattens the accessibility tree with a node budget (400) and depth budget (24). |
| Operator: matching | `operator/ScreenSnapshot.kt` — scoring, not first-hit: exact text > prefix > contains, accessibility labels, view-id tails, enabled and clickable weighted up, empty bounds penalised. |
| Operator: acting | `operator/UiActions.kt` — click via the node, gesture fallback at the element's own centre, `ACTION_SET_TEXT` for typing, node or gesture scrolling. Never taps a coordinate read from a screenshot. |
| Operator: verification | Each action re-reads the screen and reports `verified = true/false`; an unchanged screen says "screen looks unchanged" instead of claiming success. |
| Screen understanding | `operator/ScreenCaptureService.kt` (MediaProjection, foreground, on-demand frames only) + `operator/ScreenAnalyzer.kt` (ML Kit on-device OCR, 1400 px downscale, combined tree+OCR summary, error-line detection). |
| Voice | `voice/VoiceController.kt` — the phone's own recogniser and TTS, push-to-talk, interruptible speech. The Whisper/Kokoro stack stays on the PC (`docs/VOICE.md`). |
| Screens | Chat (with conversation switcher, queued/failed states, mic), Memory (search, add, correct importance, forget), Activity (live task list, approve/deny, stop, new goal), Operator (read the screen, tap/type/scroll/back, action log), Settings (address, pairing, device, notifications, voice, permissions, about). |
| Navigation | `ui/MimoNav.kt`, five destinations, state preserved per tab. |

### Backend change this required

`POST /chat` now returns `user_message_id`, `assistant_message_id` and `created_at` alongside the
answer. Additive only; no existing field, route or status changed. It exists because the phone
writes the user's turn locally before posting it, and without the real ids it could only guess
which new messages were its own — the usual cause of duplicated turns after a reconnect.
Test: `backend/tests/test_conversations.py::test_chat_returns_the_ids_it_stored`.

## Build and install

Verified in this container (Linux, JDK 21, Android SDK 37.0, Gradle 9.6.0):

```
cd android
./gradlew :app:assembleDebug        # BUILD SUCCESSFUL — app/build/outputs/apk/debug/app-debug.apk (65 MB)
./gradlew :app:testDebugUnitTest    # 12 tests, 0 failures
./gradlew :app:assembleRelease      # BUILD SUCCESSFUL — unsigned, 45.8 MB
```

The debug APK is large because ML Kit's text recogniser is bundled (it works with no Play
Services and no model download, which is the right trade for an offline-first personal app).

Install on the phone:

```
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

or copy the APK to the phone and open it (sideloading must be allowed for the file manager).

Release signing — keys are never committed:

```
export MIMO_KEYSTORE=/path/to/mimo-release.jks
export MIMO_KEYSTORE_PASSWORD=...
export MIMO_KEY_ALIAS=mimo
export MIMO_KEY_PASSWORD=...
./gradlew :app:assembleRelease
```

Without those variables the release task still builds, unsigned; that APK installs nowhere and is
only useful as proof the minified build compiles. Create the key once with:

```
keytool -genkeypair -v -keystore mimo-release.jks -alias mimo -keyalg RSA -keysize 2048 -validity 10000
```

## First run on the phone

1. Start the backend on the PC: `uvicorn backend.api:app --host 0.0.0.0 --port 8000`
   (or the *MIMO* shortcut the Windows installer creates — see `docs/INSTALL_WINDOWS.md`).
2. On the PC: `python -m backend.main pair android` → it prints a single-use code.
   The kind in the command is the kind of device the code may enroll; a phone code cannot be
   redeemed as a desktop.
3. In the app: Settings → MIMO address = `http://<PC-LAN-IP>:8000` → Save → type the code → Pair.
   The address must be a private LAN address for `http://`; a public host has to be `https://`.
4. Grant notifications when Android asks.
5. Optional, one at a time, only if you want the operator: Settings → Accessibility service →
   enable MIMO; Settings → Screen capture → accept Android's consent dialog.

## Verified here vs. not verified

**Verified in this container:** both build variants compile; 12 JVM unit tests pass (operator
matching, bounds, error detection, text merge); the backend suite passes (303 passed, 1 skipped);
the APK and the release APK exist at the sizes above; schemas export.

**Not verified here, and not claimed:** the app has never been launched on a phone or an emulator
in this environment. Nothing about the accessibility service, MediaProjection consent, notification
delivery, Room on first launch, or voice has been exercised at runtime. Those are the tests below,
and they need the real device.

## Hardware verification — Samsung Galaxy A27 5G (8 GB), Android

Do these in order; each has an observable result.

| # | Step | Expected |
|---|---|---|
| 1 | `adb install -r app-debug.apk` | "Success" — no signature mismatch |
| 2 | Open the app cold, then rotate the phone | Chat screen renders; no crash in `adb logcat -s AndroidRuntime` |
| 3 | Settings → set address, Save | Status pill turns from Offline to Connected within ~6 s |
| 4 | Pair with the PC's code | "Paired as …"; the PC's `/devices` lists the phone as `android` |
| 5 | Send "hello" | Answer appears; `adb shell run-as com.mimo.companion ls databases` shows `mimo-companion.db` |
| 6 | Force-stop, reopen, open the conversation | The same messages are there, with timestamps |
| 7 | Airplane mode, send "queued test" | Message shows "queued"; airplane mode off → it sends by itself |
| 8 | On the PC, start a task; wait for it to finish | A notification arrives; tapping it opens Activity |
| 9 | Run a task that needs approval | "MIMO is waiting for you" notification with Approve/Deny in the app |
| 10 | Settings → Accessibility, enable MIMO | Operator tab shows "Reading … N elements" |
| 11 | In a harmless app (e.g. Settings), Operator → Read this screen | Element list and OCR text appear; the screen's own text is in the summary |
| 12 | Type a label that exists, Tap it | The tap happens; if nothing changes the report says "screen looks unchanged" |
| 13 | Settings → Screen capture, accept | Persistent "MIMO can see the screen" notification appears |
| 14 | OCR on a screen with an error dialog | The error line appears under "Possible problems" |
| 15 | Turn the operator off in Android settings, return to the app | Operator tab says Off and refuses to act |
| 16 | Pair a second device / the PC's web UI, send from one | Both histories show both turns |
| 17 | Deny the microphone permission, press the mic | A readable message, no crash |

## Known limits, stated plainly

- No push notifications: the app polls every 20 s while it believes the backend is reachable. A
  phone that has just been asleep may take up to a poll interval to notice a finished task.
- `Facebook`-style apps that set `FLAG_SECURE` cannot be read or captured; the operator reports an
  empty tree rather than pretending.
- The operator taps by element, not by coordinates. Games and apps drawn on a single canvas expose
  nothing tappable; OCR text is visible but not actionable there.
- Release builds are not signed here (no key), and the app has not been through a device run yet.
