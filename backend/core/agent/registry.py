"""Structured tool registry: every tool has a validated argument schema and an autonomy level."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from pydantic import BaseModel, ValidationError

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")

# Autonomy levels (see docs/AGENT_ENGINE.md)
READ_ONLY, REVERSIBLE, CONSEQUENTIAL = 1, 2, 3


class ToolError(Exception):
    """A tool failed in an expected, user-presentable way."""


@dataclass
class ToolSpec:
    name: str
    description: str
    params: type[BaseModel]
    handler: Callable[[Any], Any]
    level: int = READ_ONLY
    timeout_s: float = 15.0
    # Optional independent check of the result: True=verified, False=failed, None=cannot verify.
    verify: Optional[Callable[[Any, Any], Optional[bool]]] = None


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not NAME_RE.match(spec.name):
            raise ValueError(f"invalid tool name: {spec.name!r}")
        if spec.level not in (READ_ONLY, REVERSIBLE, CONSEQUENTIAL):
            raise ValueError("level must be 1, 2 or 3")
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        if spec.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._tools[spec.name] = spec

    def subset(self, names: tuple[str, ...] | list[str]) -> "ToolRegistry":
        """A registry with only these tools. Unknown names are skipped, not fatal."""
        out = ToolRegistry()
        for name in names:
            spec = self._tools.get(name)
            if spec is not None:
                out._tools[name] = spec
        return out

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def validate_args(self, name: str, args: Any) -> BaseModel:
        spec = self.get(name)
        if spec is None:
            raise ToolError(f"unknown tool '{name}'")
        if not isinstance(args, dict):
            raise ToolError(f"arguments for '{name}' must be an object")
        try:
            return spec.params.model_validate(args)
        except ValidationError as e:
            problems = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'args'}: {err['msg']}"
                                 for err in e.errors()[:4])
            raise ToolError(f"invalid arguments for '{name}': {problems}")

    def catalog(self) -> list[dict]:
        return [{"name": s.name, "description": s.description, "level": s.level,
                 "timeout_s": s.timeout_s, "parameters": s.params.model_json_schema().get("properties", {})}
                for s in (self._tools[n] for n in self.names())]

    def prompt_block(self) -> str:
        lines = []
        for t in self.catalog():
            params = ", ".join(
                f"{k}: {v.get('type') or '|'.join(map(str, v.get('enum', []))) or 'any'}"
                + (f" (one of {v['enum']})" if v.get("enum") else "")
                for k, v in t["parameters"].items()) or "no arguments"
            lines.append(f"- {t['name']}({params}): {t['description']}")
        return "\n".join(lines)
