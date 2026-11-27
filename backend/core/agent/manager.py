"""Runs agent tasks in the background with cancel, confirmation, timeout and persistence."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

from .engine import AgentEngine, RunContext, StepRecord, TaskCancelled, TaskTimedOut
from .planner import Plan
from .store import AgentStore, TERMINAL

log = logging.getLogger("mimo.agent")


@dataclass
class _Live:
    cancel: threading.Event = field(default_factory=threading.Event)
    answered: threading.Event = field(default_factory=threading.Event)
    approved: bool = False
    awaiting: bool = False
    deadline: float = 0.0
    cancel_reason: str = ""
    # Which step is waiting for a decision. A reply that names a different one is refused, so a
    # late tap cannot approve the *next* consequential step by accident.
    pending_index: Optional[int] = None
    pending_since: float = 0.0


class _TaskContext(RunContext):
    def __init__(self, mgr: "TaskManager", task_id: str, live: _Live):
        self.mgr, self.task_id, self.live = mgr, task_id, live

    def check(self) -> None:
        if self.live.cancel.is_set():
            raise TaskCancelled()
        if time.monotonic() > self.live.deadline:
            raise TaskTimedOut()

    def set_status(self, status: str) -> None:
        self.mgr.store.update_task(self.task_id, status=status)

    def on_plan(self, plan: Plan) -> None:
        self.mgr.store.update_task(self.task_id, plan=[s.model_dump() for s in plan.steps],
                                   mode="action" if plan.steps else "answer")

    def on_steps(self, steps: list[StepRecord]) -> None:
        self.mgr.store.update_task(self.task_id, steps=[s.to_dict() for s in steps])

    def audit(self, step: StepRecord) -> None:
        self.mgr.store.log_action(
            task_id=self.task_id, step_index=step.index, tool=step.tool, args=step.args, level=step.level,
            decision=step.decision, outcome=step.status, verified=step.verified,
            duration_ms=step.duration_ms, detail=step.error or step.output)

    def confirm(self, step: StepRecord) -> bool:
        live, started = self.live, time.monotonic()
        live.answered.clear()
        live.pending_index = step.index
        live.pending_since = started
        live.awaiting = True
        self.mgr.store.update_task(self.task_id, status="awaiting_confirmation",
                                   pending={"index": step.index, "tool": step.tool, "args": step.args,
                                            "level": step.level})
        try:
            while not live.answered.wait(0.1):
                if live.cancel.is_set():
                    raise TaskCancelled()
                if time.monotonic() - started > self.mgr.confirm_timeout:
                    return False                       # no answer = no
            return live.approved
        finally:
            live.awaiting = False
            live.deadline += time.monotonic() - started   # waiting for the human is not task time
            self.mgr.store.update_task(self.task_id, status="running", pending=None)


class TaskManager:
    def __init__(self, engine: AgentEngine, store: AgentStore, max_workers: int = 2,
                 task_timeout: float = 120.0, confirm_timeout: float = 300.0,
                 roster: Optional["Roster"] = None):
        self.engine, self.store, self.roster = engine, store, roster
        self.task_timeout, self.confirm_timeout = task_timeout, confirm_timeout
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="mimo-task")
        self._live: dict[str, _Live] = {}
        self._lock = threading.Lock()

    def recover(self) -> int:
        n = self.store.recover_interrupted()
        if n:
            log.warning("Marked %d interrupted agent task(s) as failed", n)
        return n

    def submit(self, goal: str, session_id: str = "default", agent: Optional[str] = None) -> str:
        task_id = uuid.uuid4().hex[:12]
        self.store.create_task(task_id, goal, session_id)
        with self._lock:
            self._live[task_id] = _Live()
        self._pool.submit(self._run, task_id, goal, agent)
        return task_id

    def _choose(self, goal: str, agent: Optional[str]) -> tuple[str, AgentEngine]:
        """Which specialist handles this goal, and the engine that owns its tools."""
        if self.roster is None:
            return "", self.engine
        profile = self.roster.resolve(agent) if agent else None
        profile = profile or self.roster.select(goal)
        return profile.key, self.roster.engine_for(profile.key)

    def _run(self, task_id: str, goal: str, agent: Optional[str] = None) -> None:
        live = self._live[task_id]
        live.deadline = time.monotonic() + self.task_timeout
        try:
            if live.cancel.is_set():
                raise TaskCancelled()
            agent_key, engine = self._choose(goal, agent)
            if agent_key:
                self.store.update_task(task_id, agent=agent_key)
            res = engine.run(goal, _TaskContext(self, task_id, live))
            self.store.update_task(task_id, status=res.status, mode=res.mode, answer=res.text or None,
                                   error=res.error or None, pending=None,
                                   steps=[s.to_dict() for s in res.steps] or None)
        except TaskCancelled:
            self.store.update_task(task_id, status="cancelled", pending=None,
                                   error=live.cancel_reason or "Cancelled by user")
        except TaskTimedOut:
            self.store.update_task(task_id, status="timed_out", pending=None,
                                   error=f"Task exceeded {self.task_timeout:g}s")
        except Exception:
            log.exception("Task %s crashed", task_id)
            self.store.update_task(task_id, status="failed", pending=None,
                                   error="MIMO hit an internal error. Check the backend log.")
        finally:
            with self._lock:
                self._live.pop(task_id, None)

    # ---- user controls ----
    def get(self, task_id: str) -> Optional[dict]:
        return self.store.get_task(task_id)

    def cancel(self, task_id: str) -> bool:
        """True if a running task was signalled; False if unknown or already finished."""
        with self._lock:
            live = self._live.get(task_id)
        if live is None:
            return False
        live.cancel.set()
        return True

    def confirm(self, task_id: str, approve: bool,
                step_index: Optional[int] = None) -> bool:
        """Answer a pending confirmation.

        Returns False when nothing is waiting **or** when [step_index] names a different step than
        the one actually paused — a decision made about step 3 must not approve step 4, which is
        what happens when a user taps a stale button. A reply that arrives after the engine's own
        deadline is refused for the same reason.
        """
        with self._lock:
            live = self._live.get(task_id)
            if live is None or not live.awaiting:
                return False
            if step_index is not None and live.pending_index is not None \
                    and step_index != live.pending_index:
                return False
            if live.pending_since and time.monotonic() - live.pending_since > self.confirm_timeout:
                return False
            live.approved = approve
            live.answered.set()
            return True

    def shutdown(self) -> None:
        with self._lock:
            for live in self._live.values():
                live.cancel_reason = "Backend shutting down"
                live.cancel.set()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self.engine.shutdown()
