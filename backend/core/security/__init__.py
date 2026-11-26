"""Device identity: pairing, hashed bearer tokens, scopes, revocation, auth gate."""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path
from typing import Optional

from ..llm.config import REPO_ROOT
from .pairing import PairingCodes, SlidingWindowLimiter
from .store import SecurityStore
from .tokens import (DEVICE_KINDS, SCOPES, has_scope, hash_token, new_token, parse_bearer,
                     scopes_for_kind)

__all__ = ["DEVICE_KINDS", "SCOPES", "SecurityService", "SecurityStore", "get_service",
           "has_scope", "hash_token", "init_service", "new_token", "parse_bearer",
           "scopes_for_kind", "shutdown_service", "AuthGate", "require_scope", "current_device"]

NAME_MAX, KIND_MAX, ID_MAX = 64, 16, 64


class SecurityService:
    """Enrollment and authentication. All token handling lives here so routes stay thin."""

    def __init__(self, store: SecurityStore, codes: Optional[PairingCodes] = None,
                 pair_limiter: Optional[SlidingWindowLimiter] = None):
        self.store = store
        self.codes = codes or PairingCodes()
        self.pair_limiter = pair_limiter or SlidingWindowLimiter(limit=10, window_s=60.0)

    # ------------------------------------------------------------------ enrollment
    def issue_code(self) -> str:
        return self.codes.issue()

    def enroll(self, code: str, name: str, kind: str, client_key: str = "?") -> dict:
        """Redeem a pairing code and create a device. Raises ValueError on refusal."""
        if not self.pair_limiter.allow(client_key):
            self.store.log_event("pair_rate_limited", None, client_key[:40])
            raise ValueError("too many attempts; wait a minute")
        kind = (kind or "").strip().lower()
        if kind not in DEVICE_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(sorted(DEVICE_KINDS))}")
        name = (name or "").strip()[:NAME_MAX] or f"{kind}-device"
        if not self.codes.redeem(code):
            self.store.log_event("pair_failed", None, "invalid or expired code")
            raise ValueError("that pairing code is invalid or has expired")
        device_id = uuid.uuid4().hex[:12]
        scopes = scopes_for_kind(kind)
        token = new_token()
        self.store.create_device(device_id, name, kind, scopes)
        self.store.add_token(device_id, hash_token(token))
        self.store.log_event("device_enrolled", device_id, f"{kind}:{name}")
        return {"device": self._public(self.store.get_device(device_id)), "token": token}

    def rotate(self, device: dict, old_token: str) -> dict:
        token = new_token()
        if not self.store.rotate_token(device["id"], hash_token(old_token), hash_token(token)):
            raise ValueError("that token is no longer valid")
        self.store.log_event("token_rotated", device["id"])
        return {"token": token}

    # ------------------------------------------------------------------ auth
    def authenticate(self, token: Optional[str]) -> Optional[dict]:
        if not token:
            return None
        device = self.store.device_for_token(hash_token(token))
        if device is None:
            return None
        self.store.touch(device["id"])
        return device

    def revoke(self, device_id: str) -> bool:
        ok = self.store.revoke_device(device_id)
        if ok:
            self.store.log_event("device_revoked", device_id)
        return ok

    @staticmethod
    def _public(device: Optional[dict]) -> Optional[dict]:
        if device is None:
            return None
        return {"id": device["id"], "name": device["name"], "kind": device["kind"],
                "scopes": sorted(device["scopes"]), "created_at": device["created_at"],
                "last_seen": device["last_seen"]}


_service: Optional[SecurityService] = None
_lock = threading.Lock()


def init_service(data_dir: Optional[Path] = None) -> SecurityService:
    global _service
    with _lock:
        data = Path(data_dir or os.environ.get("MIMO_DATA_DIR", REPO_ROOT / "data"))
        store = SecurityStore(data / "security.db")
        _service = SecurityService(store)
        return _service


def get_service() -> SecurityService:
    global _service
    with _lock:
        if _service is None:
            data = Path(os.environ.get("MIMO_DATA_DIR", REPO_ROOT / "data"))
            _service = SecurityService(SecurityStore(data / "security.db"))
        return _service


def shutdown_service() -> None:
    global _service
    with _lock:
        _service = None


# Imported last: gate.py imports get_service from this module.
from .gate import AuthGate, current_device, require_scope      # noqa: E402
