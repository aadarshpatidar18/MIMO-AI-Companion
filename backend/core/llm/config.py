"""Routing settings: defaults < config/models.json < environment < saved user choice.

Secrets are NEVER read from or written to these files; API keys come only from
environment variables (see gemini.py). The saved user settings file holds the
provider selection and per-task routes only.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

from .retry import RetryPolicy

REPO_ROOT = Path(__file__).resolve().parents[3]       # backend/core/llm/config.py -> repo root
DEFAULT_OLLAMA_MODEL = "qwen2.5:1.5b"
DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"

TASK_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}$")
PROVIDER_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


@dataclass(frozen=True)
class Target:
    provider: str
    model: Optional[str] = None      # None => the provider's configured default model


@dataclass
class TaskRoute:
    targets: list[Target]
    local_only: bool = False         # True => never sent to a cloud provider


@dataclass
class RouterSettings:
    selection: str = "ollama"        # "auto" | any registered provider name
    fallback_to_local: bool = True
    routes: dict[str, TaskRoute] = field(default_factory=dict)
    limits: dict[str, dict[str, dict[str, Optional[int]]]] = field(default_factory=dict)
    retry: dict[str, RetryPolicy] = field(default_factory=dict)
    ollama: dict[str, Any] = field(default_factory=dict)
    gemini: dict[str, Any] = field(default_factory=dict)


def default_routes() -> dict[str, TaskRoute]:
    cloud_then_local = [Target("gemini"), Target("ollama")]
    return {
        # Small/fast local model is enough for classification and saves cloud quota.
        "intent": TaskRoute([Target("ollama")]),
        "chat": TaskRoute(list(cloud_then_local)),
        "plan": TaskRoute(list(cloud_then_local)),
        "summarize": TaskRoute(list(cloud_then_local)),
        "research": TaskRoute(list(cloud_then_local)),
        "code": TaskRoute(list(cloud_then_local)),
        # Personal memory content stays on this machine.
        "memory": TaskRoute([Target("ollama")], local_only=True),
    }


def normalize_ollama_url(raw: str) -> str:
    """Accept OLLAMA_HOST styles like '127.0.0.1:11434' or '0.0.0.0'."""
    raw = raw.strip()
    if not raw:
        return "http://127.0.0.1:11434"
    if "://" not in raw:
        raw = "http://" + raw
    raw = raw.replace("//0.0.0.0", "//127.0.0.1")
    if not re.search(r":\d+$", raw.split("://", 1)[1].split("/", 1)[0]):
        raw = raw.rstrip("/") + ":11434"
    return raw.rstrip("/")


def parse_route(obj: dict) -> TaskRoute:
    targets = []
    for t in obj.get("targets", []):
        provider = str(t.get("provider", ""))
        model = t.get("model")
        validate_target(provider, model)
        targets.append(Target(provider, model))
    if not targets:
        raise ValueError("a route needs at least one target")
    return TaskRoute(targets, bool(obj.get("local_only", False)))


def validate_target(provider: str, model: Optional[str]) -> None:
    if not PROVIDER_RE.match(provider):
        raise ValueError(f"invalid provider name: {provider!r}")
    if model is not None and not MODEL_RE.match(model):
        raise ValueError(f"invalid model name: {model!r}")


def _to_bool(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


def load_settings(env: Optional[Mapping[str, str]] = None,
                  config_path: Optional[Path] = None,
                  store: Optional["UserSettingsStore"] = None) -> RouterSettings:
    env = os.environ if env is None else env
    cfg_path = config_path or Path(env.get("MIMO_MODELS_CONFIG", REPO_ROOT / "config" / "models.json"))
    s = RouterSettings(routes=default_routes())
    s.ollama = {"base_url": "http://127.0.0.1:11434", "default_model": DEFAULT_OLLAMA_MODEL,
                "timeout_s": 120.0, "keep_alive": "5m"}
    s.gemini = {"default_model": DEFAULT_GEMINI_MODEL, "timeout_s": 60.0}
    s.retry = {"gemini": RetryPolicy(),
               "ollama": RetryPolicy(max_attempts=2, base_delay=0.5, max_delay=2.0, max_total_wait=3.0)}

    # 1. config file (optional)
    if cfg_path.is_file():
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        s.selection = str(data.get("selection", s.selection))
        s.fallback_to_local = bool(data.get("fallback_to_local", s.fallback_to_local))
        s.ollama.update(data.get("ollama", {}))
        s.gemini.update(data.get("gemini", {}))
        for task, r in (data.get("routes") or {}).items():
            if TASK_RE.match(task):
                s.routes[task] = parse_route(r)
        for prov, lim in (data.get("limits") or {}).items():
            s.limits[prov] = {m: {k: v for k, v in d.items() if k in ("rpm", "rpd")}
                              for m, d in lim.items() if isinstance(d, dict)}
        for prov, rp in (data.get("retry") or {}).items():
            s.retry[prov] = RetryPolicy(**{k: v for k, v in rp.items()
                                           if k in RetryPolicy.__dataclass_fields__})

    # 2. environment
    if env.get("MIMO_LLM_PROVIDER"):
        s.selection = env["MIMO_LLM_PROVIDER"].strip().lower()
    if env.get("MIMO_LLM_FALLBACK"):
        s.fallback_to_local = _to_bool(env["MIMO_LLM_FALLBACK"])
    host = env.get("MIMO_OLLAMA_URL") or env.get("OLLAMA_HOST")
    if host:
        s.ollama["base_url"] = host
    s.ollama["base_url"] = normalize_ollama_url(str(s.ollama["base_url"]))
    if env.get("MIMO_OLLAMA_MODEL"):
        s.ollama["default_model"] = env["MIMO_OLLAMA_MODEL"]
    if env.get("MIMO_GEMINI_MODEL"):
        s.gemini["default_model"] = env["MIMO_GEMINI_MODEL"]

    # 3. the user's saved choice (made in the app) wins over file/env
    if store:
        store.apply(s)
    return s


class UserSettingsStore:
    """Persists user choices (selection, fallback flag, task routes). No secrets."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def apply(self, s: RouterSettings) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if PROVIDER_RE.match(str(data.get("selection", ""))):
                s.selection = str(data["selection"])
            if "fallback_to_local" in data:
                s.fallback_to_local = bool(data["fallback_to_local"])
            for task, r in (data.get("routes") or {}).items():
                if TASK_RE.match(task):
                    s.routes[task] = parse_route(r)
        except (ValueError, OSError):
            pass   # corrupt file: ignore, keep defaults

    def save(self, s: RouterSettings) -> None:
        data = {
            "selection": s.selection,
            "fallback_to_local": s.fallback_to_local,
            "routes": {t: {"targets": [{"provider": x.provider, "model": x.model} for x in r.targets],
                           "local_only": r.local_only} for t, r in s.routes.items()},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.path)       # atomic
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
