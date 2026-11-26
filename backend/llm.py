import json
import os

from .core.llm import LLMRequest, Message, get_router
from .core.persona import current as current_persona
from .core.persona import system_prompt as persona_system_prompt

def memory_to_cloud_allowed():
    """Personal memories are only sent to a cloud model if the user opts in."""
    return os.environ.get("MIMO_ALLOW_MEMORY_TO_CLOUD", "").strip().lower() in (
        "1", "true", "yes", "on"
    )


def call_llm(messages, json_mode=False, task="chat", allow_cloud=True):
    """Send chat messages through the model router (Ollama / Gemini).

    task selects the per-task route (intent, plan, chat, ...). allow_cloud=False
    guarantees the prompt never leaves this machine.
    """
    request = LLMRequest(
        messages=[Message(m["role"], m["content"]) for m in messages],
        task=task,
        temperature=0,
        json_mode=json_mode,
        allow_cloud=allow_cloud,
    )
    return get_router().generate(request).text


# Backwards-compatible name used by older code.
call_ollama = call_llm


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

    result = call_llm(
        [{"role": "user", "content": classification_prompt}],
        json_mode=True,
        task="intent"
    )

    try:
        classification = json.loads(result)
    except ValueError:
        return {"intent": "unknown", "parameters": {}}

    if not isinstance(classification, dict):
        return {"intent": "unknown", "parameters": {}}

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
    # The character lives in core/persona.py so the UI, the CLI and the phone agree.
    system_prompt = persona_system_prompt(current_persona(), memories or [])

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

    # The system prompt embeds the user's memories, so keep that call on this
    # machine unless the user explicitly allowed memories to reach the cloud.
    return call_llm(
        messages,
        task="chat",
        allow_cloud=(not memories) or memory_to_cloud_allowed()
    )