"""File-access sandbox: every path an operator touches must resolve inside an allowed root.

Symlinks are resolved first, so a link cannot be used to step outside a root.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from ..core.agent.registry import ToolError

DEFAULT_SUBDIRECTORIES = ("Documents", "Downloads", "Desktop", "Projects", "Documents/MIMO")


def allowed_roots(env: dict | None = None) -> list[Path]:
    """MIMO_FILE_ROOTS wins (os.pathsep separated). Otherwise the usual personal folders."""
    env = os.environ if env is None else env
    raw = env.get("MIMO_FILE_ROOTS", "").strip()
    if raw:
        roots = [Path(p).expanduser() for p in raw.split(os.pathsep) if p.strip()]
    else:
        home = Path.home()
        roots = [home / sub for sub in DEFAULT_SUBDIRECTORIES]
        roots.append(home)
    out = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved.is_dir() and resolved not in out:
            out.append(resolved)
    return out


def describe_roots(roots: Iterable[Path]) -> str:
    return ", ".join(str(r) for r in roots) or "(none configured)"


def resolve_in_roots(raw: str, *, must_exist: bool = True) -> Path:
    """Resolve a user-supplied path and prove it is inside an allowed root."""
    if not raw or not str(raw).strip():
        raise ToolError("A path is required.")
    candidate = Path(str(raw).strip()).expanduser()
    if not candidate.is_absolute():
        roots = allowed_roots()
        if not roots:
            raise ToolError("No folders are allowed for file access.")
        candidate = roots[0] / candidate
    try:
        resolved = candidate.resolve()
    except OSError as e:
        raise ToolError(f"That path cannot be used: {e}") from None

    roots = allowed_roots()
    if not roots:
        raise ToolError("File access is switched off: no allowed folders are configured.")
    if not any(resolved == root or resolved.is_relative_to(root) for root in roots):
        raise ToolError(f"That path is outside the folders MIMO may touch "
                        f"({describe_roots(roots)}).")
    if must_exist and not resolved.exists():
        raise ToolError(f"There is nothing at {resolved.name}.")
    return resolved


def human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"
