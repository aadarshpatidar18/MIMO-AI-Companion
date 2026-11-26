"""Autonomy policy: decides whether a step runs, needs the user's confirmation, or is blocked."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .registry import CONSEQUENTIAL, ToolSpec

Decision = Literal["allow", "confirm", "deny"]


@dataclass
class AutonomyPolicy:
    # Highest level that may run without asking. Level 3 (consequential) ALWAYS asks;
    # the cap is enforced here so a bad setting cannot disable that.
    max_auto_level: int = 2
    deny: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.max_auto_level = max(1, min(int(self.max_auto_level), CONSEQUENTIAL - 1))

    def decide(self, spec: ToolSpec) -> Decision:
        if spec.name in self.deny:
            return "deny"
        return "allow" if spec.level <= self.max_auto_level else "confirm"

    def to_dict(self) -> dict:
        return {"max_auto_level": self.max_auto_level, "deny": sorted(self.deny)}
