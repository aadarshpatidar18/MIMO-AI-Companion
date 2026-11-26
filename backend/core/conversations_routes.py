"""HTTP API for durable conversations. Mounted in backend/api.py."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .conversations import CONTENT_MAX, get_store
from .security.gate import current_device, require_scope

router = APIRouter(prefix="/conversations", tags=["conversations"])


class NewConversation(BaseModel):
    title: str = Field(default="", max_length=120)


class TitleBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class NewMessage(BaseModel):
    role: Literal["user", "assistant"] = "user"
    content: str = Field(min_length=1, max_length=CONTENT_MAX)


def _must_exist(conversation_id: str) -> dict:
    conversation = get_store().get(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Unknown conversation.")
    return conversation


@router.post("", status_code=201)
def create_conversation(body: NewConversation | None = None,
                        device: dict = Depends(require_scope("chat:write"))) -> dict:
    body = body or NewConversation()
    return get_store().create(body.title, device_id=device["id"])


@router.get("")
def list_conversations(limit: int = Query(50, ge=1, le=200),
                       include_archived: bool = False,
                       _: dict = Depends(require_scope("chat:read"))) -> dict:
    conversations = get_store().list(limit, include_archived)
    return {"conversations": conversations, "count": len(conversations)}


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str,
                     _: dict = Depends(require_scope("chat:read"))) -> dict:
    return _must_exist(conversation_id)


@router.patch("/{conversation_id}")
def rename_conversation(conversation_id: str, body: TitleBody,
                        _: dict = Depends(require_scope("chat:write"))) -> dict:
    _must_exist(conversation_id)
    if not get_store().rename(conversation_id, body.title):
        raise HTTPException(status_code=400, detail="Title cannot be empty.")
    return get_store().get(conversation_id)


@router.delete("/{conversation_id}")
def delete_conversation(conversation_id: str,
                        _: dict = Depends(require_scope("chat:write"))) -> dict:
    _must_exist(conversation_id)
    get_store().delete(conversation_id)
    return {"deleted": conversation_id}


@router.get("/{conversation_id}/messages")
def read_messages(conversation_id: str, after_id: int = 0,
                  limit: int = Query(200, ge=1, le=500),
                  _: dict = Depends(require_scope("chat:read"))) -> dict:
    _must_exist(conversation_id)
    messages = get_store().messages(conversation_id, after_id, limit)
    return {"messages": messages, "count": len(messages),
            "next_after_id": messages[-1]["id"] if messages else after_id}


@router.post("/{conversation_id}/messages", status_code=201)
def append_message(conversation_id: str, body: NewMessage,
                   device: dict = Depends(require_scope("chat:write"))) -> dict:
    _must_exist(conversation_id)
    try:
        message_id = get_store().append(conversation_id, body.role, body.content, device["id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": message_id, "conversation_id": conversation_id}
