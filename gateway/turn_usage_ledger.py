"""Best-effort, content-free per-turn usage ledger for gateway comparisons."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any


def usage_phase_from_home(home: str | Path) -> str | None:
    """Read the local evaluation label without exposing config contents."""
    try:
        import yaml

        config = yaml.safe_load((Path(home) / "config.yaml").read_text()) or {}
        evaluation = config.get("usage_evaluation") or {}
        if isinstance(evaluation, dict):
            phase = evaluation.get("phase")
            if phase in {"asis", "tobe"}:
                return phase
    except Exception:  # best-effort measurement must not affect the reply
        pass
    return None


def append_turn_usage(
    *, home: str | Path, session_id: str, source: str,
    profile: str | None, model: str | None, usage: dict[str, Any] | None,
    failed: bool, elapsed_seconds: float | None, phase: str | None = None,
    task: str = "foreground", last_prompt_tokens: int = 0,
    context_length: int = 0, tool_count: int = 0,
    tool_schema_tokens_estimate: int = 0,
    turn_id: str | None = None,
) -> None:
    """Append one measured reply without text or account identifiers.

    Failure to write must never prevent delivery of the reply.
    """
    values = usage or {}
    row = {
        "turn_id": turn_id or uuid.uuid4().hex,
        "timestamp": time.time(),
        "phase": phase or os.environ.get("HERMES_USAGE_PHASE", "asis"),
        "task": task,
        "session_id": session_id,
        "source": source,
        "profile": profile or "",
        "model": model or "",
        "failed": bool(failed),
        "elapsed_seconds": (
            round(max(0.0, elapsed_seconds), 3)
            if elapsed_seconds is not None else None
        ),
        "last_prompt_tokens": max(0, int(last_prompt_tokens or 0)),
        "context_length": max(0, int(context_length or 0)),
        "tool_count": max(0, int(tool_count or 0)),
        "tool_schema_tokens_estimate": max(0, int(tool_schema_tokens_estimate or 0)),
    }
    for key in ("input_tokens", "cache_read_tokens", "cache_write_tokens",
                "output_tokens", "reasoning_tokens", "api_calls"):
        row[key] = max(0, int(values.get(key, 0) or 0))
    path = Path(home) / "logs" / "turn_usage.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)
