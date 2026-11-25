from memory import connect

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