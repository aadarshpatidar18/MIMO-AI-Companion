"""Memory tools, so the agent can remember and recall without going through /chat."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .. import memory as memory_mod
from ..core.agent.registry import CONSEQUENTIAL, READ_ONLY, REVERSIBLE, ToolError, ToolRegistry, ToolSpec

CATEGORIES = ("interest", "skill", "goal", "preference", "project", "education", "other")


class _Remember(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=2, max_length=500)
    category: Literal["interest", "skill", "goal", "preference", "project", "education",
                      "other"] = "other"


class _Recall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keyword: str = Field(default="", max_length=120)
    category: Optional[Literal["interest", "skill", "goal", "preference", "project", "education",
                               "other"]] = None
    limit: int = Field(default=25, ge=1, le=100)


class _Forget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keyword: str = Field(min_length=2, max_length=120)


def _remember(p: _Remember) -> dict:
    text = " ".join(p.content.split())
    if memory_mod.save_memory(text, p.category):
        return {"saved": text, "category": p.category}
    raise ToolError("I already remember that.")


def _recall(p: _Recall) -> dict:
    memories = memory_mod.search_memory(p.keyword, p.category)
    rows = [{"content": m["content"], "category": m["category"]} for m in memories[: p.limit]]
    return {"count": len(rows), "memories": rows}


def _forget(p: _Forget) -> dict:
    removed = memory_mod.forget_memory(p.keyword)
    if not removed:
        raise ToolError(f"I found nothing matching '{p.keyword}'.")
    return {"forgotten": removed, "keyword": p.keyword}


def register_memory_tools(registry: ToolRegistry) -> ToolRegistry:
    registry.register(ToolSpec(
        "remember", "Save a fact about the user so it survives restarts.",
        _Remember, _remember, REVERSIBLE))
    registry.register(ToolSpec(
        "recall", "Look up what MIMO remembers, by keyword and/or category.",
        _Recall, _recall, READ_ONLY,
        verify=lambda p, out: isinstance(out, dict) and isinstance(out.get("memories"), list)))
    registry.register(ToolSpec(
        "forget", "Delete remembered facts matching a keyword.",
        _Forget, _forget, CONSEQUENTIAL))
    return registry
