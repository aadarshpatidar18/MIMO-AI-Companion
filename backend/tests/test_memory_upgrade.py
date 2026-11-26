"""Memory: importance, ranked recall, correction, and the dashboard contract."""
import sqlite3

import pytest

import backend.memory as memory
from backend.tests.conftest import seed_device


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "mem.db"
    monkeypatch.setattr(memory, "DB_PATH", path)
    memory.initialize_memory()
    return path


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- importance
@pytest.mark.parametrize("category,expected", [
    ("goal", 4), ("project", 4), ("skill", 3), ("preference", 3), ("other", 2),
])
def test_importance_follows_the_kind_of_fact(db, category, expected):
    memory.save_memory(f"a {category} fact", category)
    assert memory.get_memories()[0]["importance"] == expected


def test_listing_puts_what_matters_first(db):
    memory.save_memory("I like pizza", "interest")
    memory.save_memory("My goal is to become a robotics engineer", "goal")
    contents = [m["content"] for m in memory.get_memories()]
    assert contents[0].startswith("My goal")


def test_importance_can_be_set_by_hand(db):
    memory.save_memory("I like pizza", "interest")
    mid = memory.get_memories()[0]["id"]
    assert memory.set_importance(mid, 5) is True
    assert memory.get_memories()[0]["importance"] == 5
    assert memory.set_importance(mid, 9) is False          # out of range


# ---------------------------------------------------------------- recall ranking
def test_partial_words_match(db):
    memory.save_memory("I am building a robotics project", "project")
    hits = memory.search_memory("robot")
    assert len(hits) == 1 and "robotics" in hits[0]["content"]


def test_search_ranks_by_relevance_not_recency(db):
    memory.save_memory("unrelated note about pizza", "other")
    memory.save_memory("robotics arm calibration", "project")
    memory.save_memory("another robotics note", "project")
    hits = memory.search_memory("robotics")
    assert len(hits) == 2 and all("robotics" in h["content"] for h in hits)


def test_recall_is_counted_and_lifts_a_fact(db):
    memory.save_memory("robotics with low importance", "other")     # base 2
    memory.save_memory("pizza with high importance", "goal")        # base 4
    for _ in range(3):
        memory.search_memory("robotics")
    row = next(m for m in memory.get_memories() if "robotics" in m["content"])
    assert row["access_count"] == 3 and row["last_used"]


def test_listing_does_not_count_as_recall(db):
    memory.save_memory("I like pizza", "interest")
    memory.get_memories()
    assert memory.get_memories()[0]["access_count"] == 0


def test_search_survives_fts_operators(db):
    memory.save_memory("I like pizza", "interest")
    for query in ('"', "*", "AND OR NOT", "c++ (pizza)"):
        assert isinstance(memory.search_memory(query), list)   # never raises


def test_category_filter_still_works_with_search(db):
    memory.save_memory("robotics project", "project")
    memory.save_memory("robotics hobby", "interest")
    assert len(memory.search_memory("robotics", category="project")) == 1


# ---------------------------------------------------------------- correction
def test_correction_changes_wording_and_category(db):
    memory.save_memory("I like pi za", "other")
    mid = memory.get_memories()[0]["id"]
    assert memory.update_memory(mid, "I like pizza", "preference") is True
    row = memory.get_memories()[0]
    assert row["content"] == "I like pizza" and row["category"] == "preference"
    assert row["importance"] == 3                            # follows the new category


def test_correction_refuses_a_duplicate(db):
    memory.save_memory("I like pizza", "interest")
    memory.save_memory("I like robots", "interest")
    target = next(m for m in memory.get_memories() if "robots" in m["content"])
    assert memory.update_memory(target["id"], "I like pizza") is False


def test_delete_removes_it_from_search(db):
    memory.save_memory("I like pizza", "interest")
    assert memory.forget_memory("pepperoni") == 0
    assert memory.forget_memory("pizza") == 1
    assert memory.search_memory("pizza") == []


# ---------------------------------------------------------------- migration
def test_an_old_database_is_upgraded_in_place(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, content TEXT NOT NULL,
            category TEXT DEFAULT 'other', normalized_content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP)""")
        connection.execute("INSERT INTO memories (content, category) VALUES ('old goal', 'goal')")
    monkeypatch.setattr(memory, "DB_PATH", path)
    memory.initialize_memory()
    row = memory.get_memories()[0]
    assert row["content"] == "old goal"
    assert row["importance"] == 4 and row["access_count"] == 0


# ---------------------------------------------------------------- HTTP
def test_memory_api_returns_and_edits(app_env):
    client, *_ = app_env
    _, token = seed_device()
    client.post("/memory", json={"content": "I like pizza", "category": "interest"})
    rows = client.get("/memory").json()["memories"]
    assert rows[0]["importance"] == 3 and "access_count" in rows[0]

    mid = rows[0]["id"]
    r = client.put(f"/memory/{mid}", json={"content": "I love pizza", "importance": 5},
                   headers=auth(token))
    assert r.status_code == 200
    assert r.json()["memory"]["content"] == "I love pizza"
    assert r.json()["memory"]["importance"] == 5


def test_memory_correction_validates(app_env):
    client, *_ = app_env
    _, token = seed_device()
    assert client.put("/memory/999", json={"content": "x"}, headers=auth(token)).status_code == 404
    client.post("/memory", json={"content": "I like pizza"})
    mid = client.get("/memory").json()["memories"][0]["id"]
    assert client.put(f"/memory/{mid}", json={"importance": 9}, headers=auth(token)).status_code == 422
