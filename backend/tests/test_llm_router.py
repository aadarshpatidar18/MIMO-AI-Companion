import json
import random

import pytest

from backend.core.llm.base import LLMRequest
from backend.core.llm.config import (RouterSettings, Target, TaskRoute, UserSettingsStore,
                                     default_routes, load_settings, normalize_ollama_url)
from backend.core.llm.errors import (AllProvidersFailedError, AuthError, ProviderUnavailableError,
                                     RateLimitError)
from backend.core.llm.retry import RetryPolicy
from backend.core.llm.router import ModelRouter
from backend.core.llm.usage import UsageTracker
from backend.tests.fakes import FakeProvider


def make(gem_script=(), oll_script=(), selection="auto", gem_configured=True, store=None, **kw):
    gem = FakeProvider("gemini", list(gem_script), local=False, configured=gem_configured,
                       default_model="g-flash")
    oll = FakeProvider("ollama", list(oll_script), local=True, default_model="qwen")
    s = RouterSettings(selection=selection, routes=default_routes(),
                       retry={"gemini": RetryPolicy(max_attempts=3, base_delay=1, jitter=0,
                                                    max_total_wait=15),
                              "ollama": RetryPolicy(max_attempts=1)})
    for k, v in kw.items():
        setattr(s, k, v)
    sleeps = []
    r = ModelRouter({"gemini": gem, "ollama": oll}, s, UsageTracker(), store,
                    sleep=sleeps.append, rng=random.Random(0))
    return r, gem, oll, sleeps


def ask(r, task="chat", **kw):
    return r.generate(LLMRequest.from_prompt("hi", task=task, **kw))


def test_auto_uses_gemini_first_for_chat():
    r, gem, oll, _ = make(["cloud"])
    resp = ask(r)
    assert resp.text == "cloud" and resp.provider == "gemini" and not resp.fell_back
    assert oll.calls == []


def test_429_retries_with_backoff_then_succeeds():
    r, gem, oll, sleeps = make([RateLimitError("x", "gemini", retry_after=2), "ok"])
    resp = ask(r)
    assert resp.provider == "gemini" and sleeps == [2] and resp.attempts[0].retries == 1
    assert oll.calls == []


def test_persistent_429_falls_back_to_ollama_and_sets_cooldown():
    r, gem, oll, _ = make([RateLimitError("x", "gemini")] * 3, ["local"])
    resp = ask(r)
    assert resp.provider == "ollama" and resp.fell_back
    assert [a.outcome for a in resp.attempts] == ["rate_limited", "success"]
    assert len(gem.calls) == 3
    # second request: Gemini is cooling down, so it is not even attempted
    resp2 = ask(r)
    assert resp2.provider == "ollama" and len(gem.calls) == 3
    assert resp2.attempts[0].outcome == "skipped" and "cooling down" in resp2.attempts[0].detail


def test_long_retry_after_falls_back_immediately_without_sleeping():
    r, gem, oll, sleeps = make([RateLimitError("x", "gemini", retry_after=120)], ["local"])
    resp = ask(r)
    assert resp.provider == "ollama" and sleeps == [] and len(gem.calls) == 1


def test_daily_quota_not_retried_and_cooldown_is_long():
    r, gem, oll, sleeps = make([RateLimitError("x", "gemini", scope="daily")], ["local"])
    ask(r)
    assert len(gem.calls) == 1 and sleeps == []
    cd = r.tracker.active_cooldowns()[0]
    assert cd["seconds_remaining"] >= 60 * 60 - 5     # >= ~1h (until Pacific midnight, or 1h fallback)


def test_missing_key_skips_gemini_and_uses_ollama():
    r, gem, oll, _ = make(gem_configured=False)
    resp = ask(r)
    assert resp.provider == "ollama" and gem.calls == []
    assert resp.attempts[0].outcome == "skipped"


def test_selection_ollama_never_touches_cloud():
    r, gem, oll, _ = make(selection="ollama")
    for task in ("chat", "plan", "intent"):
        assert ask(r, task).provider == "ollama"
    assert gem.calls == []


def test_selection_gemini_applies_to_tasks_routed_local_by_default():
    r, gem, oll, _ = make(selection="gemini")
    assert ask(r, "intent").provider == "gemini"       # intent defaults to ollama in auto


def test_selection_gemini_still_falls_back_to_ollama():
    r, gem, oll, _ = make(["x"], ["local"], selection="gemini")
    gem.script = [ProviderUnavailableError("down", "gemini", retryable=False)]
    assert ask(r).provider == "ollama"


def test_local_only_task_never_goes_to_cloud_even_when_selection_is_gemini():
    r, gem, oll, _ = make(selection="gemini")
    assert ask(r, "memory").provider == "ollama" and gem.calls == []


def test_allow_cloud_false_forces_local():
    r, gem, oll, _ = make()
    assert ask(r, allow_cloud=False).provider == "ollama" and gem.calls == []


def test_per_task_model_selection():
    r, gem, oll, _ = make()
    r.set_task_route("plan", [Target("gemini", "gemini-3.5-flash"), Target("ollama", "qwen2.5:3b")])
    ask(r, "plan")
    assert gem.calls == [("gemini-3.5-flash", "plan")]
    r.set_task_route("chat", [Target("ollama", "qwen2.5:3b")])
    ask(r, "chat")
    assert oll.calls == [("qwen2.5:3b", "chat")]


def test_unknown_task_uses_chat_route():
    r, gem, oll, _ = make(["c"])
    assert ask(r, "something_new").provider == "gemini"


def test_fallback_disabled_raises_when_cloud_fails():
    r, gem, oll, _ = make([AuthError("bad key", "gemini")], selection="gemini", fallback_to_local=False)
    with pytest.raises(AllProvidersFailedError) as ei:
        ask(r, "chat")
    assert oll.calls == [] and ei.value.attempts[0].outcome == "auth"


def test_all_failed_error_explains_each_attempt():
    r, gem, oll, _ = make([AuthError("bad", "gemini")],
                          [ProviderUnavailableError("Ollama is not reachable", "ollama")])
    with pytest.raises(AllProvidersFailedError) as ei:
        ask(r)
    msg = str(ei.value)
    assert "gemini" in msg and "ollama" in msg and "not reachable" in msg


def test_auth_error_cools_down_gemini_for_minutes_not_forever():
    r, gem, oll, _ = make([AuthError("bad", "gemini")], ["l1", "l2"])
    ask(r)
    ask(r)
    assert len(gem.calls) == 1
    assert r.tracker.active_cooldowns()[0]["reason"] == "auth problem"


def test_ollama_failure_does_not_create_cooldown():
    r, gem, oll, _ = make(selection="ollama", oll_script=[
        ProviderUnavailableError("down", "ollama"), "back"])
    with pytest.raises(AllProvidersFailedError):
        ask(r)
    assert ask(r).text == "back"                       # recovers immediately once Ollama is up


def test_local_budget_blocks_cloud_and_falls_back():
    r, gem, oll, _ = make(["a", "b"], limits={"gemini": {"g-flash": {"rpm": 1}}})
    assert ask(r).provider == "gemini"
    resp = ask(r)
    assert resp.provider == "ollama" and "local limit" in resp.attempts[0].detail


def test_usage_is_recorded_per_attempt_including_failures():
    r, gem, oll, _ = make([RateLimitError("x", "gemini")] * 3, ["local"])
    ask(r)
    rows = {(x["provider"]): x for x in r.tracker.summary(since=0)}
    assert rows["gemini"]["requests"] == 3 and rows["gemini"]["rate_limited"] == 3
    assert rows["ollama"]["successes"] == 1 and rows["ollama"]["prompt_tokens"] == 3


def test_explicit_provider_override():
    r, gem, oll, _ = make(selection="ollama")
    resp = ask(r, provider="gemini", model="gemini-3.5-flash")
    assert resp.provider == "gemini" and gem.calls[0][0] == "gemini-3.5-flash"


def test_provider_bug_does_not_crash_router():
    r, gem, oll, _ = make([RuntimeError("kaboom")], ["local"])
    assert ask(r).provider == "ollama"


def test_set_selection_validation_and_persistence(tmp_path):
    store = UserSettingsStore(tmp_path / "s.json")
    r, *_ = make(store=store)
    with pytest.raises(ValueError):
        r.set_selection("openai")
    r.set_selection("gemini", fallback_to_local=False)
    r.set_task_route("plan", [Target("ollama", "qwen2.5:3b")])
    saved = json.loads((tmp_path / "s.json").read_text())
    assert saved["selection"] == "gemini" and saved["fallback_to_local"] is False
    assert "key" not in json.dumps(saved).lower()
    s2 = load_settings(env={}, config_path=tmp_path / "none.json", store=store)
    assert s2.selection == "gemini" and s2.routes["plan"].targets == [Target("ollama", "qwen2.5:3b")]


def test_local_only_route_rejects_cloud_target():
    r, *_ = make()
    with pytest.raises(ValueError):
        r.set_task_route("memory", [Target("gemini")], local_only=True)


def test_invalid_model_name_rejected():
    r, *_ = make()
    with pytest.raises(ValueError):
        r.set_task_route("chat", [Target("gemini", "x/../../evil?alt=1")])


def test_settings_precedence_env_over_file_and_store_over_env(tmp_path):
    cfg = tmp_path / "models.json"
    cfg.write_text(json.dumps({"selection": "gemini", "ollama": {"default_model": "from-file"}}))
    s = load_settings(env={"MIMO_LLM_PROVIDER": "auto", "MIMO_OLLAMA_MODEL": "from-env"}, config_path=cfg)
    assert s.selection == "auto" and s.ollama["default_model"] == "from-env"
    store = UserSettingsStore(tmp_path / "u.json")
    store.path.write_text(json.dumps({"selection": "ollama"}))
    s = load_settings(env={"MIMO_LLM_PROVIDER": "auto"}, config_path=cfg, store=store)
    assert s.selection == "ollama"


def test_default_selection_is_local_and_corrupt_store_is_ignored(tmp_path):
    bad = tmp_path / "u.json"
    bad.write_text("{not json")
    s = load_settings(env={}, config_path=tmp_path / "none.json", store=UserSettingsStore(bad))
    assert s.selection == "ollama"


@pytest.mark.parametrize("raw,expected", [
    ("127.0.0.1:11434", "http://127.0.0.1:11434"),
    ("0.0.0.0", "http://127.0.0.1:11434"),
    ("http://localhost", "http://localhost:11434"),
    ("http://192.168.1.5:11500/", "http://192.168.1.5:11500"),
    ("", "http://127.0.0.1:11434"),
])
def test_normalize_ollama_url(raw, expected):
    assert normalize_ollama_url(raw) == expected
