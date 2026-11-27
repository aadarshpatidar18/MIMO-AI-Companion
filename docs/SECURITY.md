# Security model

What MIMO protects, how, and — just as important — what it deliberately does not.

## The shape of the threat

MIMO is a personal system that runs on one machine, on a home network, and can operate that machine.
The realistic failures are: an unpaired device on the same Wi-Fi driving the assistant, a
consequential action (deleting files, sending something, clicking a purchase) happening without the
owner's knowledge, a model being talked into it by content on a web page, and credentials leaking
into the repository.

Everything below is aimed at those four.

## Identity and device authentication

- **Pairing.** The PC issues a single-use code (`POST /auth/pair/code`), only to a caller on
  loopback or to a device already holding `device:manage`. Codes expire, are burned after repeated
  wrong guesses, and a new code invalidates the previous one. Redeeming a code returns the device
  row and a token **once**.
- **The code decides the device kind.** `pair android`, `pair desktop`, `pair windows`. A code
  issued for a phone cannot be redeemed as a desktop, which is what stops the redeeming client from
  choosing a privilege tier for itself: the issuing side picks it, and a mismatch is refused (and
  counted, so kinds cannot be probed).
- **Tokens.** A token is `mimo_` + 32 random bytes, URL-safe. Only its SHA-256 **hash** is stored
  (`device_tokens.token_hash`); the raw value exists on the device and nowhere else. A test asserts
  the raw token never appears in the database.
- **Scopes.** Each device kind gets a fixed set, enforced per route (`require_scope`):

  | Scope | android | windows | desktop |
  |---|:--:|:--:|:--:|
  | `chat:read`, `chat:write` | ✓ | ✓ | ✓ |
  | `memory:read`, `memory:write` | ✓ | ✓ | ✓ |
  | `agent:run`, `agent:control` | ✓ | ✓ | ✓ |
  | `device:read` | ✓ | ✓ | ✓ |
  | `device:manage` | — | ✓ | ✓ |

  A phone can therefore run MIMO but cannot enumerate or revoke other devices. Scope is read from
  the device row on every request, so downgrading a device takes effect immediately.

  The browser interface is its own kind (`browser`) with the phone's scopes and no `device:manage`,
  because its token lives in `localStorage` and a stolen browser token must not be able to revoke
  the phone or issue codes.
- **The gate.** With `MIMO_REQUIRE_AUTH=1`, every route except `/`, `/health`, `/info`, `/docs`,
  `/persona` (read) and `POST /auth/pair` needs a live token. The dependency that enforces scopes is
  separate from the gate, so a route that forgets its dependency still cannot be reached.
- **Revocation and rotation.** `DELETE /devices/{id}` takes effect on that device's next request;
  `POST /auth/token/rotate` swaps the token for the calling device only and invalidates the old one.
- **Audit.** `security/events` records pairing attempts, failed redemptions, rotation, revocation and
  rejected requests, with a device id and a short detail string. `GET /security/events` exposes it,
  and a `device:manage` holder can flip `require_auth`.

## What the agent is allowed to do

Tools carry a level, and the policy (`backend/core/agent/policy.py`) decides per step:

| Level | Meaning | Default |
|---|---|---|
| 1 | Read-only: `get_time`, `list_files`, `read_file`, `browser_read`, `recall` … | runs |
| 2 | Reversible: `write_file`, `move_path`, `launch_app`, `press_keys`, `remember` … | runs |
| 3 | Consequential: `delete_path`, `run_powershell`, `run_command`, `browser_click`, `close_app`, `type_text` … | **always asks** |

The 36 tools split 14 / 12 / 10 across those levels. The ceiling for automatic execution is clamped
in `__post_init__` to at most 2, so no setting — including the API — can make a level-3 action run
without a confirmation. `deny` additionally blocks named tools outright.

Two further guards:

- **Capability policy.** `ActionPolicy` maps a capability to the scope that grants it and is asked
  immediately before each tool call and each memory write. A device without `agent:run` cannot
  invoke a tool even if it reaches `/chat`.
- **The confirmation is a real step.** A level-3 step pauses the task and returns
  `awaiting_confirmation`; `POST /agent/tasks/{id}/confirm` with `approve: false` cancels it. It is
  not a "we assumed yes" gate.

## The operators

**Files.** Every path is resolved (symlinks followed) and must land inside an allowed root, by
default the user's home plus a few subdirectories (`backend/tools/paths.py`). A symlink pointing
outside is refused, not followed.

**PowerShell.** `run_powershell` is not "run this command". It takes a **cmdlet from a fixed
enum** (`Get-Process`, `Get-Service`, `Get-ChildItem`, …), with a name validated against a strict
pattern, a path resolved inside the sandbox, and every argument quoted with single-quote doubling.
Free-form command lines are not reachable through it.

**Commands.** `run_command` runs an allowlisted program with argument length and NUL checks, in its
own process group, and kills the whole group on timeout (`backend/tools/process.py`).

**Browser.** Playwright drives a real browser. Clicks that look consequential (buy, delete, confirm,
pay…) are level 3 and need approval; reading and searching do not.

**The phone.** The accessibility service only exists while the owner enabled it in Android settings
and can be switched off there at any time. It reads the active window and can tap, type and scroll —
no background timer, no overlay, no network access of its own. Screen capture needs the system's
MediaProjection consent, shows a permanent notification while armed, and takes frames only when the
owner asks for an analysis.

**Windows automation** (screenshots, input) is likewise behind `pyautogui`/`mss` and only reachable
through tools that carry a level.

## Data at rest

| Item | Where | Protection |
|---|---|---|
| Device tokens | `data/security.db` | SHA-256 hash only |
| Conversations, memory | `data/*.db` | Filesystem permissions; WAL mode |
| Cloud API keys | `.env` (git-ignored) | Never written to the database or logs |
| Phone token | Android DataStore | App-private storage; not backed up to a cloud by the app itself |
| Desktop token | `~/.mimo/desktop.json` | Written with mode 0600 |
| Voice settings | `~/.mimo/voice.json` | No secrets in it |

`scripts/check_no_secrets.py` scans the tree for key-shaped strings and runs in CI-style checks.
`.gitignore` excludes `.env`, databases, virtualenvs and local properties; no key has ever been
committed, and the release ZIP is built with an explicit exclude list.

## Exposure

The backend **refuses to start** on a non-loopback address unless `MIMO_REQUIRE_AUTH=1`, and the
Windows installer writes LAN + authentication together. `MIMO_ALLOW_OPEN_LAN=1` is the explicit,
logged opt-in for running an open server on a trusted network; nothing else reaches that state by
accident. Request bodies are capped before parsing (2 MB for JSON, 13 MB for a recording) by an ASGI
middleware that also counts streamed bytes.

## Transport

The backend serves plain HTTP on the LAN by design: it is a personal server on the owner's own
network, and TLS with a self-signed certificate would break every phone pairing flow in practice.
Two consequences, stated plainly:

- Anything on your Wi-Fi can *reach* the backend. It cannot *use* it without a device token once
  `MIMO_REQUIRE_AUTH=1`, which is the setting to turn on for any shared or public network.
- The Android app refuses a non-`https://` address unless its host is loopback or RFC1918 private, so
  a mistyped public host cannot send a token across the internet in the clear.

If you expose MIMO beyond your LAN, put it behind a reverse proxy with TLS and keep
`MIMO_REQUIRE_AUTH=1`. That configuration is out of scope here and untested.

## What is *not* protected, deliberately

- **One owner.** There are no user accounts. Every paired device acts as the owner within its
  scopes. MIMO is not multi-tenant and must not be shared between people.
- **The model can be fooled by content.** A web page can try to talk the model into an action. The
  defence is structural, not cleverness: consequential tools need your approval, and the policy is
  evaluated outside the model's control. A read-only tool being talked into reading the wrong thing
  is a residual risk.
- **The rate limiter is per process and in memory.** Restarting the backend resets it, and running
  several workers would give each its own budget. MIMO is designed and tested as **one uvicorn
  worker**: pairing codes and live task control are per process, so a second worker would not see
  them. Do not scale it horizontally.
- **Task submission is not idempotent.** A client that retries `POST /agent/tasks` gets a second
  task. None of MIMO's own clients retry a submission automatically; a third-party client must not
  either.
- **No encryption of the databases.** They are protected by filesystem permissions; anyone with your
  Windows account can read them. Use BitLocker or a vault if that matters to you.
- **Android backup.** `allowBackup="true"` is left on for the app so a re-install keeps history; the
  token is in DataStore, which Android may include in a device backup. Turn off backup for the app
  if you would rather lose history than carry a token in a backup.

## Reporting and reviewing

The audit trail for a release is in `docs/V1_STATUS.md` (what was checked, by whom, with what
evidence). Two independent reviews — one on security and backend reliability, one on Android and
performance — were run against this branch; their findings and my dispositions are recorded there,
including the ones I disagreed with and why.
