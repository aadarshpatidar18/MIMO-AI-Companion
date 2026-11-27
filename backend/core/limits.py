"""Refuse oversized request bodies before anything reads them.

ASGI middleware, not a route dependency: a cap applied inside a handler has already paid for
reading and parsing the body, which is exactly the cost an abusive caller wants to impose.
"""
from __future__ import annotations

from typing import Iterable, Optional

from starlette.responses import JSONResponse

MAX_JSON_BYTES = 2 * 1024 * 1024          # a turn is capped at 2,000 characters; 2 MB is generous
MAX_AUDIO_BYTES = 12 * 1024 * 1024        # matches the /voice/transcribe limit
MAX_UPLOAD_BYTES = 16 * 1024 * 1024


class _TooLarge(Exception):
    pass


class BodySizeLimit:
    """Pure ASGI middleware: caps Content-Length and, failing that, the streamed bytes."""

    def __init__(self, app, default: int = MAX_JSON_BYTES,
                 rules: Optional[Iterable[tuple[str, int]]] = None) -> None:
        self.app = app
        self.default = default
        self.rules = tuple(rules or ())

    def _limit_for(self, path: str) -> int:
        for prefix, limit in self.rules:
            if path.startswith(prefix):
                return limit
        return self.default

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        limit = self._limit_for(scope.get("path", ""))
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        declared = headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            await self._reject(scope, receive, send, limit)
            return

        received = 0
        started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _TooLarge
            return message

        async def watched_send(message):
            nonlocal started
            if message.get("type") == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, watched_send)
        except _TooLarge:
            if not started:
                await self._reject(scope, receive, send, limit)

    @staticmethod
    async def _reject(scope, receive, send, limit: int) -> None:
        size = f"{limit // (1024 * 1024)} MB" if limit >= 1024 * 1024 else f"{limit // 1024} KB"
        await JSONResponse(
            {"detail": f"That request is larger than this endpoint accepts ({size})."},
            status_code=413,
        )(scope, receive, send)
