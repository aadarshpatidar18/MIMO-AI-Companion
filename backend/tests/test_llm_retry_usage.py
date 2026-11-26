import random

import pytest

from backend.core.llm.errors import AuthError, ProviderUnavailableError, RateLimitError
from backend.core.llm.retry import RetryPolicy, call_with_retry, compute_delay
from backend.core.llm.usage import UsageTracker


def run(script, policy=RetryPolicy(), seed=1):
    sleeps, calls = [], []

    def fn():
        calls.append(1)
        item = script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
    return fn, sleeps, calls, lambda: call_with_retry(fn, policy, sleep=sleeps.append,
                                                      rng=random.Random(seed))


def test_success_after_429s_uses_exponential_backoff():
    pol = RetryPolicy(max_attempts=4, base_delay=1, max_delay=8, max_total_wait=60, jitter=0)
    fn, sleeps, calls, go = run([RateLimitError("x", "g"), RateLimitError("x", "g"), "ok"], pol)
    assert go() == "ok" and sleeps == [1, 2] and len(calls) == 3


def test_retry_after_is_a_floor():
    pol = RetryPolicy(max_attempts=3, base_delay=1, jitter=0, max_total_wait=60)
    fn, sleeps, calls, go = run([RateLimitError("x", "g", retry_after=7), "ok"], pol)
    assert go() == "ok" and sleeps == [7]


def test_gives_up_when_wait_exceeds_budget_so_router_can_fall_back():
    pol = RetryPolicy(max_attempts=5, jitter=0, max_total_wait=10)
    fn, sleeps, calls, go = run([RateLimitError("x", "g", retry_after=45)], pol)
    with pytest.raises(RateLimitError):
        go()
    assert sleeps == [] and len(calls) == 1


def test_daily_quota_and_non_retryable_are_not_retried():
    for err in (RateLimitError("x", "g", scope="daily"), AuthError("k", "g"),
                ProviderUnavailableError("down", "o", retryable=False)):
        fn, sleeps, calls, go = run([err])
        with pytest.raises(type(err)):
            go()
        assert len(calls) == 1 and sleeps == []


def test_attempt_cap():
    pol = RetryPolicy(max_attempts=3, jitter=0, max_total_wait=100)
    fn, sleeps, calls, go = run([ProviderUnavailableError("x", "g", retryable=True)] * 5, pol)
    with pytest.raises(ProviderUnavailableError):
        go()
    assert len(calls) == 3 and len(sleeps) == 2


def test_jitter_stays_in_bounds():
    pol = RetryPolicy(base_delay=2, jitter=0.25)
    rng = random.Random(0)
    for _ in range(200):
        d = compute_delay(pol, 0, None, rng)
        assert 1.5 <= d <= 2.5


# ---------------- usage ----------------
class Clock:
    t = 1_000_000.0

    def __call__(self):
        return self.t


def test_usage_counts_and_summary():
    clk = Clock()
    u = UsageTracker(clock=clk)
    u.record("gemini", "m", "chat", "success", prompt_tokens=10, completion_tokens=5, latency_ms=100)
    u.record("gemini", "m", "chat", "rate_limited")
    clk.t += 30
    u.record("ollama", "q", "intent", "success", latency_ms=50)
    assert u.requests_last_minute("gemini", "m") == 2
    clk.t += 61
    assert u.requests_last_minute("gemini", "m") == 0
    rows = {(r["provider"], r["model"]): r for r in u.summary(since=0)}
    g = rows[("gemini", "m")]
    assert (g["requests"], g["successes"], g["rate_limited"], g["prompt_tokens"]) == (2, 1, 1, 10)


def test_budget_and_cooldown_expiry():
    clk = Clock()
    u = UsageTracker(clock=clk)
    for _ in range(3):
        u.record("gemini", "m", "chat", "success")
    assert "3 requests" not in (u.check_budget("gemini", "m", {"rpm": 5}) or "")
    assert u.check_budget("gemini", "m", {"rpm": 3}) is not None
    assert u.check_budget("gemini", "m", None) is None
    u.set_cooldown("gemini", "m", 60, "rate limited")
    assert "cooling down" in u.cooldown_reason("gemini", "m")
    clk.t += 61
    assert u.cooldown_reason("gemini", "m") is None


def test_usage_never_stores_prompt_text():
    u = UsageTracker()
    u.record("gemini", "m", "chat", "error", error="x" * 1000)
    assert len(u.recent(1)[0]["error"]) == 300
