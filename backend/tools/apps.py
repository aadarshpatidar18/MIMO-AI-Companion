"""Application control: launch, close and inspect the windows on this machine.

Aliases come from `config/apps.json` when it exists, so you can map "vscode" to your own path
without touching code.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..core.agent.registry import CONSEQUENTIAL, READ_ONLY, REVERSIBLE, ToolError, ToolRegistry, ToolSpec
from ..core.llm.config import REPO_ROOT

CONFIG = REPO_ROOT / "config" / "apps.json"

# alias -> what to run, per platform. Values are argv lists, never shell strings.
BUILTIN: dict[str, dict[str, list[str]]] = {
    "notepad": {"Windows": ["notepad.exe"]},
    "calculator": {"Windows": ["calc.exe"]},
    "explorer": {"Windows": ["explorer.exe"], "Linux": ["xdg-open", "."]},
    "terminal": {"Windows": ["wt.exe"], "Linux": ["x-terminal-emulator"]},
    "powershell": {"Windows": ["powershell.exe"]},
    "browser": {"Windows": ["explorer.exe", "https://"], "Darwin": ["open", "-a", "Safari"],
                "Linux": ["xdg-open", "https://"]},
    "vscode": {"Windows": ["code.cmd"], "Darwin": ["open", "-a", "Visual Studio Code"],
               "Linux": ["code"]},
    "android studio": {"Windows": ["C:\\Program Files\\Android\\Android Studio\\bin\\studio64.exe"],
                       "Darwin": ["open", "-a", "Android Studio"], "Linux": ["studio"]},
    "chrome": {"Windows": ["chrome.exe"], "Darwin": ["open", "-a", "Google Chrome"],
               "Linux": ["google-chrome"]},
    "spotify": {"Windows": ["spotify.exe"], "Darwin": ["open", "-a", "Spotify"], "Linux": ["spotify"]},
}


class _Launch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    app: str = Field(min_length=1, max_length=80, description="alias, or an .exe name on Windows")


class _Close(BaseModel):
    model_config = ConfigDict(extra="forbid")
    process: str = Field(min_length=1, max_length=80,
                         description="process name as shown by Get-Process, for example 'notepad'")


class _NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _load_config() -> dict[str, list[str]]:
    if not CONFIG.is_file():
        return {}
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k).lower(): [str(x) for x in v] for k, v in data.items()
            if isinstance(v, list) and v}


def _argv_for(alias: str) -> list[str]:
    key = alias.strip().lower()
    custom = _load_config()
    if key in custom:
        return custom[key]
    table = BUILTIN.get(key)
    if table is None:
        raise ToolError(f"I do not know an app called '{alias}'. Add it to config/apps.json.")
    system = platform.system()
    if system not in table:
        raise ToolError(f"'{alias}' has no launch command for {system} yet. "
                        f"Add it to config/apps.json.")
    return list(table[system])


def _launch(p: _Launch) -> dict:
    argv = _argv_for(p.app)
    exe = shutil.which(argv[0]) or (argv[0] if Path(argv[0]).is_file() else None)
    if exe is None:
        raise ToolError(f"{argv[0]} is not installed or not on PATH.")
    try:
        if platform.system() == "Windows" and argv[0].lower().endswith((".exe", ".cmd")):
            subprocess.Popen(argv, shell=False, close_fds=True)  # noqa: S603
        else:
            subprocess.Popen(argv, shell=False, close_fds=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
    except OSError as e:
        raise ToolError(f"{p.app} could not start: {e}") from None
    return {"launched": p.app, "argv": argv}


def _close(p: _Close) -> dict:
    system = platform.system()
    name = p.process.strip()
    if not name or any(ch in name for ch in "/\\:*?\"<>|"):
        raise ToolError("That process name is not valid.")
    if system == "Windows":
        result = subprocess.run(["taskkill", "/IM", name if "." in name else f"{name}.exe"],
                                capture_output=True, text=True)  # noqa: S603,S607
        if result.returncode != 0:
            raise ToolError(f"Windows could not close {name}: {(result.stderr or result.stdout).strip()}")
        return {"closed": name}
    if system == "Linux":
        result = subprocess.run(["pkill", "-x", name], capture_output=True, text=True)  # noqa: S603,S607
        return {"closed": name, "ok": result.returncode == 0}
    raise ToolError(f"Closing applications is not supported on {system} yet.")


def _list_windows(_: _NoArgs) -> dict:
    if platform.system() != "Windows":
        raise ToolError("Listing open windows is a Windows feature; this machine is "
                        f"{platform.system()}.")
    try:
        import pygetwindow as gw          # optional dependency
    except ImportError:
        raise ToolError("Install the optional 'pygetwindow' package to list open windows.") from None
    titles = [t for t in gw.getAllTitles() if t.strip()]
    return {"count": len(titles), "windows": titles[:40]}


def _verify_launch(p: _Launch, out: object) -> Optional[bool]:
    """Best effort: on Windows, is a process for that alias running now?"""
    if platform.system() != "Windows":
        return None
    try:
        import psutil
    except ImportError:
        return None
    target = Path(_argv_for(p.app)[0]).stem.lower()
    for _ in range(6):
        for proc in psutil.process_iter(["name"]):
            if (proc.info.get("name") or "").lower().startswith(target[:12]):
                return True
        time.sleep(0.25)
    return False


def register_app_tools(registry: ToolRegistry) -> ToolRegistry:
    registry.register(ToolSpec(
        "launch_app", "Open an application such as vscode, chrome, notepad, explorer or terminal.",
        _Launch, _launch, REVERSIBLE, verify=_verify_launch))
    registry.register(ToolSpec(
        "close_app", "Close a running application by process name. Unsaved work is lost.",
        _Close, _close, CONSEQUENTIAL))
    registry.register(ToolSpec(
        "list_windows", "List the titles of open windows (Windows only).",
        _NoArgs, _list_windows, READ_ONLY))
    return registry


def known_apps() -> list[str]:
    return sorted(set(BUILTIN) | set(_load_config()))
