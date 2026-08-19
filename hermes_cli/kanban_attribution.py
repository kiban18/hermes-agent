"""Who last worked a kanban task — profile plus actual run model."""

from __future__ import annotations

from typing import Any, Optional

_PROFILE_MODEL_CACHE: dict[str, Optional[str]] = {}


def short_model_name(model: str | None) -> Optional[str]:
    text = str(model or "").strip()
    if not text:
        return None
    if "/" in text and not text.startswith(("http://", "https://")):
        text = text.rsplit("/", 1)[-1]
    return text or None


def profile_default_model(assignee: str | None) -> Optional[str]:
    name = str(assignee or "").strip()
    if not name:
        return None
    if name in _PROFILE_MODEL_CACHE:
        return _PROFILE_MODEL_CACHE[name]
    label = None
    try:
        from hermes_cli.profiles import _read_config_model, get_profile_dir

        model, _provider = _read_config_model(get_profile_dir(name))
        label = short_model_name(model)
    except Exception:
        label = None
    _PROFILE_MODEL_CACHE[name] = label
    return label


def resolve_task_model(
    task: Any,
    *,
    last_run_model: str | None = None,
) -> Optional[str]:
    """Model shown on the card.

    Last run's actual model wins (fallback/switch included). Until a run
    has stamped one, fall back to the task pin, then the current
    assignee profile default. This is not "who created the card".
    """
    last = short_model_name(last_run_model)
    if last:
        return last
    override = short_model_name(getattr(task, "model_override", None))
    if override:
        return override
    return profile_default_model(getattr(task, "assignee", None))


def format_worker_attribution(
    task: Any,
    *,
    last_run_model: str | None = None,
) -> str:
    """One line for Telegram. No @ prefix so Telegram does not treat it as a mention."""
    if task is None:
        return ""
    parts: list[str] = []
    assignee = str(getattr(task, "assignee", None) or "").strip()
    if assignee:
        parts.append(assignee)
    model = resolve_task_model(task, last_run_model=last_run_model)
    if model:
        parts.append(model)
    if not parts:
        return ""
    return "AI: " + " · ".join(parts)


def attach_worker_attribution(
    msg: str,
    task: Any,
    *,
    last_run_model: str | None = None,
) -> str:
    line = format_worker_attribution(task, last_run_model=last_run_model)
    if not line:
        return msg
    first, sep, rest = msg.partition("\n")
    if not sep:
        return f"{msg}\n{line}"
    return f"{first}\n{line}\n{rest}"
