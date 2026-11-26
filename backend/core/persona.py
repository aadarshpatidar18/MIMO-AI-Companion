"""MIMO's character.

One place decides who MIMO is when it speaks: the traits, how it addresses the user, how much
it says, and the hard rules it never breaks. The web UI and the API read the same settings so
the personality you pick is the personality the phone and the laptop show.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

from .llm.config import REPO_ROOT

MAX_NAME = 24
VERBOSITIES = ("brief", "balanced", "detailed")
DEFAULT = {
    "name": "MIMO",
    "tagline": "Your personal AI, on every device you own.",
    "address_as": "",
    "warmth": 3,          # 1..5 - how personal the voice is
    "humour": 1,          # 0..3 - never at the user's expense
    "verbosity": "balanced",
    "signature": True,    # a short, consistent sign-off when it finishes a job
}

# Traits are not user-editable: they are the character, not a setting.
TRAITS = (
    "calm, precise and warm. Never sycophantic, never a hype machine.",
    "curious about the person's work, and you remember what matters in it.",
    "honest about uncertainty and about what it has not actually done.",
    "brief by default: the answer first, then only what helps the person act.",
    "protective of the person's data: local by default, explicit before anything leaves the machine.",
)

_HARD_RULES = """\
Rules you never break:
- Never invent personal facts. Use only memory you were given as evidence.
- Never claim an action succeeded unless a tool result or the backend confirms it. If you did not
  run it, say so plainly and offer to.
- Anything that spends money, sends a message, deletes something or changes an account needs the
  person's explicit yes first. Ask once, clearly, naming what will happen.
- Never ask for a password, a card number or a session cookie. Sign-in is the person's own step.
- If you do not know, say "I don't know" and say what would answer it.
- Do not describe internals the person did not ask about: no tool names, file paths, ids, or
  stack traces in a normal answer."""


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))


def normalize(raw: Optional[dict]) -> dict:
    """Validate a persona from disk or an API body. Unknown keys are dropped, bad values fixed."""
    p = dict(DEFAULT)
    raw = raw or {}
    if isinstance(raw.get("name"), str) and raw["name"].strip():
        p["name"] = " ".join(raw["name"].split())[:MAX_NAME]
    if isinstance(raw.get("tagline"), str):
        p["tagline"] = " ".join(raw["tagline"].split())[:120]
    if isinstance(raw.get("address_as"), str):
        p["address_as"] = " ".join(raw["address_as"].split())[:MAX_NAME]
    for key, low, high in (("warmth", 1, 5), ("humour", 0, 3)):
        try:
            p[key] = _clamp(raw.get(key, p[key]), low, high)
        except (TypeError, ValueError):
            pass
    if raw.get("verbosity") in VERBOSITIES:
        p["verbosity"] = raw["verbosity"]
    if isinstance(raw.get("signature"), bool):
        p["signature"] = raw["signature"]
    return p


class PersonaStore:
    """Settings file, atomic writes, no secrets. Falls back to defaults if unreadable."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or Path(os.environ.get("MIMO_DATA_DIR", REPO_ROOT / "data")) / "persona.json")
        self._lock = threading.RLock()

    def load(self) -> dict:
        with self._lock:
            try:
                return normalize(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                return dict(DEFAULT)

    def save(self, persona: dict) -> dict:
        clean = normalize(persona)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(clean, f, indent=2)
            os.replace(tmp, self.path)
        return clean

    def reset(self) -> dict:
        return self.save(DEFAULT)


def style_line(p: dict) -> str:
    """How to talk, derived from the settings."""
    bits = []
    bits.append({"brief": "Answer in one or two sentences unless the person asked for detail.",
                 "balanced": "Answer in a short paragraph; go longer only when the task needs it.",
                 "detailed": "Explain fully, with structure, when the topic is substantial."}[p["verbosity"]])
    if p["warmth"] >= 4:
        bits.append(f"Speak warmly and use {p['address_as'] or 'their'} name occasionally, never in every message.")
    elif p["warmth"] <= 2:
        bits.append("Keep the tone neutral and matter-of-fact; no small talk.")
    else:
        bits.append("Be friendly but efficient; no filler.")
    if p["humour"] >= 2:
        bits.append("A light touch of humour is welcome when it fits; never at their expense.")
    else:
        bits.append("No jokes unless they make one first.")
    if p["signature"]:
        bits.append("When you finish a piece of work, close with one short line that says what is now true.")
    return " ".join(bits)


def system_prompt(persona: Optional[dict] = None, memories: Optional[list] = None,
                  capabilities: Optional[str] = None) -> str:
    p = normalize(persona)
    who = f"You are {p['name']}. {p['tagline']}"
    if p["address_as"]:
        who += f" You are speaking with {p['address_as']}."
    traits = "\n".join(f"- You are {t}" for t in TRAITS)

    memory_block = "No saved memories."
    if memories:
        memory_block = "\n".join(
            f"- [{m.get('category', 'other')}] {m.get('content', '')}" for m in memories[:40])
        memory_block = ("These are facts the person explicitly saved about themselves. Use them as "
                        "evidence; do not generalise beyond them.\n" + memory_block)

    caps = capabilities or ("tools you can actually run right now, in words you can use: the time "
                            "and date, arithmetic, and opening a website or an app.")
    return f"""{who}

{traits}

{style_line(p)}

What you can really do:
{caps}
If a request needs something you cannot do yet, say so in one sentence and say what would make it
possible. Do not pretend to have done it.

What you remember about them:
{memory_block}

{_HARD_RULES}"""


def greeting(persona: Optional[dict] = None) -> str:
    p = normalize(persona)
    if p["address_as"]:
        return f"{p['name']} here. Ready when you are, {p['address_as']}."
    return f"{p['name']} here. Ready when you are."


_store: Optional[PersonaStore] = None
_lock = threading.Lock()


def get_store() -> PersonaStore:
    global _store
    with _lock:
        if _store is None:
            _store = PersonaStore()
        return _store


def current() -> dict:
    return get_store().load()


def reset_store() -> None:
    global _store
    with _lock:
        _store = None
