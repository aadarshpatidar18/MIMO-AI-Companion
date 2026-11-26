"""SQLite persistence for devices, token hashes, security events and the auth setting."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional, Union

_SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    scopes TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_seen REAL,
    revoked_at REAL
);
CREATE TABLE IF NOT EXISTS device_tokens (
    token_hash TEXT PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    revoked_at REAL
);
CREATE INDEX IF NOT EXISTS idx_tokens_device ON device_tokens(device_id);
CREATE TABLE IF NOT EXISTS security_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    device_id TEXT,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS security_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _to_bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


class SecurityStore:
    """One connection, one lock - the same pattern the agent store uses."""

    def __init__(self, path: Union[str, Path] = ":memory:", clock: Callable[[], float] = time.time):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        if str(path) != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(_SCHEMA)

    # ---------------------------------------------------------------- devices
    def create_device(self, device_id: str, name: str, kind: str, scopes) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO devices (id, name, kind, scopes, created_at) VALUES (?,?,?,?,?)",
                (device_id, name, kind, json.dumps(sorted(scopes)), self._clock()))

    def get_device(self, device_id: str) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
        return self._row(row) if row else None

    def list_devices(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM devices WHERE revoked_at IS NULL ORDER BY created_at").fetchall()
        return [self._row(r) for r in rows]

    def rename_device(self, device_id: str, name: str) -> bool:
        with self._lock, self._db:
            cur = self._db.execute("UPDATE devices SET name=? WHERE id=? AND revoked_at IS NULL",
                                   (name, device_id))
            return cur.rowcount > 0

    def revoke_device(self, device_id: str) -> bool:
        """Revokes the device and every token it holds. Takes effect on the next request."""
        with self._lock, self._db:
            now = self._clock()
            cur = self._db.execute(
                "UPDATE devices SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (now, device_id))
            if cur.rowcount == 0:
                return False
            self._db.execute("UPDATE device_tokens SET revoked_at=? WHERE device_id=?", (now, device_id))
            return True

    def touch(self, device_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE devices SET last_seen=? WHERE id=?", (self._clock(), device_id))

    # ---------------------------------------------------------------- tokens
    def add_token(self, device_id: str, token_hash: str) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO device_tokens (token_hash, device_id, created_at)"
                             " VALUES (?,?,?)", (token_hash, device_id, self._clock()))

    def device_for_token(self, token_hash: str) -> Optional[dict]:
        """The live device behind a token, or None if unknown, revoked or orphaned."""
        with self._lock:
            row = self._db.execute(
                "SELECT d.* FROM device_tokens t JOIN devices d ON d.id = t.device_id"
                " WHERE t.token_hash=? AND t.revoked_at IS NULL AND d.revoked_at IS NULL",
                (token_hash,)).fetchone()
        return self._row(row) if row else None

    def revoke_token(self, token_hash: str) -> bool:
        with self._lock, self._db:
            cur = self._db.execute("UPDATE device_tokens SET revoked_at=? WHERE token_hash=?"
                                   " AND revoked_at IS NULL", (self._clock(), token_hash))
            return cur.rowcount > 0

    def rotate_token(self, device_id: str, old_hash: str, new_hash: str) -> bool:
        """Replace one token with another atomically; False if the old one was not live."""
        with self._lock, self._db:
            row = self._db.execute(
                "SELECT 1 FROM device_tokens WHERE token_hash=? AND device_id=? AND revoked_at IS NULL",
                (old_hash, device_id)).fetchone()
            if row is None:
                return False
            now = self._clock()
            self._db.execute("UPDATE device_tokens SET revoked_at=? WHERE token_hash=?",
                             (now, old_hash))
            self._db.execute("INSERT INTO device_tokens (token_hash, device_id, created_at)"
                             " VALUES (?,?,?)", (new_hash, device_id, now))
            return True

    # ---------------------------------------------------------------- events
    def log_event(self, kind: str, device_id: Optional[str] = None, detail: str = "") -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO security_events (ts, kind, device_id, detail) VALUES (?,?,?,?)",
                             (self._clock(), kind[:40], device_id, detail[:300]))

    def list_events(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM security_events ORDER BY id DESC LIMIT ?",
                                    (min(max(limit, 1), 500),)).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- settings
    def require_auth(self) -> bool:
        """Env wins (so a deployment can harden without a DB write); otherwise the stored value."""
        env = os.environ.get("MIMO_REQUIRE_AUTH")
        if env is not None:
            return _to_bool(env)
        with self._lock:
            row = self._db.execute("SELECT value FROM security_settings WHERE key='require_auth'"
                                   ).fetchone()
        return bool(json.loads(row[0])) if row else False

    def set_require_auth(self, value: bool) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO security_settings (key, value) VALUES ('require_auth', ?)"
                             " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(bool(value)),))

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["scopes"] = frozenset(json.loads(d["scopes"]))
        return d
