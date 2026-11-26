"""Operator tools: files, the system, applications, the screen and the browser.

Registered into the same registry as the built-ins, so the planner sees them and the policy and
verification machinery apply unchanged.
"""
from __future__ import annotations

from ..core.agent.registry import ToolRegistry
from .apps import known_apps, register_app_tools
from .browser import register_browser_tools
from .files import register_file_tools, roots_summary
from .memory_tools import register_memory_tools
from .screen import capabilities, register_screen_tools
from .system import register_system_tools


def register_operator_tools(registry: ToolRegistry) -> ToolRegistry:
    register_memory_tools(registry)
    register_file_tools(registry)
    register_system_tools(registry)
    register_app_tools(registry)
    register_screen_tools(registry)
    register_browser_tools(registry)
    return registry


def capability_report() -> dict:
    report = capabilities()
    report["app_aliases"] = known_apps()
    report["file_roots"] = roots_summary()
    return report


__all__ = ["register_operator_tools", "capability_report", "known_apps", "roots_summary"]
