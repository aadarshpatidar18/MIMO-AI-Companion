"""Ollama (local) provider. Works fully offline."""
from __future__ import annotations

import time
from typing import Any, Optional

import requests

from .base import LLMProvider, LLMRequest, LLMResponse
from .errors import BadRequestError, LLMError, ProviderUnavailableError


class OllamaProvider(LLMProvider):
    name = "ollama"
    is_local = True

    def __init__(self, base_url: str = "http://127.0.0.1:11434",
                 default_model: str = "qwen2.5:1.5b", timeout: float = 120.0,
                 keep_alive: str = "5m", http: Any = None):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout
        self.keep_alive = keep_alive
        self._http = http or requests

    def is_configured(self) -> bool:
        return True   # nothing to configure; reachability is checked on use

    def _body(self, request: LLMRequest, model: str) -> dict:
        options: dict = {}
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens
        body: dict = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": False,
            "keep_alive": self.keep_alive,
        }
        if options:
            body["options"] = options
        if request.json_mode:
            body["format"] = "json"
        return body

    def generate(self, request: LLMRequest, model: Optional[str] = None) -> LLMResponse:
        model = model or self.default_model
        url = f"{self.base_url}/api/chat"
        t0 = time.monotonic()
        try:
            resp = self._http.post(url, json=self._body(request, model),
                                   timeout=request.timeout or self.timeout)
        except requests.exceptions.ConnectionError:
            raise ProviderUnavailableError(
                f"Ollama is not reachable at {self.base_url}. Start it with `ollama serve`.",
                self.name, retryable=False)
        except requests.exceptions.Timeout:
            raise ProviderUnavailableError(
                f"Ollama timed out after {request.timeout or self.timeout:.0f}s "
                f"(model '{model}' may still be loading).", self.name, retryable=False)
        except requests.exceptions.RequestException as e:
            raise ProviderUnavailableError(f"Ollama request failed: {type(e).__name__}",
                                           self.name, retryable=False)

        if resp.status_code != 200:
            self._raise_for_status(resp, model)
        try:
            data = resp.json()
            text = data["message"]["content"]
        except (ValueError, KeyError, TypeError):
            raise LLMError("Ollama returned an unexpected response shape", self.name)
        return LLMResponse(
            text=text, provider=self.name, model=model,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
            latency_ms=int((time.monotonic() - t0) * 1000))

    def _raise_for_status(self, resp: Any, model: str) -> None:
        detail = ""
        try:
            detail = str(resp.json().get("error", ""))
        except Exception:
            detail = (getattr(resp, "text", "") or "")[:200]
        if resp.status_code == 404:
            raise BadRequestError(
                f"Ollama model '{model}' not found. Run `ollama pull {model}`. {detail}".strip(),
                self.name)
        if resp.status_code >= 500 or resp.status_code == 429:
            raise ProviderUnavailableError(f"Ollama error {resp.status_code}: {detail}",
                                           self.name, retryable=True)
        raise BadRequestError(f"Ollama rejected the request ({resp.status_code}): {detail}",
                              self.name)

    def health(self) -> dict:
        try:
            r = self._http.get(f"{self.base_url}/api/tags", timeout=2)
            r.raise_for_status()
            models = [m.get("name", "") for m in r.json().get("models", [])]
            return {"configured": True, "reachable": True, "models": models,
                    "default_model_installed": any(
                        m == self.default_model or m.split(":")[0] == self.default_model
                        for m in models)}
        except Exception:
            return {"configured": True, "reachable": False, "models": []}
