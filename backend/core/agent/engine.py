"""Plan -> validate -> policy -> execute -> verify -> (replan once) loop."""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional

from .planner import AgentPlanner, Plan, PlanError
from .policy import AutonomyPolicy
from .registry import ToolError, ToolRegistry

log = logging.getLogger("mimo.agent")
MAX_OUTPUT = 2000


class TaskCancelled(Exception):
    pass


class TaskTimedOut(Exception):
    pass


@dataclass
class StepRecord:
    index: int
    tool: str
    args: dict
    level: int = 0
    status: str = "pending"      # succeeded | failed | denied | blocked
    decision: str = ""
    output: str = ""
    verified: Optional[bool] = None
    error: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class RunContext:
    """Hooks the engine uses to talk to whoever runs it (the TaskManager, or tests)."""

    def check(self) -> None:                         # raise TaskCancelled / TaskTimedOut
        pass

    def set_status(self, status: str) -> None:
        pass

    def on_plan(self, plan: Plan) -> None:
        pass

    def on_steps(self, steps: list[StepRecord]) -> None:
        pass

    def confirm(self, step: StepRecord) -> bool:     # ask the user; True = approved
        return False

    def audit(self, step: StepRecord) -> None:
        pass


@dataclass
class EngineResult:
    status: str                  # succeeded | failed
    mode: str                    # answer | action
    text: str = ""
    error: str = ""
    steps: list[StepRecord] = field(default_factory=list)


class AgentEngine:
    def __init__(self, registry: ToolRegistry, planner: AgentPlanner, policy: AutonomyPolicy,
                 answerer: Callable[[str], str], max_replans: int = 1, tool_workers: int = 4):
        self.registry, self.planner, self.policy = registry, planner, policy
        self.answerer, self.max_replans = answerer, max_replans
        self._pool = ThreadPoolExecutor(max_workers=tool_workers, thread_name_prefix="mimo-tool")

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------
    def run(self, goal: str, ctx: Optional[RunContext] = None) -> EngineResult:
        ctx = ctx or RunContext()
        ctx.set_status("planning")
        try:
            plan = self.planner.plan(goal)
        except PlanError as e:
            return EngineResult("failed", "action", error=str(e))
        ctx.on_plan(plan)
        ctx.check()

        if not plan.steps:                            # a question, not an action
            ctx.set_status("running")
            return EngineResult("succeeded", "answer", text=self.answerer(goal))

        ctx.set_status("running")
        done: list[StepRecord] = []
        queue, replans = list(plan.steps), 0
        while queue:
            ctx.check()
            step = queue.pop(0)
            rec = StepRecord(index=len(done), tool=step.tool, args=dict(step.args))
            done.append(rec)
            self._run_step(rec, ctx)
            ctx.on_steps(done)
            ctx.audit(rec)
            if rec.status == "succeeded":
                continue
            if rec.status in ("denied", "blocked"):   # never route around a user/policy "no"
                return EngineResult("failed", "action", error=rec.error, steps=done)
            if replans >= self.max_replans:
                return EngineResult("failed", "action", error=f"Step {rec.index + 1} ({rec.tool}) "
                                    f"failed: {rec.error}", steps=done)
            replans += 1
            try:
                ctx.set_status("planning")
                queue = list(self.planner.plan(goal, [r.to_dict() for r in done]).steps)
                ctx.set_status("running")
            except PlanError as e:
                return EngineResult("failed", "action", error=f"{rec.error}; replanning failed: {e}",
                                    steps=done)
        return EngineResult("succeeded", "action", text=self._summarize(done), steps=done)

    # ------------------------------------------------------------------
    def _run_step(self, rec: StepRecord, ctx: RunContext) -> None:
        t0 = time.monotonic()
        try:
            spec = self.registry.get(rec.tool)
            params = self.registry.validate_args(rec.tool, rec.args)       # raises ToolError
            rec.level = spec.level
            rec.decision = self.policy.decide(spec)
            if rec.decision == "deny":
                rec.status, rec.error = "blocked", f"'{rec.tool}' is disabled by your autonomy policy"
                return
            if rec.decision == "confirm" and not ctx.confirm(rec):
                rec.status, rec.error = "denied", f"You did not approve '{rec.tool}'"
                return
            output = self._execute(spec.handler, params, spec.timeout_s, ctx)
            rec.output = str(output)[:MAX_OUTPUT]
            if spec.verify is not None:
                rec.verified = spec.verify(params, output)
                if rec.verified is False:
                    raise ToolError("result failed verification")
            rec.status = "succeeded"
        except (TaskCancelled, TaskTimedOut):
            raise
        except ToolError as e:
            rec.status, rec.error = "failed", str(e)
        except Exception:
            log.exception("Tool %s crashed", rec.tool)
            rec.status, rec.error = "failed", f"'{rec.tool}' hit an unexpected error"
        finally:
            rec.duration_ms = int((time.monotonic() - t0) * 1000)

    def _execute(self, handler: Callable[[Any], Any], params: Any, timeout_s: float, ctx: RunContext) -> Any:
        fut = self._pool.submit(handler, params)
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                return fut.result(timeout=0.05)
            except FutureTimeout:
                try:
                    ctx.check()
                except (TaskCancelled, TaskTimedOut):
                    fut.cancel()      # cannot stop a running thread; the result is simply abandoned
                    raise
                if time.monotonic() > deadline:
                    fut.cancel()
                    raise ToolError(f"timed out after {timeout_s:g}s (the tool may still be running)")

    @staticmethod
    def _summarize(done: list[StepRecord]) -> str:
        """Report only what the tools actually returned - never model-invented claims."""
        if len(done) == 1:
            return done[0].output
        return "\n".join(f"{r.index + 1}. {r.tool}: {r.output}" for r in done)
