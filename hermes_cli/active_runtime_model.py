"""Last-known agent model for the current process/context.

Kanban workers are one agent per process. Gateway sessions can overlap, so
the ContextVar is preferred and the process copy is a fallback for tool
threads that do not inherit the context.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

_active_model: ContextVar[Optional[str]] = ContextVar(
    "hermes_active_runtime_model", default=None,
)
_last_model: Optional[str] = None


def short_runtime_model(model: str | None) -> Optional[str]:
    text = str(model or "").strip()
    if not text:
        return None
    if "/" in text and not text.startswith(("http://", "https://")):
        text = text.rsplit("/", 1)[-1]
    return text or None


def note_active_runtime_model(model: str | None) -> None:
    """Record the model the current agent is actually running."""
    global _last_model
    label = short_runtime_model(model)
    _active_model.set(label)
    _last_model = label


def get_active_runtime_model() -> Optional[str]:
    return _active_model.get() or _last_model
