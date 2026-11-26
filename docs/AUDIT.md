# MIMO technical audit (Phase 0) and milestone log

Audited: GitHub `main` @ 8f30ca1 ("refactor: implement MVVM architecture").
Method: read every backend file and the Android data/remote layer; ran the existing API (`/health`).
Not audited: Room / conversation-management code (exists only on your PC, not on GitHub), the Android build (no SDK in my environment).

## Findings
| # | Area | Finding | Status |
|---|---|---|---|
| 1 | Backend | Ollama URL and model hardcoded in `llm.py` | Fixed (router + config/env) |
| 2 | Backend | Memory short-circuit matched any sentence with "my " + "project/learn/goal..." - "Help me debug my project" returned a memory dump | Fixed (`intent_rules.py`, tested) |
| 3 | Backend | Whole memory table is injected into every chat prompt - would leak to any cloud model | Fixed: such calls are local-only unless `MIMO_ALLOW_MEMORY_TO_CLOUD=true` |
| 4 | Backend | Mixed absolute/relative imports; `planner.py`/`agent.py`/`main.py` not importable with `uvicorn backend.api:app` | Fixed (package imports; CLI is now `python -m backend.main`) |
| 5 | Backend | `json.loads` on model output unguarded in planner/classifier -> HTTP 500 on malformed JSON | Fixed |
| 6 | Backend | `/chat` returned `str(exception)` to the client | Fixed: friendly 503 / generic 500, details logged |
| 7 | Backend | `initialize_memory()` ran at import (side effects, untestable) | Fixed (FastAPI lifespan) |
| 8 | Backend | `planner.py`/`agent.py` multi-step execution is not reachable from the API; chat does one classifier call + one tool | Fixed in Milestone 2: `/agent/*` (legacy files kept for the CLI) |
| 9 | Backend | `main.py` ran its loop at import time; `database.py` empty; `conversation_history` in-memory only | Fixed in P2: `python -m backend.main` CLI (`chat`/`pair`/`devices`); durable conversations in `core/conversations.py`. `database.py` still empty - delete it when the next storage module lands |
| 10 | Security | CORS `*`, server binds 0.0.0.0, no authentication on any endpoint | Partly fixed in P2: device tokens + scopes + `AuthGate` (`MIMO_REQUIRE_AUTH=1`), CORS narrowed to localhost. Still open: the default bind stays 0.0.0.0 and the legacy `/chat` path is unauthenticated until the apps switch to conversations |
| 11 | Tools | Allow-listed tools and AST calculator are sound; only 5 tools (no browser/file/terminal/UI) | Schemas + levels added (M2); more tools Phase 3 |
| 12 | Android | `ApiService.BASE_URL` hardcoded to `http://192.168.0.151:8000`; no settings screen | Open - needs on-device build/test |
| 13 | Android | `usesCleartextTraffic=true` globally; `allowBackup=true` | Open - restrict to LAN/debug |
| 14 | Android | Repo has no Room/conversation code; local tree is ahead of GitHub | Action: commit/push your local Android work |
| 15 | Tests | No tests existed | 88 added (backend only) |

## Milestone 1 (this change): model layer + backend stabilization
Implemented: provider interface, Ollama + Gemini providers, router with per-task models, user-selectable provider,
429 backoff, cooldowns, automatic Ollama fallback, usage tracking, env-only keys, `/llm/*` API, fixes 1-7 above.

Verified: 88 automated tests pass (providers, retry, usage, router, HTTP round-trip against a stub server, real FastAPI app
with fake models). Two regression mutations (privacy gate removed; old intent heuristic restored) were caught by the tests.
NOT verified: live Ollama, live Gemini, Android, Windows.

## Milestone 2: agent engine
Implemented: tool registry with pydantic schemas and autonomy levels 1-3, planner with validation/repair, plan -> policy ->
execute -> verify -> replan loop, task manager (background runs, cancel, confirmation, per-task timeout, restart recovery),
persistent task history + audit log, `/agent/*` API, `scripts/eval_planner.py`. See `docs/AGENT_ENGINE.md`.
Verified: 128 tests total pass (40 new). Mutation checks: auto-approving level 3, ignoring cancel, and ignoring failed
verification were each caught. Suite repeated 15x with no flakes. NOT verified: planning quality of the real qwen2.5:1.5b
(run `python -m scripts.eval_planner --local`), live Ollama/Gemini, Windows, Android.

## P2: identity + shared conversations
Implemented: `backend/core/security/` (hashed bearer tokens, pairing codes, per-device scopes,
revocation, rotation, event log, optional auth gate), `backend/core/conversations.py` (durable,
device-tagged conversations), `POST /chat` with `conversation_id`, CLI `pair`/`devices`.
Verified: 179 tests (51 new); six mutations each caught (plaintext token, ignored revocation,
open gate, history ignored, unauthenticated shared chat, scope escalation). Live uvicorn pairing
flow checked end to end. NOT verified: Windows, Android, live Ollama.

## Next milestones
3. Windows tools: killable subprocess execution first, then browser (Playwright), apps, files, PowerShell with confirmation. Must be tested on your Windows PC.
4. Conversations stored server-side (`database.py`) with migration-safe schema; memory dashboard API.
5. Auth (token) + LAN-only binding; then Android settings/connection screen and conversation drawer.
6. PySide6 desktop app; voice; Android accessibility agent.
