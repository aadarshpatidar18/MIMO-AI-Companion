"""Print stored memories. Run from the repo root: python -m backend.inspect_memory"""
from .memory import initialize_memory, get_memories


def main():
    initialize_memory()
    memories = get_memories()

    print("\nMIMO MEMORY DATABASE\n")

    if not memories:
        print("No memories found.")

    for memory in memories:
        print(f"ID: {memory['id']}")
        print(f"Category: {memory['category']}")
        print(f"Content: {memory['content']}")
        print(f"Created: {memory['created_at']}")
        print("-" * 40)


if __name__ == "__main__":
    main()
