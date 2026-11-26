"""Device tokens and scopes.

A device proves its identity with a bearer token. Only the SHA-256 hash of a token is
ever stored; the plaintext exists once, in the enrollment response, and never again.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets

PREFIX = "mimo_"
TOKEN_BYTES = 32

# Scopes are deliberately coarse. A route asks for exactly one.
SCOPES = frozenset({
    "chat:read",       # read stored conversations and messages
    "chat:write",      # send messages, create conversations
    "memory:read",
    "memory:write",
    "agent:run",       # submit agent tasks
    "agent:control",   # cancel tasks, answer confirmations
    "device:read",     # see which devices exist and are online
    "device:manage",   # enroll new devices, revoke devices, rotate tokens
})

# What each kind of device may do. The phone cannot revoke the laptop; the PC can.
DEVICE_KINDS: dict[str, frozenset[str]] = {
    "android": frozenset({"chat:read", "chat:write", "memory:read", "memory:write",
                          "agent:run", "agent:control", "device:read"}),
    "windows": frozenset({"chat:read", "chat:write", "memory:read", "memory:write",
                          "agent:run", "agent:control", "device:read", "device:manage"}),
    "desktop": frozenset({"chat:read", "chat:write", "memory:read", "memory:write",
                          "agent:run", "agent:control", "device:read", "device:manage"}),
}


def new_token() -> str:
    return PREFIX + secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def same_hash(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def scopes_for_kind(kind: str) -> frozenset[str]:
    try:
        return DEVICE_KINDS[kind]
    except KeyError:
        raise ValueError(f"unknown device kind '{kind}'; expected one of "
                         f"{', '.join(sorted(DEVICE_KINDS))}") from None


def has_scope(scopes, scope: str) -> bool:
    return scope in set(scopes)


def parse_bearer(header: str | None) -> str | None:
    """'Bearer mimo_...' -> 'mimo_...'. Anything malformed -> None."""
    if not header or not header.startswith("Bearer "):
        return None
    token = header[len("Bearer "):].strip()
    return token if token.startswith(PREFIX) and len(token) > len(PREFIX) else None
