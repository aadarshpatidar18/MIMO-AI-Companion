import requests
import json

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5:1.5b"

SYSTEM_PROMPT = """
You are MIMO, a personal AI companion.

You are being developed as a personal AI project.

You can:
- Answer questions.
- Explain concepts.
- Have conversations.
- Use information explicitly stored in user memory.

Never invent personal information.
Never claim an action was completed unless the application confirms it.

When answering questions about the user:
- Use the supplied memory as evidence.
- Do not invent interests, skills, goals or experiences.
- Clearly distinguish known information from reasonable suggestions.
- If the memory does not contain the answer, admit that you do not know.

Be concise, accurate and friendly.
"""


def call_ollama(messages, json_mode=False):
    payload = {
        "model": MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0
        }
    }

    if json_mode:
        payload["format"] = "json"

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=120
    )

    response.raise_for_status()

    return response.json()["message"]["content"]


def classify_intent(prompt):
    classification_prompt = f"""
Classify the user's request into exactly one intent.

Available intents:

get_time
get_date
calculate
open_website
open_app
save_memory
search_memory
forget_memory
general_question
unknown

Return a JSON object with:
intent
parameters

Rules:

get_time:
The user asks for the actual current clock time.

get_date:
The user asks for today's date.

calculate:
The user requests a mathematical calculation.
Extract the expression.

open_website:
The user asks to open a website.
Supported examples: youtube, google, github.

open_app:
The user asks to launch an application.

save_memory:
The user explicitly asks MIMO to remember something.
Extract the complete statement.
Also assign one category:
interest, skill, goal, preference, project, education, other.

search_memory:
The user asks what MIMO remembers.
Extract a keyword and optional category.
Use an empty keyword when asking about all memories.

forget_memory:
The user asks MIMO to forget information.
Extract the specific keyword.

general_question:
The user asks a normal informational or conversational question.

unknown:
The request is unclear or unsupported.

Important:
Do not classify a question about time complexity as get_time.
Do not classify time dilation as get_time.
Do not classify an explanation request as a tool action.
Do not remove the subject from a memory statement.
Do not invent information.

Examples:

Input: What time is it?
Output: {{"intent":"get_time","parameters":{{}}}}

Input: What is time complexity?
Output: {{"intent":"general_question","parameters":{{}}}}

Input: Remember that I like robotics.
Output: {{"intent":"save_memory","parameters":{{"content":"I like robotics","category":"interest"}}}}

Input: Remember that I am learning Python.
Output: {{"intent":"save_memory","parameters":{{"content":"I am learning Python","category":"skill"}}}}

Input: Remember that my goal is to become a robotics engineer.
Output: {{"intent":"save_memory","parameters":{{"content":"My goal is to become a robotics engineer","category":"goal"}}}}

Input: What do you remember about me?
Output: {{"intent":"search_memory","parameters":{{"keyword":"","category":null}}}}

Input: What are my learning interests?
Output: {{"intent":"search_memory","parameters":{{"keyword":"","category":"interest"}}}}

Input: What do you remember about robotics?
Output: {{"intent":"search_memory","parameters":{{"keyword":"robotics","category":null}}}}

Input: Forget that I like robotics.
Output: {{"intent":"forget_memory","parameters":{{"keyword":"I like robotics"}}}}

Input: Calculate 25 multiplied by 35.
Output: {{"intent":"calculate","parameters":{{"expression":"25 * 35"}}}}

Input: Open YouTube.
Output: {{"intent":"open_website","parameters":{{"url":"youtube"}}}}

Input: Explain artificial intelligence.
Output: {{"intent":"general_question","parameters":{{}}}}

Return only valid JSON.

User request: {prompt}
"""

    result = call_ollama(
        [{"role": "user", "content": classification_prompt}],
        json_mode=True
    )

    classification = json.loads(result)

    allowed_intents = {
        "get_time",
        "get_date",
        "calculate",
        "open_website",
        "open_app",
        "save_memory",
        "search_memory",
        "forget_memory",
        "general_question",
        "unknown"
    }

    if classification.get("intent") not in allowed_intents:
        return {
            "intent": "unknown",
            "parameters": {}
        }

    if not isinstance(classification.get("parameters"), dict):
        return {
            "intent": "unknown",
            "parameters": {}
        }

    return classification


def ask_mimo(prompt, memories=None, history=None):
    memory_context = ""

    if memories:
        memory_context = "\n".join(
            f"- [{memory.get('category', 'other')}] {memory['content']}"
            for memory in memories
        )

    system_prompt = SYSTEM_PROMPT + f"""

USER MEMORY:

{memory_context if memory_context else "No saved memories available."}

MEMORY RULES:
- Use these memories when answering personal questions.
- Treat them as facts explicitly saved by the user.
- Never invent additional personal information.
- If the information is missing, say so.
"""

    messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]

    if history:
        messages.extend(history[-10:])

    messages.append({
        "role": "user",
        "content": prompt
    })

    return call_ollama(messages)