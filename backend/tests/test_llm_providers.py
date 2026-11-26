import pytest
import requests

from backend.core.llm.base import LLMRequest, Message
from backend.core.llm.errors import (AuthError, BadRequestError, ContentBlockedError,
                                     ProviderUnavailableError, RateLimitError)
from backend.core.llm.gemini import GeminiProvider
from backend.core.llm.ollama import OllamaProvider
from backend.tests.fakes import FakeHTTP, FakeResponse, gemini_429, gemini_ok

KEY = "AIzaFAKEKEYFORTESTS000000000000000000000"


def gem(*script, env=None):
    http = FakeHTTP(*script)
    env = {"GEMINI_API_KEY": KEY} if env is None else env
    return GeminiProvider(http=http, env=env), http


# ---------------- Gemini ----------------
def test_gemini_request_shape_and_key_only_in_header():
    p, http = gem(gemini_ok("hi", 7, 3))
    req = LLMRequest(messages=[Message("system", "be brief"), Message("user", "a"),
                               Message("user", "b"), Message("assistant", "c"), Message("user", "d")],
                     temperature=0.2, max_tokens=50, json_mode=True)
    r = p.generate(req)
    call = http.calls[0]
    assert call["url"].endswith("/models/gemini-3.1-flash-lite:generateContent")
    assert call["headers"]["x-goog-api-key"] == KEY
    assert KEY not in call["url"]
    body = call["json"]
    assert body["systemInstruction"]["parts"][0]["text"] == "be brief"
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    assert body["contents"][0]["parts"][0]["text"] == "a\n\nb"       # merged neighbours
    assert body["generationConfig"] == {"temperature": 0.2, "maxOutputTokens": 50,
                                        "responseMimeType": "application/json"}
    assert (r.text, r.prompt_tokens, r.completion_tokens, r.provider) == ("hi", 7, 3, "gemini")


def test_gemini_missing_key_raises_auth_without_network():
    p, http = gem(env={})
    assert not p.is_configured()
    with pytest.raises(AuthError):
        p.generate(LLMRequest.from_prompt("x"))
    assert http.calls == []


def test_gemini_key_is_read_per_call_so_rotation_needs_no_restart():
    env = {}
    p = GeminiProvider(http=FakeHTTP(gemini_ok()), env=env)
    assert not p.is_configured()
    env["GEMINI_API_KEY"] = KEY
    assert p.is_configured()


def test_gemini_429_parses_retry_delay_and_scope():
    p, _ = gem(gemini_429("37s"))
    with pytest.raises(RateLimitError) as ei:
        p.generate(LLMRequest.from_prompt("x"))
    assert ei.value.retry_after == 37.0 and ei.value.scope == "unknown" and ei.value.retryable

    p, _ = gem(gemini_429("3600s", daily=True))
    with pytest.raises(RateLimitError) as ei:
        p.generate(LLMRequest.from_prompt("x"))
    assert ei.value.scope == "daily" and not ei.value.retryable


def test_gemini_429_uses_retry_after_header_fallback():
    p, _ = gem(FakeResponse(429, {"error": {"message": "slow down"}}, headers={"Retry-After": "9"}))
    with pytest.raises(RateLimitError) as ei:
        p.generate(LLMRequest.from_prompt("x"))
    assert ei.value.retry_after == 9.0


@pytest.mark.parametrize("status,body,exc", [
    (400, {"error": {"message": "API key not valid. Please pass a valid API key."}}, AuthError),
    (403, {"error": {"message": "permission denied"}}, AuthError),
    (401, {"error": {"message": "nope"}}, AuthError),
    (404, {"error": {"message": "model not found"}}, BadRequestError),
    (400, {"error": {"message": "bad payload"}}, BadRequestError),
    (503, {"error": {"message": "overloaded"}}, ProviderUnavailableError),
])
def test_gemini_status_mapping(status, body, exc):
    p, _ = gem(FakeResponse(status, body))
    with pytest.raises(exc):
        p.generate(LLMRequest.from_prompt("x"))


def test_gemini_503_is_retryable_but_network_error_too():
    p, _ = gem(FakeResponse(503, {"error": {"message": "x"}}))
    with pytest.raises(ProviderUnavailableError) as ei:
        p.generate(LLMRequest.from_prompt("x"))
    assert ei.value.retryable
    p, _ = gem(requests.exceptions.ConnectionError("boom"))
    with pytest.raises(ProviderUnavailableError) as ei:
        p.generate(LLMRequest.from_prompt("x"))
    assert ei.value.retryable


def test_gemini_error_text_never_contains_key():
    p, _ = gem(FakeResponse(400, {"error": {"message": f"bad key {KEY} supplied"}}))
    with pytest.raises(BadRequestError) as ei:
        p.generate(LLMRequest.from_prompt("x"))
    assert KEY not in str(ei.value) and "***" in str(ei.value)


def test_gemini_safety_block():
    p, _ = gem(FakeResponse(200, {"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(ContentBlockedError):
        p.generate(LLMRequest.from_prompt("x"))
    p, _ = gem(FakeResponse(200, {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}))
    with pytest.raises(ContentBlockedError):
        p.generate(LLMRequest.from_prompt("x"))


def test_gemini_skips_thought_parts_and_strips_models_prefix():
    resp = FakeResponse(200, {"candidates": [{"content": {"parts": [
        {"text": "thinking...", "thought": True}, {"text": "answer"}]}}]})
    p, http = gem(resp)
    r = p.generate(LLMRequest.from_prompt("x"), model="models/gemini-3.5-flash")
    assert r.text == "answer" and r.model == "gemini-3.5-flash"
    assert "/models/gemini-3.5-flash:generateContent" in http.calls[0]["url"]


# ---------------- Ollama ----------------
def test_ollama_request_and_response():
    http = FakeHTTP(FakeResponse(200, {"message": {"content": "yo"}, "prompt_eval_count": 4,
                                       "eval_count": 2}))
    o = OllamaProvider(http=http)
    r = o.generate(LLMRequest.from_prompt("hi", "sys", temperature=0.5, max_tokens=20, json_mode=True))
    body = http.calls[0]["json"]
    assert http.calls[0]["url"] == "http://127.0.0.1:11434/api/chat"
    assert body["model"] == "qwen2.5:1.5b" and body["stream"] is False and body["format"] == "json"
    assert body["options"] == {"temperature": 0.5, "num_predict": 20}
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert (r.text, r.prompt_tokens, r.completion_tokens) == ("yo", 4, 2)


def test_ollama_offline_is_clear_and_not_retried():
    o = OllamaProvider(http=FakeHTTP(requests.exceptions.ConnectionError("refused")))
    with pytest.raises(ProviderUnavailableError) as ei:
        o.generate(LLMRequest.from_prompt("x"))
    assert "ollama serve" in str(ei.value) and not ei.value.retryable


def test_ollama_missing_model_hint():
    o = OllamaProvider(http=FakeHTTP(FakeResponse(404, {"error": "model 'x' not found"})))
    with pytest.raises(BadRequestError) as ei:
        o.generate(LLMRequest.from_prompt("x"), model="x")
    assert "ollama pull x" in str(ei.value)


def test_ollama_health():
    o = OllamaProvider(http=FakeHTTP(FakeResponse(200, {"models": [{"name": "qwen2.5:1.5b"}]})))
    h = o.health()
    assert h["reachable"] and h["default_model_installed"]
    o = OllamaProvider(http=FakeHTTP(requests.exceptions.ConnectionError("x")))
    assert o.health()["reachable"] is False
