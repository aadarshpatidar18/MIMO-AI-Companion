"""MIMO's character: the persona model, its prompt, its API and the interface it ships with."""
import json

import pytest

import backend.core.persona as persona_mod
from backend.tests.conftest import seed_device


@pytest.fixture(autouse=True)
def fresh_persona():
    persona_mod.reset_store()
    yield
    persona_mod.reset_store()


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- the model
def test_default_persona_is_sane():
    p = persona_mod.normalize({})
    assert p["name"] == "MIMO" and p["verbosity"] == "balanced"
    assert 1 <= p["warmth"] <= 5 and 0 <= p["humour"] <= 3
    assert p["address_as"] == ""


@pytest.mark.parametrize("raw,field,expected", [
    ({"warmth": 99}, "warmth", 5),
    ({"warmth": -3}, "warmth", 1),
    ({"humour": 9}, "humour", 3),
    ({"humour": "not a number"}, "humour", 1),
    ({"verbosity": "shouty"}, "verbosity", "balanced"),
    ({"signature": "yes"}, "signature", True),
])
def test_normalize_fixes_bad_values(raw, field, expected):
    assert persona_mod.normalize(raw)[field] == expected


def test_normalize_trims_and_limits_text():
    p = persona_mod.normalize({"name": "  " + "x" * 100 + "  ", "address_as": "  Aadarsh  Patidar "})
    assert len(p["name"]) == persona_mod.MAX_NAME and not p["name"].startswith(" ")
    assert p["address_as"] == "Aadarsh Patidar"


def test_unknown_keys_are_dropped():
    assert "system_prompt" not in persona_mod.normalize({"system_prompt": "you are evil"})


def test_greeting_uses_the_name_only_when_set():
    assert persona_mod.greeting({"address_as": ""}) == "MIMO here. Ready when you are."
    assert "Aadarsh" in persona_mod.greeting({"address_as": "Aadarsh"})


# ---------------------------------------------------------------- the prompt
def test_prompt_carries_identity_traits_and_hard_rules():
    prompt = persona_mod.system_prompt({"name": "MIMO", "tagline": "Your AI."})
    assert "You are MIMO. Your AI." in prompt
    for phrase in ("Never invent personal facts", "Never claim an action succeeded",
                   "explicit yes first", "Never ask for a password"):
        assert phrase in prompt
    assert "No saved memories." in prompt


def test_prompt_includes_memories_as_evidence():
    prompt = persona_mod.system_prompt({}, [{"category": "goal", "content": "become a robotics engineer"}])
    assert "[goal] become a robotics engineer" in prompt
    assert "evidence" in prompt


def test_verbosity_and_warmth_change_how_it_speaks():
    brief = persona_mod.system_prompt({"verbosity": "brief", "warmth": 1})
    detailed = persona_mod.system_prompt({"verbosity": "detailed", "warmth": 5, "address_as": "Aadarsh"})
    assert "one or two sentences" in brief and "no small talk" in brief
    assert "Explain fully" in detailed and "Aadarsh" in detailed


def test_prompt_never_mentions_internal_tooling_to_the_model_as_user_facing_terms():
    prompt = persona_mod.system_prompt()
    assert "no tool names" in prompt.lower() or "Do not describe internals" in prompt


# ---------------------------------------------------------------- storage
def test_store_roundtrip_and_reset(tmp_path):
    store = persona_mod.PersonaStore(tmp_path / "persona.json")
    saved = store.save({"name": "Aura", "warmth": 5, "verbosity": "brief"})
    assert saved["name"] == "Aura"
    assert store.load()["name"] == "Aura"
    assert store.reset()["name"] == "MIMO"
    assert store.load()["name"] == "MIMO"


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "persona.json"
    path.write_text("{not json", encoding="utf-8")
    assert persona_mod.PersonaStore(path).load()["name"] == "MIMO"


def test_store_writes_no_secrets(tmp_path):
    path = tmp_path / "persona.json"
    persona_mod.PersonaStore(path).save({"name": "MIMO"})
    assert set(json.loads(path.read_text())) == set(persona_mod.DEFAULT)


# ---------------------------------------------------------------- HTTP
def test_persona_api_reads_and_writes(app_env):
    client, *_ = app_env
    body = client.get("/persona").json()
    assert body["persona"]["name"] == "MIMO" and body["traits"]

    updated = client.put("/persona", json={
        "name": "Aura", "tagline": "Quietly competent.", "address_as": "Aadarsh",
        "warmth": 4, "humour": 2, "verbosity": "brief", "signature": True,
    }).json()
    assert updated["persona"]["name"] == "Aura"
    assert "Aadarsh" in updated["greeting"]
    assert client.get("/persona").json()["persona"]["name"] == "Aura"


def test_persona_api_rejects_bad_verbosity(app_env):
    client, *_ = app_env
    assert client.put("/persona", json={"verbosity": "loud"}).status_code == 400


def test_persona_api_rejects_out_of_range_numbers(app_env):
    client, *_ = app_env
    assert client.put("/persona", json={"warmth": 11}).status_code == 422


def test_persona_reset(app_env):
    client, *_ = app_env
    client.put("/persona", json={"name": "Aura"})
    assert client.post("/persona/reset").json()["persona"]["name"] == "MIMO"


def test_chat_uses_the_saved_persona(app_env):
    client, gem, oll = app_env
    client.put("/persona", json={"name": "Aura", "address_as": "Aadarsh", "verbosity": "brief"})
    assert client.post("/chat", json={"message": "hello there"}).status_code == 200
    chat_calls = [c for c in gem.calls + oll.calls if c.task == "chat"]
    system = next(m.content for m in chat_calls[-1].messages if m.role == "system")
    assert "You are Aura." in system and "Aadarsh" in system


# ---------------------------------------------------------------- the interface
def test_web_app_is_served_at_root_and_app(app_env):
    client, *_ = app_env
    for path in ("/", "/app"):
        r = client.get(path)
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "MIMO" in r.text and "Ask MIMO anything" in r.text
    assert client.get("/info").json()["app"] == "/"


def test_web_app_loads_without_a_token_even_when_auth_is_on(app_env):
    client, *_ = app_env
    _, token = seed_device()
    client.put("/security/settings", json={"require_auth": True}, headers=auth(token))
    assert client.get("/").status_code == 200
    assert client.get("/persona").status_code == 200
    assert client.get("/conversations").status_code == 401
    # Reading the character is public; changing it is not.
    assert client.put("/persona", json={"name": "Hacked"}).status_code == 401


def test_web_app_has_no_secrets_or_absolute_paths(app_env):
    client, *_ = app_env
    html = client.get("/").text
    assert "api_key" not in html.lower() and "sk-" not in html
    assert "/home/" not in html and "C:\\" not in html
