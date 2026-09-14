"""Per-provider-call API list-price equivalent, independent of subscription billing.

The catalog is refreshed out of band. Request handling never contacts price
sites, and an unknown model/rate never silently becomes a zero-dollar cost.
"""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parents[2] / "pricing" / "catalog.json"
_CACHE: tuple[int, dict[str, Any]] | None = None
_MILLION = Decimal(1_000_000)


def load_catalog() -> dict[str, Any]:
    global _CACHE
    try:
        mtime = CATALOG_PATH.stat().st_mtime_ns
        if _CACHE and _CACHE[0] == mtime:
            return _CACHE[1]
        data = json.loads(CATALOG_PATH.read_text())
        if data.get("version") != 1 or not isinstance(data.get("models"), dict):
            return {}
        _CACHE = (mtime, data)
        return data
    except (OSError, ValueError, TypeError):
        return {}


def canonical_key(provider: str | None, model: str | None) -> str:
    family = (provider or "").lower()
    family = {"xai-oauth": "xai", "openai-codex": "openai",
              "gemini-oauth": "google", "google": "google"}.get(family, family)
    name = (model or "").lower().rsplit("/", 1)[-1]
    return f"{family}/{name}"


def call_cost_usd(provider: str | None, model: str | None, usage: Any,
                  prompt_tokens: int) -> Decimal | None:
    model_data = load_catalog().get("models", {}).get(canonical_key(provider, model))
    if not model_data:
        return None
    tiers = model_data.get("tiers") or []
    eligible = [x for x in tiers if int(x.get("min_prompt_tokens", 0)) <= prompt_tokens]
    if not eligible:
        return None
    selected = max(eligible, key=lambda x: int(x["min_prompt_tokens"]))
    total = Decimal(0)
    try:
        for bucket, rate_name in (("input_tokens", "input"),
                                  ("output_tokens", "output"),
                                  ("cache_read_tokens", "cache_read"),
                                  ("cache_write_tokens", "cache_write")):
            count = max(0, int(getattr(usage, bucket, 0) or 0))
            rate = selected.get(rate_name)
            if count and rate is None:
                return None
            if rate is not None:
                total += Decimal(count) * Decimal(str(rate)) / _MILLION
    except (ValueError, TypeError, InvalidOperation):
        return None
    return total


def record_call_cost(agent: Any, usage: Any, *, provider: str | None,
                     model: str | None, prompt_tokens: int) -> None:
    """Accumulate before/after deltas for a gateway turn, including fallbacks."""
    value = call_cost_usd(provider, model, usage, prompt_tokens)
    if value is None:
        agent._api_equivalent_unknown_calls = (
            getattr(agent, "_api_equivalent_unknown_calls", 0) + 1
        )
    else:
        agent._api_equivalent_cost_usd = (
            getattr(agent, "_api_equivalent_cost_usd", Decimal(0)) + value
        )
    # A Kanban worker exits before its completion watcher runs. Persist the
    # per-call price (including the request's pricing tier) so a retry's usage
    # can be reported without repricing an aggregated session at one tier.
    session_id = str(getattr(agent, "session_id", "") or "")
    home = os.environ.get("HERMES_HOME", "")
    if not home or not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", session_id):
        return
    try:
        folder = Path(home) / "usage" / "model_calls"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{session_id}.jsonl"
        row = {
            "provider": provider, "model": model,
            "turn_id": str(getattr(agent, "_usage_probe_turn_id", "") or ""),
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "cache_read_tokens": int(getattr(usage, "cache_read_tokens", 0) or 0),
            "cache_write_tokens": int(getattr(usage, "cache_write_tokens", 0) or 0),
            "prompt_tokens": prompt_tokens,
            "api_equivalent_cost_usd": str(value) if value is not None else None,
        }
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (json.dumps(row, ensure_ascii=False) + "\n").encode())
        finally:
            os.close(fd)
    except (OSError, TypeError, ValueError):
        # Cost display remains available in memory; a write failure must not
        # interrupt a model response.
        pass


def verified_turn_cost(home: Path, session_id: str, turn_id: str,
                       turn_usage: dict[str, int]) -> Decimal | None:
    """Recover a turn price only when its priced call ledger matches the footer."""
    if not (re.fullmatch(r"[A-Za-z0-9_-]{8,100}", session_id)
            and re.fullmatch(r"[0-9a-f]{32}", turn_id)):
        return None
    path = home / "usage" / "model_calls" / f"{session_id}.jsonl"
    buckets = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        calls = [row for row in rows if row.get("turn_id") == turn_id]
        if len(calls) != int(turn_usage.get("api_calls") or 0) or not calls:
            return None
        if any(sum(int(row.get(bucket) or 0) for row in calls)
               != int(turn_usage.get(bucket) or 0) for bucket in buckets):
            return None
        prices = [Decimal(str(row["api_equivalent_cost_usd"])) for row in calls]
        return sum(prices, Decimal(0)) if all(price >= 0 for price in prices) else None
    except (OSError, ValueError, TypeError, KeyError, InvalidOperation):
        return None
