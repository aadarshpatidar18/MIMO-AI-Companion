"""Short-lived pairing codes: how a new device gets its first token.

The code is generated on the PC (loopback request or an already-trusted device),
read out by the user and typed into the phone. Codes are single-use, expire, and
burn after too many wrong guesses.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

# No 0/O/1/I: these get read aloud and typed by hand.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LEN = 8


@dataclass
class _Code:
    code: str
    created: float
    kind: str = "android"


class PairingCodes:
    """One live code at a time, single use, expiring, and burned after too many wrong guesses."""

    def __init__(self, ttl_s: float = 600.0, max_attempts: int = 5,
                 clock: Callable[[], float] = time.time):
        self.ttl_s, self.max_attempts = ttl_s, max_attempts
        self._clock = clock
        self._codes: dict[str, _Code] = {}
        self._failures = 0
        self._lock = threading.Lock()

    def issue(self, kind: str = "android") -> str:
        """Create a new code bound to one device kind. Only one code is live at a time."""
        code = "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LEN))
        with self._lock:
            self._codes = {code: _Code(code, self._clock(), kind)}
            self._failures = 0
        return code

    def kind_for(self, code: str) -> Optional[str]:
        """The kind this code was issued for, without consuming it."""
        code = (code or "").strip().upper().replace("-", "").replace(" ", "")
        with self._lock:
            entry = self._codes.get(code)
            if entry is None or self._clock() - entry.created > self.ttl_s:
                return None
            return entry.kind

    def _failed(self) -> None:
        self._failures += 1
        if self._failures >= self.max_attempts:
            self._codes.clear()
            self._failures = 0

    def redeem(self, code: str, kind: Optional[str] = None) -> bool:
        """Consume a code. True only for a live, unexpired, not-yet-burned code of this kind.

        A code is issued for one kind of device. A phone cannot redeem a code issued for a desktop
        (which carries `device:manage`) simply by asking for that kind, and a wrong kind counts as
        a failed attempt so kinds cannot be probed.
        """
        code = (code or "").strip().upper().replace("-", "").replace(" ", "")
        with self._lock:
            entry = self._codes.get(code)
            if entry is None:
                self._failed()                          # brute force: enough wrong guesses kill it
                return False
            if self._clock() - entry.created > self.ttl_s:
                self._codes.pop(code, None)
                return False
            if kind is not None and kind != entry.kind:
                self._failed()
                return False
            self._codes.pop(code, None)                 # single use
            self._failures = 0
            return True

    def pending(self) -> bool:
        with self._lock:
            return any(self._clock() - c.created <= self.ttl_s for c in self._codes.values())

    def clear(self) -> None:
        with self._lock:
            self._codes.clear()


class SlidingWindowLimiter:
    """In-memory per-key rate limiter: at most `limit` hits per `window_s`."""

    def __init__(self, limit: int = 30, window_s: float = 60.0,
                 clock: Callable[[], float] = time.monotonic):
        self.limit, self.window_s, self._clock = limit, window_s, clock
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.window_s]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True

    def reset(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)
