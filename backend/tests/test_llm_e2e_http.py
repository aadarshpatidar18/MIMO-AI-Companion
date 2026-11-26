"""Real HTTP round-trips (requests -> local stub server) through the whole stack."""
import json
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from backend.core.llm.base import LLMRequest
from backend.core.llm.config import RouterSettings, default_routes
from backend.core.llm.gemini import GeminiProvider
from backend.core.llm.ollama import OllamaProvider
from backend.core.llm.retry import RetryPolicy
from backend.core.llm.router import ModelRouter
from backend.core.llm.usage import UsageTracker

KEY = "AIzaE2EKEY00000000000000000000000000000"


class Stub(BaseHTTPRequestHandler):
    seen: list = []
    gemini_mode = "429"

    def log_message(self, *a):
        pass

    def _send(self, code, obj, headers=None):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Stub.seen.append((self.path, self.headers.get("x-goog-api-key"), body))
        if self.path.startswith("/v1beta/models/"):
            if Stub.gemini_mode == "429":
                self._send(429, {"error": {"code": 429, "message": "quota", "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "1s"}]}})
            else:
                self._send(200, {"candidates": [{"content": {"parts": [{"text": "from-gemini"}]}}],
                                 "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1}})
        elif self.path == "/api/chat":
            self._send(200, {"message": {"content": "from-ollama"}, "prompt_eval_count": 2,
                             "eval_count": 3})
        else:
            self._send(404, {})


@pytest.fixture
def stack():
    srv = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    Stub.seen, Stub.gemini_mode = [], "429"
    sleeps = []
    s = RouterSettings(selection="auto", routes=default_routes(),
                       retry={"gemini": RetryPolicy(max_attempts=3, base_delay=1, jitter=0, max_total_wait=15),
                              "ollama": RetryPolicy(max_attempts=1)})
    r = ModelRouter({"gemini": GeminiProvider(base_url=base + "/v1beta", env={"GEMINI_API_KEY": KEY}),
                     "ollama": OllamaProvider(base_url=base)},
                    s, UsageTracker(), sleep=sleeps.append, rng=random.Random(0))
    yield r, sleeps
    srv.shutdown()


def test_real_http_429_backoff_then_fallback_to_ollama(stack):
    r, sleeps = stack
    resp = r.generate(LLMRequest.from_prompt("hello", task="chat"))
    assert resp.text == "from-ollama" and resp.fell_back
    gem_calls = [x for x in Stub.seen if x[0].startswith("/v1beta")]
    assert len(gem_calls) == 3 and sleeps == [1.0, 2.0]       # hint (1s) is a floor; backoff doubles
    assert all(c[1] == KEY for c in gem_calls)                # key sent as header
    assert all(KEY not in c[0] for c in Stub.seen)            # never in the URL


def test_real_http_gemini_success(stack):
    r, _ = stack
    Stub.gemini_mode = "ok"
    resp = r.generate(LLMRequest.from_prompt("hello", task="chat"))
    assert resp.text == "from-gemini" and not resp.fell_back


def test_real_http_ollama_down_and_gemini_blocked_gives_clear_error(stack):
    r, _ = stack
    r.providers["ollama"] = OllamaProvider(base_url="http://127.0.0.1:1")   # nothing listens
    r.set_selection("ollama")
    from backend.core.llm.errors import AllProvidersFailedError
    with pytest.raises(AllProvidersFailedError) as ei:
        r.generate(LLMRequest.from_prompt("x"))
    assert "ollama serve" in str(ei.value)
