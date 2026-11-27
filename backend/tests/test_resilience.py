"""Failure and recovery through the HTTP layer.

Load testing proved the fast path is fast; these prove the slow paths are survivable: a total
provider outage must be a clean 503 that heals by itself, and one noisy device must not be able to
lock another device out.
"""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from backend.core.llm.errors import ProviderUnavailableError  # noqa: E402
from backend.tests.conftest import seed_device  # noqa: E402


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def _conversation(client, token):
    return client.post("/conversations", json={}, headers=auth(token)).json()["id"]


def test_a_total_provider_outage_is_a_503_and_recovers_by_itself(app_env, monkeypatch):
    client, gem, oll = app_env
    _, token = seed_device("android")
    conversation = _conversation(client, token)
    body = {"message": "are you there", "conversation_id": conversation}

    def down(*_args, **_kwargs):
        raise ProviderUnavailableError("the model is not running")

    original_gem, original_oll = gem.fn, oll.fn
    monkeypatch.setattr(gem, "fn", down)
    monkeypatch.setattr(oll, "fn", down)
    failed = client.post("/chat", json=body, headers=auth(token))
    assert failed.status_code == 503
    # Nothing was stored: a failed turn must not leave half a conversation behind.
    assert client.get(f"/conversations/{conversation}/messages",
                      headers=auth(token)).json()["count"] == 0

    monkeypatch.setattr(gem, "fn", original_gem)
    monkeypatch.setattr(oll, "fn", original_oll)
    recovered = client.post("/chat", json=body, headers=auth(token))
    assert recovered.status_code == 200
    assert recovered.json()["response"]
    assert client.get(f"/conversations/{conversation}/messages",
                      headers=auth(token)).json()["count"] == 2


def test_one_noisy_device_cannot_lock_another_out(app_env):
    client, *_ = app_env
    _, noisy = seed_device("android", "noisy-phone")
    _, quiet = seed_device("windows", "calm-pc")
    noisy_conversation = _conversation(client, noisy)
    quiet_conversation = _conversation(client, quiet)

    # The limiter is 60 turns per minute per device (backend/api.py).
    statuses = [
        client.post("/chat", json={"message": f"spam {i}",
                                   "conversation_id": noisy_conversation},
                    headers=auth(noisy)).status_code
        for i in range(61)
    ]
    assert statuses[-1] == 429, f"expected the 61st turn to be refused, got {statuses[-1]}"
    assert statuses.count(429) == 1

    allowed = client.post("/chat", json={"message": "hello",
                                         "conversation_id": quiet_conversation},
                          headers=auth(quiet))
    assert allowed.status_code == 200


def test_a_conversation_created_by_one_device_is_readable_after_a_restart(app_env, monkeypatch):
    """Restart-shaped check: the store is closed and reopened, and the history is still there."""
    import backend.core.conversations as conversations_pkg

    client, *_ = app_env
    _, token = seed_device("android")
    conversation = _conversation(client, token)
    client.post(f"/conversations/{conversation}/messages",
                json={"role": "user", "content": "remember this line"}, headers=auth(token))

    conversations_pkg.shutdown_store()
    reopened = client.get(f"/conversations/{conversation}/messages", headers=auth(token))
    assert reopened.status_code == 200
    assert reopened.json()["messages"][0]["content"] == "remember this line"


def test_an_oversized_json_body_is_refused_without_being_parsed(app_env):
    client, *_ = app_env
    _, token = seed_device("android")
    huge = {"message": "x" * (3 * 1024 * 1024), "conversation_id": "whatever"}
    response = client.post("/chat", json=huge, headers=auth(token))
    assert response.status_code == 413
    assert "larger than" in response.json()["detail"]


def test_a_normal_body_is_not_refused(app_env):
    client, *_ = app_env
    _, token = seed_device("android")
    conversation = client.post("/conversations", json={}, headers=auth(token)).json()["id"]
    response = client.post("/chat", json={"message": "hello", "conversation_id": conversation},
                           headers=auth(token))
    assert response.status_code == 200


def test_two_devices_talking_at_once_do_not_interleave_turns(app_env):
    """Each answer must follow the question it answers, even from two devices at the same moment."""
    import threading

    client, *_ = app_env
    _, pc = seed_device("windows")
    _, phone = seed_device("android")
    conversation = client.post("/conversations", json={}, headers=auth(pc)).json()["id"]

    errors: list[str] = []

    def send(token: str, text: str) -> None:
        try:
            response = client.post("/chat",
                                   json={"message": text, "conversation_id": conversation},
                                   headers=auth(token))
            if response.status_code != 200:
                errors.append(f"{response.status_code}: {response.text[:120]}")
        except Exception as error:  # pragma: no cover - surfaced through `errors`
            errors.append(str(error))

    threads = [
        threading.Thread(target=send, args=(pc, "question from the pc")),
        threading.Thread(target=send, args=(phone, "question from the phone")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, errors
    messages = client.get(f"/conversations/{conversation}/messages", headers=auth(pc)).json()["messages"]
    roles = [m["role"] for m in messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    # No answer may sit between two questions.
    assert all(roles[i] == "user" for i in (0, 2))
