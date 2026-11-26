"""One policy-checked dispatch boundary for effects.

Authorization has to be asked where an effect actually starts, not only on the route
that happened to receive the request. `/chat` classifies an intent and then reaches the
same tools and memory mutations that the dedicated routes expose, so it needs the same
answers. This module maps a capability to the scope that grants it and exposes one
`ActionPolicy` that both paths use.

Rules:
* A paired device may dispatch a capability only when its scopes include the mapped one.
* No device at all is allowed only when authentication is switched off (development
  mode); with authentication on, the gate would already have rejected the request, and
  the policy denies anyway rather than trusting the gate to have run first.
"""
from __future__ import annotations

from typing import Optional

from .tokens import has_scope

# Capability -> the single scope that grants it. Coarse on purpose: one question per
# effect, answered in one place.
CAPABILITY_SCOPES: dict[str, str] = {
    "tool.invoke": "agent:run",     # run a tool/mutation on the user's behalf
    "memory.read": "memory:read",   # show or use personal memories
    "memory.write": "memory:write", # save or forget a memory
}


class ActionDenied(Exception):
    """A capability was requested that the caller's device does not hold."""

    def __init__(self, capability: str, scope: str):
        self.capability = capability
        self.scope = scope
        super().__init__(f"This device is not allowed to {capability} "
                         f"(needs '{scope}').")

    def to_dict(self) -> dict:
        return {"detail": str(self), "capability": self.capability, "required_scope": self.scope}


class ActionPolicy:
    """Answers one question: may this caller dispatch this capability?"""

    def __init__(self, device: Optional[dict], auth_required: bool = False):
        self.device = device
        self.auth_required = auth_required

    def allows(self, capability: str) -> bool:
        scope = CAPABILITY_SCOPES[capability]
        if self.device is None:
            return not self.auth_required
        return has_scope(self.device.get("scopes") or (), scope)

    def require(self, capability: str) -> None:
        if not self.allows(capability):
            raise ActionDenied(capability, CAPABILITY_SCOPES[capability])
