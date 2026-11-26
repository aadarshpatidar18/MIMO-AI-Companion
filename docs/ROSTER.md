# The agent roster

MIMO hands a goal to one named specialist. Each has its own tools, its own autonomy ceiling and its
own model route, so a research request cannot delete a file and a file request cannot spend an hour
in a browser.

Routing lives in `backend/core/agent/roster.py`. It is keyword-scored and readable on purpose: a
goal that names nothing goes to the **generalist**, which holds the whole registry, so behaviour
never gets worse than before the roster existed.

| Agent | Handles | Tools it holds | Ceiling | Model route |
|---|---|---|---|---|
| Research | "find out", "search", "latest", "compare" | browser search/read/open, time, date, arithmetic | 2 | `research` |
| Coding | code, bugs, tests, refactor, build | read/search/list/write files, run tests, run allowlisted commands | 3 | `code` |
| Computer Operator | open/close apps, click, type, screen, PowerShell | app control, screen capture + OCR, input, PowerShell, system facts | 3 | `plan` |
| File Manager | documents, folders, rename, move, organise | list/read/write/move/delete/search, create folder | 3 | `summarize` |
| Browser | youtube, sites, tabs, forms, follow links | open site, Playwright session, search, click, screenshot | 3 | `plan` |
| Memory | remember, recall, forget, "what do you know" | remember, recall, forget | 2 | `memory` |
| **Generalist (MIMO)** | anything unmatched | every tool | 2 | `plan` |

## Three roles from the brief that are deliberately not here

`RESERVED` in `roster.py` records them, with the reason:

* **Communication** — needs email and chat transports that do not exist yet. An agent with no tools
  would only be a name in a list.
* **Verification** — the engine already verifies every step against the tool's own verifier and
  records `true` / `false` / `null`. It is a behaviour, not a colleague.
* **Planning** — that is the planner itself.

If the transports arrive, Communication becomes a real profile with `send_email` and `send_message`
tools and nothing else changes.

## What a run looks like

1. `submit(goal)` → the roster picks a specialist (or you name one).
2. That specialist's planner is given **only its own tools** in the prompt, so the plan cannot
   mention a tool it does not have.
3. The engine runs plan → policy → execute → verify → replan with the specialist's ceiling; a
   ceiling can turn "run it" into "ask first", never the other way round.
4. The task record keeps the agent's key, so the Activity screen and the API show who did the work.

`GET /agent/roster` lists the roster and the reserved roles. `POST /agent/tasks` accepts
`"agent": "files"` to force one.
