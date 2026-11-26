"""MIMO agent engine: plan -> validate -> policy -> execute -> verify -> recover."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

from ..llm.config import REPO_ROOT
from .builtin import register_builtin_tools
from .engine import AgentEngine, EngineResult, RunContext, StepRecord
from .manager import TaskManager
from .planner import AgentPlanner, Plan, PlanError
from .roster import ROSTER, AgentProfile, Roster
from .policy import AutonomyPolicy
from .registry import (CONSEQUENTIAL, READ_ONLY, REVERSIBLE, ToolError, ToolRegistry, ToolSpec)
from .store import AgentStore

__all__ = ["AgentEngine", "AgentPlanner", "AgentStore", "AutonomyPolicy", "EngineResult", "Plan",
           "PlanError", "Roster", "RunContext", "StepRecord", "TaskManager", "ToolError", "ToolRegistry",
           "ToolSpec", "READ_ONLY", "REVERSIBLE", "CONSEQUENTIAL", "build_manager", "get_manager",
           "get_registry", "get_policy", "shutdown_manager"]

_manager: Optional[TaskManager] = None
_registry: Optional[ToolRegistry] = None
_policy: Optional[AutonomyPolicy] = None
_lock = threading.Lock()


def build_manager(data_dir: Optional[Path] = None) -> TaskManager:
    global _registry, _policy
    from ...llm import ask_mimo, call_llm          # late import: avoids a cycle with backend.llm
    from ...memory import get_memories

    data = Path(data_dir or os.environ.get("MIMO_DATA_DIR", REPO_ROOT / "data"))
    store = AgentStore(data / "agent.db")
    saved = store.get_setting("policy") or {}
    _policy = AutonomyPolicy(max_auto_level=saved.get("max_auto_level", 2),
                             deny=set(saved.get("deny", [])))
    from ...tools import register_operator_tools
    _registry = register_operator_tools(register_builtin_tools(ToolRegistry()))
    planner = AgentPlanner(_registry, lambda msgs: call_llm(msgs, json_mode=True, task="plan"))
    engine = AgentEngine(_registry, planner, _policy,
                         answerer=lambda goal: ask_mimo(goal, memories=get_memories()))
    roster = Roster(_registry, _policy, lambda msgs: call_llm(msgs, json_mode=True, task="plan"),
                    answerer=lambda goal: ask_mimo(goal, memories=get_memories()))
    manager = TaskManager(engine, store, roster=roster)
    manager.recover()
    return manager


def get_manager() -> TaskManager:
    global _manager
    with _lock:
        if _manager is None:
            _manager = build_manager()
        return _manager


def get_registry() -> ToolRegistry:
    get_manager()
    return _registry          # type: ignore[return-value]


def get_policy() -> AutonomyPolicy:
    get_manager()
    return _policy            # type: ignore[return-value]


def shutdown_manager() -> None:
    global _manager
    with _lock:
        if _manager is not None:
            _manager.shutdown()
            _manager = None
