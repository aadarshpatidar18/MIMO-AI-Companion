"""File management tools: inspect, read, write, move, search - all inside the allowed roots."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..core.agent.registry import CONSEQUENTIAL, READ_ONLY, REVERSIBLE, ToolError, ToolRegistry, ToolSpec
from .paths import allowed_roots, human_size, resolve_in_roots

TEXT_SUFFIXES = {".txt", ".md", ".py", ".kt", ".java", ".js", ".ts", ".json", ".yaml", ".yml",
                 ".toml", ".ini", ".cfg", ".csv", ".html", ".css", ".xml", ".log", ".sh", ".ps1",
                 ".gradle", ".kts", ".properties", ".sql", ".rb", ".go", ".rs", ".c", ".cpp", ".h"}
MAX_READ_BYTES = 400_000


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _List(_Base):
    path: str = Field(default=".", max_length=1000)
    pattern: Optional[str] = Field(default=None, max_length=80)
    limit: int = Field(default=100, ge=1, le=500)


class _Read(_Base):
    path: str = Field(min_length=1, max_length=1000)
    max_chars: int = Field(default=12000, ge=200, le=100_000)


class _Write(_Base):
    path: str = Field(min_length=1, max_length=1000)
    content: str = Field(max_length=200_000)
    overwrite: bool = False


class _Mkdir(_Base):
    path: str = Field(min_length=1, max_length=1000)


class _Move(_Base):
    source: str = Field(min_length=1, max_length=1000)
    destination: str = Field(min_length=1, max_length=1000)


class _Delete(_Base):
    path: str = Field(min_length=1, max_length=1000)


class _Search(_Base):
    query: str = Field(min_length=1, max_length=120)
    path: str = Field(default=".", max_length=1000)
    limit: int = Field(default=30, ge=1, le=200)


def _list(p: _List) -> dict:
    folder = resolve_in_roots(p.path)
    if not folder.is_dir():
        raise ToolError(f"{folder.name} is a file, not a folder.")
    entries = sorted(folder.glob(p.pattern or "*"), key=lambda x: (x.is_file(), x.name.lower()))
    out = []
    for item in entries[: p.limit]:
        try:
            size = item.stat().st_size
        except OSError:
            size = 0
        out.append({"name": item.name, "type": "folder" if item.is_dir() else "file",
                    "size": human_size(size), "path": str(item)})
    return {"folder": str(folder), "count": len(out),
            "more": max(0, len(entries) - len(out)), "entries": out}


def _read(p: _Read) -> dict:
    path = resolve_in_roots(p.path)
    if path.is_dir():
        raise ToolError(f"{path.name} is a folder. List it first, then read a file inside it.")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _pdf_text(path)
        if text is None:
            raise ToolError("I cannot read this PDF: extract text needs the optional 'pypdf' package.")
        return {"path": str(path), "kind": "pdf", "chars": len(text),
                "text": text[: p.max_chars]}
    if suffix not in TEXT_SUFFIXES and _looks_binary(path):
        raise ToolError(f"{path.name} is not a text document I can read.")
    raw = path.read_bytes()[:MAX_READ_BYTES]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    return {"path": str(path), "kind": "text", "chars": len(text), "truncated": len(text) > p.max_chars,
            "text": text[: p.max_chars]}


def _looks_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:2048]
    except OSError as e:
        raise ToolError(f"I could not open {path.name}: {e}") from None
    return b"\x00" in chunk


def _pdf_text(path: Path) -> Optional[str]:
    try:
        from pypdf import PdfReader            # optional dependency
    except ImportError:
        return None
    try:
        reader = PdfReader(str(path))
        pages = []
        for i, page in enumerate(reader.pages[:40]):
            pages.append(f"--- page {i + 1} ---\n" + (page.extract_text() or ""))
        return "\n".join(pages).strip()
    except Exception as e:                     # a corrupt or encrypted PDF
        raise ToolError(f"That PDF could not be opened: {e}") from None


def _write(p: _Write) -> dict:
    path = resolve_in_roots(p.path, must_exist=False)
    if path.exists() and not p.overwrite:
        raise ToolError(f"{path.name} already exists. Say overwrite if you want to replace it.")
    if path.is_dir():
        raise ToolError(f"{path.name} is a folder.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(p.content, encoding="utf-8")
    written = path.stat().st_size
    return {"path": str(path), "bytes": written, "created": True}


def _mkdir(p: _Mkdir) -> dict:
    path = resolve_in_roots(p.path, must_exist=False)
    if path.exists():
        raise ToolError(f"{path.name} already exists.")
    path.mkdir(parents=True)
    return {"path": str(path), "created": True}


def _move(p: _Move) -> dict:
    source = resolve_in_roots(p.source)
    destination = resolve_in_roots(p.destination, must_exist=False)
    if destination.exists() and destination.is_dir():
        destination = destination / source.name
    if destination.exists():
        raise ToolError(f"{destination.name} already exists at the destination.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return {"from": str(source), "to": str(destination)}


def _delete(p: _Delete) -> dict:
    path = resolve_in_roots(p.path)
    if path.is_dir():
        if any(path.iterdir()):
            raise ToolError(f"{path.name} is not empty. I will not delete a folder with files in it.")
        path.rmdir()
        return {"deleted": str(path), "kind": "empty folder"}
    path.unlink()
    return {"deleted": str(path), "kind": "file"}


def _search(p: _Search) -> dict:
    root = resolve_in_roots(p.path)
    if not root.is_dir():
        raise ToolError(f"{root.name} is not a folder.")
    needle = p.query.lower()
    hits = []
    for item in root.rglob("*"):
        if len(hits) >= p.limit:
            break
        if any(part.startswith(".") for part in item.relative_to(root).parts):
            continue
        if needle in item.name.lower():
            hits.append({"name": item.name, "path": str(item),
                         "type": "folder" if item.is_dir() else "file"})
    return {"query": p.query, "root": str(root), "count": len(hits), "matches": hits}


def register_file_tools(registry: ToolRegistry) -> ToolRegistry:
    registry.register(ToolSpec(
        "list_files", "List a folder inside the allowed folders (name, type, size).",
        _List, _list, READ_ONLY,
        verify=lambda p, out: isinstance(out, dict) and "entries" in out))
    registry.register(ToolSpec(
        "read_file", "Read a text document or PDF inside the allowed folders.",
        _Read, _read, READ_ONLY,
        verify=lambda p, out: isinstance(out, dict) and bool(out.get("text"))))
    registry.register(ToolSpec(
        "search_files", "Find files by name inside the allowed folders.",
        _Search, _search, READ_ONLY))
    registry.register(ToolSpec(
        "write_file", "Create a text file, or replace one when overwrite is true.",
        _Write, _write, REVERSIBLE,
        verify=lambda p, out: isinstance(out, dict) and out.get("bytes", 0) > 0))
    registry.register(ToolSpec(
        "create_folder", "Create a new folder inside the allowed folders.",
        _Mkdir, _mkdir, REVERSIBLE))
    registry.register(ToolSpec(
        "move_path", "Move or rename a file or folder inside the allowed folders.",
        _Move, _move, CONSEQUENTIAL))
    registry.register(ToolSpec(
        "delete_path", "Delete one file, or an empty folder. Never deletes recursively.",
        _Delete, _delete, CONSEQUENTIAL))
    return registry


def roots_summary() -> list[str]:
    return [str(r) for r in allowed_roots()]
