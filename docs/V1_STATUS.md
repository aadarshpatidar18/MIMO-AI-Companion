# MIMO V1.0 release candidate — status

Date: 2026-11-27. Branch `mimo/v2-continuation`, tag `v1.0.0-rc1`. `main` untouched at `59c2c25`.

**What this document is:** the honest scoreboard for the release. Every claim below is marked with
how it was established, and the things that could not be established here are listed rather than
implied.

| Status word | Meaning in this document |
|---|---|
| **Tests passed** | An automated test asserts it and passed in this container |
| **Built** | It compiled / packaged into an artifact |
| **Reviewed** | An independent reviewer read the code; findings recorded below |
| **Hardware** | Verified on the real laptop/phone — **nothing is at this level** |

## 1. Architecture (as built)

```
        Android app          PySide6 desktop          Browser (served at /)
             \                    |                        /
              \----- HTTP/JSON + bearer token -----------/
                                    |
                      FastAPI  (backend/api.py)
                      ├── BodySizeLimit  (reject oversize before parse)
                      ├── AuthGate       (token required per settings)
                      └── routers: chat, memory, conversations, agent,
                                   llm, security, persona, voice
                                    |
   ModelRouter (Ollama|Gemini)  Agent engine (plan→policy→execute→verify)
   Memory (SQLite + FTS5)       Conversations (SQLite WAL, device-tagged)
   Security (paired devices, hashed tokens, scopes)   Voice (Whisper|Kokoro)
```

One process, one data directory, four SQLite files. One uvicorn worker is the supported
configuration — pairing codes and live task control are per process. Details:
`docs/ARCHITECTURE.md`.

## 2. Modules

| Module | State | Evidence |
|---|---|---|
| Backend brain: models, routing, fallback, usage | Complete | 68 LLM tests; live Ollama/Gemini paths unchanged |
| Agent engine: planner, 36 tools, roster of 7, approvals, cancel | Complete | 30 engine + 11 API + 25 roster tests |
| Memory: importance, FTS5 recall, correction, migration | Complete | 19 memory tests + web/desktop/phone screens |
| Conversations: durable, shared, paginated, atomic turns | Complete | 26 tests incl. concurrency and restart |
| Security: pairing, tokens, scopes, gate, dispatch policy | Complete | 31 tests incl. the new kind-binding |
| Windows operators: files, PowerShell, commands, apps, screen, browser | Complete, Linux/mock-tested | 44 operator tests. **Windows behaviour unverified** |
| Android app: Room, pairing, offline queue, notifications, operator, OCR | Complete, built | 20 JVM tests incl. wire-contract; APK builds |
| Voice: Whisper + Kokoro, streaming, cancel, cloud opt-in | Complete, measured | 36 tests; round-trip benchmark below |
| Desktop shell: chat, activity, memory, devices, stop | Complete, headless-tested | 8 tests incl. a live-server run |
| Packaging: Windows scripts, APK, signing, source ZIP | Complete (scripts unrun) | `docs/INSTALL_WINDOWS.md`, `docs/ANDROID_OPERATOR.md` |

## 3. Bugs found and fixed in this round

Found by the two independent reviews (Claude's lane reached the contract bug before its credits ran
out; GPT and Gemini completed), plus my own sweep. Each is fixed and covered by a test unless noted.

**Release blockers**

1. **Android: first-launch crash.** `NotificationCenter` reached `MimoApp.container` while the
   container was still being constructed → `UninitializedPropertyAccessException` before any screen
   opened. Fixed by passing the container's scope. *(Gemini; code path verified)*
2. **Android: every screen would have shown "this app could not read the response".** The backend
   sends timestamps as epoch **numbers**; the DTOs declared `String`, and one wrong field rejects a
   whole response. Fixed in all DTOs, plus `WireContractTest` decoding 8 captured real responses.
   *(Claude's lane → confirmed here by decoding live payloads)*
3. **Desktop: task table crashed on epoch timestamps** (sliced a float as text). Fixed with one
   `stamp()` helper; regression test renders epoch values.
4. **LAN served without authentication.** The installer bound `0.0.0.0` with auth off, so anyone on
   the Wi-Fi could drive the agent. The backend now **refuses to start** on a non-loopback address
   without `MIMO_REQUIRE_AUTH=1`; the installer writes LAN + auth together. *(GPT #1)*
5. **Pairing let the client choose its privileges.** A phone code could be redeemed as `desktop`,
   which carries `device:manage`. Codes are now bound to a kind at issue time; mismatch is refused
   and logged. *(GPT #2)*

**Security and correctness**

6. `POST_NOTIFICATIONS` prompted on every cold start → now once per install, only if missing.
7. Missing `<queries>`: Android 11+ hid the phone's speech/TTS services, so voice reported "no
   engine" on devices that have one. *(Gemini #2)*
8. `isAccessibilityTool="true"` was a false declaration (and a Play policy breach). Set to `false`;
   the Restricted Settings step is documented.
9. Taps were not verified: a stale node could be tapped at old coordinates and the gesture was not
   awaited, producing false "screen looks unchanged". Node is refreshed, live bounds are used, the
   gesture is awaited, and the screen is re-read after a settle delay. *(Gemini #4)*
10. Approval was a boolean keyed to a task: a stale tap could approve the *next* consequential step.
    Approvals can now name their step; a mismatch or an expired wait is `409`. *(GPT #4)*
11. No request-size limit before parsing. Added an ASGI `BodySizeLimit` (2 MB JSON, 13 MB audio,
    streamed-byte counting). *(GPT #5)*
12. Two devices could read the same history and append out of order. A per-conversation turn lock
    now covers read → model → append, with existence re-checked inside it. *(GPT #8)*
13. Voice: bad audio returned `503` ("no model"), conflating the caller's mistake with a missing
    engine; audio is now validated **before** a model is loaded and returns `400`. Inference moved
    off the event loop. *(GPT #9)*
14. Accessibility walked 400 nodes on every content-changed event (jank/battery). Reads are on
    demand now. *(Gemini #6)*
15. Bitmap copies were not recycled on every capture. Fixed. *(Gemini minor)*
16. No edge-to-edge handling for `targetSdk 35+`. `enableEdgeToEdge()` added. *(Gemini #5)*
17. The Android "speak replies" setting was stored and never used. Spoken answers now work, and
    Emergency Stop exists on the phone (it did not).
18. Desktop polled every 4 s even minimised; now 3 s when visible, 20 s otherwise. The phone went
    from 20 s to 60 s in the background. *(Gemini #9)*
19. `stt_cpu_threads` cap added, and `POST /voice/unload` frees ~1.25 GB without a restart.
20. Web UI paired as `desktop` (device:manage) from a browser — now a `browser` kind with no
    device-management scope.

**Documentation defects found and fixed:** a non-existent `python -m backend.main serve` command;
pairing instructions that predated kind-bound codes (8 files); "33 tools" where the catalogue holds
36.

## 4. Test results — exact

Backend (`pytest backend/tests`, Python 3.12.3, this container):

| Suite | Total | Passed | Failed | Skipped |
|---|---:|---:|---:|---:|
| test_agent_api | 11 | 11 | 0 | 0 |
| test_agent_engine | 30 | 30 | 0 | 0 |
| test_app_integration | 21 | 21 | 0 | 0 |
| test_conversations | 26 | 26 | 0 | 0 |
| test_dispatch_policy | 10 | 10 | 0 | 0 |
| test_llm_e2e_http | 3 | 3 | 0 | 0 |
| test_llm_providers | 19 | 19 | 0 | 0 |
| test_llm_retry_usage | 9 | 9 | 0 | 0 |
| test_llm_router | 31 | 31 | 0 | 0 |
| test_llm_routes | 5 | 5 | 0 | 0 |
| test_memory_upgrade | 19 | 19 | 0 | 0 |
| test_operators | 44 | 44 | 0 | 0 |
| test_persona | 25 | 25 | 0 | 0 |
| test_resilience | 6 | 6 | 0 | 0 |
| test_roster | 25 | 25 | 0 | 0 |
| test_security | 31 | 31 | 0 | 0 |
| test_voice | 36 | 36 | 0 | 0 |
| **backend total** | **351** | **351** | **0** | **0** |

The one skipped item is `test_browser_live` (a single test module): Playwright is not installed in
this container, so the real-browser tests are skipped rather than reported as passing.

| Other suites | Total | Passed | Failed | Skipped |
|---|---:|---:|---:|---:|
| Android JVM (`./gradlew :app:testDebugUnitTest`) | 20 | 20 | 0 | 0 |
| Desktop (`pytest desktop/tests`, offscreen Qt, live server) | 8 | 8 | 0 | 0 |
| Android instrumented (`androidTest`) | 1 | — | — | **not run**: needs an emulator or device; none available (no KVM) |
| Load harness (`scripts/load_test.py`) | 10 scenarios | 10 | 0 | 0 |

## 5. Security audit — results

Two independent reviews (GPT: security/backend/testing; Gemini: Android/voice/perf) plus my own
pass. Findings and dispositions:

| # | Finding | Disposition |
|---|---|---|
| 1 | LAN reachable without authentication | **Fixed** — startup guard + installer default |
| 2 | Redeemer chose its own privilege tier | **Fixed** — codes bound to a kind |
| 3 | Browser clicks classified by visible text | **Open, documented** — a click whose action is not visible in its label can still be automatic if it carries a navigation role. Consequential clicks remain level 3; see `docs/SECURITY.md` |
| 4 | Approval not bound to a step / reusable | **Fixed** — step index, deadline, 409 |
| 5 | Limits applied after parsing; queue unbounded | **Partly fixed** — body cap added; the agent queue is still unbounded (a personal server, one user) |
| 6 | Multi-worker breaks pairing and task control | **Documented** — one worker is the supported configuration |
| 7 | Task submission is not idempotent | **Open, documented** — no client retries a submission automatically |
| 8 | Turn ordering under concurrency | **Fixed** — per-conversation lock |
| 9 | Input errors looked like provider failures | **Fixed** — 400 vs 503 |
| 10 | Filesystem/subprocess are not OS isolation | **Accepted** — documented as the sandbox's limit; allowlist + roots + process groups |
| 11 | Audit log is not tamper-evident | **Accepted** — local SQLite, owner's own machine; stated in `docs/SECURITY.md` |

No secrets are committed: `.gitignore` covers `.env`, databases and keystores; the source ZIP was
built with an explicit exclude list and audited afterwards (no `.env`, `.db`, `.apk`, `.jks`, `.venv`).

## 6. Performance (measured here)

| Scenario | Result |
|---|---|
| 40 sequential turns, one device | p50 4.2 ms, p95 7.6 ms → 230 turns/s |
| 90 turns, 9 devices in parallel | p50 35.2 ms, p95 53.4 ms → 241 turns/s, 0 rejections |
| Memory search over 300 facts | p50 4.9 ms |
| Server after the run | 71.5 MB RSS, 1.0 % CPU, database 7.09 MB |
| Voice STT (Whisper small.en int8, 4 CPU) | RTF 0.45 warm (2.67 s audio in ~1.2 s), +792 MB |
| Voice TTS (Kokoro) | first chunk ~0.4 s warm, 1.7 s cold, +454 MB |
| Voice round trip | transcribed exactly |

Environment: Python 3.12.3, Linux x86-64, 4 vCPU, 7 GB RAM, no GPU. **Not measured:** Windows, any
GPU, a real LLM's latency. `docs/PERFORMANCE.md` and `docs/VOICE.md` carry the detail and caveats.

## 7. Artifacts

| Artifact | Path (in this sandbox) | Size | SHA-256 (first 20) |
|---|---|---|---|
| Debug APK | `android/app/build/outputs/apk/debug/app-debug.apk` | 65,009,471 B (62 MB) | `ccd9e45205d5a82ce4ae` |
| Release APK (unsigned) | `android/app/build/outputs/apk/release/app-release-unsigned.apk` | 45,854,123 B (43.7 MB) | `8af0c2a8134d0965d8a7` |
| Source ZIP | `MIMO-v1.0.0-rc1-source.zip` | 469,353 B (459 KB), 276 entries | `e206ff751f19d5dd8e80` |
| Windows installer | `scripts/windows/` (32 KB: install/start/stop/uninstall) | — | in the source ZIP |

The release APK is **unsigned**: no signing key exists in this repository or container, and inventing
one would be worse than shipping unsigned. `docs/ANDROID_OPERATOR.md` has the four environment
variables that sign it when Aadarsh has a key.

## 8. Verified levels

| Capability | Implemented | Tests passed | Built | Emulator | Hardware |
|---|:--:|:--:|:--:|:--:|:--:|
| Backend core (chat, memory, conversations, security) | ✓ | ✓ | ✓ | n/a | — |
| Agent engine, roster, approvals, cancel | ✓ | ✓ | ✓ | n/a | — |
| Voice STT/TTS (PC) | ✓ | ✓ | ✓ | n/a | — (measured on this machine) |
| Browser interface | ✓ | ✓ | ✓ | n/a | — |
| Desktop shell | ✓ | ✓ | ✓ | — | **no** |
| Android app | ✓ | ✓ | ✓ | **no** | **no** |
| Windows operators | ✓ | ✓ (mocked/Linux) | ✓ | — | **no** |
| Windows installer | ✓ | — | ✓ | — | **no** |
| Android operator (accessibility, OCR) | ✓ | ✓ (logic only) | ✓ | **no** | **no** |

## 9. Still requires Aadarsh's hardware

Everything in `docs/V1_RELEASE_CHECKLIST.md` — 4 install steps on the laptop, 12 capability checks,
9 phone install steps, 9 phone behaviour steps, 9 operator steps, 4 cross-device steps. Highlights:

- installer, shortcuts, service start/stop, firewall
- Ollama + a real model answering
- Windows operators: files, PowerShell, screenshot/OCR, mouse/keyboard, browser, approval gate
- APK install, pairing, chat persistence, notifications, offline queue, reconnection
- accessibility permission, screen reading, element tapping, OCR, verification
- Emergency Stop on both devices

## 10. Known limitations (carried into V1.0)

1. **No hardware verification.** The single most important sentence in this document.
2. Windows operators and the installer are unrun on Windows.
3. Browser clicks can be misclassified by label (finding 3 above).
4. Task submission is not idempotent; the agent queue is unbounded.
5. One worker only; no horizontal scaling.
6. The mobile app polls for task state (60 s idle / 5 s on the Activity screen) — no push.
7. Release APK unsigned; no GitHub release assets uploaded from here.
8. Voice models cost ~1.25 GB resident (unloadable via `POST /voice/unload`).
9. Memory/voice quality depends on the chosen local model; `qwen3:4b` is the documented default.

## 11. Install

**Laptop (Windows):** `powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1 -WithVoice -WithDesktop`,
then `ollama pull qwen3:4b`, then the *MIMO* shortcut. Pair the desktop with
`python -m backend.main pair desktop`. Full steps: `docs/INSTALL_WINDOWS.md`.

**Phone:** `adb install -r app-debug.apk` (or sideload), Settings → address
`http://<PC-LAN-IP>:8000`, pair with `python -m backend.main pair android`, grant notifications,
then enable accessibility and screen capture only if you want the operator.
