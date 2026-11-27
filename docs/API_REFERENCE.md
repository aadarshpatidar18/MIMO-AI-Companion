# API reference

Base URL: `http://<host>:8000`. Everything is JSON except `POST /voice/transcribe` (raw WAV in,
JSON out) and `POST /voice/speak` (JSON in, `audio/wav` out).

Interactive documentation with live schemas is served by the backend itself at `/docs`, and the raw
OpenAPI document at `/openapi.json` — the tables below were generated from that document, so they
cannot drift from the code without this file being regenerated.

## Authentication

Paired devices send a bearer token:

```
Authorization: Bearer mimo_...
```

With `MIMO_REQUIRE_AUTH=1`, every route except `/`, `/health`, `/info`, `/docs`, `/redoc`,
`GET /persona` and `POST /auth/pair` refuses an unauthenticated caller with `401`. Routes that act on
another device's behalf also require a scope (`403` when the device lacks it).

Errors are always `{"detail": "..."}` — a string for a single problem, a list of objects for a
validation error. The message is meant to be shown to the user.

## The five things you will actually call

```bash
# 1. Pair a new device (run on the PC; the code is single use)
python -m backend.main pair android      # or: desktop | windows

# 2. Redeem it (the device does this once)
curl -X POST http://PC:8000/auth/pair -H 'Content-Type: application/json' \
     -d '{"code":"AB12CD34","name":"Aadarsh phone","kind":"android"}'
# -> {"device": {...}, "token": "mimo_..."}

# 3. Create a conversation, then talk in it
curl -X POST http://PC:8000/conversations -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d '{"title":"Morning"}'
curl -X POST http://PC:8000/chat -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"message":"plan my day","conversation_id":"<id>"}'
# -> {"response": "...", "user_message_id": 41, "assistant_message_id": 42, "created_at": "..."}

# 4. Read what was stored (this is what every client renders)
curl "http://PC:8000/conversations/<id>/messages?after_id=40" -H "Authorization: Bearer $TOKEN"

# 5. Give MIMO a goal and watch it work
curl -X POST http://PC:8000/agent/tasks -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d '{"goal":"tidy the Downloads folder"}'
curl http://PC:8000/agent/tasks/<task_id> -H "Authorization: Bearer $TOKEN"
```

`POST /chat` returns the ids it just stored. Clients use them to reconcile their own optimistic copy
of the turn instead of re-reading the conversation and guessing which rows are new.

## Routes

### agent

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/agent/actions` | List Actions |
| `GET` | `/agent/policy` | Read Policy |
| `PUT` | `/agent/policy` | Write Policy |
| `GET` | `/agent/roster` | List Roster |
| `GET` | `/agent/tasks` | List Tasks |
| `POST` | `/agent/tasks` | Create Task |
| `GET` | `/agent/tasks/{task_id}` | Get Task |
| `POST` | `/agent/tasks/{task_id}/cancel` | Cancel Task |
| `POST` | `/agent/tasks/{task_id}/confirm` | Confirm Task |
| `GET` | `/agent/tools` | List Tools |

### conversations

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/conversations` | List Conversations |
| `POST` | `/conversations` | Create Conversation |
| `DELETE` | `/conversations/{conversation_id}` | Delete Conversation |
| `GET` | `/conversations/{conversation_id}` | Get Conversation |
| `PATCH` | `/conversations/{conversation_id}` | Rename Conversation |
| `GET` | `/conversations/{conversation_id}/messages` | Read Messages |
| `POST` | `/conversations/{conversation_id}/messages` | Append Message |

### llm

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/llm/cooldowns/clear` | Clear Cooldowns |
| `PUT` | `/llm/selection` | Set Selection |
| `GET` | `/llm/status` | Status |
| `PUT` | `/llm/tasks/{task}` | Set Task |
| `POST` | `/llm/test` | Test |
| `GET` | `/llm/usage` | Usage |

### other

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/chat` | Chat |
| `GET` | `/health` | Health |
| `GET` | `/info` | Info |
| `DELETE` | `/memory` | Delete Memory |
| `GET` | `/memory` | Read Memory |
| `POST` | `/memory` | Create Memory |
| `PUT` | `/memory/{memory_id}` | Correct Memory |
| `GET` | `/system/capabilities` | System Capabilities |

### persona

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/persona` | Read Persona |
| `PUT` | `/persona` | Write Persona |
| `POST` | `/persona/reset` | Reset Persona |

### security

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/auth/me` | Me |
| `POST` | `/auth/pair` | Pair |
| `POST` | `/auth/pair/code` | Issue Pairing Code |
| `GET` | `/auth/status` | Auth Status |
| `POST` | `/auth/token/rotate` | Rotate Token |
| `GET` | `/devices` | List Devices |
| `DELETE` | `/devices/{device_id}` | Revoke Device |
| `PATCH` | `/devices/{device_id}` | Rename Device |
| `GET` | `/security/events` | Security Events |
| `PUT` | `/security/settings` | Write Settings |

### voice

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/voice/cancel` | Cancel |
| `GET` | `/voice/settings` | Read Settings |
| `PUT` | `/voice/settings` | Write Settings |
| `POST` | `/voice/speak` | Speak |
| `GET` | `/voice/status` | Voice Status |
| `POST` | `/voice/transcribe` | Transcribe |


## Status codes that mean something specific

| Code | Where | Meaning |
|---|---|---|
| `401` | any authenticated route | No token, or a revoked/rotated one |
| `403` | tool calls, device routes | The device is paired but lacks the scope, or a policy denied the action |
| `404` | `/conversations/{id}`, `/agent/tasks/{id}` | Unknown object — clients should drop their cached copy |
| `409` | `/agent/tasks/{id}/confirm`, `/auth/token/rotate` | The task is not waiting for confirmation; the token was already rotated |
| `413` | `/voice/transcribe` | Recording over 12 MB |
| `415` | `/voice/transcribe` | Body is not `audio/wav` |
| `429` | `/chat` | More than 60 turns in a minute from one device |
| `503` | `/chat`, `/voice/*` | No model provider available, or the voice model is not installed — the message says which |

## Streaming and cancellation

There is no websocket. Clients poll `GET /agent/tasks?limit=N` (the phone every 20 s, the desktop
every 4 s) and `GET /agent/tasks/{id}` while a task runs. Cancellation is
`POST /agent/tasks/{id}/cancel`; confirmation of a paused step is `POST /agent/tasks/{id}/confirm`
with `{"approve": true|false}`. Speech can be interrupted with `POST /voice/cancel`, which stops the
next sentence rather than the whole process.
