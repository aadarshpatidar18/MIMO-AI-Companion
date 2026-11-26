"""Common LLM interface. Add a new provider by subclassing LLMProvider."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass
class LLMRequest:
    messages: list[Message]
    task: str = "chat"                 # routing key: chat, intent, plan, ...
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    json_mode: bool = False            # ask for a JSON-only reply
    allow_cloud: bool = True           # False => never leaves this machine
    provider: Optional[str] = None     # force a provider for this call
    model: Optional[str] = None        # force a model for this call
    timeout: Optional[float] = None

    @classmethod
    def from_prompt(cls, prompt: str, system: Optional[str] = None, **kw: Any) -> "LLMRequest":
        msgs: list[Message] = []
        if system:
            msgs.append(Message("system", system))
        msgs.append(Message("user", prompt))
        return cls(messages=msgs, **kw)


@dataclass
class Attempt:
    provider: str
    model: str
    outcome: str        # success | rate_limited | unavailable | auth | bad_request | blocked | skipped | error
    detail: str = ""
    latency_ms: int = 0
    retries: int = 0


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    latency_ms: int = 0
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def fell_back(self) -> bool:
        """True if a different provider than the first-choice one answered."""
        return bool(self.attempts) and self.attempts[0].provider != self.provider


class LLMProvider(ABC):
    name: str = ""
    is_local: bool = False
    default_model: str = ""

    @abstractmethod
    def is_configured(self) -> bool:
        """Cheap local check (e.g. API key present). Must not hit the network."""

    @abstractmethod
    def generate(self, request: LLMRequest, model: Optional[str] = None) -> LLMResponse:
        """Single attempt. Raise an LLMError subclass on failure. No retry here."""

    def health(self) -> dict:
        """Optional live check. Default: report configuration only."""
        return {"configured": self.is_configured()}
