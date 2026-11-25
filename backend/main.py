from llm import ask_mimo, classify_intent
from tools import execute_tool
from memory import (
    initialize_memory,
    save_memory,
    get_memories,
    search_memory,
    forget_memory
)

initialize_memory()

conversation_history = []

print("MIMO Agent is starting...")
print("Type 'exit' to stop.")
print("Type 'memories' to inspect stored memories.")

while True:
    command = input("\nYou: ").strip()

    if not command:
        continue

    if command.lower() in ["exit", "quit"]:
        print("\nMIMO: See you again.")
        break

    if command.lower() == "memories":
        memories = get_memories()

        if memories:
            print("\nMIMO Memory Database:")

            for memory in memories:
                print(
                    f"[{memory['id']}] "
                    f"[{memory['category']}] "
                    f"{memory['content']}"
                )
        else:
            print("\nMIMO: No memories stored.")

        continue

    try:
        classification = classify_intent(command)

        intent = classification.get("intent")
        parameters = classification.get("parameters", {})

        if intent in [
            "get_time",
            "get_date",
            "calculate",
            "open_website",
            "open_app"
        ]:
            result = execute_tool(intent, parameters)
            response = str(result["result"])

        elif intent == "save_memory":
            content = parameters.get("content")
            category = parameters.get("category", "other")

            if isinstance(content, str) and content.strip():
                saved = save_memory(content, category)

                response = (
                    "I'll remember that."
                    if saved
                    else "I already have that memory stored."
                )
            else:
                response = "Please tell me what to remember."

        elif intent == "search_memory":
            keyword = parameters.get("keyword", "")
            lower_command = command.lower()

            category_rules = {
                "interest": ["interest", "interests"],
                "skill": ["skill", "skills", "learning"],
                "goal": ["goal", "goals", "ambition", "ambitions"],
                "project": ["project", "projects"],
                "preference": ["preference", "preferences"],
                "education": ["education", "academic"]
            }

            category = parameters.get("category")

            for category_name, keywords in category_rules.items():
                if any(word in lower_command for word in keywords):
                    category = category_name
                    break

            memories = search_memory(keyword, category)

            if memories:
                response = "Here's what I remember:\n"
                response += "\n".join(
                    f"- [{memory['category']}] {memory['content']}"
                    for memory in memories
                )
            else:
                response = "I couldn't find a matching memory."

        elif intent == "forget_memory":
            keyword = parameters.get("keyword", "")

            if keyword:
                count = forget_memory(keyword)
                response = f"Forgot {count} matching memories."
            else:
                response = "Please specify what to forget."

        elif intent == "general_question":
            memories = get_memories()

            response = ask_mimo(
                command,
                memories=memories,
                history=conversation_history
            )

        else:
            response = "I cannot handle that request yet."

        print("\nMIMO:", response)

        conversation_history.append({
            "role": "user",
            "content": command
        })

        conversation_history.append({
            "role": "assistant",
            "content": response
        })

        conversation_history = conversation_history[-10:]

    except Exception as error:
        print("\nMIMO: Something went wrong:", error)