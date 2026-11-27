"""HTTP API for the agent engine. Mounted in backend/api.py."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..security.gate import require_scope
from . import get_manager, get_policy, get_registry
from .manager import TaskManager
from .policy import AutonomyPolicy
from .registry import ToolRegistry

router = APIRouter(prefix="/agent", tags=["agent"])


class TaskBody(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="default", max_length=64)
    agent: Optional[str] = Field(default=None, max_length=32,
                                 description="force a specialist, e.g. 'files'; empty = MIMO chooses")


class ConfirmBody(BaseModel):
    approve: bool
    # Which step the user was looking at. Supplying it means a late tap on an old prompt cannot
    # approve the step that happens to be waiting now.
    step_index: Optional[int] = Field(default=None, ge=0)


class PolicyBody(BaseModel):
    max_auto_level: int = Field(ge=1, le=2)       # level 3 can never be auto-approved
    deny: list[str] = Field(default_factory=list, max_length=50)


def manager_dep() -> TaskManager:
    return get_manager()


@router.post("/tasks", status_code=202)
def create_task(body: TaskBody, m: TaskManager = Depends(manager_dep),
                _: Optional[dict] = Depends(require_scope("agent:run", allow_unpaired=True))) -> dict:
    goal = body.goal.strip()
    if not goal:
        raise HTTPException(status_code=400, detail="Goal cannot be empty.")
    if body.agent and (m.roster is None or m.roster.resolve(body.agent) is None):
        raise HTTPException(status_code=400, detail=f"Unknown agent '{body.agent}'.")
    task_id = m.submit(goal, body.session_id, agent=body.agent)
    return {"id": task_id, "status": "queued",
            "agent": body.agent or (m.roster.select(goal).key if m.roster else None)}


@router.get("/tasks")
def list_tasks(limit: int = Query(50, ge=1, le=200), m: TaskManager = Depends(manager_dep),
               _: Optional[dict] = Depends(require_scope("agent:run", allow_unpaired=True))) -> dict:
    return {"tasks": m.store.list_tasks(limit)}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, m: TaskManager = Depends(manager_dep),
             _: Optional[dict] = Depends(require_scope("agent:run", allow_unpaired=True))) -> dict:
    task = m.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Unknown task.")
    return task


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str, m: TaskManager = Depends(manager_dep),
                _: Optional[dict] = Depends(require_scope("agent:control", allow_unpaired=True))) -> dict:
    if m.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Unknown task.")
    return {"cancelling": m.cancel(task_id)}      # False = it had already finished


@router.post("/tasks/{task_id}/confirm")
def confirm_task(task_id: str, body: ConfirmBody, m: TaskManager = Depends(manager_dep),
                 _: Optional[dict] = Depends(require_scope("agent:control", allow_unpaired=True))) -> dict:
    if m.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Unknown task.")
    if not m.confirm(task_id, body.approve, step_index=body.step_index):
        raise HTTPException(
            status_code=409,
            detail="This task is not waiting for that confirmation — it may have timed out, "
                   "moved on, or the step you answered is no longer the current one.",
        )
    return {"approved": body.approve}


@router.get("/roster")
def list_roster(m: TaskManager = Depends(manager_dep),
                _: Optional[dict] = Depends(require_scope("agent:run", allow_unpaired=True))) -> dict:
    """The specialists MIMO can hand a goal to, and the roles it deliberately does not have."""
    if m.roster is None:
        return {"agents": [], "reserved": {}}
    from .roster import RESERVED
    return {"agents": m.roster.describe(), "reserved": RESERVED}


@router.get("/tools")
def list_tools(reg: ToolRegistry = Depends(get_registry),
               _: Optional[dict] = Depends(require_scope("agent:run", allow_unpaired=True))) -> dict:
    return {"tools": reg.catalog()}


@router.get("/actions")
def list_actions(task_id: Optional[str] = None, limit: int = Query(100, ge=1, le=500),
                 m: TaskManager = Depends(manager_dep),
                 _: Optional[dict] = Depends(require_scope("agent:run", allow_unpaired=True))) -> dict:
    return {"actions": m.store.list_actions(limit, task_id)}


@router.get("/policy")
def read_policy(p: AutonomyPolicy = Depends(get_policy),
                _: Optional[dict] = Depends(require_scope("agent:run", allow_unpaired=True))) -> dict:
    return p.to_dict()


@router.put("/policy")
def write_policy(body: PolicyBody, m: TaskManager = Depends(manager_dep),
                 p: AutonomyPolicy = Depends(get_policy), reg: ToolRegistry = Depends(get_registry),
                 _: Optional[dict] = Depends(require_scope("agent:control", allow_unpaired=True))) -> dict:
    unknown = [n for n in body.deny if reg.get(n) is None]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown tool(s): {', '.join(unknown)}")
    p.max_auto_level, p.deny = body.max_auto_level, set(body.deny)
    m.store.set_setting("policy", p.to_dict())
    return p.to_dict()
