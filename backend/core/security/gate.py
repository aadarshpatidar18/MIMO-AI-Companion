"""The auth gate and the scope dependency.

Two layers:
* `AuthGate` middleware: when auth is required, every non-exempt route needs a live token.
* `require_scope("x")`: a per-route dependency for routes that must be permissioned even
  when the gate is off (device management, for example).
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .tokens import has_scope, parse_bearer

# Reading these needs no token: the app shell must load before a device is paired.
PUBLIC_READ = frozenset({"/", "/app", "/favicon.ico", "/info", "/health", "/docs",
                         "/redoc", "/openapi.json", "/auth/status", "/persona"})
# Writing is never public: only redeeming a pairing code is, because that is how a
# device gets its first token.
PUBLIC_WRITE = frozenset({("/auth/pair", "POST")})


def is_public(method: str, path: str) -> bool:
    if method in ("GET", "HEAD"):
        return path in PUBLIC_READ or path.startswith("/docs")
    return (path, method) in PUBLIC_WRITE


def _service():
    # Imported here, not at module load: security/__init__ imports this file.
    from . import get_service
    return get_service()


def peek_device(request: Request) -> Optional[dict]:
    """Resolve the caller's device without enforcing anything. Cached on the request."""
    cached = getattr(request.state, "device", None)
    if cached is not None:
        return cached
    token = parse_bearer(request.headers.get("authorization"))
    if token is None:
        return None
    device = _service().authenticate(token)
    request.state.device = device
    request.state.raw_token = token
    return device


class AuthGate(BaseHTTPMiddleware):
    """When `require_auth` is on, every non-exempt route needs a live device token."""

    async def dispatch(self, request: Request, call_next):
        service = _service()
        if (not service.store.require_auth() or request.method == "OPTIONS"
                or is_public(request.method, request.url.path)):
            return await call_next(request)
        if peek_device(request) is None:
            service.store.log_event(
                "auth_rejected", None, f"{request.method} {request.url.path}"[:120])
            return JSONResponse(status_code=401,
                                content={"detail": "A valid device token is required. "
                                                   "Pair this device first."})
        return await call_next(request)


def current_device(request: Request) -> Optional[dict]:
    return peek_device(request)


def require_scope(scope: str, *, allow_unpaired: bool = False):
    """FastAPI dependency factory: the caller must hold `scope`.

    `allow_unpaired=True` lets a caller with no token through only while authentication
    is switched off (development mode and the pre-M2 baseline tests). A paired device
    that lacks the scope is always refused, so a device can never use the development
    bypass to reach another device's capabilities.
    """

    def _dep(request: Request) -> Optional[dict]:
        device = peek_device(request)
        if device is None:
            if allow_unpaired and not _service().store.require_auth():
                return None
            raise HTTPException(status_code=401, detail="A valid device token is required.")
        if not has_scope(device["scopes"], scope):
            raise HTTPException(status_code=403, detail=f"This device is not allowed to '{scope}'.")
        return device

    return _dep
