import json
from llm import call_ollama

PLANNER_PROMPT = """
You are MIMO's task planner.

Available tools:
- get_time
- get_date
- calculate
- open_website
- open_app

Break the user's request into ordered steps.

Return JSON in this format:

{
    "steps": [
        {
            "tool": "get_time",
            "parameters": {}
        }
    ]
}

Rules:
- Use only available tools.
- Never invent tool names.
- If the request requires general knowledge, return an empty steps list.
- Do not claim that any action has been executed.
- Keep plans simple.
"""

def create_plan(command):
    messages = [
        {
            "role": "system",
            "content": PLANNER_PROMPT
        },
        {
            "role": "user",
            "content": command
        }
    ]

    result = call_ollama(messages, json_mode=True)

    return json.loads(result)