import json
import time

import pytest
from pydantic import BaseModel, ConfigDict

from backend.core.agent import ToolSpec, get_policy, get_registry
from backend.tests.test_app_integration import env  # noqa: F401  (shared fixture: app + fake models)


class Echo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str


def planning(tool, args):
    """Make the fake models answer the planner with one step (other tasks keep default behaviour)."""
    def fn(req):
        if req.task == "plan":
            return json.dumps({"steps": [{"tool": tool, "args": args}]}) if tool else '{"steps": []}'
        return "answer-from-model"
    return fn


def poll(client, tid, statuses, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        t = client.get(f"/agent/tasks/{tid}").json()
        if t["status"] in statuses:
            return t
        time.sleep(0.02)
    raise AssertionError(f"stuck: {t['status']}")


def submit(client, goal="do it"):
    r = client.post("/agent/tasks", json={"goal": goal})
    assert r.status_code == 202
    return r.json()["id"]


def test_action_task_end_to_end(env):
    client, gem, oll = env
    gem.fn = oll.fn = planning("get_time", {})
    tid = submit(client, "what time is it")
    t = poll(client, tid, {"succeeded"})
    assert t["mode"] == "action" and ":" in t["answer"] and t["steps"][0]["verified"] is True
    acts = client.get("/agent/actions", params={"task_id": tid}).json()["actions"]
    assert acts[0]["tool"] == "get_time" and acts[0]["decision"] == "allow" and acts[0]["outcome"] == "succeeded"
    assert tid in [x["id"] for x in client.get("/agent/tasks").json()["tasks"]]


def test_question_is_answered_not_acted_on(env):
    client, gem, oll = env
    gem.fn = oll.fn = planning(None, {})
    t = poll(client, submit(client, "explain ROS"), {"succeeded"})
    assert t["mode"] == "answer" and t["answer"] == "answer-from-model" and not t["steps"]


def test_open_website_is_level2_runs_automatically(env, monkeypatch):
    import backend.core.agent.builtin as b
    opened = []
    monkeypatch.setattr(b.webbrowser, "open", lambda u: opened.append(u) or True)
    client, gem, oll = env
    gem.fn = oll.fn = planning("open_website", {"url": "youtube"})
    t = poll(client, submit(client, "open youtube"), {"succeeded"})
    assert opened == ["https://www.youtube.com"] and t["steps"][0]["level"] == 2


def test_input_validation_and_unknown_ids(env):
    client, *_ = env
    assert client.post("/agent/tasks", json={"goal": ""}).status_code == 422
    assert client.post("/agent/tasks", json={"goal": "x" * 2001}).status_code == 422
    assert client.post("/agent/tasks", json={"goal": "   "}).status_code == 400
    for path, body in (("/agent/tasks/nope", None), ("/agent/tasks/nope/cancel", {}),
                       ("/agent/tasks/nope/confirm", {"approve": True})):
        r = client.get(path) if body is None else client.post(path, json=body)
        assert r.status_code == 404


def test_tools_catalog(env):
    client, *_ = env
    tools = {t["name"]: t for t in client.get("/agent/tools").json()["tools"]}
    builtin = {"get_time", "get_date", "calculate", "open_website", "open_app"}
    operators = {"read_file", "write_file", "list_files", "run_tests", "launch_app",
                 "capture_screen", "browser_open", "browser_search"}
    assert builtin <= set(tools) and operators <= set(tools)
    assert tools["open_website"]["level"] == 2 and tools["calculate"]["level"] == 1
    # Anything that can destroy, spend or send must be level 3 so the engine asks first.
    for name in ("delete_path", "move_path", "close_app", "browser_click_action", "run_command"):
        assert tools[name]["level"] == 3, name


def test_confirm_flow_over_http_and_409_when_nothing_waits(env):
    client, gem, oll = env
    get_registry().register(ToolSpec("danger", "Level 3 action.", Echo, lambda p: f"did:{p.text}", 3))
    gem.fn = oll.fn = planning("danger", {"text": "now"})
    tid = submit(client, "risky")
    t = poll(client, tid, {"awaiting_confirmation"})
    assert t["pending"]["tool"] == "danger"
    assert client.post(f"/agent/tasks/{tid}/confirm", json={"approve": True}).json() == {"approved": True}
    assert poll(client, tid, {"succeeded"})["answer"] == "did:now"
    assert client.post(f"/agent/tasks/{tid}/confirm", json={"approve": True}).status_code == 409


def test_deny_over_http_runs_nothing(env):
    client, gem, oll = env
    ran = []
    get_registry().register(ToolSpec("danger", "x", Echo, lambda p: ran.append(1), 3))
    gem.fn = oll.fn = planning("danger", {"text": "now"})
    tid = submit(client, "risky")
    poll(client, tid, {"awaiting_confirmation"})
    client.post(f"/agent/tasks/{tid}/confirm", json={"approve": False})
    t = poll(client, tid, {"failed"})
    assert ran == [] and t["steps"][0]["status"] == "denied"


def test_cancel_endpoint_on_waiting_task(env):
    client, gem, oll = env
    get_registry().register(ToolSpec("danger", "x", Echo, lambda p: "x", 3))
    gem.fn = oll.fn = planning("danger", {"text": "now"})
    tid = submit(client, "risky")
    poll(client, tid, {"awaiting_confirmation"})
    assert client.post(f"/agent/tasks/{tid}/cancel").json() == {"cancelling": True}
    poll(client, tid, {"cancelled"})
    assert client.post(f"/agent/tasks/{tid}/cancel").json() == {"cancelling": False}


def test_policy_endpoints_validate_persist_and_block(env):
    client, gem, oll = env
    assert client.get("/agent/policy").json() == {"max_auto_level": 2, "deny": []}
    assert client.put("/agent/policy", json={"max_auto_level": 3}).status_code == 422   # no auto level 3
    assert client.put("/agent/policy", json={"max_auto_level": 2, "deny": ["nope"]}).status_code == 400
    assert client.put("/agent/policy", json={"max_auto_level": 2, "deny": ["open_website"]}).status_code == 200
    gem.fn = oll.fn = planning("open_website", {"url": "youtube"})
    t = poll(client, submit(client, "open youtube"), {"failed"})
    assert t["steps"][0]["status"] == "blocked" and "autonomy policy" in t["error"]
    assert get_policy().deny == {"open_website"}
    # level-1-only mode: a level-2 tool now needs confirmation instead of running
    client.put("/agent/policy", json={"max_auto_level": 1, "deny": []})
    tid = submit(client, "open youtube")
    assert poll(client, tid, {"awaiting_confirmation"})["pending"]["level"] == 2
    client.post(f"/agent/tasks/{tid}/cancel")


def test_unplannable_goal_fails_cleanly(env):
    client, gem, oll = env
    gem.fn = oll.fn = lambda req: "not json at all"
    t = poll(client, submit(client, "x"), {"failed"})
    assert "valid plan" in t["error"]


def test_an_approval_names_the_step_it_was_about(env):
    """A stale tap must not approve whatever happens to be waiting now."""
    client, gem, oll = env
    get_registry().register(ToolSpec("danger", "Level 3 action.", Echo, lambda p: f"did:{p.text}", 3))
    gem.fn = oll.fn = planning("danger", {"text": "now"})
    tid = submit(client, "risky")
    task = poll(client, tid, {"awaiting_confirmation"})
    index = task["pending"]["index"]

    stale = client.post(f"/agent/tasks/{tid}/confirm",
                        json={"approve": True, "step_index": index + 5})
    assert stale.status_code == 409
    assert poll(client, tid, {"awaiting_confirmation"})["pending"]["index"] == index

    ok = client.post(f"/agent/tasks/{tid}/confirm",
                     json={"approve": True, "step_index": index})
    assert ok.status_code == 200
    assert poll(client, tid, {"succeeded"})["answer"] == "did:now"
