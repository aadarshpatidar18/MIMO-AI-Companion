"""Exponential backoff with jitter that honours server Retry-After hints."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Callable, Optional, TypeVar

from .errors import LLMError, ProviderUnavailableError, RateLimitError

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3          # total tries, including the first
    base_delay: float = 1.0        # seconds; doubles each retry
    max_delay: float = 8.0
    max_total_wait: float = 15.0   # never block a user request longer than this
    jitter: float = 0.25           # +/- fraction applied to the backoff


def compute_delay(policy: RetryPolicy, retry_index: int,
                  retry_after: Optional[float], rng: random.Random) -> float:
    backoff = min(policy.max_delay, policy.base_delay * (2 ** retry_index))
    backoff *= 1 + rng.uniform(-policy.jitter, policy.jitter)
    # A server hint is a floor: never retry sooner than it asked.
    return max(backoff, retry_after or 0.0)


def call_with_retry(
    fn: Callable[[], T],
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], None] = time.sleep,
    rng: Optional[random.Random] = None,
    on_retry: Optional[Callable[[int, float, LLMError], None]] = None,
) -> T:
    """Run fn, retrying 429s and retryable outages with exponential backoff.

    Gives up immediately (raising the last error) when:
      * the quota is daily-exhausted,
      * the error is not retryable,
      * the next wait would push total waiting past policy.max_total_wait
        (the router then falls back instead of making the user wait).
    """
    rng = rng or random.Random()
    waited = 0.0
    for attempt in range(policy.max_attempts):
        try:
            return fn()
        except RateLimitError as e:
            err: LLMError = e
            retry_after = e.retry_after
            if e.scope == "daily":
                raise
        except ProviderUnavailableError as e:
            if not e.retryable:
                raise
            err, retry_after = e, None
        if attempt == policy.max_attempts - 1:
            raise err
        delay = compute_delay(policy, attempt, retry_after, rng)
        if waited + delay > policy.max_total_wait:
            raise err
        if on_retry:
            on_retry(attempt + 1, delay, err)
        sleep(delay)
        waited += delay
    raise RuntimeError("unreachable")  # pragma: no cover
