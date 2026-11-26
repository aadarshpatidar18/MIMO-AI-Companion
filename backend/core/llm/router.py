"""Model router: picks providers per task/selection, retries, cools down, falls back."""
from __future__ import annotations

import copy
import random
import threading
import time
from typing import Callable, Optional

from .base import Attempt, LLMProvider, LLMRequest, LLMResponse
from .config import (RouterSettings, Target, TaskRoute, UserSettingsStore,
                     validate_target)
from .errors import (AllProvidersFailedError, AuthError, BadRequestError, ContentBlockedError,
                     LLMError, ProviderUnavailableError, RateLimitError)
from .retry import RetryPolicy, call_with_retry
from .usage import UsageTracker

_OUTCOME = [(RateLimitError, "rate_limited"), (ProviderUnavailableError, "unavailable"),
            (AuthError, "auth"), (BadRequestError, "bad_request"),
            (ContentBlockedError, "blocked")]


def _outcome_of(e: LLMError) -> str:
    for cls, name in _OUTCOME:
        if isinstance(e, cls):
            return name
    return "error"


class ModelRouter:
    def __init__(self, providers: dict[str, LLMProvider], settings: RouterSettings,
                 tracker: UsageTracker, store: Optional[UserSettingsStore] = None,
                 sleep: Callable[[float], None] = time.sleep,
                 rng: Optional[random.Random] = None):
        self.providers = providers
        self.tracker = tracker
        self._settings = settings
        self._store = store
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ settings
    def snapshot(self) -> RouterSettings:
        with self._lock:
            return copy.deepcopy(self._settings)

    def set_selection(self, selection: str, fallback_to_local: Optional[bool] = None) -> None:
        if selection != "auto" and selection not in self.providers:
            raise ValueError(f"unknown provider '{selection}'. "
                             f"Choose 'auto' or one of: {', '.join(sorted(self.providers))}")
        with self._lock:
            self._settings.selection = selection
            if fallback_to_local is not None:
                self._settings.fallback_to_local = fallback_to_local
            self._persist()

    def set_task_route(self, task: str, targets: list[Target], local_only: bool = False) -> None:
        if not targets:
            raise ValueError("a route needs at least one target")
        for t in targets:
            validate_target(t.provider, t.model)
            if t.provider not in self.providers:
                raise ValueError(f"unknown provider '{t.provider}'")
            if local_only and not self.providers[t.provider].is_local:
                raise ValueError("a local_only route cannot contain a cloud provider")
        with self._lock:
            self._settings.routes[task] = TaskRoute(list(targets), local_only)
            self._persist()

    def _persist(self) -> None:
        if self._store:
            self._store.save(self._settings)

    # ------------------------------------------------------------------ planning
    def _first_local(self) -> Optional[str]:
        return next((n for n, p in self.providers.items() if p.is_local), None)

    def plan(self, request: LLMRequest) -> list[Target]:
        """Ordered candidate (provider, model) list for this request. Pure; makes no calls."""
        s = self.snapshot()
        route = s.routes.get(request.task) or s.routes.get("chat") or TaskRoute([Target("ollama")])
        local_only = route.local_only or not request.allow_cloud
        is_local = lambda name: name in self.providers and self.providers[name].is_local

        if request.provider:                                   # explicit per-call override
            targets = [Target(request.provider, request.model)]
        elif s.selection == "auto":
            targets = list(route.targets)
        else:                                                  # user picked a provider
            chosen = [t for t in route.targets if t.provider == s.selection] or [Target(s.selection)]
            rest = [t for t in route.targets if t.provider != s.selection]
            # A cloud selection only keeps the route's other targets (e.g. Ollama) as
            # fallbacks when fallback_to_local is on; a local selection stays local-only.
            targets = chosen + (rest if (s.fallback_to_local and not is_local(s.selection)) else [])

        if local_only:
            targets = [t for t in targets if is_local(t.provider)]
            if not targets:
                targets = [Target(self._first_local() or "ollama")]

        # Offline safety net: the local provider is always the last resort when allowed.
        local = self._first_local()
        if local and s.fallback_to_local and not any(is_local(t.provider) for t in targets):
            targets.append(Target(local))

        seen, out = set(), []
        for t in targets:
            key = (t.provider, t.model)
            if key not in seen:
                seen.add(key)
                out.append(t)
        return out

    # ------------------------------------------------------------------ execution
    def generate(self, request: LLMRequest) -> LLMResponse:
        s = self.snapshot()
        attempts: list[Attempt] = []

        for target in self.plan(request):
            provider = self.providers.get(target.provider)
            if provider is None:
                attempts.append(Attempt(target.provider, target.model or "?", "skipped",
                                        "provider not registered"))
                continue
            model = target.model or provider.default_model

            if not provider.is_configured():
                attempts.append(Attempt(provider.name, model, "skipped",
                                        "not configured (API key missing)"))
                continue
            reason = (self.tracker.cooldown_reason(provider.name, model)
                      or self.tracker.check_budget(provider.name, model,
                                                   s.limits.get(provider.name, {}).get(model)
                                                   or s.limits.get(provider.name, {}).get("*")))
            if reason:
                attempts.append(Attempt(provider.name, model, "skipped", reason))
                continue

            policy = s.retry.get(provider.name, RetryPolicy())
            retries = 0

            def on_retry(n: int, delay: float, err: LLMError) -> None:
                nonlocal retries
                retries = n

            def one_try() -> LLMResponse:
                t0 = time.monotonic()
                try:
                    r = provider.generate(request, model)
                except LLMError as e:
                    self.tracker.record(provider.name, model, request.task, _outcome_of(e),
                                        latency_ms=int((time.monotonic() - t0) * 1000), error=str(e))
                    raise
                self.tracker.record(provider.name, model, request.task, "success",
                                    prompt_tokens=r.prompt_tokens, completion_tokens=r.completion_tokens,
                                    latency_ms=r.latency_ms)
                return r

            try:
                resp = call_with_retry(one_try, policy, sleep=self._sleep, rng=self._rng,
                                       on_retry=on_retry)
            except LLMError as e:
                self._apply_cooldown(provider, model, e)
                attempts.append(Attempt(provider.name, model, _outcome_of(e), str(e), retries=retries))
                continue
            except Exception as e:                      # provider bug: don't take MIMO down
                self.tracker.record(provider.name, model, request.task, "error",
                                    error=f"{type(e).__name__}: {e}")
                attempts.append(Attempt(provider.name, model, "error",
                                        f"unexpected {type(e).__name__}", retries=retries))
                continue

            attempts.append(Attempt(provider.name, model, "success", latency_ms=resp.latency_ms,
                                    retries=retries))
            resp.attempts = attempts
            return resp

        summary = "; ".join(f"{a.provider}/{a.model}: {a.outcome} ({a.detail})" for a in attempts)
        raise AllProvidersFailedError(f"No model could answer. {summary}", attempts)

    def _apply_cooldown(self, provider: LLMProvider, model: str, e: LLMError) -> None:
        if provider.is_local:
            return                                   # never lock ourselves out of the offline fallback
        if isinstance(e, RateLimitError):
            if e.scope == "daily":
                secs = self.tracker.seconds_until_quota_reset()
            else:
                secs = max(e.retry_after or 0.0, 60.0)
            self.tracker.set_cooldown(provider.name, model, secs, "rate limited")
        elif isinstance(e, AuthError):
            self.tracker.set_cooldown(provider.name, model, 300, "auth problem")
        elif isinstance(e, ProviderUnavailableError):
            self.tracker.set_cooldown(provider.name, model, 15, "unavailable")

    # ------------------------------------------------------------------ conveniences
    def generate_text(self, prompt: str, system: Optional[str] = None, task: str = "chat",
                      **kw) -> str:
        return self.generate(LLMRequest.from_prompt(prompt, system, task=task, **kw)).text

    def status(self, live: bool = True) -> dict:
        s = self.snapshot()
        provs = {}
        for name, p in self.providers.items():
            info = {"local": p.is_local, "default_model": p.default_model,
                    "configured": p.is_configured()}
            if live:
                info.update(p.health())
            provs[name] = info
        return {
            "selection": s.selection,
            "fallback_to_local": s.fallback_to_local,
            "providers": provs,
            "routes": {t: {"targets": [{"provider": x.provider, "model": x.model} for x in r.targets],
                           "local_only": r.local_only} for t, r in s.routes.items()},
            "cooldowns": self.tracker.active_cooldowns(),
        }
