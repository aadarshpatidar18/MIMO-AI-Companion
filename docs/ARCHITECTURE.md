# MIMO architecture — as built, and the extension points

This describes the code that exists today (verified by reading it), plus the seams a new
capability plugs into. Read this before adding a module.

## Process picture

```
Android app (Kotlin/Compose)   Desktop app (planned, PySide6)
          |                              |
          +-------- HTTP/JSON -----------+
                          |
                    FastAPI (backend/api.py)
                          |
   +----------------------+----------------------+
   |                      |                      |
 /chat, /memory       /agent/*               /llm/*
 (backend/llm.py)   (core/agent)           (core/llm)
   |                      |                      |
 ask_mimo()          AgentEngine              ModelRouter
   |                      |                      |
   +---- generate_text ---+-----------> Ollama / Gemini
```

## Module map

| Module | Responsibility | Notes |
|---|---|---|
| `backend/api.py` | App wiring, `/chat`, `/memory`, lifespan | Conversation history is an in-process dict (to be replaced) |
| `backend/llm.py` | Prompt construction, intent classification, `ask_mimo` | Legacy intent path still used by `/chat` |
| `backend/memory.py` | SQLite memories, categories, dedupe | Keyword LIKE search, no importance |
| `backend/tools.py` | 5 legacy tools | Wrapped by `core/agent/builtin.py` |
| `backend/core/llm/` | Provider interface, Ollama, Gemini, router, retry, usage, config | Add a provider by subclassing `LLMProvider` |
| `backend/core/agent/` | Registry, planner, policy, engine, task manager, store, routes | The real execution path |
| `backend/database.py` | Empty | Reserved for conversations/identity |
| `android/` | Chat client | Hardcoded base URL, no persistence |

## The five seams

1. **A new tool** — `registry.register(ToolSpec(name, description, ParamsModel, handler, level, timeout_s, verify))`
   in `core/agent/builtin.py` or a new `backend/tools/<domain>.py` that takes a registry.
   `level`: 1 read-only, 2 reversible, 3 consequential (always confirmed). `verify` returns
   True/False/None. Raise `ToolError("user-presentable message")` for expected failures.
   The planner sees tools through `registry.prompt_block()`, so nothing else needs editing.

2. **A new model provider** — subclass `core/llm/base.py::LLMProvider`
   (`name`, `is_local`, `default_model`, `is_configured()`, `generate()`), register it in
   `core/llm/__init__.py`, then it becomes selectable per task in `config/models.json` / `PUT /llm/tasks/{task}`.

3. **A new API surface** — a module exposing `router = APIRouter(prefix="/x")`, included in
   `backend/api.py`. Keep handlers thin; put state in a store class with its own SQLite file
   (see `core/agent/store.py` for the concurrency pattern: one connection, `RLock`, `check_same_thread=False`).

4. **A new device/platform operator** — implement the tool handlers against an interface with a
   real backend (Windows/PowerShell/Playwright/Android) and a mock used by tests. The engine must
   not know which one is loaded.

5. **Persistent identity** — `backend/core/security/` (device tokens, scopes) and
   `core/conversations.py` (durable messages). Every device authenticates with a token carrying
   scopes; `/chat` writes to the shared store so any device reads the same history.

## Conventions that must hold

- Errors the user should read are `ToolError`; anything else is logged and reported generically.
- Result text is built from tool output, never from a model's claim (`AgentEngine._summarize`).
- A user or policy "no" is final: no replan around a denied step.
- Every route that can act gets a scope check before it can be reached by a device token.
- Secrets only in environment/`.env`; `scripts/check_no_secrets.py android` gates the app.

## Known weak points (do not build on them)

- `AgentEngine._execute` cannot kill a running handler thread — long tools must be subprocesses
  that the tool itself can terminate (Windows/browser work must respect this).
- `/chat`'s intent path duplicates what the agent engine does with fewer checks; it should be
  collapsed onto the engine once the roster exists.
- `memory.py` normalises and dedupes on every startup — will not scale past a few thousand rows.
