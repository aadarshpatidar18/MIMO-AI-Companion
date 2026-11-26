# Device identity and shared conversations

This is the foundation the phone, the laptop and the desktop app sit on: a device proves who it
is, and every conversation lives in one store that all of them read.

## Pairing a new device

1. Start the backend on the PC: `uvicorn backend.api:app --host 127.0.0.1 --port 8000`
2. On the PC: `python -m backend.main pair` — prints an 8-character code, valid 10 minutes,
   single use, burned after 5 wrong guesses.
3. On the new device: `POST /auth/pair` with `{"code": "...", "name": "Pixel", "kind": "android"}`.
   The response carries a token **once**; the server only keeps its SHA-256 hash.
4. That device now sends `Authorization: Bearer mimo_...` on every call.

A code can only be issued from the PC itself (loopback) or by a device holding `device:manage`,
so a phone on the network cannot mint codes or enroll itself.

`python -m backend.main devices` lists paired devices and when each was last seen.

## Scopes

| Scope | Lets a device | android | windows/desktop |
|---|---|---|---|
| `chat:read` | read conversations | ✅ | ✅ |
| `chat:write` | send messages, create/rename/delete conversations | ✅ | ✅ |
| `memory:read` / `memory:write` | inspect and edit memories | ✅ | ✅ |
| `agent:run` | submit agent tasks | ✅ | ✅ |
| `agent:control` | cancel, approve confirmations | ✅ | ✅ |
| `device:read` | see the device list | ✅ | ✅ |
| `device:manage` | enroll, rename, revoke devices, change security settings | ❌ | ✅ |

Revocation is immediate: the next request from a revoked device gets 401.

## Endpoints

| Method | Path | Scope | Purpose |
|---|---|---|---|
| GET | `/auth/status` | public | auth mode, whether a pairing window is open, device count |
| POST | `/auth/pair/code` | loopback or `device:manage` | show a code on the PC |
| POST | `/auth/pair` | the code | enroll, returns the token once |
| GET | `/auth/me` | token | this device's identity and scopes |
| POST | `/auth/token/rotate` | token | replace this device's token |
| GET | `/devices` | `device:read` | list devices, last seen |
| PATCH | `/devices/{id}` | `device:manage` | rename |
| DELETE | `/devices/{id}` | `device:manage` | revoke (cannot revoke yourself) |
| GET | `/security/events` | `device:manage` | audit trail: enrollments, failures, revocations |
| PUT | `/security/settings` | loopback or `device:manage` | require auth on/off |
| POST | `/conversations` | `chat:write` | create |
| GET | `/conversations` | `chat:read` | list, newest first, with count and last message |
| GET | `/conversations/{id}/messages` | `chat:read` | paginate with `after_id` |
| POST | `/conversations/{id}/messages` | `chat:write` | append |
| PATCH / DELETE | `/conversations/{id}` | `chat:write` | rename / delete (messages cascade) |

## Two ways to chat

* **Shared** — `POST /chat` with `conversation_id`. Needs a paired device with `chat:write`;
  the two turns are stored, and the next call is given the recent history from the store.
  This is the phone → laptop continuity path: create a conversation on the phone, open the
  laptop, `GET /conversations`.
* **Legacy** — `POST /chat` without `conversation_id` keeps the old in-memory `session_id`
  behaviour so the current Android build keeps working. It is LAN-development-only.

## Auth mode

`require_auth` is **off by default** so an existing install keeps working. Turn it on with
`PUT /security/settings {"require_auth": true}` from a paired PC device, or with
`MIMO_REQUIRE_AUTH=1` (env wins). When on, every route except `/`, `/health`, `/auth/status`,
`/auth/pair` and the API docs needs a live token. Pair the PC first, before you close the door.

## What is not here yet

* The Android app does not send a token or use conversations yet — that is the next slice of
  Milestone 6.
* One user, one household. There is no multi-account model, by design.
* Pairing codes live in the backend process, so a restart cancels an unused code.
* Rate limits are in-memory (60 chat messages/minute per device), so they reset on restart.
