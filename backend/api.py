import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
from uuid import uuid4

from .core.agent import get_manager, shutdown_manager
from .core.agent.routes import router as agent_router
from .core.conversations import CONTENT_MAX, get_store as get_conversations, shutdown_store
from .core.conversations_routes import router as conversations_router
from .core.limits import MAX_AUDIO_BYTES, MAX_JSON_BYTES, MAX_UPLOAD_BYTES, BodySizeLimit
from .core.llm import AllProvidersFailedError
from .core.llm.routes import router as llm_router
from .core.persona_routes import INDEX as WEB_INDEX
from .core.persona_routes import router as persona_router
from .core.security import (AuthGate, current_device, get_service,
                            init_service as init_security, require_scope, shutdown_service)
from .core.security.dispatch import ActionDenied, ActionPolicy
from .core.security.pairing import SlidingWindowLimiter
from .core.security.routes import router as security_router
from .core.voice.routes import router as voice_router
from .intent_rules import detect_memory_category
from .llm import ask_mimo, classify_intent
from .legacy_tools import execute_tool
from .memory import (
    initialize_memory,
    save_memory,
    get_memories,
    search_memory,
    forget_memory,
    set_importance,
    update_memory
)

logger = logging.getLogger("mimo.api")


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _guard_lan_exposure() -> None:
    """Refuse to expose an unauthenticated API to the network.

    The backend is a personal server, and the whole product assumes it: a LAN-reachable MIMO with
    authentication off lets anyone on the Wi-Fi drive the agent. Binding to a non-loopback address
    therefore requires authentication, unless the operator explicitly says they know.
    """
    host = (os.environ.get("MIMO_HOST") or "").strip()
    if not host or host in LOOPBACK_HOSTS:
        return
    if os.environ.get("MIMO_REQUIRE_AUTH", "").strip() in ("1", "true", "yes", "on"):
        return
    if os.environ.get("MIMO_ALLOW_OPEN_LAN", "").strip() in ("1", "true", "yes", "on"):
        logger.warning("MIMO is listening on %s without authentication because "
                       "MIMO_ALLOW_OPEN_LAN is set. Anyone on this network can use it.", host)
        return
    raise RuntimeError(
        f"MIMO_HOST is {host}, so MIMO would be reachable from your network, but "
        "MIMO_REQUIRE_AUTH is off. Set MIMO_REQUIRE_AUTH=1 (pair each device first), or set "
        "MIMO_HOST=127.0.0.1 for this PC only, or set MIMO_ALLOW_OPEN_LAN=1 if you really mean "
        "to run it open on this network."
    )


@asynccontextmanager
async def lifespan(_app):
    _guard_lan_exposure()
    initialize_memory()
    get_manager()          # opens the agent DB and marks tasks interrupted by a restart
    init_security()
    get_conversations()
    yield
    shutdown_manager()
    shutdown_service()
    shutdown_store()


app = FastAPI(
    title="MIMO AI Companion API",
    description="API for the MIMO personal AI companion",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(llm_router)
app.include_router(agent_router)
app.include_router(security_router)
app.include_router(conversations_router)
app.include_router(persona_router)
app.include_router(voice_router)

# Browsers only ever talk to this backend from the local machine; native Android and
# desktop clients are unaffected by CORS. Override with MIMO_CORS_ORIGINS if you serve a web UI.
_origins = [o.strip() for o in os.environ.get("MIMO_CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=None if _origins else r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Added after the CORS layer so a rejected request still gets CORS headers.
app.add_middleware(AuthGate)
# Outermost of the stack: an oversized body is refused before authentication or parsing costs
# anything. The voice route gets its own, larger budget.
app.add_middleware(
    BodySizeLimit,
    default=MAX_JSON_BYTES,
    rules=(("/voice/transcribe", MAX_AUDIO_BYTES + 1024 * 1024),),
)

chat_limiter = SlidingWindowLimiter(limit=60, window_s=60.0)

conversation_history = {}

# One lock per conversation, so two devices talking at once cannot both read the same history and
# then append out of order (which reads as the model answering a message it never saw). Locks are
# kept for the life of the process — bounded by the number of conversations, each a few bytes.
_turn_locks: dict[str, threading.Lock] = {}
_turn_locks_guard = threading.Lock()


def turn_lock(conversation_id: str) -> threading.Lock:
    with _turn_locks_guard:
        lock = _turn_locks.get(conversation_id)
        if lock is None:
            lock = threading.Lock()
            _turn_locks[conversation_id] = lock
        return lock


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"
    # When set, the turn is stored in the shared conversation and the history comes from it.
    conversation_id: Optional[str] = None


class MemoryRequest(BaseModel):
    content: str
    category: str = "other"


class ForgetRequest(BaseModel):
    keyword: str


class MemoryPatch(BaseModel):
    content: Optional[str] = Field(default=None, max_length=500)
    category: Optional[str] = Field(default=None, max_length=20)
    importance: Optional[int] = Field(default=None, ge=1, le=5)


def process_message(message, session_id, history=None, policy=None):
    # Every effect below goes through one policy question, because this function is
    # the place where chat-triggered tools and memory writes actually start.
    policy = policy or ActionPolicy(None, auth_required=False)

    if history is None:
        history = conversation_history.setdefault(session_id, [])

    category = detect_memory_category(message)

    if category:
        policy.require("memory.read")
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
        policy.require("tool.invoke")
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
            policy.require("memory.write")
            saved = save_memory(content, category)

            response = (
                "I'll remember that."
                if saved
                else "I already have that memory stored."
            )

    elif intent == "search_memory":
        policy.require("memory.read")
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
            policy.require("memory.write")
            count = forget_memory(keyword)
            response = f"Forgot {count} matching memories."
        else:
            response = "Please specify what to forget."

    elif intent == "general_question":
        # Personal context is optional here: a device without memory:read still gets
        # an answer, just without stored memories.
        memories = get_memories() if policy.allows("memory.read") else []

        response = ask_mimo(
            message,
            memories=memories,
            history=history
        )

    else:
        response = "I cannot handle that request yet."

    return response, intent


@app.get("/", include_in_schema=False)
def root():
    """The MIMO interface. On a phone it is a chat app; on the laptop it is the full panel."""
    if WEB_INDEX.is_file():
        return FileResponse(WEB_INDEX, media_type="text/html",
                            headers={"Cache-Control": "no-cache"})
    return {"name": "MIMO AI Companion", "status": "running", "version": "1.0.0",
            "detail": "Web interface missing from this build."}


@app.get("/system/capabilities")
def system_capabilities():
    """What MIMO can actually do on this machine right now."""
    from .tools import capability_report
    return capability_report()


@app.get("/info")
def info():
    return {
        "name": "MIMO AI Companion",
        "status": "running",
        "version": "1.1.0",
        "app": "/",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "MIMO Backend"
    }


def _no_model():
    logger.warning("No model available for chat request", exc_info=True)
    raise HTTPException(
        status_code=503,
        detail="No AI model is available. Make sure Ollama is running "
               "(or configure a cloud model)."
    )


def _internal():
    logger.exception("Chat request failed")
    raise HTTPException(
        status_code=500,
        detail="MIMO hit an internal error. Check the backend log."
    )


@app.post("/chat")
def chat(request: ChatRequest, http_request: Request):
    message = request.message.strip()

    if not message:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty."
        )

    if len(message) > CONTENT_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Message is too long (max {CONTENT_MAX} characters)."
        )

    device = current_device(http_request)
    policy = ActionPolicy(device, get_service().store.require_auth())
    if not chat_limiter.allow(device["id"] if device else
                              (getattr(http_request.client, "host", "") or "?")):
        raise HTTPException(status_code=429, detail="Too many messages; wait a moment.")

    session_id = request.session_id or "default"

    # Durable path: the one the apps use. Requires a paired device to write to the
    # shared history, because that history is readable from every other device.
    if request.conversation_id is None and device is not None:
        # A paired device must name its conversation: falling back to a shared
        # in-process default would put two devices into one implicit history.
        raise HTTPException(status_code=400,
                            detail="'conversation_id' is required for a paired device.")

    if request.conversation_id:
        if device is None or "chat:write" not in device["scopes"]:
            raise HTTPException(status_code=401,
                                detail="A paired device with 'chat:write' is required "
                                       "to use a shared conversation.")
        conversations = get_conversations()
        # The whole turn — read history, call the model, append both rows — happens under this
        # conversation's lock. Existence is checked inside it too, so a delete cannot slip between
        # the check and the append.
        with turn_lock(request.conversation_id):
            if conversations.get(request.conversation_id) is None:
                raise HTTPException(status_code=404, detail="Unknown conversation.")
            history = conversations.history(request.conversation_id, limit=10)
            try:
                response, intent = process_message(message, session_id, history=history,
                                                   policy=policy)
            except ActionDenied as denied:
                raise HTTPException(status_code=403, detail=str(denied)) from None
            except AllProvidersFailedError:
                _no_model()
            except Exception:
                _internal()
            try:
                stored = conversations.append_turn(request.conversation_id, message, response,
                                                   device_id=device["id"])
            except Exception:
                _internal()
        if stored is None:
            raise HTTPException(status_code=404, detail="Unknown conversation.")
        return {
            "success": True,
            "session_id": session_id,
            "conversation_id": request.conversation_id,
            "device_id": device["id"],
            "intent": intent,
            "response": response,
            # The ids the store just assigned to both rows. Clients need them to reconcile their
            # own optimistic copy of this turn without pulling the whole conversation and guessing
            # which message is which.
            "user_message_id": stored[0],
            "assistant_message_id": stored[1],
            "created_at": (conversations.get(request.conversation_id) or {}).get("updated_at")
        }

    try:
        response, intent = process_message(message, session_id, policy=policy)

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

    except ActionDenied as denied:
        raise HTTPException(status_code=403, detail=str(denied)) from None

    except AllProvidersFailedError:
        _no_model()

    except Exception:
        _internal()


@app.get("/memory")
def read_memory(
    keyword: str = "",
    category: Optional[str] = None,
    _: Optional[dict] = Depends(require_scope("memory:read", allow_unpaired=True))
):
    memories = search_memory(keyword, category)

    return {
        "success": True,
        "count": len(memories),
        "memories": memories
    }


@app.post("/memory")
def create_memory(request: MemoryRequest,
                  _: Optional[dict] = Depends(require_scope("memory:write", allow_unpaired=True))):
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


@app.put("/memory/{memory_id}")
def correct_memory(memory_id: int, request: MemoryPatch,
                   _: Optional[dict] = Depends(require_scope("memory:write", allow_unpaired=True))):
    """Correct a remembered fact: its wording, its category, or how much it matters."""
    if not any(m["id"] == memory_id for m in get_memories(1000)):
        raise HTTPException(status_code=404, detail="Unknown memory.")
    if request.content is not None or request.category is not None:
        ok = update_memory(memory_id, request.content or "", request.category)
        if not ok and request.content:
            raise HTTPException(status_code=400,
                                detail="That memory could not be updated: it is empty or "
                                       "duplicates another one.")
    if request.importance is not None and not set_importance(memory_id, request.importance):
        raise HTTPException(status_code=404, detail="Unknown memory.")
    row = next((m for m in get_memories(500) if m["id"] == memory_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown memory.")
    return {"success": True, "memory": row}


@app.delete("/memory")
def delete_memory(request: ForgetRequest,
                  _: Optional[dict] = Depends(require_scope("memory:write", allow_unpaired=True))):
    count = forget_memory(request.keyword)

    return {
        "success": True,
        "deleted": count
    }