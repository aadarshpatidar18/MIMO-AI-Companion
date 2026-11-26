"""MIMO multi-model LLM layer.

Typical use from the agent/planner:

    from backend.core.llm import generate_text, LLMRequest, get_router
    reply = generate_text("Plan my day", system="You are MIMO", task="plan")
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

from .base import Attempt, LLMProvider, LLMRequest, LLMResponse, Message
from .config import REPO_ROOT, UserSettingsStore, load_settings
from .errors import (AllProvidersFailedError, AuthError, BadRequestError, ContentBlockedError,
                     LLMError, ProviderUnavailableError, RateLimitError)
from .gemini import GeminiProvider
from .ollama import OllamaProvider
from .router import ModelRouter
from .usage import UsageTracker

__all__ = ["Attempt", "LLMProvider", "LLMRequest", "LLMResponse", "Message", "ModelRouter",
           "OllamaProvider", "GeminiProvider", "UsageTracker", "LLMError", "RateLimitError",
           "AllProvidersFailedError", "AuthError", "BadRequestError", "ContentBlockedError",
           "ProviderUnavailableError", "build_router", "get_router", "generate_text"]


def load_dotenv_file(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines). Never overrides real environment variables."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def build_router(data_dir: Optional[Path] = None) -> ModelRouter:
    load_dotenv_file(REPO_ROOT / ".env")
    data = Path(data_dir or os.environ.get("MIMO_DATA_DIR", REPO_ROOT / "data"))
    store = UserSettingsStore(data / "llm_settings.json")
    settings = load_settings(store=store)
    providers: dict[str, LLMProvider] = {
        "ollama": OllamaProvider(base_url=settings.ollama["base_url"],
                                 default_model=settings.ollama["default_model"],
                                 timeout=float(settings.ollama["timeout_s"]),
                                 keep_alive=str(settings.ollama["keep_alive"])),
        "gemini": GeminiProvider(default_model=settings.gemini["default_model"],
                                 timeout=float(settings.gemini["timeout_s"])),
    }
    return ModelRouter(providers, settings, UsageTracker(data / "llm_usage.db"), store)


_router: Optional[ModelRouter] = None
_lock = threading.Lock()


def get_router() -> ModelRouter:
    global _router
    with _lock:
        if _router is None:
            _router = build_router()
        return _router


def generate_text(prompt: str, system: Optional[str] = None, task: str = "chat", **kw) -> str:
    """Drop-in helper for the existing agent/planner code."""
    return get_router().generate_text(prompt, system, task, **kw)
