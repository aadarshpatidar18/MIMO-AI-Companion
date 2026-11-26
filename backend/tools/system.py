"""System operations: approved PowerShell, allowlisted commands, system facts.

Nothing here takes a free-form command string. The caller names a cmdlet or a program and its
arguments separately, and the operator builds the argv itself - so there is no shell to escape
out of.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import sys
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..core.agent.registry import CONSEQUENTIAL, READ_ONLY, ToolError, ToolRegistry, ToolSpec
from .paths import resolve_in_roots
from .process import run_process, which

SAFE_NAME = re.compile(r"^[A-Za-z0-9 ._\-*]{1,64}$")

POWERSHELL_CMDLETS = {
    "Get-Process": "list running processes",
    "Get-Service": "list Windows services and their state",
    "Get-Date": "current date and time on the machine",
    "Get-ComputerInfo": "hardware and operating-system summary",
    "Get-ChildItem": "list a folder",
    "Get-NetIPAddress": "network interfaces and addresses",
    "Get-Volume": "drives and free space",
}

ALLOWED_PROGRAMS = ("python", "python3", "pytest", "npm", "node", "git", "gradle", "gradlew",
                    "java", "pip", "uvicorn", "adb")


class _NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Pwsh(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cmdlet: Literal["Get-Process", "Get-Service", "Get-Date", "Get-ComputerInfo",
                    "Get-ChildItem", "Get-NetIPAddress", "Get-Volume"]
    name: Optional[str] = Field(default=None, max_length=64,
                                description="filter by name, for Get-Process/Get-Service")
    path: Optional[str] = Field(default=None, max_length=1000,
                                description="folder, for Get-ChildItem")


class _Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    program: Literal["python", "python3", "pytest", "npm", "node", "git", "gradle", "gradlew",
                     "java", "pip", "uvicorn", "adb"]
    args: list[str] = Field(default_factory=list, max_length=20)
    cwd: Optional[str] = Field(default=None, max_length=1000)
    timeout_s: int = Field(default=60, ge=5, le=300)


class _Tests(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_path: str = Field(min_length=1, max_length=1000)
    args: list[str] = Field(default_factory=lambda: ["-q"], max_length=10)
    timeout_s: int = Field(default=180, ge=10, le=300)


def _system_info(_: _NoArgs) -> dict:
    info: dict[str, Any] = {
        "platform": platform.system(),
        "machine": platform.machine(),
        "hostname": platform.node(),
        "python": platform.python_version(),
        "cpus": os.cpu_count(),
    }
    try:
        import psutil
        info["memory_total"] = f"{psutil.virtual_memory().total / 1e9:.1f} GB"
        info["memory_available"] = f"{psutil.virtual_memory().available / 1e9:.1f} GB"
        info["disk_free"] = f"{psutil.disk_usage(str(os.path.expanduser('~'))).free / 1e9:.1f} GB"
    except ImportError:
        info["memory_total"] = "install psutil for memory details"
    if platform.system() == "Windows":
        info["powershell"] = bool(which("powershell") or which("pwsh"))
    return info


def _powershell(p: _Pwsh) -> dict:
    if platform.system() != "Windows":
        raise ToolError("PowerShell is only available on Windows; this machine is "
                        f"{platform.system()}.")
    shell = which("powershell") or which("pwsh")
    if shell is None:
        raise ToolError("PowerShell is not installed on this machine.")

    script = f"{p.cmdlet}"
    if p.cmdlet in ("Get-Process", "Get-Service"):
        if p.name:
            if not SAFE_NAME.match(p.name):
                raise ToolError("That name contains characters I will not pass to PowerShell.")
            script += f" -Name '{p.name}'"
    if p.cmdlet == "Get-ChildItem":
        if not p.path:
            raise ToolError("Get-ChildItem needs a path inside your allowed folders.")
        folder = resolve_in_roots(p.path)
        script = f"Get-ChildItem -LiteralPath '{str(folder).replace(chr(39), chr(39) * 2)}'"
    script += " | Select-Object -First 40 | Out-String -Width 200"

    result = run_process([shell, "-NoProfile", "-NonInteractive", "-Command", script], timeout=25)
    if not result.ok:
        raise ToolError(result.tail(600) or "PowerShell returned an error.")
    return {"cmdlet": p.cmdlet, "output": result.tail(6000), "duration_ms": result.duration_ms}


def _command(p: _Command) -> dict:
    program = which(p.program)
    if program is None:
        raise ToolError(f"{p.program} is not installed or not on PATH.")
    for arg in p.args:
        if len(arg) > 200 or "\x00" in arg:
            raise ToolError("One of those arguments is too long or contains a null byte.")
    cwd = resolve_in_roots(p.cwd) if p.cwd else None
    if cwd and not cwd.is_dir():
        raise ToolError("That working folder does not exist.")
    result = run_process([program] + list(p.args), timeout=p.timeout_s, cwd=cwd)
    if result.timed_out:
        raise ToolError(f"{p.program} ran for over {p.timeout_s}s and was stopped.")
    return {"program": p.program, "args": p.args, "code": result.code, "ok": result.ok,
            "output": result.tail(6000), "duration_ms": result.duration_ms}


def _tests(p: _Tests) -> dict:
    project = resolve_in_roots(p.project_path)
    if not project.is_dir():
        raise ToolError("That project folder does not exist.")
    runner = which("pytest")
    argv = [runner or sys.executable, *([] if runner else ["-m", "pytest"]), *p.args]
    result = run_process(argv, timeout=p.timeout_s, cwd=project)
    if result.timed_out:
        raise ToolError(f"The tests ran for over {p.timeout_s}s and were stopped.")
    summary = _test_summary(result.output)
    return {"project": str(project), "ok": result.ok, "code": result.code,
            "summary": summary, "output": result.tail(6000)}


def _test_summary(output: str) -> str:
    for line in reversed(output.splitlines()):
        if re.search(r"\b(passed|failed|error|no tests ran)\b", line, re.IGNORECASE):
            return line.strip("= ").strip()
    return "no summary line found"


def register_system_tools(registry: ToolRegistry) -> ToolRegistry:
    registry.register(ToolSpec(
        "system_info", "Operating system, CPU, memory, disk and Python version.",
        _NoArgs, _system_info, READ_ONLY))
    registry.register(ToolSpec(
        "run_powershell", "Run one approved PowerShell cmdlet (no free-form commands).",
        _Pwsh, _powershell, READ_ONLY,
        verify=lambda p, out: isinstance(out, dict) and bool(out.get("output") is not None)))
    registry.register(ToolSpec(
        "run_command", "Run an allowlisted developer command (python, git, npm, gradle, adb…) "
                       "inside an allowed folder.",
        _Command, _command, CONSEQUENTIAL))
    registry.register(ToolSpec(
        "run_tests", "Run the test suite in a project folder and report the summary line.",
        _Tests, _tests, CONSEQUENTIAL))
    return registry
