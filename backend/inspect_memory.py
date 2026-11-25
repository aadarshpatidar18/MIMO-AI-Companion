from memory import initialize_memory, get_memories

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