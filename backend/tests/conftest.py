"""Shared fixture: the real FastAPI app, isolated on a temp data dir, with fake models."""
import json
from uuid import uuid4

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

import backend.core.agent as agent_pkg
import backend.core.conversations as conversations_pkg
import backend.core.llm as llm_pkg
import backend.core.security as security_pkg
from backend import memory
from backend.core.llm.base import LLMProvider, LLMResponse
from backend.core.llm.config import RouterSettings, default_routes
from backend.core.llm.retry import RetryPolicy
from backend.core.llm.router import ModelRouter
from backend.core.llm.usage import UsageTracker
from backend.core.security import hash_token, new_token, scopes_for_kind


class FnProvider(LLMProvider):
    def __init__(self, name, fn, local):
        self.name, self.is_local, self.default_model = name, local, name + "-m"
        self.fn, self.calls = fn, []

    def is_configured(self):
        return True

    def generate(self, request, model=None):
        self.calls.append(request)
        out = self.fn(request)
        return LLMResponse(text=out, provider=self.name, model=model or self.default_model)


def behave(req):
    user = req.messages[-1].content
    if req.task == "intent":
        text = user.split("User request:")[-1].strip().lower()
        if "remember that" in text:
            return json.dumps({"intent": "save_memory",
                               "parameters": {"content": "I like robotics", "category": "interest"}})
        return json.dumps({"intent": "general_question", "parameters": {}})
    if req.task == "plan":
        return json.dumps({"steps": []})
    # Echo how much history the model was given, so a test can prove history is shared.
    return f"answer(history={max(len(req.messages) - 2, 0)})"


def seed_device(kind="windows", name="test-pc"):
    """Create a live device directly, the way enrollment would. Returns (device_id, token)."""
    service = security_pkg.get_service()
    token = new_token()
    device_id = uuid4().hex[:12]
    service.store.create_device(device_id, name, kind, scopes_for_kind(kind))
    service.store.add_token(device_id, hash_token(token))
    return device_id, token


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MIMO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("MIMO_REQUIRE_AUTH", raising=False)
    monkeypatch.delenv("MIMO_ALLOW_MEMORY_TO_CLOUD", raising=False)
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")
    monkeypatch.setattr(agent_pkg, "_manager", None)
    monkeypatch.setattr(security_pkg, "_service", None)
    monkeypatch.setattr(conversations_pkg, "_store", None)

    gem, oll = FnProvider("gemini", behave, False), FnProvider("ollama", behave, True)
    settings = RouterSettings(selection="auto", routes=default_routes(),
                              retry={"gemini": RetryPolicy(max_attempts=1),
                                     "ollama": RetryPolicy(max_attempts=1)})
    router = ModelRouter({"gemini": gem, "ollama": oll}, settings, UsageTracker(),
                         sleep=lambda s: None)
    monkeypatch.setattr(llm_pkg, "_router", router)

    from backend.api import app, chat_limiter, conversation_history
    conversation_history.clear()
    chat_limiter.reset()

    with TestClient(app) as client:
        yield client, gem, oll

    monkeypatch.setattr(security_pkg, "_service", None)
    monkeypatch.setattr(conversations_pkg, "_store", None)
