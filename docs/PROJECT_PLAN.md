# MIMO — project plan

Owner: Spark (coordination, integration, release). Created 2026-11-26 from the supplied
Milestone 2 archive, after reading every backend file and running the suite.

## 1. What actually exists today (verified, not claimed)

| Area | State | Evidence |
|---|---|---|
| FastAPI backend | Runs; `/health`, `/chat`, `/memory`, `/agent/*`, `/llm/*` | `backend/api.py`, tests |
| Local LLM | Ollama provider + Gemini provider, provider-independent router, retry/backoff, cooldowns, fallback, token/usage tracking, per-task routing, `local_only` routes | `backend/core/llm/*`, `docs/MODEL_ROUTING.md` |
| Agent engine | plan → validate → policy → execute → verify → one replan; autonomy levels 1–3; background tasks, cancel, confirmation, timeouts, restart recovery, audit log | `backend/core/agent/*`, `docs/AGENT_ENGINE.md` |
| Tools | 5 only: `get_time`, `get_date`, `calculate`, `open_website`, `open_app` | `backend/core/agent/builtin.py` |
| Memory | SQLite keyword memory, 7 categories, dedupe, privacy gate for cloud | `backend/memory.py` |
| Conversations | **in-memory `dict` in the API process** — lost on restart, not shared between devices, `backend/database.py` is empty | `backend/api.py` |
| Security | **none**: CORS `*`, no auth, no device identity, no rate limit | `docs/AUDIT.md` #10 |
| Android | Kotlin/Compose chat client only (335-line `MainActivity`, ViewModel, repository, hardcoded URL); no persistence, no voice, no device operator | `android/` |
| Desktop | does not exist | — |
| Voice | does not exist | — |
| Tests | 128 passing (`pytest`, ~4s), backend only | verified 2026-11-26 |

The Milestone 2 work is real and worth keeping. The gaps are additive, not a rewrite.

## 2. Gap list against the vision

1. No durable, device-shared conversation store (blocks the phone → laptop reminder demo).
2. No authentication or device registry (blocks every cross-device and automation feature).
3. Five trivial tools; no Windows, browser, file or terminal operators.
4. One monolithic agent (`AgentEngine`) — no specialised agent roster, no per-agent permissions/models.
5. Memory is keyword LIKE only: no importance, no semantic recall, no correction UI, no dashboard.
6. No voice, no desktop client, no Android operator.
7. Platform facts unverified: live Ollama/Gemini, Windows automation, Android build.

## 3. Way of working

- Repo is the single source of truth; `main` stays green (`pytest` must pass before every commit).
- Small, testable commits. Every new capability ships with tests, or with a clearly-marked
  "requires real hardware/credentials" note — never reported as done.
- Platform-specific code (Windows, Android) is written behind an interface with a mock
  implementation so the test suite runs on any machine, per engineering rule 15.
- Each agent owns a lane (below) and reports back through Spark; Spark integrates, runs the
  suite and ships one archive per milestone.
- Disagreements are settled by evidence: a test, a measurement, or a cited source.

## 4. Lanes

| Agent | Lane | First package |
|---|---|---|
| Spark | Roadmap, integration, security/conversations/devices, packaging, verification | Week 1 slice (below) |
| Claude | Architecture, core implementation, code quality, review of every merge | Agent roster design + engine v2 interface spec |
| GPT | Independent review, defect hunt, test design, verification gates | Adversarial review of engine/planner/policy/store + test plan |
| Gemini | Technology research with citations, model/library comparison, multimodal & device feasibility | Stack decisions for voice, Android accessibility, memory search |

## 5. Milestones

| # | Milestone | Acceptance (can be demonstrated) | Lane |
|---|---|---|---|
| 1 | Stabilisation | Suite green, junk removed, architecture documented, baseline tagged | Spark — **done** |
| 2 | Foundation: identity + durable conversations | Device enrolls with a pairing code, gets a token; two "devices" read the same conversation; `/chat` persists; restart keeps history | Spark — **in progress** |
| 3 | Central intelligence | Named agent roster with per-agent tools/permissions/model; orchestrator picks agent; memory importance + recall scoring + dashboard API | Claude + Spark |
| 4 | Windows operator | Killable subprocess runner, PowerShell allowlist, file ops sandboxed to allowed roots, app launch/close, screen capture + OCR, input control | Claude |
| 5 | Browser operator | Playwright session, search → open → extract → summarize, tab management, confirmation gate for consequential actions | Claude |
| 6 | Android operator | Compose app with Room persistence, settings/connection screen, notifications, accessibility service behind explicit permission (see `docs/DECISIONS.md` D4; probe APK first) | Gemini research → Spark/Claude impl |
| 7 | Voice | `faster-whisper` STT + Kokoro TTS behind one `VoiceService`, openWakeWord + silero-vad, barge-in, text/voice parity (`docs/DECISIONS.md` D2/D3) | Gemini research → Claude impl |
| 8 | Desktop app | PySide6 client: chat, history, memory dashboard, task/agent activity, device status, stop button | Claude |
| 9 | Cross-device sync | Same conversations, memory and task state on both clients; device presence; task takeover | Spark |
| 10 | Hardening & install | Security tests, rate limits, audit review, recovery drills, Windows installer, signed APK, setup docs | GPT gate + Spark release |

Order rationale: 2 before everything — nothing can be shared across devices without identity and
a shared store. 3 before 4/6 — operators need the roster and permission model. 9 last of the
functional ones because it composes 2 + 3 + 6 + 8.

## 6. Definition-of-done tracker (Aadarsh's §16)

| # | Requirement | Status |
|---|---|---|
| 1 | Text chat | ✅ interface, API and Android client |
| 2 | Voice | ✅ speak and hear in the browser interface; local Whisper still to come |
| 3 | Remembers across sessions | ✅ memory + durable conversations |
| 4 | Works on Windows | ⚠️ built for Windows (operators, screenshot, PowerShell) — untested until Aadarsh's PC |
| 5 | Works on Android | ⚠️ phone browser has the full interface; native app still chat-only, unbuilt here |
| 6 | Shared conversations + memory | ✅ paired devices, one history |
| 7 | Launch applications | ✅ implemented (alias table + config); verified on Linux, Windows untested |
| 8 | Manage authorised files | ✅ list/read/write/move/search/delete inside a proven sandbox |
| 9 | Browse and research | ✅ Playwright: search, open, read, screenshot; sensitive clicks need approval |
| 10 | Multi-step tasks | ✅ engine with 33 tools |
| 11 | Coordinate specialised agents | ✅ six specialists + generalist, each with its own tools and ceiling (`docs/ROSTER.md`) |
| 12 | Verify its actions | ✅ per-step verify, honest `verified: null` |
| 13 | Recover from failures | ✅ one replan, restart recovery, killed subprocesses |
| 14 | Cancel running tasks | ✅ API + Stop in the interface |
| 15 | Inspect/control permissions | ✅ device scopes, revocation, autonomy levels, confirmations |

Still missing: a packaged Windows installer and APK, and hardware verification on Windows and
Android. Everything else in the list now exists and is tested.

## 6c. Operators + voice — shipped

- `backend/tools/`: files inside a proven sandbox, approved PowerShell, allowlisted commands,
  app launch/close, screenshot + OCR, mouse/keyboard, and a Playwright browser with a code-level
  guard on consequential clicks. 33 tools, each with a level and, where possible, a verifier.
- Voice in the interface: speech in and out through the browser, with language choice and a stated
  privacy caveat; local Whisper remains the planned path.
- `docs/OPERATORS.md`, `docs/INSTALL.md`, `requirements-optional.txt`, `config/apps.example.json`.
- 262 tests, including 5 real browser tests against a local server and a real pytest run.

## 6d. The roster — shipped

- `backend/core/agent/roster.py`: six specialists (Research, Coding, Computer, Files, Browser,
  Memory) plus a generalist that keeps the full registry; keyword routing; per-agent tool subsets;
  a ceiling that can only make a run more cautious, read live from the user's policy.
- `backend/tools/memory_tools.py`: remember / recall / forget, so the Memory agent is real.
- `GET /agent/roster`, `agent` override on task creation, the agent recorded on every task and shown
  in Activity. 288 tests.

## 7. Decisions I need from Aadarsh

1. **Repo remote** — the workspace has no git remote. I can keep shipping archives, or push to a
   repository you name.
2. **Windows machine access** — the Windows operator has to be tested on your PC. Everything else
   I can verify here.
3. **Cloud keys** — Gemini/OpenAI/Anthropic keys stay on the PC in `.env`; local Ollama remains
   the default. Nothing is needed from you to proceed.

Technology choices from Gemini's research are recorded in `docs/DECISIONS.md` (D1–D5), each with
its verification gate. Nothing there needs a decision from you unless you object to Qwen3 4B/1.7B
as the local defaults or to Kokoro over Piper.

## 8. P2 — shipped

- `backend/core/security/`: hashed bearer tokens, per-device scopes, single-use pairing codes
  (expiring, burned after repeated wrong guesses, issuable only from the PC or a `device:manage`
  device), revocation, rotation, security-event audit, optional auth gate.
- `backend/core/conversations.py`: SQLite conversation + message store, WAL, device-tagged,
  paginated, auto-titled, cascade delete.
- `/chat` accepts `conversation_id` and writes both turns to the shared store, feeding the next
  turn its history from there; the legacy in-memory path is untouched.
- `python -m backend.main pair|devices`, and the import-time CLI loop is gone.
- Suite: 179 tests (51 new). Six mutations were each caught by the tests: plaintext token
  storage, ignored revocation, an open auth gate, durable chat ignoring history, an
  unauthenticated shared conversation, and an escalated device scope.
- Verified live: loopback pairing → token → `/auth/me` against a running uvicorn.

Not verified here: Windows, the Android build, live Ollama.
