"""Built-in tools: wrappers around the original backend/tools.py with schemas and levels."""
from __future__ import annotations

import platform
import re
import webbrowser
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ... import legacy_tools as legacy
from .registry import REVERSIBLE, READ_ONLY, ToolError, ToolRegistry, ToolSpec


class _NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Calc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expression: str = Field(min_length=1, max_length=200)


class _Site(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: Literal["youtube", "google", "github"]


class _App(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app_name: Literal["notepad", "calculator"]


def _calc(p: _Calc) -> Any:
    result = legacy.calculate(p.expression)
    if isinstance(result, str):                # legacy returns error strings
        raise ToolError(result)
    return result


def _open_site(p: _Site) -> str:
    if not webbrowser.open(legacy_url(p.url)):
        raise ToolError("No browser could be launched")
    return f"Opened {p.url} in the default browser."


def legacy_url(name: str) -> str:
    return {"youtube": "https://www.youtube.com", "google": "https://www.google.com",
            "github": "https://github.com"}[name]


def _open_app(p: _App) -> str:
    if platform.system() != "Windows":
        raise ToolError("Application launching is only available on Windows")
    result = legacy.open_app(p.app_name)
    if not result.startswith("Opened"):
        raise ToolError(result)
    return result


def register_builtin_tools(registry: ToolRegistry) -> ToolRegistry:
    registry.register(ToolSpec(
        "get_time", "Get the current local time.", _NoArgs, lambda p: legacy.get_time(), READ_ONLY,
        verify=lambda p, out: bool(re.match(r"^\d{2}:\d{2}:\d{2} (AM|PM)$", str(out)))))
    registry.register(ToolSpec(
        "get_date", "Get today's date.", _NoArgs, lambda p: legacy.get_date(), READ_ONLY,
        verify=lambda p, out: bool(re.match(r"^\w+, \d{2} \w+ \d{4}$", str(out)))))
    registry.register(ToolSpec(
        "calculate", "Evaluate an arithmetic expression such as '25 * 35'.", _Calc, _calc, READ_ONLY,
        verify=lambda p, out: isinstance(out, (int, float)) and not isinstance(out, bool)))
    registry.register(ToolSpec(
        "open_website", "Open an approved website in the default browser.", _Site, _open_site, REVERSIBLE))
    registry.register(ToolSpec(
        "open_app", "Launch an approved Windows application.", _App, _open_app, REVERSIBLE))
    return registry
