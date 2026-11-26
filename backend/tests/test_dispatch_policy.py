"""S2 — indirect effects obey the same capability policy as the direct routes.

`/chat` reaches tools and memory mutations after the model classifies an intent. These
tests hold the caller constant and change only the granted scope, so a failure means
the dispatch boundary moved, not that the request shape changed.

Mutation each test must kill (from docs/REVIEW_W1.md, S2):
  * replace the capability check inside `process_message` with the route's generic
    chat-write check  -> every denial test goes red;
  * look up the device without applying its scopes -> the 403 tests go red.
"""
import json
from uuid import uuid4

import pytest

import backend.core.llm as llm_pkg
import backend.core.security as security_pkg
from backend import memory
from backend.core.llm.base import LLMProvider, LLMResponse
from backend.core.llm.config import RouterSettings, default_routes
from backend.core.llm.retry import RetryPolicy
from backend.core.llm.router import ModelRouter
from backend.core.llm.usage import UsageTracker
from backend.core.security import hash_token, new_token


def seed_scoped(scopes, name="limited-device"):
    """A live device with exactly `scopes` — unlike seed_device, no kind presets."""
    service = security_pkg.get_service()
    token = new_token()
    device_id = uuid4().hex[:12]
    service.store.create_device(device_id, name, "windows", frozenset(scopes))
    service.store.add_token(device_id, hash_token(token))
    return device_id, token


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def open_conversation(client, token):
    response = client.post("/conversations", json={}, headers=bearer(token))
    assert response.status_code == 201, response.text
    return response.json()["id"]


def conversation_messages(client, token, conversation_id):
    response = client.get(f"/conversations/{conversation_id}/messages", headers=bearer(token))
    assert response.status_code == 200, response.text
    return response.json()["messages"]


CHAT_ONLY = ("chat:read", "chat:write")


# --------------------------------------------------------------- memory through /chat
def test_chat_write_token_cannot_save_memory_through_chat(app_env):
    client, _, _ = app_env
    full = seed_scoped(("chat:read", "chat:write", "memory:read", "memory:write"))
    limited = seed_scoped(CHAT_ONLY)
    conversation = open_conversation(client, full[1])

    response = client.post("/chat",
                           json={"message": "remember that I like robotics",
                                 "conversation_id": conversation},
                           headers=bearer(limited[1]))

    assert response.status_code == 403
    assert "memory:write" in response.json()["detail"]
    assert memory.get_memories() == []                        # no effect happened
    assert conversation_messages(client, full[1], conversation) == []   # no partial turn


def test_chat_write_token_cannot_read_memory_through_chat(app_env):
    client, _, _ = app_env
    full = seed_scoped(("chat:read", "chat:write", "memory:read", "memory:write"))
    limited = seed_scoped(CHAT_ONLY)
    memory.save_memory("I like robotics", "interest")
    conversation = open_conversation(client, full[1])

    response = client.post("/chat",
                           json={"message": "what are my interests?",
                                 "conversation_id": conversation},
                           headers=bearer(limited[1]))

    assert response.status_code == 403
    assert "memory:read" in response.json()["detail"]
    assert conversation_messages(client, full[1], conversation) == []


def test_chat_write_token_cannot_invoke_tools_through_chat(app_env, monkeypatch):
    client, _, _ = app_env
    full = seed_scoped(("chat:read", "chat:write", "memory:read", "memory:write"))
    limited = seed_scoped(CHAT_ONLY)
    conversation = open_conversation(client, full[1])
    calls = []

    import backend.api as api
    monkeypatch.setattr(api, "execute_tool",
                        lambda name, params: calls.append(name) or {"success": True, "result": 4})
    monkeypatch.setattr(api, "classify_intent",
                        lambda message: {"intent": "calculate",
                                         "parameters": {"expression": "2+2"}})

    response = client.post("/chat",
                           json={"message": "what is 2+2", "conversation_id": conversation},
                           headers=bearer(limited[1]))

    assert response.status_code == 403
    assert "agent:run" in response.json()["detail"]
    assert calls == []                       # the handler never started
    assert conversation_messages(client, full[1], conversation) == []


def test_chat_with_paired_device_still_reaches_its_granted_capabilities(app_env):
    client, _, _ = app_env
    full = seed_scoped(("chat:read", "chat:write", "memory:read", "memory:write"))
    conversation = open_conversation(client, full[1])

    saved = client.post("/chat",
                        json={"message": "remember that I like robotics",
                              "conversation_id": conversation},
                        headers=bearer(full[1]))
    assert saved.status_code == 200, saved.text
    assert [row["content"] for row in memory.get_memories()] == ["I like robotics"]

    turns = conversation_messages(client, full[1], conversation)
    assert [turn["role"] for turn in turns] == ["user", "assistant"]


def test_chat_without_memory_read_answers_without_personal_context(app_env):
    """Missing memory:read must not block conversation; it only drops stored context."""
    client, _, _ = app_env
    full = seed_scoped(("chat:read", "chat:write", "memory:read", "memory:write"))
    limited = seed_scoped(CHAT_ONLY)
    memory.save_memory("I like robotics", "interest")
    conversation = open_conversation(client, full[1])

    response = client.post("/chat",
                           json={"message": "hello there", "conversation_id": conversation},
                           headers=bearer(limited[1]))

    assert response.status_code == 200, response.text
    assert response.json()["response"]
    assert len(conversation_messages(client, full[1], conversation)) == 2


# --------------------------------------------------------------- direct routes
def test_memory_routes_require_memory_scopes(app_env):
    client, _, _ = app_env
    _, chat_token = seed_scoped(CHAT_ONLY)
    _, reader = seed_scoped(("memory:read",))
    _, writer = seed_scoped(("chat:read", "chat:write", "memory:write"))

    denied_write = client.post("/memory", json={"content": "secret"},
                               headers=bearer(chat_token))
    assert denied_write.status_code == 403
    assert memory.get_memories() == []

    assert client.get("/memory", headers=bearer(chat_token)).status_code == 403
    assert client.request("DELETE", "/memory", json={"keyword": "secret"},
                          headers=bearer(chat_token)).status_code == 403

    assert client.get("/memory", headers=bearer(reader)).status_code == 200
    assert client.post("/memory", json={"content": "kept"}, headers=bearer(writer)).status_code == 200
    assert [row["content"] for row in memory.get_memories()] == ["kept"]


def test_agent_routes_require_run_and_control_scopes(app_env):
    client, _, _ = app_env
    _, chat_token = seed_scoped(CHAT_ONLY)
    _, runner = seed_scoped(("agent:run",))
    _, controller = seed_scoped(("agent:control",))

    assert client.post("/agent/tasks", json={"goal": "do a thing"},
                       headers=bearer(chat_token)).status_code == 403
    assert client.get("/agent/tasks", headers=bearer(chat_token)).status_code == 403
    assert client.put("/agent/policy", json={"max_auto_level": 1, "deny": []},
                      headers=bearer(chat_token)).status_code == 403

    submitted = client.post("/agent/tasks", json={"goal": "do a thing"},
                            headers=bearer(runner))
    assert submitted.status_code == 202, submitted.text
    task_id = submitted.json()["id"]

    assert client.post(f"/agent/tasks/{task_id}/cancel",
                       headers=bearer(runner)).status_code == 403
    assert client.post(f"/agent/tasks/{task_id}/cancel",
                       headers=bearer(controller)).status_code == 200


def test_model_configuration_requires_device_manage(app_env):
    client, _, _ = app_env
    _, runner = seed_scoped(("agent:run",))
    _, admin = seed_scoped(("device:read", "device:manage"))

    body = {"provider": "ollama"}
    assert client.put("/llm/selection", json=body, headers=bearer(runner)).status_code == 403
    assert client.post("/llm/cooldowns/clear", headers=bearer(runner)).status_code == 403
    assert client.put("/llm/selection", json=body, headers=bearer(admin)).status_code == 200


# --------------------------------------------------------------- C2 / C5 durability gates
def test_paired_chat_without_a_conversation_id_is_refused(app_env):
    """C2: no implicit shared default for a paired device.

    Mutation: fall back to the in-process 'default' session for any caller -> red.
    """
    client, _, _ = app_env
    _, token = seed_scoped(CHAT_ONLY)

    response = client.post("/chat", json={"message": "hello"}, headers=bearer(token))

    assert response.status_code == 400
    assert "conversation_id" in response.json()["detail"]


def test_a_turn_is_stored_whole_or_not_at_all(app_env):
    """C5: a failed write leaves neither the question nor an answer behind.

    Mutation: commit the user row before writing the assistant row -> red.
    """
    client, _, _ = app_env
    full = seed_scoped(("chat:read", "chat:write"))
    conversation = open_conversation(client, full[1])

    from backend.core.conversations import get_store
    store = get_store()
    store._db.execute(
        "CREATE TRIGGER fail_assistant BEFORE INSERT ON messages"
        " WHEN NEW.role = 'assistant' BEGIN SELECT RAISE(ABORT, 'injected'); END")

    failed = client.post("/chat",
                         json={"message": "remember this turn", "conversation_id": conversation},
                         headers=bearer(full[1]))
    assert failed.status_code >= 400
    assert conversation_messages(client, full[1], conversation) == []

    store._db.execute("DROP TRIGGER fail_assistant")
    retried = client.post("/chat",
                          json={"message": "remember this turn", "conversation_id": conversation},
                          headers=bearer(full[1]))
    assert retried.status_code == 200, retried.text
    assert [turn["role"] for turn in conversation_messages(client, full[1], conversation)] == \
        ["user", "assistant"]
