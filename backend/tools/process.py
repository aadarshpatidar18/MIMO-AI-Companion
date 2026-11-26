"""Run a child process safely and kill it when it overruns.

The engine cannot kill a thread, so every operator that could hang must own its timeout here:
start in its own process group, wait, then kill the whole group.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Sequence

MAX_OUTPUT = 20_000


@dataclass
class CommandResult:
    argv: list[str]
    code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.timed_out

    @property
    def output(self) -> str:
        """stdout, or stderr when stdout is empty - what a user wants to read."""
        return (self.stdout or self.stderr).strip()

    def tail(self, limit: int = 4000) -> str:
        text = self.output
        return text if len(text) <= limit else "…" + text[-limit:]


def _clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    head = MAX_OUTPUT // 3
    return text[:head] + f"\n… [{len(text) - MAX_OUTPUT} characters omitted] …\n" + text[-MAX_OUTPUT // 3:]


def run_process(argv: Sequence[str], timeout: float = 30.0, cwd: Optional[Path] = None,
                env_extra: Optional[Mapping[str, str]] = None,
                stdin_text: Optional[str] = None) -> CommandResult:
    """Run without a shell. No shell means no quoting bugs and no accidental injection."""
    env = os.environ.copy()
    env.update(env_extra or {})
    started = time.monotonic()
    kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE,
                  cwd=str(cwd) if cwd else None, text=True, errors="replace", env=env,
                  start_new_session=(os.name != "nt"))
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    try:
        proc = subprocess.Popen(list(argv), **kwargs)  # noqa: S603 - argv list, no shell
    except FileNotFoundError:
        return CommandResult(list(argv), 127, "", f"{argv[0]} is not installed or not on PATH.",
                             int((time.monotonic() - started) * 1000))

    timed_out = False
    try:
        out, err = proc.communicate(input=stdin_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:                     # pragma: no cover - stubborn child
            out, err = "", ""
    return CommandResult(list(argv), proc.returncode if proc.returncode is not None else -9,
                         _clip(out or ""), _clip(err or ""),
                         int((time.monotonic() - started) * 1000), timed_out)


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            proc.kill()
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def which(program: str) -> Optional[str]:
    return shutil.which(program)
