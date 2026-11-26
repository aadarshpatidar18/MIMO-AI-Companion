from __future__ import annotations

from typing import Any, Callable, Optional, Union

from backend.core.llm.base import LLMProvider, LLMRequest, LLMResponse


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None, headers: Optional[dict] = None,
                 text: str = ""):
        self.status_code = status_code
        self._json = json_data
        self.headers = headers or {}
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHTTP:
    """Scripted stand-in for `requests`. Items are FakeResponse or an Exception to raise."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls: list[dict] = []

    def _next(self, url, **kw):
        self.calls.append({"url": url, **kw})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, url, **kw):
        return self._next(url, **kw)

    def get(self, url, **kw):
        return self._next(url, **kw)


class FakeProvider(LLMProvider):
    """Scripted provider: each item is a str (reply) or an LLMError to raise."""

    def __init__(self, name: str, script: list, local: bool = False, configured: bool = True,
                 default_model: str = "m"):
        self.name = name
        self.is_local = local
        self.default_model = default_model
        self._configured = configured
        self.script = list(script)
        self.calls: list[tuple[str, str]] = []

    def is_configured(self) -> bool:
        return self._configured

    def generate(self, request: LLMRequest, model: Optional[str] = None) -> LLMResponse:
        model = model or self.default_model
        self.calls.append((model, request.task))
        item = self.script.pop(0) if self.script else f"{self.name}-default"
        if isinstance(item, Exception):
            raise item
        return LLMResponse(text=item, provider=self.name, model=model,
                           prompt_tokens=3, completion_tokens=2, latency_ms=5)


def gemini_ok(text="hello", prompt=5, out=2) -> FakeResponse:
    return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": text}]},
                                              "finishReason": "STOP"}],
                              "usageMetadata": {"promptTokenCount": prompt,
                                                "candidatesTokenCount": out}})


def gemini_429(retry="2s", daily=False, msg="Resource exhausted") -> FakeResponse:
    details = [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry}]
    if daily:
        details.append({"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]})
    return FakeResponse(429, {"error": {"code": 429, "message": msg, "status": "RESOURCE_EXHAUSTED",
                                        "details": details}})
