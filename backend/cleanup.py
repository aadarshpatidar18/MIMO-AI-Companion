"""Remove duplicate memories. Run from the repo root: python -m backend.cleanup"""
from .memory import connect


def main():
    with connect() as connection:
        connection.execute("""
            DELETE FROM memories
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM memories
                GROUP BY LOWER(TRIM(content))
            )
        """)
    print("Duplicate memories removed.")


if __name__ == "__main__":
    main()
