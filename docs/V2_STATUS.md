# MIMO — state after the v2 continuation round

Date: 2026-11-27. Branch: `mimo/v2-continuation` (from `main` @ `59c2c25`).

This is the honest scoreboard: what exists, what was measured, and what has **not** been proven. The
release gate at the end of your brief is reproduced verbatim against reality.

## 1. Sources reconciled

Your ZIP and GitHub `main` were byte-identical (143 files, `59c2c25`). Nothing to merge, nothing
lost. Evidence and method: `docs/RECONCILIATION.md`.

The handover's "307 tests pass" is not reproducible: the tree collects 303 (302 passed, 1 skipped —
Playwright not installed). The number is corrected in the reconciliation report; no test was
deleted to make anything match.

## 2. What this round built

| Module | State | Where |
|---|---|---|
| A. Native Android operator | **Built, compiles, APK produced** | `android/`, `docs/ANDROID_OPERATOR.md` |
| B. Local voice engine | **Built and measured** | `backend/core/voice/`, `docs/VOICE.md` |
| C. PySide6 Windows desktop shell | **Built, tested headless** | `desktop/`, `docs/DESKTOP.md` |
| D. Load and performance testing | **Harness + real report** | `scripts/load_test.py`, `docs/PERFORMANCE.md` |
| E. Packaging | **Windows scripts + Android APK/signing** | `scripts/windows/`, `docs/INSTALL_WINDOWS.md` |
| Hardware verification | **Checklists only** | `docs/ANDROID_OPERATOR.md` (phone), `docs/AUDIT.md` (PC) |

Backend changes were additive only: `POST /chat` now also returns the ids it stored for both rows
(so a phone can reconcile its own optimistic message), and `/voice/*` was mounted. No route was
renamed, removed or repurposed; the database schema and the pairing protocol are unchanged.

## 3. Measured, in this environment

Backend (Python 3.12.3, Linux, 4 vCPU, 7 GB, no GPU):

| Suite | Result |
|---|---|
| `pytest backend/tests -q` | **339 passed, 1 skipped** (skip = Playwright absent) |
| `pytest desktop/tests -q` (offscreen Qt, real server) | **7 passed** |
| `./gradlew :app:testDebugUnitTest` | **12 passed** |
| `./gradlew :app:assembleDebug` / `assembleRelease` | **both succeed** — 62 MB / 45.8 MB |
| `python scripts/load_test.py` | p50 5.4 ms sequential, p50 37.6 ms at 9 devices, server RSS 71 MB |
| `python scripts/bench_voice.py --roundtrip` | Whisper RTF 0.45 warm; Kokoro first chunk 0.4 s warm; 1.25 GB resident |

## 4. Your Definition of Done, against reality

| # | Requirement | Status |
|---|---|---|
| 1 | Android native application works | **Built and installable; not run on a phone.** 62 MB debug APK builds; every runtime behaviour is unverified |
| 2 | Android conversations persist | Implemented (Room + server sync). **Unverified at runtime** |
| 3 | Android pairing works | Implemented against the existing pairing protocol. Server side is tested; the app's side is unverified |
| 4 | Android notifications work | Implemented (three channels, polling). **Unverified at runtime** |
| 5 | Android operator works with authorised permissions | Implemented (accessibility + verified actions + OCR). **Unverified at runtime** |
| 6 | Local Whisper works | **Verified**: exact round-trip transcription, measured RTF |
| 7 | Local Kokoro works | **Verified**: audio produced and re-transcribed; latency measured |
| 8 | Native Windows desktop application works | **Built and tested headless**; no display, no Windows run |
| 9 | Existing browser interface still works | **Unchanged** — same routes, same web app; suite green |
| 10 | Load tests completed | **Yes**, with a measured report and named bottlenecks |
| 11 | Windows installer generated and tested | **Generated, not executed** — no Windows machine here |
| 12 | Android APK generated and installed | Generated; **not installed** (no device) |
| 13 | Windows automation verified on Windows | **No.** Code exists from the previous round, tested only through mocks/Linux |
| 14 | Android automation verified on a physical phone | **No.** Checklist written, not run |
| 15 | Regression tests pass | **Yes**: 339 backend + 7 desktop + 12 Android, 0 failures |
| 16 | No unresolved critical security issues | No new critical issue found; the token never leaves DataStore/the 0600 desktop file; `http://` is refused for non-private hosts; the operator requires explicit Android permission |

Rows 1–5 and 11–14 are exactly the ones your brief said not to claim without hardware. They are not
claimed.

## 5. What blocks the next step

1. **GitHub push is switched off for me.** The branch lives only in my sandbox and in a backup
   bundle; the request card is in your DM. Once it is allowed, the first thing I do is push.
2. **Your laptop and phone.** The remaining work in the release gate is not more code — it is running
   the checklists that are already written, and fixing what they turn up.
3. **Windows.** The installer, operators and desktop shell all need one real run on Windows.

## 6. Suggested order from here

1. Push (once allowed) and tag `v2.0.0-rc1`.
2. Install on the laptop: `install.ps1 -WithVoice -WithDesktop`; run the Windows checklist.
3. Install the APK on the A27 and walk the 17-step phone checklist.
4. Fix whatever those two find — that list is worth more than any amount of code written here.
5. Then: `large-v3`/GPU measurement, a real soak test, and replacing the phone's polling with
   something quieter if the 20 s interval proves annoying in use.
