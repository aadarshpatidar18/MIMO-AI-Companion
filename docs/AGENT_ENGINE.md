# Agent engine

`backend/core/agent` turns a goal into validated, permission-checked, verified tool steps.

## Flow
1. **Plan** - the `plan` route of the model router returns JSON `{"steps":[{"tool","args","reason"}]}`.
   Output is validated with pydantic (one automatic repair retry; max 8 steps; oversize plans are rejected, not truncated).
   An empty plan means "this is a question": the goal goes to the normal chat answerer instead of tools.
2. **Validate** - tool name must exist; args must match the tool's schema (`extra="forbid"`), e.g. `open_website.url` is an enum.
3. **Policy** - each tool has a level; the autonomy policy returns allow / confirm / deny.
4. **Execute** - in a worker thread with a per-tool timeout; cancellation is polled every 50 ms.
5. **Verify** - optional per-tool check (True / False / None = cannot verify). `False` fails the step.
6. **Recover** - a failed step triggers ONE replan that sees what failed. Denied or policy-blocked steps are never worked around.
7. **Report** - the final text is built only from tool output, never from model claims.

## Autonomy levels
| Level | Meaning | Default |
|---|---|---|
| 1 read-only | time, date, calculate | runs |
| 2 reversible | open website / app | runs (set `max_auto_level` to 1 to require confirmation) |
| 3 consequential | subscribe, send, delete, purchase... | ALWAYS needs confirmation; the policy clamps `max_auto_level` to 2 |

No level-3 tool is registered yet (the engine and tests support them). Waiting for confirmation does not count against the task timeout; no answer within 5 min = denied.

## API (`/agent`)
`POST /tasks` (202, runs in background) - `GET /tasks`, `GET /tasks/{id}` - `POST /tasks/{id}/cancel` -
`POST /tasks/{id}/confirm {"approve": bool}` - `GET /tools` - `GET /actions` (audit log) - `GET|PUT /policy`.
Task status: queued, planning, running, awaiting_confirmation, succeeded, failed, cancelled, timed_out.
Tasks, steps and every action are stored in `data/agent.db`; tasks interrupted by a restart are marked failed on startup.

## Adding a tool
```python
registry.register(ToolSpec("name", "what it does", ParamsModel, handler, level=2, timeout_s=15, verify=check))
```
Raise `ToolError("user-presentable message")` for expected failures. Other exceptions are logged and reported generically.

## Known limits
* A running tool thread cannot be force-killed: on cancel/timeout its result is abandoned and it may finish in the background. Long-running tools (browser, PowerShell) must be killable subprocesses - to be designed in Phase 3.
* `open_website`/`open_app` cannot confirm the page/app actually appeared (`verified: null`).
* Planning quality depends on the model. Measure yours: `python -m scripts.eval_planner --local`.
* The existing `/chat` endpoint is unchanged; `/agent` is a separate path until the apps are switched over.
* No authentication yet (Phase 9) - keep the backend on your LAN.
