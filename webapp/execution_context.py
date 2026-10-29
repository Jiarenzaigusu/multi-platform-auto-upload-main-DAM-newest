"""Verified browser-to-agent routing, scoped to one HTTP request."""
from contextvars import ContextVar

verified_agent_id: ContextVar[str | None] = ContextVar("mpau_verified_agent_id", default=None)
verified_agent_binding: ContextVar[str | None] = ContextVar("mpau_verified_agent_binding", default=None)


class AgentTargetError(ValueError):
    pass
