"""Durable conversations: shared across devices, surviving restarts, correct under concurrency."""
import threading

import pytest

from backend.core.conversations import CONTENT_MAX, ConversationStore
from backend.tests.conftest import seed_device


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- store level
def test_append_and_read_in_order(tmp_path):
    store = ConversationStore(tmp_path / "c.db")
    conversation = store.create()
    for i in range(5):
        store.append(conversation["id"], "user" if i % 2 == 0 else "assistant", f"m{i}")
    messages = store.messages(conversation["id"])
    assert [m["content"] for m in messages] == [f"m{i}" for i in range(5)]
    assert [m["id"] for m in messages] == sorted(m["id"] for m in messages)


def test_first_user_message_titles_the_conversation(tmp_path):
    store = ConversationStore(tmp_path / "c.db")
    conversation = store.create()
    store.append(conversation["id"], "user", "  Remind me to continue my\nrobotics project  ")
    assert store.get(conversation["id"])["title"] == "Remind me to continue my robotics project"


def test_long_title_is_truncated(tmp_path):
    store = ConversationStore(tmp_path / "c.db")
    conversation = store.create()
    store.append(conversation["id"], "user", "x" * 500)
    assert store.get(conversation["id"])["title"].endswith("...")


def test_pagination_with_after_id(tmp_path):
    store = ConversationStore(tmp_path / "c.db")
    cid = store.create()["id"]
    for i in range(10):
        store.append(cid, "user", f"m{i}")
    first = store.messages(cid, limit=4)
    second = store.messages(cid, after_id=first[-1]["id"], limit=4)
    assert len(first) == 4 and len(second) == 4
    assert first[-1]["id"] < second[0]["id"]


def test_messages_survive_reopening_the_database(tmp_path):
    path = tmp_path / "c.db"
    cid = ConversationStore(path).create()["id"]
    store = ConversationStore(path)
    store.append(cid, "user", "remember this")
    del store                                   # simulate a backend restart
    reopened = ConversationStore(path)
    assert [m["content"] for m in reopened.messages(cid)] == ["remember this"]


def test_append_to_unknown_conversation_returns_none(tmp_path):
    assert ConversationStore(tmp_path / "c.db").append("nope", "user", "hi") is None


@pytest.mark.parametrize("role,content", [("system", "x"), ("user", ""), ("user", "   ")])
def test_invalid_messages_are_refused(tmp_path, role, content):
    store = ConversationStore(tmp_path / "c.db")
    cid = store.create()["id"]
    with pytest.raises(ValueError):
        store.append(cid, role, content)


def test_oversize_message_is_refused(tmp_path):
    store = ConversationStore(tmp_path / "c.db")
    cid = store.create()["id"]
    with pytest.raises(ValueError, match="too long"):
        store.append(cid, "user", "x" * (CONTENT_MAX + 1))


def test_delete_removes_messages(tmp_path):
    store = ConversationStore(tmp_path / "c.db")
    cid = store.create()["id"]
    store.append(cid, "user", "hello")
    assert store.delete(cid) is True
    assert store.messages(cid) == []
    assert store.delete(cid) is False


def test_listing_is_newest_first_with_count_and_preview(tmp_path):
    store = ConversationStore(tmp_path / "c.db")
    old = store.create()["id"]
    store.append(old, "user", "first")
    new = store.create()["id"]
    store.append(new, "user", "second")
    listing = store.list()
    assert listing[0]["id"] == new
    assert listing[0]["message_count"] == 1 and listing[0]["last_message"] == "second"


def test_concurrent_appends_keep_every_message_and_unique_ids(tmp_path):
    store = ConversationStore(tmp_path / "c.db")
    cid = store.create()["id"]
    errors = []

    def writer(n):
        try:
            for i in range(25):
                store.append(cid, "user", f"t{n}-{i}")
        except Exception as e:                       # pragma: no cover - surfaced below
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    messages = store.messages(cid, limit=500)
    assert not errors
    assert len(messages) == 100
    assert len({m["id"] for m in messages}) == 100


def test_history_tail_is_chronological_and_bounded(tmp_path):
    store = ConversationStore(tmp_path / "c.db")
    cid = store.create()["id"]
    for i in range(20):
        store.append(cid, "user", f"m{i}")
    history = store.history(cid, limit=6)
    assert len(history) == 6
    assert history[-1]["content"] == "m19"
    assert set(history[0]) == {"role", "content"}


def test_search_returns_matching_messages(tmp_path):
    store = ConversationStore(tmp_path / "c.db")
    cid = store.create()["id"]
    store.append(cid, "user", "my robotics project deadline")
    store.append(cid, "user", "buy milk")
    hits = store.search("robotics")
    assert len(hits) == 1 and hits[0]["conversation_id"] == cid


# ---------------------------------------------------------------- HTTP, two devices
def test_two_devices_share_one_history(app_env):
    client, *_ = app_env
    pc_id, pc_token = seed_device("windows", "Aadarsh-PC")
    phone_id, phone_token = seed_device("android", "Pixel")

    created = client.post("/conversations", json={"title": "Plan"},
                          headers=auth(phone_token))
    assert created.status_code == 201
    cid = created.json()["id"]
    client.post(f"/conversations/{cid}/messages",
                json={"role": "user", "content": "Tomorrow, remind me about robotics."},
                headers=auth(phone_token))

    # The laptop sees the phone's conversation and message.
    listing = client.get("/conversations", headers=auth(pc_token)).json()
    assert listing["count"] == 1
    assert listing["conversations"][0]["title"] == "Plan"
    messages = client.get(f"/conversations/{cid}/messages", headers=auth(pc_token)).json()
    assert messages["messages"][0]["content"] == "Tomorrow, remind me about robotics."
    assert messages["messages"][0]["device_id"] == phone_id

    # And it can continue it.
    client.post(f"/conversations/{cid}/messages",
                json={"role": "assistant", "content": "Noted for tomorrow."},
                headers=auth(pc_token))
    assert len(client.get(f"/conversations/{cid}/messages", headers=auth(pc_token)).json()["messages"]) == 2


def test_conversations_require_a_paired_device(app_env):
    client, *_ = app_env
    assert client.get("/conversations").status_code == 401
    assert client.post("/conversations", json={}).status_code == 401


def test_unknown_conversation_is_404(app_env):
    client, *_ = app_env
    _, token = seed_device()
    assert client.get("/conversations/deadbeef", headers=auth(token)).status_code == 404
    assert client.post("/conversations/deadbeef/messages", json={"content": "x"},
                       headers=auth(token)).status_code == 404


def test_rename_and_delete_over_http(app_env):
    client, *_ = app_env
    _, token = seed_device()
    cid = client.post("/conversations", json={}, headers=auth(token)).json()["id"]
    assert client.patch(f"/conversations/{cid}", json={"title": "Renamed"},
                        headers=auth(token)).json()["title"] == "Renamed"
    assert client.delete(f"/conversations/{cid}", headers=auth(token)).status_code == 200
    assert client.get(f"/conversations/{cid}", headers=auth(token)).status_code == 404


def test_chat_through_a_shared_conversation_persists_and_reuses_history(app_env):
    client, gem, oll = app_env
    pc_id, pc_token = seed_device("windows")
    cid = client.post("/conversations", json={}, headers=auth(pc_token)).json()["id"]

    first = client.post("/chat", json={"message": "hello there", "conversation_id": cid},
                        headers=auth(pc_token))
    assert first.status_code == 200 and first.json()["conversation_id"] == cid

    second = client.post("/chat", json={"message": "and again", "conversation_id": cid},
                         headers=auth(pc_token))
    assert second.status_code == 200
    # The second turn was given the first two messages as history.
    assert "history=2" in second.json()["response"]

    stored = client.get(f"/conversations/{cid}/messages", headers=auth(pc_token)).json()
    assert [m["role"] for m in stored["messages"]] == ["user", "assistant", "user", "assistant"]
    assert stored["messages"][0]["content"] == "hello there"


def test_chat_to_a_shared_conversation_needs_a_token(app_env):
    client, *_ = app_env
    _, token = seed_device()
    cid = client.post("/conversations", json={}, headers=auth(token)).json()["id"]
    assert client.post("/chat", json={"message": "hi", "conversation_id": cid}).status_code == 401


def test_chat_to_an_unknown_conversation_is_404(app_env):
    client, *_ = app_env
    _, token = seed_device()
    r = client.post("/chat", json={"message": "hi", "conversation_id": "nope"}, headers=auth(token))
    assert r.status_code == 404


def test_legacy_chat_still_works_without_a_token(app_env):
    client, *_ = app_env
    r = client.post("/chat", json={"message": "hello", "session_id": "legacy"})
    assert r.status_code == 200 and r.json()["intent"] == "general_question"
    assert "conversation_id" not in r.json()


def test_chat_rate_limit(app_env):
    client, *_ = app_env
    from backend.api import chat_limiter
    chat_limiter.reset()
    chat_limiter.limit = 3
    try:
        codes = [client.post("/chat", json={"message": f"m{i}"}).status_code for i in range(4)]
        assert codes[:3] == [200, 200, 200] and codes[3] == 429
    finally:
        chat_limiter.limit = 60
        chat_limiter.reset()


def test_conversation_message_length_is_enforced_by_the_api(app_env):
    client, *_ = app_env
    _, token = seed_device()
    cid = client.post("/conversations", json={}, headers=auth(token)).json()["id"]
    r = client.post(f"/conversations/{cid}/messages", json={"content": "x" * (CONTENT_MAX + 1)},
                    headers=auth(token))
    assert r.status_code == 422
