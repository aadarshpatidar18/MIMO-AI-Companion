"""Integration tests: the real FastAPI app + memory DB, with fake model providers."""
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

import backend.core.agent as agent_pkg
import backend.core.llm as llm_pkg
from backend import memory
from backend.core.llm.base import LLMProvider, LLMResponse
from backend.core.llm.config import RouterSettings, default_routes
from backend.core.llm.errors import ProviderUnavailableError
from backend.core.llm.retry import RetryPolicy
from backend.core.llm.router import ModelRouter
from backend.core.llm.usage import UsageTracker
from backend.intent_rules import detect_memory_category


class FnProvider(LLMProvider):
    def __init__(self, name, fn, local):
        self.name, self.is_local, self.default_model, self.fn, self.calls = name, local, name + "-m", fn, []

    def is_configured(self):
        return True

    def generate(self, request, model=None):
        self.calls.append(request)
        out = self.fn(request)
        if isinstance(out, Exception):
            raise out
        return LLMResponse(text=out, provider=self.name, model=model or self.default_model)


def behave(req):
    user = req.messages[-1].content
    if req.task == "intent":
        req_text = user.split("User request:")[-1].strip().lower()
        if "what time" in req_text:
            return json.dumps({"intent": "get_time", "parameters": {}})
        if "remember that i like robotics" in req_text:
            return json.dumps({"intent": "save_memory",
                               "parameters": {"content": "I like robotics", "category": "interest"}})
        if "garbage" in req_text:
            return "this is not json"
        return json.dumps({"intent": "general_question", "parameters": {}})
    if req.task == "plan":
        return json.dumps({"steps": [{"tool": "get_time", "parameters": {}}]})
    return "answer-from-" + "model"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setenv("MIMO_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(agent_pkg, "_manager", None)
    monkeypatch.delenv("MIMO_ALLOW_MEMORY_TO_CLOUD", raising=False)
    gem, oll = FnProvider("gemini", behave, False), FnProvider("ollama", behave, True)
    settings = RouterSettings(selection="auto", routes=default_routes(),
                              retry={"gemini": RetryPolicy(max_attempts=1), "ollama": RetryPolicy(max_attempts=1)})
    router = ModelRouter({"gemini": gem, "ollama": oll}, settings, UsageTracker(), sleep=lambda s: None)
    monkeypatch.setattr(llm_pkg, "_router", router)
    from backend.api import app, conversation_history
    conversation_history.clear()
    with TestClient(app) as client:
        yield client, gem, oll


def chat(client, msg):
    return client.post("/chat", json={"message": msg, "session_id": "t"})


# ---- intent rule fix ----
@pytest.mark.parametrize("text,expected", [
    ("What are my interests?", "interest"),
    ("What are my learning interests?", "interest"),
    ("what is my goal?", "goal"),
    ("List my skills", "skill"),
    ("Do you remember my projects?", "project"),
    ("What do you remember about my preferences", "preference"),
    ("Help me debug my project", None),
    ("What should I learn for my project?", None),
    ("Explain what a goal is", None),
    ("What is my favourite colour?", None),
])
def test_detect_memory_category(text, expected):
    assert detect_memory_category(text) == expected


def test_project_help_request_reaches_the_llm_instead_of_dumping_memories(env):
    client, gem, oll = env
    client.post("/memory", json={"content": "Building MIMO", "category": "project"})
    r = chat(client, "Help me debug my project")
    assert r.status_code == 200 and r.json()["intent"] == "general_question"
    assert "Here's what I remember" not in r.json()["response"]


# ---- core flows ----
def test_health_and_llm_routes_are_mounted(env):
    client, *_ = env
    assert client.get("/health").json()["status"] == "healthy"
    st = client.get("/llm/status", params={"live": "false"}).json()
    assert st["selection"] == "auto" and "gemini" in st["providers"]


def test_tool_intent_uses_local_classifier_and_runs_tool(env):
    client, gem, oll = env
    r = chat(client, "What time is it?").json()
    assert r["intent"] == "get_time" and ":" in r["response"]
    assert gem.calls == [] and oll.calls[0].task == "intent"      # classification never goes to cloud


def test_memory_save_then_recall_roundtrip(env):
    client, *_ = env
    assert chat(client, "Remember that I like robotics").json()["response"] == "I'll remember that."
    assert chat(client, "Remember that I like robotics").json()["response"].startswith("I already have")
    mems = client.get("/memory").json()
    assert mems["count"] == 1 and mems["memories"][0]["content"] == "I like robotics"
    assert "I like robotics" in chat(client, "What are my interests?").json()["response"]


def test_malformed_classifier_json_degrades_gracefully(env):
    client, *_ = env
    r = chat(client, "garbage")
    assert r.status_code == 200 and r.json()["intent"] == "unknown"


# ---- privacy gate for memories ----
def test_chat_with_memories_stays_local_by_default(env):
    client, gem, oll = env
    client.post("/memory", json={"content": "I like robotics", "category": "interest"})
    chat(client, "Tell me something interesting")
    chat_calls = [c for c in oll.calls if c.task == "chat"]
    assert len(chat_calls) == 1 and not [c for c in gem.calls if c.task == "chat"]


def test_chat_with_memories_can_use_cloud_only_when_opted_in(env, monkeypatch):
    client, gem, oll = env
    client.post("/memory", json={"content": "I like robotics", "category": "interest"})
    monkeypatch.setenv("MIMO_ALLOW_MEMORY_TO_CLOUD", "true")
    chat(client, "Tell me something interesting")
    assert [c for c in gem.calls if c.task == "chat"]


def test_chat_without_memories_can_use_cloud_in_auto_mode(env):
    client, gem, oll = env
    chat(client, "Tell me something interesting")
    assert [c for c in gem.calls if c.task == "chat"]


# ---- errors ----
def test_no_model_available_returns_friendly_503_without_internals(env):
    client, gem, oll = env
    down = lambda req: ProviderUnavailableError("secret-internal-detail", "x", retryable=False)
    gem.fn = oll.fn = down
    r = chat(client, "hello")
    assert r.status_code == 503
    assert "Ollama" in r.json()["detail"] and "secret-internal-detail" not in r.text


def test_empty_message_rejected(env):
    client, *_ = env
    assert chat(client, "   ").status_code == 400


# ---- planner / agent ----
def test_planner_survives_malformed_json_and_agent_runs_valid_plan(env):
    from backend.agent import run_agent
    from backend.planner import create_plan
    client, gem, oll = env
    results = run_agent("what time is it")
    assert results[0]["tool"] == "get_time" and results[0]["success"] is True
    gem.fn = oll.fn = lambda req: "not json"
    assert create_plan("anything") == {"steps": []}
