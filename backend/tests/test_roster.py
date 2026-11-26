"""The agent roster: routing, per-agent tool belts, and the confirmation ceiling."""
import pytest

from backend.core.agent import AutonomyPolicy, Roster, ToolError, ToolRegistry
from backend.core.agent.builtin import register_builtin_tools
from backend.core.agent.registry import READ_ONLY, ToolSpec
from backend.core.agent.roster import (CODING, COMPUTER, FILES, GENERAL, MEMORY, RESEARCH,
                                       RESERVED, ROSTER, CappedPolicy)
from backend.tools import register_operator_tools


@pytest.fixture
def registry():
    from backend.core.agent.registry import ToolRegistry
    return register_operator_tools(register_builtin_tools(ToolRegistry()))


@pytest.fixture
def roster(registry):
    return Roster(registry, AutonomyPolicy(), lambda msgs: "{}", answerer=lambda g: "ok")


# ---------------------------------------------------------------- routing
@pytest.mark.parametrize("goal,expected", [
    ("research the latest humanoid robots", "research"),
    ("find out who makes the best actuator", "research"),
    ("fix the failing test in my project", "coding"),
    ("run the tests and tell me what broke", "coding"),
    ("open vscode", "computer"),
    ("take a screenshot of the screen", "computer"),
    ("rename my robotics notes file", "files"),
    ("organise the documents in downloads", "files"),
    ("subscribe to that channel on youtube", "browser"),
    ("remember that my deadline is Friday", "memory"),
    ("what do you know about me", "memory"),
    ("tell me a joke", "general"),
    ("", "general"),
])
def test_routing_picks_the_right_specialist(roster, goal, expected):
    assert roster.select(goal).key == expected


def test_unknown_goal_falls_back_to_the_generalist_with_every_tool(roster, registry):
    profile = roster.select("something nobody planned for")
    assert profile is GENERAL
    engine = roster.engine_for(profile.key)
    assert set(engine.registry.names()) == set(registry.names())


def test_reserved_roles_are_documented_not_invented():
    assert {"communication", "verification", "planning"} == set(RESERVED)
    assert all(RESERVED.values())          # each says why


def test_roster_is_six_real_agents_plus_the_generalist():
    assert [p.key for p in ROSTER] == ["research", "coding", "computer", "files", "browser", "memory"]
    assert GENERAL.key == "general"


# ---------------------------------------------------------------- tool belts
def test_each_agent_can_only_reach_its_own_tools(roster):
    coding = roster.engine_for("coding").registry
    research = roster.engine_for("research").registry
    memory = roster.engine_for("memory").registry

    assert "run_tests" in coding.names() and "browser_search" not in coding.names()
    assert "browser_search" in research.names() and "write_file" not in research.names()
    assert set(memory.names()) == {"remember", "recall", "forget", "get_time"}


def test_a_specialist_never_gets_a_tool_it_was_not_given(roster):
    computer = roster.engine_for("computer").registry.names()
    assert "click_at" in computer and "delete_path" not in computer
    files = roster.engine_for("files").registry.names()
    assert "delete_path" in files and "browser_click" not in files


def test_engines_are_reused_not_rebuilt(roster):
    assert roster.engine_for("files") is roster.engine_for("files")


# ---------------------------------------------------------------- ceilings
def test_a_ceiling_turns_an_allow_into_a_confirmation(registry):
    class Anything:
        name, level = "x", 2

    capped = CappedPolicy(AutonomyPolicy(max_auto_level=2), cap=1)
    assert capped.decide(Anything()) == "confirm"
    assert CappedPolicy(AutonomyPolicy(max_auto_level=2), cap=2).decide(Anything()) == "allow"


def test_the_ceiling_follows_the_live_global_policy(registry):
    global_policy = AutonomyPolicy(max_auto_level=2)

    class Level2:
        name, level = "y", 2

    capped = CappedPolicy(global_policy, cap=2)
    assert capped.decide(Level2()) == "allow"
    global_policy.max_auto_level = 1        # the user tightens it in Settings
    assert capped.decide(Level2()) == "confirm"


# ---------------------------------------------------------------- HTTP
def test_roster_endpoint_lists_agents_and_reserved_roles(app_env):
    client, *_ = app_env
    body = client.get("/agent/roster").json()
    keys = [a["key"] for a in body["agents"]]
    assert "files" in keys and "coding" in keys and "general" in keys
    assert "communication" in body["reserved"]


def test_a_task_records_which_agent_handled_it(app_env):
    client, gem, oll = app_env
    gem.fn = oll.fn = lambda req: '{"steps": []}' if req.task == "plan" else "answer"
    created = client.post("/agent/tasks", json={"goal": "organise my downloads folder"}).json()
    assert created["agent"] == "files"

    import time
    for _ in range(60):
        task = client.get(f"/agent/tasks/{created['id']}").json()
        if task["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.02)
    assert task["agent"] == "files"


def test_an_unknown_agent_is_refused(app_env):
    client, *_ = app_env
    assert client.post("/agent/tasks", json={"goal": "x", "agent": "wizard"}).status_code == 400


def test_an_explicit_agent_overrides_routing(app_env):
    client, gem, oll = app_env
    gem.fn = oll.fn = lambda req: '{"steps": []}' if req.task == "plan" else "answer"
    r = client.post("/agent/tasks", json={"goal": "tell me a joke", "agent": "memory"}).json()
    assert r["agent"] == "memory"
