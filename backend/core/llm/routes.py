"""FastAPI routes for inspecting and controlling the model layer.

Wire up with two lines in backend/api.py:

    from backend.core.llm.routes import router as llm_router
    app.include_router(llm_router)

No endpoint ever returns an API key - only whether one is configured.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..security.gate import require_scope
from . import get_router
from .base import LLMRequest
from .config import MODEL_RE, PROVIDER_RE, TASK_RE, Target
from .errors import AllProvidersFailedError, LLMError
from .router import ModelRouter

router = APIRouter(prefix="/llm", tags=["llm"])


def router_dep() -> ModelRouter:
    return get_router()


class SelectionBody(BaseModel):
    provider: str = Field(pattern=PROVIDER_RE.pattern)
    fallback_to_local: Optional[bool] = None


class TargetBody(BaseModel):
    provider: str = Field(pattern=PROVIDER_RE.pattern)
    model: Optional[str] = Field(default=None, pattern=MODEL_RE.pattern)


class TaskRouteBody(BaseModel):
    targets: list[TargetBody] = Field(min_length=1, max_length=5)
    local_only: bool = False


class TestBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    task: str = Field(default="chat", pattern=TASK_RE.pattern)
    provider: Optional[str] = Field(default=None, pattern=PROVIDER_RE.pattern)
    allow_cloud: bool = True


@router.get("/status")
def status(live: bool = True, r: ModelRouter = Depends(router_dep),
           _: Optional[dict] = Depends(require_scope("device:read", allow_unpaired=True))) -> dict:
    return r.status(live=live)


@router.get("/usage")
def usage(recent: int = Query(0, ge=0, le=200), r: ModelRouter = Depends(router_dep),
          _: Optional[dict] = Depends(require_scope("device:read", allow_unpaired=True))) -> dict:
    out: dict = {"today": r.tracker.summary(),
                 "note": "'today' = Pacific-time quota day (rolling 24h if tz data is missing). "
                         "Provider-side quotas are authoritative; see Google AI Studio."}
    if recent:
        out["recent"] = r.tracker.recent(recent)
    return out


@router.put("/selection")
def set_selection(body: SelectionBody, r: ModelRouter = Depends(router_dep),
                  _: Optional[dict] = Depends(require_scope("device:manage", allow_unpaired=True))) -> dict:
    try:
        r.set_selection(body.provider, body.fallback_to_local)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return r.status(live=False)


@router.put("/tasks/{task}")
def set_task(task: str, body: TaskRouteBody, r: ModelRouter = Depends(router_dep),
             _: Optional[dict] = Depends(require_scope("device:manage", allow_unpaired=True))) -> dict:
    if not TASK_RE.match(task):
        raise HTTPException(status_code=422, detail="invalid task name")
    try:
        r.set_task_route(task, [Target(t.provider, t.model) for t in body.targets], body.local_only)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return r.status(live=False)


@router.post("/cooldowns/clear")
def clear_cooldowns(r: ModelRouter = Depends(router_dep),
                    _: Optional[dict] = Depends(require_scope("device:manage", allow_unpaired=True))) -> dict:
    r.tracker.clear_cooldown()
    return {"cleared": True}


@router.post("/test")
def test(body: TestBody, r: ModelRouter = Depends(router_dep),
         _: Optional[dict] = Depends(require_scope("device:manage", allow_unpaired=True))) -> dict:
    """Send a prompt through the router and report which model answered and why."""
    try:
        resp = r.generate(LLMRequest.from_prompt(
            body.prompt, task=body.task, provider=body.provider,
            allow_cloud=body.allow_cloud, max_tokens=256))
    except AllProvidersFailedError as e:
        raise HTTPException(status_code=503, detail={
            "error": "no_model_available", "message": str(e),
            "attempts": [a.__dict__ for a in e.attempts]})
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"text": resp.text, "provider": resp.provider, "model": resp.model,
            "fell_back": resp.fell_back, "latency_ms": resp.latency_ms,
            "attempts": [a.__dict__ for a in resp.attempts]}
