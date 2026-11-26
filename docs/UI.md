# The MIMO interface

Served by the backend itself: start it, then open <http://127.0.0.1:8000>. The same page works in
a phone browser, and the phone sees exactly the same conversations as the laptop.

One HTML file, no build step, no CDN: `backend/web/index.html`. It talks to the same public API the
Android app uses, so anything the interface can do is scriptable.

## Screens

| Screen | What it does | APIs |
|---|---|---|
| Chat | The conversation, the orb, history sidebar, suggested starts | `/conversations`, `/chat` |
| Memory | Everything MIMO knows, add/correct/forget | `/memory` |
| Devices & permissions | Who is paired, last seen, scopes, revoke, show a pairing code | `/devices`, `/auth/pair/code` |
| Activity | Multi-step tasks, status, approve/deny, stop | `/agent/tasks`, `/agent/tasks/{id}/cancel`, `/confirm` |
| Settings | Character, theme, require-auth, forget this device | `/persona`, `/security/settings` |

The Stop button in the chat header appears whenever a task is queued or running and cancels it.

## Pairing from inside the app

1. On the PC: `python -m backend.main pair` prints an 8-character code (or press "This is the PC" on
   the pairing screen, which fills it in for you).
2. On the phone: open the same URL, type the code, name the device, Connect.
3. The token is kept in that browser's `localStorage`; the server stores only its hash.

Without a token the app still works in a local-only mode (legacy `/chat`, history kept in the
browser) unless `require_auth` is on, in which case pairing is required before anything else.

## The character

`backend/core/persona.py` owns it: identity, five traits, the hard rules, and the style derived from
four settings — warmth (1–5), humour (0–3), verbosity (brief / balanced / detailed), and whether it
signs off after finishing work. Settings are saved to `data/persona.json` and read by every answer,
including the CLI. Traits and the hard rules are deliberately not editable: they are the character,
not a preference.

The orb is the character's face: it breathes when idle and spins a ring while thinking. Two eyes
blink on a slow timer. It is pure CSS, so it costs nothing to draw on a phone.

## What is not here yet

* Voice input and speech output — milestone 6, no audio code in the build.
* Streaming tokens: an answer arrives in one piece, with a typing indicator while it works.
* The desktop window (PySide6): today this page in a browser is the desktop experience. A native
  shell that wraps the same page is the low-risk path when we get there.
* Android runs this page in a browser; the native Compose app still only chats.
