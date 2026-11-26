"""SQLite persistence for agent tasks, the action (audit) log, and agent settings."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional, Union

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_tasks (
    id TEXT PRIMARY KEY, session_id TEXT, goal TEXT NOT NULL, status TEXT NOT NULL,
    mode TEXT, created_at REAL NOT NULL, finished_at REAL, answer TEXT, error TEXT,
    plan TEXT, steps TEXT, pending TEXT, agent TEXT
);
CREATE TABLE IF NOT EXISTS agent_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, task_id TEXT, step_index INTEGER,
    tool TEXT NOT NULL, args TEXT, level INTEGER, decision TEXT, outcome TEXT NOT NULL,
    verified INTEGER, duration_ms INTEGER, detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_actions_task ON agent_actions(task_id, id);
CREATE TABLE IF NOT EXISTS agent_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""
_JSON_FIELDS = ("plan", "steps", "pending")
TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}


class AgentStore:
    def __init__(self, path: Union[str, Path] = ":memory:", clock: Callable[[], float] = time.time):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Additive migrations for databases created by an older build."""
        cols = {row["name"] for row in self._db.execute("PRAGMA table_info(agent_tasks)")}
        if "agent" not in cols:
            with self._lock, self._db:
                self._db.execute("ALTER TABLE agent_tasks ADD COLUMN agent TEXT")

    # ---- tasks ----
    def create_task(self, task_id: str, goal: str, session_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO agent_tasks (id, session_id, goal, status, created_at)"
                             " VALUES (?,?,?,?,?)", (task_id, session_id, goal, "queued", self._clock()))

    def update_task(self, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols, vals = [], []
        for k, v in fields.items():
            if k not in {"status", "mode", "answer", "error", "plan", "steps", "pending",
                         "finished_at", "agent"}:
                raise ValueError(f"unknown task field {k}")
            cols.append(f"{k}=?")
            vals.append(json.dumps(v) if k in _JSON_FIELDS and v is not None else v)
        if fields.get("status") in TERMINAL and "finished_at" not in fields:
            cols.append("finished_at=?")
            vals.append(self._clock())
        with self._lock, self._db:
            self._db.execute(f"UPDATE agent_tasks SET {', '.join(cols)} WHERE id=?", (*vals, task_id))

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        d = dict(row)
        for k in _JSON_FIELDS:
            d[k] = json.loads(d[k]) if d.get(k) else None
        return d

    def get_task(self, task_id: str) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT * FROM agent_tasks WHERE id=?", (task_id,)).fetchone()
        return self._row(row) if row else None

    def list_tasks(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM agent_tasks ORDER BY created_at DESC, rowid DESC LIMIT ?",
                                    (min(max(limit, 1), 200),)).fetchall()
        return [self._row(r) for r in rows]

    def recover_interrupted(self) -> int:
        """Tasks left queued/running by a crash or restart can never finish: mark them failed."""
        with self._lock, self._db:
            cur = self._db.execute(
                "UPDATE agent_tasks SET status='failed', finished_at=?, pending=NULL,"
                " error='Interrupted by a backend restart' WHERE status NOT IN"
                " ('succeeded','failed','cancelled','timed_out')", (self._clock(),))
            return cur.rowcount

    # ---- audit log ----
    def log_action(self, *, task_id: str, step_index: int, tool: str, args: dict, level: int,
                   decision: str, outcome: str, verified: Optional[bool], duration_ms: int,
                   detail: str = "") -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO agent_actions (ts, task_id, step_index, tool, args, level, decision,"
                " outcome, verified, duration_ms, detail) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (self._clock(), task_id, step_index, tool, json.dumps(args, default=str)[:500], level,
                 decision, outcome, None if verified is None else int(verified), duration_ms, detail[:300]))

    def list_actions(self, limit: int = 100, task_id: Optional[str] = None) -> list[dict]:
        q, args = "SELECT * FROM agent_actions", []
        if task_id:
            q += " WHERE task_id=?"
            args.append(task_id)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(min(max(limit, 1), 500))
        with self._lock:
            return [dict(r) for r in self._db.execute(q, args).fetchall()]

    # ---- settings ----
    def get_setting(self, key: str) -> Optional[Any]:
        with self._lock:
            row = self._db.execute("SELECT value FROM agent_settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO agent_settings (key, value) VALUES (?,?)"
                             " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))
