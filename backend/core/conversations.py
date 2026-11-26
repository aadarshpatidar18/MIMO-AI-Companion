"""Durable conversation store: the shared history every MIMO device reads.

Replaces the in-process `conversation_history` dict for anything that needs to survive a
restart or be visible from another device. One SQLite file, WAL, one lock - the same
pattern as the agent and security stores.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Optional, Union

from .llm.config import REPO_ROOT

TITLE_MAX = 120
CONTENT_MAX = 8000
ROLES = ("user", "assistant")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    device_origin TEXT,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL,
    device_id TEXT,
    meta TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversations(archived, updated_at DESC);
"""


def _auto_title(content: str) -> str:
    line = " ".join(content.split())
    return (line[:77] + "...") if len(line) > 80 else line


class ConversationStore:
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

    # ------------------------------------------------------------------ conversations
    def create(self, title: Optional[str] = None, device_id: Optional[str] = None) -> dict:
        cid = uuid.uuid4().hex[:12]
        now = self._clock()
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at, device_origin)"
                " VALUES (?,?,?,?,?)",
                (cid, (title or "").strip()[:TITLE_MAX], now, now, device_id))
        return self.get(cid)

    def get(self, conversation_id: str) -> Optional[dict]:
        with self._lock:
            row = self._db.execute("SELECT * FROM conversations WHERE id=?",
                                   (conversation_id,)).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 50, include_archived: bool = False) -> list[dict]:
        """Newest first, each with its message count and the latest message, for the sidebar."""
        where = "" if include_archived else "WHERE c.archived = 0"
        with self._lock:
            rows = self._db.execute(f"""
                SELECT c.*,
                       (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count,
                       (SELECT m.content FROM messages m WHERE m.conversation_id = c.id
                          ORDER BY m.id DESC LIMIT 1) AS last_message
                FROM conversations c {where}
                ORDER BY c.updated_at DESC LIMIT ?
            """, (min(max(limit, 1), 200),)).fetchall()
        return [dict(r) for r in rows]

    def rename(self, conversation_id: str, title: str) -> bool:
        title = (title or "").strip()[:TITLE_MAX]
        if not title:
            return False
        with self._lock, self._db:
            cur = self._db.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                                   (title, self._clock(), conversation_id))
            return cur.rowcount > 0

    def archive(self, conversation_id: str, archived: bool = True) -> bool:
        with self._lock, self._db:
            cur = self._db.execute("UPDATE conversations SET archived=?, updated_at=? WHERE id=?",
                                   (1 if archived else 0, self._clock(), conversation_id))
            return cur.rowcount > 0

    def delete(self, conversation_id: str) -> bool:
        with self._lock, self._db:
            cur = self._db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------ messages
    @staticmethod
    def _clean(role: str, content: str) -> str:
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        content = (content or "").strip()
        if not content:
            raise ValueError("message content cannot be empty")
        if len(content) > CONTENT_MAX:
            raise ValueError(f"message is too long (max {CONTENT_MAX} characters)")
        return content

    def append(self, conversation_id: str, role: str, content: str,
               device_id: Optional[str] = None, meta: Optional[str] = None) -> Optional[int]:
        """Add one message. Returns its id, or None if the conversation does not exist."""
        content = self._clean(role, content)
        now = self._clock()
        with self._lock, self._db:
            if self._db.execute("SELECT 1 FROM conversations WHERE id=?",
                                (conversation_id,)).fetchone() is None:
                return None
            cur = self._db.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at, device_id, meta)"
                " VALUES (?,?,?,?,?,?)", (conversation_id, role, content, now, device_id, meta))
            # The first user message names an untitled conversation.
            self._db.execute(
                "UPDATE conversations SET updated_at=?,"
                " title = CASE WHEN title = '' AND ? = 'user' THEN ? ELSE title END WHERE id=?",
                (now, role, _auto_title(content), conversation_id))
            return int(cur.lastrowid)

    def append_turn(self, conversation_id: str, question: str, answer: str,
                    device_id: Optional[str] = None) -> Optional[tuple[int, int]]:
        """Store a request and its answer as one unit.

        The pair is committed in a single transaction, so a reader from another device
        never sees a user message whose answer is still missing, and a failure leaves
        neither row behind.
        """
        question = self._clean("user", question)
        answer = self._clean("assistant", answer)
        now = self._clock()
        with self._lock, self._db:          # one transaction, both rows or none
            if self._db.execute("SELECT 1 FROM conversations WHERE id=?",
                                (conversation_id,)).fetchone() is None:
                return None
            rows = []
            for role, content in (("user", question), ("assistant", answer)):
                cur = self._db.execute(
                    "INSERT INTO messages (conversation_id, role, content, created_at,"
                    " device_id, meta) VALUES (?,?,?,?,?,?)",
                    (conversation_id, role, content, now, device_id, None))
                rows.append(int(cur.lastrowid))
            self._db.execute(
                "UPDATE conversations SET updated_at=?,"
                " title = CASE WHEN title = '' THEN ? ELSE title END WHERE id=?",
                (now, _auto_title(question), conversation_id))
            return rows[0], rows[1]

    def messages(self, conversation_id: str, after_id: int = 0, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM messages WHERE conversation_id=? AND id>? ORDER BY id LIMIT ?",
                (conversation_id, max(after_id, 0), min(max(limit, 1), 500))).fetchall()
        return [dict(r) for r in rows]

    def history(self, conversation_id: str, limit: int = 10) -> list[dict]:
        """The tail of a conversation in the shape the LLM layer expects."""
        with self._lock:
            rows = self._db.execute(
                "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
                (conversation_id, min(max(limit, 1), 50))).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Substring search for now; FTS5 is the Milestone 3 upgrade."""
        q = (query or "").strip()
        if not q:
            return []
        with self._lock:
            rows = self._db.execute(
                "SELECT m.*, c.title FROM messages m JOIN conversations c ON c.id = m.conversation_id"
                " WHERE m.content LIKE ? ORDER BY m.id DESC LIMIT ?",
                (f"%{q}%", min(max(limit, 1), 100))).fetchall()
        return [dict(r) for r in rows]


_store: Optional[ConversationStore] = None
_lock = threading.Lock()


def init_store(data_dir: Optional[Path] = None) -> ConversationStore:
    global _store
    with _lock:
        data = Path(data_dir or os.environ.get("MIMO_DATA_DIR", REPO_ROOT / "data"))
        _store = ConversationStore(data / "conversations.db")
        return _store


def get_store() -> ConversationStore:
    global _store
    with _lock:
        if _store is None:
            data = Path(os.environ.get("MIMO_DATA_DIR", REPO_ROOT / "data"))
            _store = ConversationStore(data / "conversations.db")
        return _store


def shutdown_store() -> None:
    global _store
    with _lock:
        _store = None
