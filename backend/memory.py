import os
import sqlite3
import re
from pathlib import Path

# Default location is unchanged (backend/mimo.db); override with MIMO_DB_PATH.
DB_PATH = Path(os.environ.get("MIMO_DB_PATH") or Path(__file__).resolve().parent / "mimo.db")

CATEGORIES = {
    "interest",
    "skill",
    "goal",
    "preference",
    "project",
    "education",
    "other"
}


def connect():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def normalize_content(content):
    content = content.lower().strip()
    content = re.sub(r"\s+", " ", content)
    content = re.sub(r"[.!?]+$", "", content)
    return content


# How much a fact matters by kind, before it is ever recalled.
BASE_IMPORTANCE = {"goal": 4, "project": 4, "preference": 3, "skill": 3,
                   "interest": 3, "education": 3, "other": 2}
MAX_IMPORTANCE = 5
_FTS5 = None          # None = not probed yet, True/False once known


def _has_fts5(connection) -> bool:
    global _FTS5
    if _FTS5 is None:
        try:
            connection.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(x)")
            connection.execute("DROP TABLE IF EXISTS _fts_probe")
            _FTS5 = True
        except sqlite3.OperationalError:
            _FTS5 = False
    return _FTS5


def _fts_query(keyword: str) -> str:
    """Turn a plain query into FTS syntax: every word a prefix, quoted, so users cannot
    inject operators or crash the match."""
    words = [re.sub(r'[^\w]', '', w) for w in keyword.split()]
    words = [w for w in words if w]
    return " ".join(f'"{w}"*' for w in words)


def _score_sql(prefix="") -> str:
    """Relevance a person would expect: importance first, then how often it was recalled."""
    return (f"({prefix}importance + MIN({prefix}access_count, 10) * 0.1) DESC, "
            f"{prefix}id DESC")


def initialize_memory():
    with connect() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'other',
                normalized_content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                importance INTEGER DEFAULT 3,
                access_count INTEGER DEFAULT 0,
                last_used TIMESTAMP
            )
        """)

        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(memories)"
            ).fetchall()
        }

        if "category" not in columns:
            connection.execute(
                "ALTER TABLE memories ADD COLUMN category TEXT DEFAULT 'other'"
            )

        if "normalized_content" not in columns:
            connection.execute(
                "ALTER TABLE memories ADD COLUMN normalized_content TEXT"
            )

        if "updated_at" not in columns:
            connection.execute(
                "ALTER TABLE memories ADD COLUMN updated_at TIMESTAMP"
            )

        if "importance" not in columns:
            connection.execute("ALTER TABLE memories ADD COLUMN importance INTEGER DEFAULT 3")
            for category, value in BASE_IMPORTANCE.items():
                connection.execute("UPDATE memories SET importance = ? WHERE category = ?",
                                   (value, category))

        if "access_count" not in columns:
            connection.execute("ALTER TABLE memories ADD COLUMN access_count INTEGER DEFAULT 0")

        if "last_used" not in columns:
            connection.execute("ALTER TABLE memories ADD COLUMN last_used TIMESTAMP")

        rows = connection.execute(
            "SELECT id, content FROM memories"
        ).fetchall()

        for row in rows:
            connection.execute(
                """
                UPDATE memories
                SET normalized_content = ?,
                    updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
                WHERE id = ?
                """,
                (normalize_content(row["content"]), row["id"])
            )

        connection.execute("""
            DELETE FROM memories
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM memories
                GROUP BY normalized_content
            )
        """)

        connection.execute("""
            UPDATE memories
            SET category = 'interest'
            WHERE LOWER(TRIM(content)) IN (
                'i like robotics',
                'like robotics'
            )
        """)

        connection.execute("""
            UPDATE memories
            SET category = 'skill'
            WHERE LOWER(TRIM(content)) IN (
                'i am learning python',
                'learning python'
            )
        """)

        connection.execute("""
            DELETE FROM memories
            WHERE LOWER(TRIM(content)) = 'learning python'
            AND EXISTS (
                SELECT 1
                FROM memories AS other
                WHERE LOWER(TRIM(other.content)) = 'i am learning python'
            )
        """)

        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_normalized
            ON memories(normalized_content)
        """)

        if _has_fts5(connection):
            # External-content index: the table stays the truth, the index only mirrors it.
            connection.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(content, content='memories', content_rowid='id')
            """)
            connection.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
                END
            """)
            connection.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content)
                    VALUES ('delete', old.id, old.content);
                END
            """)
            connection.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content)
                    VALUES ('delete', old.id, old.content);
                    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
                END
            """)
            connection.execute("INSERT INTO memories_fts(memories_fts) VALUES ('rebuild')")


def save_memory(content, category="other"):
    content = content.strip()
    category = category.lower().strip()

    if not content:
        return False

    if category not in CATEGORIES:
        category = "other"

    normalized = normalize_content(content)

    with connect() as connection:
        existing = connection.execute(
            """
            SELECT id, category
            FROM memories
            WHERE normalized_content = ?
            """,
            (normalized,)
        ).fetchone()

        if existing:
            if category != "other" and existing["category"] == "other":
                connection.execute(
                    """
                    UPDATE memories
                    SET category = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (category, existing["id"])
                )

            return False

        connection.execute(
            """
            INSERT INTO memories (
                content,
                category,
                normalized_content,
                importance
            )
            VALUES (?, ?, ?, ?)
            """,
            (content, category, normalized, BASE_IMPORTANCE.get(category, 2))
        )

    return True


def get_memories(limit=50, category=None):
    query = ("SELECT id, content, category, importance, access_count, last_used,"
             " created_at, updated_at FROM memories")
    params = []
    if category and category.lower() in CATEGORIES:
        query += " WHERE category = ?"
        params.append(category.lower())
    query += " ORDER BY importance DESC, id DESC LIMIT ?"
    params.append(limit)
    with connect() as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def search_memory(keyword="", category=None, limit=50, remember_use=True):
    """Find memories. With a keyword, FTS5 relevance decides; otherwise importance does.

    A real query counts as a recall: the rows it returns get their access_count bumped, which
    slowly lifts facts that keep mattering. Listing everything does not count.
    """
    keyword = keyword.strip()
    category = category.lower() if category and category.lower() in CATEGORIES else None
    columns = ("id, content, category, importance, access_count, last_used, created_at, updated_at")

    with connect() as connection:
        rows = []
        if keyword and _has_fts5(connection):
            match = _fts_query(keyword)
            if match:
                query = (f"SELECT m.{columns.replace(', ', ', m.')} FROM memories_fts f "
                         "JOIN memories m ON m.id = f.rowid WHERE memories_fts MATCH ?")
                params = [match]
                if category:
                    query += " AND m.category = ?"
                    params.append(category)
                query += " ORDER BY bm25(memories_fts), " + _score_sql("m.") + " LIMIT ?"
                params.append(limit)
                try:
                    rows = connection.execute(query, params).fetchall()
                except sqlite3.OperationalError:
                    rows = []
        if not rows:
            query = (f"SELECT {columns} FROM memories WHERE 1=1")
            params = []
            if keyword:
                query += " AND content LIKE ?"
                params.append(f"%{keyword}%")
            if category:
                query += " AND category = ?"
                params.append(category)
            query += " ORDER BY " + _score_sql() + " LIMIT ?"
            params.append(limit)
            rows = connection.execute(query, params).fetchall()

        results = [dict(row) for row in rows]

        if keyword and remember_use and results:
            ids = [r["id"] for r in results]
            connection.executemany(
                "UPDATE memories SET access_count = COALESCE(access_count, 0) + 1,"
                " last_used = CURRENT_TIMESTAMP WHERE id = ?", [(i,) for i in ids])
            for row in results:                      # report what was just recorded
                row["access_count"] = (row.get("access_count") or 0) + 1

    return results


def set_importance(memory_id: int, importance: int) -> bool:
    if not isinstance(importance, int) or not 1 <= importance <= MAX_IMPORTANCE:
        return False
    with connect() as connection:
        cursor = connection.execute("UPDATE memories SET importance = ? WHERE id = ?",
                                    (importance, memory_id))
        return cursor.rowcount > 0


def update_memory(memory_id, content, category=None):
    content = content.strip()

    if not content:
        return False

    normalized = normalize_content(content)

    if category is not None:
        category = category.lower().strip()

        if category not in CATEGORIES:
            return False

    with connect() as connection:
        existing = connection.execute(
            """
            SELECT id FROM memories
            WHERE normalized_content = ? AND id != ?
            """,
            (normalized, memory_id)
        ).fetchone()

        if existing:
            return False

        if category:
            cursor = connection.execute(
                """
                UPDATE memories
                SET content = ?,
                    category = ?,
                    normalized_content = ?,
                    importance = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (content, category, normalized, BASE_IMPORTANCE.get(category, 2), memory_id)
            )
        else:
            cursor = connection.execute(
                """
                UPDATE memories
                SET content = ?,
                    normalized_content = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (content, normalized, memory_id)
            )

        return cursor.rowcount > 0


def forget_memory(keyword):
    keyword = keyword.strip()

    if not keyword:
        return 0

    with connect() as connection:
        cursor = connection.execute(
            "DELETE FROM memories WHERE content LIKE ?",
            (f"%{keyword}%",)
        )

        return cursor.rowcount


def clear_memories():
    with connect() as connection:
        cursor = connection.execute("DELETE FROM memories")
        return cursor.rowcount