from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from uuid import uuid4

from .llm import ask_mimo, classify_intent
from .tools import execute_tool
from .memory import (
    initialize_memory,
    save_memory,
    get_memories,
    search_memory,
    forget_memory
)

app = FastAPI(
    title="MIMO AI Companion API",
    description="API for the MIMO personal AI companion",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)

conversation_history = {}

initialize_memory()


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"


class MemoryRequest(BaseModel):
    content: str
    category: str = "other"


class ForgetRequest(BaseModel):
    keyword: str


def detect_memory_category(message):
    text = message.lower()

    category_rules = {
        "interest": [
            "interest",
            "interests",
            "hobby",
            "hobbies"
        ],
        "skill": [
            "skill",
            "skills",
            "learning",
            "learn"
        ],
        "goal": [
            "goal",
            "goals",
            "ambition",
            "ambitions"
        ],
        "project": [
            "project",
            "projects"
        ],
        "preference": [
            "preference",
            "preferences"
        ],
        "education": [
            "education",
            "academic"
        ]
    }

    personal_question = (
        "my " in text
        or "about me" in text
        or "do you remember" in text
    )

    if not personal_question:
        return None

    for category, keywords in category_rules.items():
        if any(word in text for word in keywords):
            return category

    return None


def process_message(message, session_id):
    history = conversation_history.setdefault(session_id, [])

    category = detect_memory_category(message)

    if category:
        memories = search_memory("", category)

        if memories:
            response = "Here's what I remember:\n"
            response += "\n".join(
                f"- [{memory['category']}] {memory['content']}"
                for memory in memories
            )
        else:
            response = "I couldn't find any memories in that category."

        return response, "search_memory"

    classification = classify_intent(message)

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

        if not result["success"]:
            return str(result["result"]), intent

        response = str(result["result"])

    elif intent == "save_memory":
        content = parameters.get("content")
        category = parameters.get("category", "other")

        if not isinstance(content, str) or not content.strip():
            response = "Please tell me what to remember."
        else:
            saved = save_memory(content, category)

            response = (
                "I'll remember that."
                if saved
                else "I already have that memory stored."
            )

    elif intent == "search_memory":
        keyword = parameters.get("keyword", "")
        category = parameters.get("category")

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
            message,
            memories=memories,
            history=history
        )

    else:
        response = "I cannot handle that request yet."

    return response, intent


@app.get("/")
def root():
    return {
        "name": "MIMO AI Companion",
        "status": "running",
        "version": "1.0.0"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "MIMO Backend"
    }


@app.post("/chat")
def chat(request: ChatRequest):
    message = request.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty."
        )

    session_id = request.session_id or "default"

    try:
        response, intent = process_message(message, session_id)

        history = conversation_history.setdefault(session_id, [])

        history.extend([
            {
                "role": "user",
                "content": message
            },
            {
                "role": "assistant",
                "content": response
            }
        ])

        conversation_history[session_id] = history[-10:]

        return {
            "success": True,
            "session_id": session_id,
            "intent": intent,
            "response": response
        }

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error)
        )


@app.get("/memory")
def read_memory(
    keyword: str = "",
    category: Optional[str] = None
):
    memories = search_memory(keyword, category)

    return {
        "success": True,
        "count": len(memories),
        "memories": memories
    }


@app.post("/memory")
def create_memory(request: MemoryRequest):
    if not request.content.strip():
        raise HTTPException(
            status_code=400,
            detail="Memory content cannot be empty."
        )

    saved = save_memory(
        request.content,
        request.category
    )

    return {
        "success": True,
        "saved": saved,
        "message": (
            "Memory saved."
            if saved
            else "Memory already exists."
        )
    }


@app.delete("/memory")
def delete_memory(request: ForgetRequest):
    count = forget_memory(request.keyword)

    return {
        "success": True,
        "deleted": count
    }