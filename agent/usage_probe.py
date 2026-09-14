"""Content-free request-shape measurements for opted-in gateway turns.

Provider usage is exact as reported; component token counts are local rough
estimates. No prompt, tool argument, response, or account identifier is saved.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from agent.model_metadata import (
    _estimate_tools_tokens_rough,
    estimate_messages_tokens_rough,
)


def request_shape(messages: list[dict[str, Any]],
                  tools: list[dict[str, Any]]) -> dict[str, int]:
    """Estimate mutually exclusive request buckets before transport encoding."""
    buckets = {"system": 0, "tool_result": 0, "other_message": 0}
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        bucket = ("system" if role == "system" else
                  "tool_result" if role == "tool" else "other_message")
        buckets[bucket] += estimate_messages_tokens_rough([message])
    return {
        "system_tokens_estimate": buckets["system"],
        "tool_result_tokens_estimate": buckets["tool_result"],
        "other_message_tokens_estimate": buckets["other_message"],
        "tool_schema_tokens_estimate": _estimate_tools_tokens_rough(tools),
        "message_count": len(messages),
        "tool_count": len(tools),
    }


def append_model_call_usage(
    *, home: str | Path, turn_id: str, session_id: str,
    phase: str, profile: str, model: str, provider: str,
    call_index: int, prompt_tokens: int, output_tokens: int,
    input_tokens: int, cache_read_tokens: int, cache_write_tokens: int,
    duration_seconds: float, messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> None:
    """Append one successful provider call. Caller must opt in explicitly."""
    if not turn_id or not session_id:
        return
    row = {
        "timestamp": time.time(),
        "turn_id": turn_id,
        "session_id": session_id,
        "phase": phase,
        "profile": profile,
        "task": "foreground",
        "model": model,
        "provider": provider,
        "call_index": max(1, int(call_index)),
        "prompt_tokens": max(0, int(prompt_tokens)),
        "output_tokens": max(0, int(output_tokens)),
        "input_tokens": max(0, int(input_tokens)),
        "cache_read_tokens": max(0, int(cache_read_tokens)),
        "cache_write_tokens": max(0, int(cache_write_tokens)),
        "duration_seconds": round(max(0.0, duration_seconds), 3),
        **request_shape(messages, tools),
    }
    path = Path(home) / "logs" / "model_call_usage.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)
