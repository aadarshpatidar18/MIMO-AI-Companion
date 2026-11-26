"""Usage logging, local budget checks and per-model cooldowns.

Every request actually sent to a provider is one row in SQLite (no prompt or
response text is stored - only counts, tokens, timings and outcomes).
Provider quotas are enforced server-side; the counters here let MIMO show
usage, apply optional self-imposed limits, and stop hammering a model that
just returned 429.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional, Union

# Gemini's daily quota resets at midnight Pacific time.
_QUOTA_TZ = "America/Los_Angeles"


def quota_day_bounds(now: float) -> Optional[tuple[float, float]]:
    """(start, end) of the current Pacific-time day, or None if tz data is missing.

    On Windows, zoneinfo needs the `tzdata` package; callers must cope with None.
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(_QUOTA_TZ)
    except Exception:
        return None
    dt = datetime.fromtimestamp(now, tz)
    start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    task TEXT NOT NULL,
    outcome TEXT NOT NULL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    latency_ms INTEGER,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_ts ON llm_usage(ts);
CREATE INDEX IF NOT EXISTS idx_llm_usage_pm ON llm_usage(provider, model, ts);
"""


class UsageTracker:
    def __init__(self, db_path: Union[str, Path] = ":memory:",
                 clock: Callable[[], float] = time.time):
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self._cooldowns: dict[tuple[str, str], tuple[float, str]] = {}

    def now(self) -> float:
        return self._clock()

    # ---- recording -------------------------------------------------
    def record(self, provider: str, model: str, task: str, outcome: str, *,
               prompt_tokens: Optional[int] = None,
               completion_tokens: Optional[int] = None,
               latency_ms: int = 0, error: str = "") -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO llm_usage (ts, provider, model, task, outcome, prompt_tokens,"
                " completion_tokens, latency_ms, error) VALUES (?,?,?,?,?,?,?,?,?)",
                (self.now(), provider, model, task, outcome, prompt_tokens,
                 completion_tokens, latency_ms, error[:300]))

    # ---- counters ---------------------------------------------------
    def count_since(self, provider: str, model: Optional[str], since: float) -> int:
        q = "SELECT COUNT(*) FROM llm_usage WHERE provider=? AND ts>=?"
        args: list = [provider, since]
        if model is not None:
            q += " AND model=?"
            args.append(model)
        with self._lock:
            return int(self._db.execute(q, args).fetchone()[0])

    def requests_last_minute(self, provider: str, model: Optional[str]) -> int:
        return self.count_since(provider, model, self.now() - 60)

    def requests_today(self, provider: str, model: Optional[str]) -> int:
        b = quota_day_bounds(self.now())
        since = b[0] if b else self.now() - 86400   # fall back to rolling 24h
        return self.count_since(provider, model, since)

    def check_budget(self, provider: str, model: str, limits: Optional[dict]) -> Optional[str]:
        """Return a reason string if a self-imposed limit is reached, else None.

        `limits` looks like {"rpm": 10, "rpd": 200}; missing/None means unlimited.
        """
        if not limits:
            return None
        rpm, rpd = limits.get("rpm"), limits.get("rpd")
        if rpm is not None and self.requests_last_minute(provider, model) >= rpm:
            return f"local limit reached ({rpm} requests/min)"
        if rpd is not None and self.requests_today(provider, model) >= rpd:
            return f"local limit reached ({rpd} requests/day)"
        return None

    # ---- cooldowns --------------------------------------------------
    def set_cooldown(self, provider: str, model: str, seconds: float, reason: str) -> None:
        with self._lock:
            self._cooldowns[(provider, model)] = (self.now() + seconds, reason)

    def cooldown_reason(self, provider: str, model: str) -> Optional[str]:
        with self._lock:
            item = self._cooldowns.get((provider, model))
            if not item:
                return None
            until, reason = item
            remaining = until - self.now()
            if remaining <= 0:
                del self._cooldowns[(provider, model)]
                return None
            return f"cooling down for {int(remaining) + 1}s ({reason})"

    def clear_cooldown(self, provider: Optional[str] = None) -> None:
        with self._lock:
            if provider is None:
                self._cooldowns.clear()
            else:
                for k in [k for k in self._cooldowns if k[0] == provider]:
                    del self._cooldowns[k]

    def active_cooldowns(self) -> list[dict]:
        out = []
        with self._lock:
            now = self.now()
            for (p, m), (until, reason) in list(self._cooldowns.items()):
                if until > now:
                    out.append({"provider": p, "model": m,
                                "seconds_remaining": int(until - now) + 1, "reason": reason})
        return out

    def seconds_until_quota_reset(self) -> float:
        b = quota_day_bounds(self.now())
        return (b[1] - self.now()) if b else 3600.0   # unknown tz: re-probe hourly

    # ---- reporting ---------------------------------------------------
    def summary(self, since: Optional[float] = None) -> list[dict]:
        """Per provider/model totals since `since` (default: start of quota day)."""
        if since is None:
            b = quota_day_bounds(self.now())
            since = b[0] if b else self.now() - 86400
        q = ("SELECT provider, model, COUNT(*),"
             " SUM(outcome='success'), SUM(outcome='rate_limited'),"
             " SUM(outcome NOT IN ('success','rate_limited')),"
             " COALESCE(SUM(prompt_tokens),0), COALESCE(SUM(completion_tokens),0),"
             " COALESCE(AVG(CASE WHEN outcome='success' THEN latency_ms END),0)"
             " FROM llm_usage WHERE ts>=? GROUP BY provider, model ORDER BY provider, model")
        with self._lock:
            rows = self._db.execute(q, (since,)).fetchall()
        return [{
            "provider": r[0], "model": r[1], "requests": r[2], "successes": int(r[3] or 0),
            "rate_limited": int(r[4] or 0), "other_errors": int(r[5] or 0),
            "prompt_tokens": r[6], "completion_tokens": r[7], "avg_latency_ms": int(r[8]),
            "requests_last_minute": self.requests_last_minute(r[0], r[1]),
        } for r in rows]

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT ts, provider, model, task, outcome, latency_ms, error FROM llm_usage"
                " ORDER BY id DESC LIMIT ?", (min(max(limit, 1), 500),)).fetchall()
        return [dict(zip(("ts", "provider", "model", "task", "outcome", "latency_ms", "error"), r))
                for r in rows]
