"""Gateway runtime-metadata footer.

Renders a compact footer showing runtime state (model, context %, cwd) and
appends it to the FINAL message of an agent turn when enabled.  Off by default
except Telegram, which shows ``AI: {profile} · {model}`` and the four
non-overlapping provider usage buckets for the current reply.

Config (``~/.hermes/config.yaml``)::

    display:
      runtime_footer:
        enabled: true                       # off by default
        fields: [model, context_pct, cwd]   # order shown; drop any to hide

Available fields:
    profile      — active Hermes profile name (``proposal_lead``)
    model        — bare model id, vendor prefix dropped (``gpt-5.4``)
    turn_tokens  — provider-reported input + cache + output for this reply
    turn_token_breakdown — uncached input/output and cached input read/write
    cache_read_tokens — cached input included in turn_tokens (opt-in)
    context_pct  — last-call context occupancy as a percent (``5%``)
    latency      — wall-clock duration of the turn (``22s``, ``1m05s``)
    cwd          — home-relative working dir (``~``)

``latency`` is opt-in: it is NOT in the default field set, so a footer whose
``fields`` are unset renders exactly as before.

Per-platform overrides live under ``display.platforms.<platform>.runtime_footer``.
Users can toggle the global setting with ``/footer on|off`` from both the CLI
and any gateway platform.

On Telegram the footer is a short trailing message, whether the answer was
streamed or sent at once. This keeps a stable message ID for editing the
footer when causally linked work finishes after the answer. Other platforms
append the footer to the final answer text for non-streamed delivery.
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Optional
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

_DEFAULT_FIELDS: tuple[str, ...] = ("model", "context_pct", "cwd")
_TELEGRAM_DEFAULT_FIELDS: tuple[str, ...] = ("profile", "model", "turn_token_breakdown", "api_equivalent_cost")
_SEP = " · "


def format_turn_token_breakdown(usage: dict[str, int] | None) -> str:
    """Show the four canonical, non-overlapping provider usage buckets."""
    if not usage:
        return ""
    amounts = {
        key: max(0, int(usage.get(key, 0) or 0))
        for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
    }
    return _SEP.join((
        f"비캐시 입력 {amounts['input_tokens']:,}",
        f"비캐시 출력 {amounts['output_tokens']:,}",
        f"캐시 읽기 입력 {amounts['cache_read_tokens']:,}",
        f"캐시 저장 입력 {amounts['cache_write_tokens']:,}",
    ))


def format_api_equivalent_cost(cost_usd: str | None) -> str:
    """Format API list-price equivalent using the catalog's ECB reference rate."""
    if cost_usd is None:
        return "API 환산 미확인"
    try:
        from agent.api_equivalent_cost import load_catalog
        usd = Decimal(str(cost_usd))
        krw_rate = Decimal(str(load_catalog()["fx"]["krw_per_usd"]))
        if usd < 0 or krw_rate <= 0:
            return "API 환산 미확인"
        precision = (Decimal("0.000001") if usd < Decimal("0.0001")
                     else Decimal("0.0001") if usd < Decimal("1")
                     else Decimal("0.01"))
        usd_display = usd.quantize(precision, rounding=ROUND_HALF_UP)
        krw_display = (usd * krw_rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"API 환산 약 ${usd_display:,.{abs(precision.as_tuple().exponent)}f} (약 ₩{krw_display:,})"
    except (KeyError, ValueError, TypeError, InvalidOperation):
        return "API 환산 미확인"


def _home_relative_cwd(cwd: str) -> str:
    """Return *cwd* with ``$HOME`` collapsed to ``~``.  Empty string if unset."""
    if not cwd:
        return ""
    try:
        home = os.path.expanduser("~")
        p = os.path.abspath(cwd)
        if home and (p == home or p.startswith(home + os.sep)):
            return "~" + p[len(home):]
        return p
    except Exception:
        return cwd


def _model_short(model: Optional[str]) -> str:
    """Drop ``vendor/`` prefix for readability (``openai/gpt-5.4`` → ``gpt-5.4``)."""
    if not model:
        return ""
    return model.rsplit("/", 1)[-1]


def resolve_footer_config(
    user_config: dict[str, Any] | None,
    platform_key: str | None = None,
) -> dict[str, Any]:
    """Resolve effective runtime-footer config for *platform_key*.

    Merge order (later wins):
        1. Built-in defaults (enabled=False)
        2. ``display.runtime_footer``
        3. ``display.platforms.<platform_key>.runtime_footer``
    """
    resolved = {"enabled": False, "fields": list(_DEFAULT_FIELDS), "label": ""}
    if platform_key == "telegram":
        # Telegram replies otherwise look anonymous across profile gateways
        # and fallback models. Quiet: profile + model only, no cwd/%.
        resolved = {
            "enabled": True,
            "fields": list(_TELEGRAM_DEFAULT_FIELDS),
            "label": "AI",
        }
    cfg = (user_config or {}).get("display") or {}

    global_cfg = cfg.get("runtime_footer")
    if isinstance(global_cfg, dict):
        if "enabled" in global_cfg:
            resolved["enabled"] = bool(global_cfg.get("enabled"))
        if isinstance(global_cfg.get("fields"), list) and global_cfg["fields"]:
            resolved["fields"] = [str(f) for f in global_cfg["fields"]]
        if "label" in global_cfg:
            resolved["label"] = str(global_cfg.get("label") or "")

    if platform_key:
        platforms = cfg.get("platforms") or {}
        plat_cfg = platforms.get(platform_key)
        if isinstance(plat_cfg, dict):
            plat_footer = plat_cfg.get("runtime_footer")
            if isinstance(plat_footer, dict):
                if "enabled" in plat_footer:
                    resolved["enabled"] = bool(plat_footer.get("enabled"))
                if isinstance(plat_footer.get("fields"), list) and plat_footer["fields"]:
                    resolved["fields"] = [str(f) for f in plat_footer["fields"]]
                if "label" in plat_footer:
                    resolved["label"] = str(plat_footer.get("label") or "")

    return resolved


def _format_latency(seconds: float) -> str:
    """Humanize a turn duration: ``<1s``, ``22s``, ``1m05s``."""
    if seconds < 1:
        return "<1s"
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    m, sec = divmod(total, 60)
    return f"{m}m{sec:02d}s"


def format_runtime_footer(
    *,
    model: Optional[str],
    context_tokens: int,
    context_length: Optional[int],
    cwd: Optional[str] = None,
    turn_seconds: Optional[float] = None,
    profile: Optional[str] = None,
    turn_usage: Optional[dict[str, int]] = None,
    api_equivalent_cost_usd: Optional[str] = None,
    fields: Iterable[str] = _DEFAULT_FIELDS,
    label: str = "",
) -> str:
    """Render the footer line, or return "" if no fields have data.

    Fields are skipped silently when their underlying data is missing — a
    partially-populated footer is better than a line with ``?%`` or empty slots.
    """
    parts: list[str] = []
    for field in fields:
        if field == "profile":
            p = (
                profile
                or os.environ.get("HERMES_PROFILE")
                or os.environ.get("HERMES_PROFILE_NAME")
                or ""
            ).strip()
            if p:
                parts.append(p)
        elif field == "model":
            m = _model_short(model)
            if m:
                parts.append(m)
        elif field == "turn_tokens":
            usage = turn_usage or {}
            # Canonical input excludes cached reads; include both so the
            # displayed total covers the full provider-reported turn usage.
            total = sum(max(0, int(usage.get(key, 0) or 0)) for key in (
                "input_tokens", "cache_read_tokens", "cache_write_tokens",
                "output_tokens",
            ))
            if total:
                parts.append(f"{total:,} tokens")
        elif field == "turn_token_breakdown":
            breakdown = format_turn_token_breakdown(turn_usage)
            if breakdown:
                parts.append(breakdown)
        elif field == "api_equivalent_cost":
            if turn_usage:
                parts.append(format_api_equivalent_cost(api_equivalent_cost_usd))
        elif field == "cache_read_tokens":
            cached = max(0, int((turn_usage or {}).get("cache_read_tokens", 0) or 0))
            if cached:
                parts.append(f"cache-read {cached:,}")
        elif field == "context_pct":
            if context_length and context_length > 0 and context_tokens >= 0:
                pct = max(0, min(100, round((context_tokens / context_length) * 100)))
                parts.append(f"{pct}%")
        elif field == "latency":
            # Wall-clock turn duration. Skipped when the caller supplied no
            # timing (call sites that don't measure) or the value is negative.
            if turn_seconds is not None and turn_seconds >= 0:
                parts.append(_format_latency(turn_seconds))
        elif field == "cwd":
            rel = _home_relative_cwd(cwd or os.environ.get("TERMINAL_CWD", ""))
            if rel:
                parts.append(rel)
        # Unknown field names are silently ignored.

    if not parts:
        return ""
    line = _SEP.join(parts)
    prefix = str(label or "").strip()
    if prefix:
        return f"{prefix}: {line}"
    return line


def build_footer_line(
    *,
    user_config: dict[str, Any] | None,
    platform_key: str | None,
    model: Optional[str],
    context_tokens: int,
    context_length: Optional[int],
    cwd: Optional[str] = None,
    turn_seconds: Optional[float] = None,
    profile: Optional[str] = None,
    turn_usage: Optional[dict[str, int]] = None,
    api_equivalent_cost_usd: Optional[str] = None,
) -> str:
    """Top-level entry point used by gateway/run.py.

    Returns the footer text (empty string when disabled or no data).  Callers
    append this to the final response themselves, preserving a single blank
    line of separation.

    ``turn_seconds`` is the wall-clock duration of the agent run, measured by
    the caller with ``time.monotonic()``.  Callers that don't measure it leave
    it ``None`` and the ``latency`` field is skipped.
    """
    cfg = resolve_footer_config(user_config, platform_key)
    if not cfg.get("enabled"):
        return ""
    return format_runtime_footer(
        model=model,
        context_tokens=context_tokens,
        context_length=context_length,
        cwd=cwd,
        turn_seconds=turn_seconds,
        profile=profile,
        turn_usage=turn_usage,
        api_equivalent_cost_usd=api_equivalent_cost_usd,
        fields=cfg.get("fields") or _DEFAULT_FIELDS,
        label=str(cfg.get("label") or ""),
    )
