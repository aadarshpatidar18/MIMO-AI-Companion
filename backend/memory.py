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


def initialize_memory():
    with connect() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'other',
                normalized_content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                normalized_content
            )
            VALUES (?, ?, ?)
            """,
            (content, category, normalized)
        )

    return True


def get_memories(limit=50):
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, content, category, created_at, updated_at
            FROM memories
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

    return [dict(row) for row in rows]


def search_memory(keyword="", category=None):
    keyword = keyword.strip()

    query = """
        SELECT id, content, category, created_at, updated_at
        FROM memories
        WHERE 1=1
    """

    parameters = []

    if keyword:
        query += " AND content LIKE ?"
        parameters.append(f"%{keyword}%")

    if category and category.lower() in CATEGORIES:
        query += " AND category = ?"
        parameters.append(category.lower())

    query += " ORDER BY id DESC"

    with connect() as connection:
        rows = connection.execute(query, parameters).fetchall()

    return [dict(row) for row in rows]


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
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (content, category, normalized, memory_id)
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