"""Tests for per-model reasoning_effort override in cron scheduler."""

import pytest


class TestCronPerModelReasoningConfig:
    """Test cron scheduler respects per-model reasoning overrides.

    Rather than spinning up a full CronScheduler (heavy), we verify the
    resolution logic by testing the helper directly against a config dict
    shaped the same way the scheduler reads it.
    """

    def test_per_model_override_resolves_for_cron_model(self):
        """The spelling-tolerant helper resolves the cron config's model."""
        from hermes_constants import resolve_per_model_reasoning_effort

        # Simulate cron scheduler config shape
        _cfg = {
            "model": {"default": "anthropic/claude-opus-4.5"},
            "agent": {
                "reasoning_effort": "medium",
                "reasoning_overrides": {
                    "anthropic/claude-opus-4.5": "xhigh",
                },
            },
        }
        _model_cfg = _cfg.get("model", {})
        _model = str(_model_cfg.get("default", "") or "").strip()
        _overrides = (_cfg.get("agent", {}) or {}).get("reasoning_overrides", {}) or {}

        result = resolve_per_model_reasoning_effort(_model, _overrides)
        assert result is not None
        assert result["effort"] == "xhigh"

    def test_cron_falls_back_to_global_when_no_override(self):
        """When no per-model override matches, global effort is used."""
        from hermes_constants import parse_reasoning_effort, resolve_per_model_reasoning_effort

        _cfg = {
            "model": {"default": "gpt-5"},
            "agent": {
                "reasoning_effort": "low",
                "reasoning_overrides": {
                    "anthropic/claude-opus-4.5": "xhigh",
                },
            },
        }
        _model = _cfg["model"]["default"]
        _overrides = _cfg["agent"]["reasoning_overrides"]

        per_model = resolve_per_model_reasoning_effort(_model, _overrides)
        assert per_model is None  # no match

        # Scheduler falls back to global
        effort = _cfg["agent"]["reasoning_effort"]
        result = parse_reasoning_effort(effort)
        assert result is not None
        assert result["effort"] == "low"


    def test_global_fallback_with_yaml_false(self):
        """YAML boolean False must reach parse_reasoning_effort uncoerced.

        Regression: str(... or "").strip() turned False into "", silently
        re-enabling thinking. The raw value must pass through so
        parse_reasoning_effort(False) returns {'enabled': False}.
        """
        from hermes_constants import parse_reasoning_effort, resolve_per_model_reasoning_effort

        _cfg = {
            "model": {"default": "gpt-5"},
            "agent": {
                "reasoning_effort": False,  # YAML boolean, not string
                "reasoning_overrides": {"claude-opus-4.5": "xhigh"},
            },
        }
        _model = _cfg["model"]["default"]
        _overrides = _cfg["agent"]["reasoning_overrides"]

        per_model = resolve_per_model_reasoning_effort(_model, _overrides)
        assert per_model is None  # no match

        # Scheduler global fallback — raw value, no coercion
        result = parse_reasoning_effort(
            _cfg.get("agent", {}).get("reasoning_effort", "")
        )
        assert result is not None
        assert result.get("enabled") is False


class TestCronFleetReasoningOverride:
    def test_cron_fleet_low_beats_agent_medium(self):
        from hermes_constants import resolve_cron_reasoning_config

        cfg = {
            "agent": {"reasoning_effort": "medium"},
            "cron": {"reasoning_effort": "low"},
        }
        result = resolve_cron_reasoning_config(cfg, "gpt-5", {})
        assert result == {"enabled": True, "effort": "low"}

    def test_monitor_job_defaults_to_thinking_off(self):
        from hermes_constants import resolve_cron_reasoning_config

        cfg = {
            "agent": {"reasoning_effort": "medium"},
            "cron": {"reasoning_effort": "low"},
        }
        result = resolve_cron_reasoning_config(
            cfg, "gpt-5", {"monitor_script": "workspace-delivery-monitor.sh"}
        )
        assert result == {"enabled": False}

    def test_job_pin_wins_over_monitor_default(self):
        from hermes_constants import resolve_cron_reasoning_config

        cfg = {"agent": {"reasoning_effort": "medium"}, "cron": {"reasoning_effort": "low"}}
        result = resolve_cron_reasoning_config(
            cfg,
            "gpt-5",
            {"monitor_script": "x.sh", "reasoning_effort": "low"},
        )
        assert result == {"enabled": True, "effort": "low"}

    def test_empty_cron_key_falls_through_to_agent(self):
        from hermes_constants import resolve_cron_reasoning_config

        cfg = {"agent": {"reasoning_effort": "high"}, "cron": {"reasoning_effort": ""}}
        result = resolve_cron_reasoning_config(cfg, "gpt-5", {})
        assert result == {"enabled": True, "effort": "high"}

    def test_fallback_model_keeps_monitor_none_pin(self):
        """A monitor job pinned to none stays off after a fallback swap."""
        from hermes_constants import (
            resolve_cron_reasoning_config,
            resolve_switched_model_reasoning_config,
        )

        cfg = {
            "agent": {
                "reasoning_effort": "medium",
                "reasoning_overrides": {
                    "grok-4.6": "high",
                    "gemini-3.5-flash": "low",
                },
            },
            "cron": {"reasoning_effort": "low"},
        }
        pin = resolve_cron_reasoning_config(
            cfg,
            "gemini-3.5-flash",
            {
                "monitor_script": "workspace-delivery-monitor.sh",
                "reasoning_effort": "none",
            },
        )
        assert pin == {"enabled": False}
        swapped = resolve_switched_model_reasoning_config(
            cfg, "grok-4.6", pin=pin
        )
        assert swapped == {"enabled": False}

    def test_fallback_may_lower_but_not_raise_pin(self):
        from hermes_constants import resolve_switched_model_reasoning_config

        pin = {"enabled": True, "effort": "low"}
        raised = {
            "agent": {
                "reasoning_effort": "medium",
                "reasoning_overrides": {"gpt-5": "high"},
            }
        }
        lowered = {
            "agent": {
                "reasoning_effort": "medium",
                "reasoning_overrides": {"gpt-5": "none"},
            }
        }
        assert resolve_switched_model_reasoning_config(
            raised, "gpt-5", pin=pin
        ) == pin
        assert resolve_switched_model_reasoning_config(
            lowered, "gpt-5", pin=pin
        ) == {"enabled": False}


class TestNormalizeJobReasoningEffort:
    def test_none_and_false(self):
        from cron.jobs import _normalize_job_reasoning_effort

        assert _normalize_job_reasoning_effort(None) is None
        assert _normalize_job_reasoning_effort("") is None
        assert _normalize_job_reasoning_effort(False) == "none"
        assert _normalize_job_reasoning_effort("none") == "none"
        assert _normalize_job_reasoning_effort("low") == "low"

    def test_unknown_raises(self):
        from cron.jobs import _normalize_job_reasoning_effort

        with pytest.raises(ValueError, match="invalid reasoning_effort"):
            _normalize_job_reasoning_effort("hyperthink")
