# Architecture — as built

This describes the code that exists, verified by reading it, plus the seams a new capability plugs
into. It supersedes the earlier sketch in this file, which described a conversation store that has
since been replaced.

## Process picture

```
      Android app (Kotlin/Compose)   Desktop (PySide6)   Browser (served by the backend)
                    \                     |                    /
                     \------ HTTP/JSON + bearer token --------/
                                        |
                          FastAPI  (backend/api.py)
                          ├── AuthGate middleware  (token when required)
                          ├── BodySizeLimit       (reject oversize before parse)
                          └── routers: /chat /memory /conversations /agent /llm
                                        /security /persona /voice
                          |
     +-------------+--------------+-------------+-------------+--------------+
     |             |              |             |             |              |
  ModelRouter   Agent engine   Memory (FTS5)  Conversations  Security      Voice
  Ollama/Gemini plan→policy    SQLite         SQLite WAL     SQLite        Whisper/Kokoro
                →execute       rank+recall    device-tagged  hashed tokens  lazy models
                →verify
```

One process, one data directory (`MIMO_DATA_DIR`, default `./data`), four SQLite files:
`security.db`, `conversations.db`, `agent.db`, `memory.db`. WAL mode, one writer at a time; the
conversation store additionally holds a per-conversation lock for the length of a turn so two
devices cannot interleave.

## Module map

| Module | Responsibility | Notes |
|---|---|---|
| `backend/api.py` | App wiring, `/chat`, `/memory`, lifespan, LAN guard | A turn is read-history → model → append, under a per-conversation lock |
| `backend/llm.py` | Prompt building, intent classification | Legacy intent path still used by `/chat` |
| `backend/core/llm/` | Providers, router, retry, cooldown, usage, per-task routes | Ollama local, Gemini cloud; `local_only` routes never leave the machine |
| `backend/core/agent/` | Planner, policy, engine, roster, task store, manager | plan → policy → execute → verify → one replan; level-3 always asks |
| `backend/core/agent/registry.py` | The 36 tools and their levels | 14 read-only, 12 reversible, 10 consequential |
| `backend/core/conversations.py` | Durable shared history | Server-owned ids; `append_turn` writes both rows in one transaction |
| `backend/memory.py` | Memory with importance and ranked recall | FTS5 with a LIKE fallback; in-place migration |
| `backend/core/security/` | Pairing, tokens, scopes, gate, dispatch policy | Codes bound to a device kind; tokens stored hashed |
| `backend/tools/` | Operators: files, PowerShell, commands, apps, screen, browser | Sandbox, allowlists, process-group timeouts |
| `backend/core/voice/` | Whisper STT + Kokoro TTS behind one manager | Lazy loading, sentence streaming, cloud opt-in twice |
| `android/` | Phone client and operator | Room cache, offline queue, accessibility + OCR, verified actions |
| `desktop/mimo_desktop/` | PySide6 client | Same API, all calls off the GUI thread |
| `backend/web/index.html` | Browser interface (served at `/`) | Token in localStorage, kind `browser` |
| `scripts/` | Installers, load harness, voice benchmark, evals | Windows scripts are PowerShell, tested on Linux only by review |

## The two contracts that matter

**1. Wire format.** Every timestamp on the wire is epoch seconds as a JSON **number** (SQLite REAL).
The web UI does `new Date(ts * 1000)`; Android reads it through `WireTime.toIsoInstant()`; the
desktop formats it in one `stamp()` helper. A client that reads one as a string fails to decode the
whole response — `android/app/src/test/.../WireContractTest.kt` decodes captured real responses with
the app's own types so that cannot happen silently again.

**2. Turn atomicity.** `POST /chat` with a `conversation_id` writes the question and the answer in a
single transaction and returns `user_message_id` and `assistant_message_id`. Clients use those ids
to reconcile their own optimistic copy instead of guessing. A failed turn stores nothing.

## Extension points

- **A new tool:** define it in `backend/tools/`, give it a `level` and, where possible, a verifier,
  register it in `backend/core/agent/registry.py`, and add it to the specialists' subsets in
  `roster.py` if they should have it. Tests assert the level of anything destructive.
- **A new model provider:** subclass `LLMProvider`, declare `is_configured()` and `generate()`, and
  add it to the router's provider map; retry/cooldown/usage are already generic.
- **A new client:** read `docs/API_REFERENCE.md`, honour the two contracts above, and do not
  re-implement memory or policy — they live on the server for a reason.

## What is deliberately single-process

Pairing codes, the chat rate limiter and live task control are in memory. Running more than one
uvicorn worker would break pairing (a code issued by one worker is unknown to another) and task
cancellation (the task lives in the worker that started it). MIMO is a personal server; one worker
is the supported configuration and the load figures in `docs/PERFORMANCE.md` are for one worker.
