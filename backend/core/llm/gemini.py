"""Google Gemini Developer API provider (REST, no extra dependencies).

The API key is read from the environment on every call, is sent only in the
`x-goog-api-key` header, and is scrubbed from any error text.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Mapping, Optional
from urllib.parse import quote

import requests

from .base import LLMProvider, LLMRequest, LLMResponse
from .errors import (AuthError, BadRequestError, ContentBlockedError, LLMError,
                     ProviderUnavailableError, RateLimitError)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_BLOCK_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "RECITATION", "SPII", "IMAGE_SAFETY"}


def parse_retry_delay(error_obj: dict) -> Optional[float]:
    """Extract seconds from a google.rpc.RetryInfo detail ("retryDelay": "37s")."""
    for d in error_obj.get("details", []) or []:
        if isinstance(d, dict) and str(d.get("@type", "")).endswith("RetryInfo"):
            m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)s\s*$", str(d.get("retryDelay", "")))
            if m:
                return float(m.group(1))
    return None


def is_daily_quota(error_obj: dict) -> bool:
    """Heuristic: QuotaFailure violations whose quotaId mentions a per-day limit."""
    for d in error_obj.get("details", []) or []:
        if isinstance(d, dict) and str(d.get("@type", "")).endswith("QuotaFailure"):
            for v in d.get("violations", []) or []:
                if "perday" in str(v.get("quotaId", "")).replace("_", "").lower():
                    return True
    return "per day" in str(error_obj.get("message", "")).lower()


class GeminiProvider(LLMProvider):
    name = "gemini"
    is_local = False

    def __init__(self, default_model: str = "gemini-3.1-flash-lite",
                 base_url: str = GEMINI_BASE_URL, timeout: float = 60.0,
                 api_key_env: tuple[str, ...] = ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
                 env: Optional[Mapping[str, str]] = None, http: Any = None):
        self.default_model = default_model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._api_key_env = api_key_env
        self._env = env if env is not None else os.environ
        self._http = http or requests

    # ---- key handling ------------------------------------------------
    def _api_key(self) -> Optional[str]:
        for name in self._api_key_env:
            v = (self._env.get(name) or "").strip()
            if v:
                return v
        return None

    def is_configured(self) -> bool:
        return self._api_key() is not None

    def _scrub(self, text: str, key: Optional[str]) -> str:
        return text.replace(key, "***") if key else text

    # ---- request building ----------------------------------------------
    @staticmethod
    def _body(request: LLMRequest) -> dict:
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        contents: list[dict] = []
        for m in request.messages:
            if m.role == "system":
                continue
            role = "model" if m.role == "assistant" else "user"
            if contents and contents[-1]["role"] == role:     # merge same-role neighbours
                contents[-1]["parts"][0]["text"] += "\n\n" + m.content
            else:
                contents.append({"role": role, "parts": [{"text": m.content}]})
        if not contents:
            raise BadRequestError("Request has no user/assistant messages", "gemini")
        body: dict = {"contents": contents}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        gen: dict = {}
        if request.temperature is not None:
            gen["temperature"] = request.temperature
        if request.max_tokens is not None:
            gen["maxOutputTokens"] = request.max_tokens
        if request.json_mode:
            gen["responseMimeType"] = "application/json"
        if gen:
            body["generationConfig"] = gen
        return body

    # ---- main call ---------------------------------------------------
    def generate(self, request: LLMRequest, model: Optional[str] = None) -> LLMResponse:
        key = self._api_key()
        if not key:
            raise AuthError("GEMINI_API_KEY is not set in the backend environment", self.name)
        model = (model or self.default_model).removeprefix("models/")
        url = f"{self.base_url}/models/{quote(model, safe='')}:generateContent"
        body = self._body(request)
        t0 = time.monotonic()
        try:
            resp = self._http.post(
                url, json=body, timeout=request.timeout or self.timeout,
                headers={"x-goog-api-key": key, "Content-Type": "application/json"})
        except requests.exceptions.Timeout:
            raise ProviderUnavailableError("Gemini request timed out", self.name, retryable=True)
        except requests.exceptions.RequestException as e:
            raise ProviderUnavailableError(
                self._scrub(f"Gemini network error: {type(e).__name__}", key),
                self.name, retryable=True)

        if resp.status_code != 200:
            self._raise_for_status(resp, key, model)

        try:
            data = resp.json()
        except ValueError:
            raise LLMError("Gemini returned non-JSON response", self.name)
        text = self._extract_text(data)
        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            text=text, provider=self.name, model=model,
            prompt_tokens=usage.get("promptTokenCount"),
            completion_tokens=usage.get("candidatesTokenCount"),
            latency_ms=int((time.monotonic() - t0) * 1000))

    def _extract_text(self, data: dict) -> str:
        cands = data.get("candidates") or []
        if not cands:
            reason = (data.get("promptFeedback") or {}).get("blockReason")
            if reason:
                raise ContentBlockedError(f"Gemini blocked the prompt ({reason})", self.name)
            raise LLMError("Gemini returned no candidates", self.name)
        cand = cands[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts
                       if isinstance(p, dict) and not p.get("thought"))
        if not text.strip():
            if cand.get("finishReason") in _BLOCK_REASONS:
                raise ContentBlockedError(
                    f"Gemini withheld the answer ({cand.get('finishReason')})", self.name)
            raise LLMError(f"Gemini returned empty text (finishReason={cand.get('finishReason')})",
                           self.name)
        return text

    def _raise_for_status(self, resp: Any, key: str, model: str) -> None:
        status = resp.status_code
        try:
            err = (resp.json() or {}).get("error") or {}
        except Exception:
            err = {}
        msg = self._scrub(str(err.get("message") or getattr(resp, "text", "") or "")[:300], key)
        low = msg.lower()

        if status == 429 or (status == 403 and "quota" in low):
            retry_after = parse_retry_delay(err)
            if retry_after is None:
                hdr = (getattr(resp, "headers", None) or {}).get("Retry-After")
                try:
                    retry_after = float(hdr) if hdr is not None else None
                except ValueError:
                    retry_after = None
            scope = "daily" if is_daily_quota(err) else "unknown"
            raise RateLimitError(f"Gemini rate limit/quota ({status}): {msg}", self.name,
                                 retry_after=retry_after, scope=scope)
        if status in (401, 403) or "api key not valid" in low or "api_key_invalid" in low:
            raise AuthError(f"Gemini rejected the API key/permissions ({status}): {msg}", self.name)
        if status == 404:
            raise BadRequestError(f"Gemini model '{model}' not found for this API version: {msg}",
                                  self.name)
        if status == 400:
            raise BadRequestError(f"Gemini rejected the request: {msg}", self.name)
        if status in (500, 502, 503, 504):
            raise ProviderUnavailableError(f"Gemini temporarily unavailable ({status}): {msg}",
                                           self.name, retryable=True)
        raise LLMError(f"Gemini error {status}: {msg}", self.name)
