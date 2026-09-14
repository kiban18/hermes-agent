"""API list-price estimates use actual provider calls and canonical buckets."""

from decimal import Decimal
from types import SimpleNamespace

from agent.api_equivalent_cost import call_cost_usd, record_call_cost, verified_turn_cost
from gateway.runtime_footer import format_api_equivalent_cost, format_runtime_footer


def usage(input_=0, output=0, read=0, write=0):
    return SimpleNamespace(input_tokens=input_, output_tokens=output,
                           cache_read_tokens=read, cache_write_tokens=write)


def test_all_routed_model_families_are_priced():
    calls = [("xai-oauth", "grok-4.6"),
             ("anthropic", "claude-sonnet-4-6"),
             ("anthropic", "claude-opus-5"),
             ("openai-codex", "gpt-5.6-sol"),
             ("openai-codex", "gpt-5.6-terra"),
             ("openai-codex", "gpt-5.6-luna"),
             ("gemini-oauth", "gemini-3.5-flash")]
    for provider, model in calls:
        assert call_cost_usd(provider, model, usage(1000, 100, 1000), 2000) > 0


def test_tier_applies_per_call_and_fallback_models_add():
    agent = SimpleNamespace()
    record_call_cost(agent, usage(1000, 100, 199_000),
                     provider="xai-oauth", model="grok-4.6", prompt_tokens=200_000)
    record_call_cost(agent, usage(1000, 100),
                     provider="anthropic", model="claude-sonnet-4-6", prompt_tokens=1000)
    assert agent._api_equivalent_cost_usd == Decimal("0.2087")


def test_unknown_rate_does_not_become_zero():
    assert call_cost_usd("unknown", "new-model", usage(1000), 1000) is None
    assert call_cost_usd("xai-oauth", "grok-4.6", usage(write=1), 1) is None
    assert call_cost_usd("gemini-oauth", "gemini-3.5-flash", usage(write=1), 1) is None


def test_krw_footer_uses_ecb_rate_and_marks_unknown():
    assert format_api_equivalent_cost("1") == "API 환산 약 $1.00 (약 ₩1,343)"
    assert format_api_equivalent_cost(None) == "API 환산 미확인"
    footer = format_runtime_footer(
        model="claude-sonnet-4-6", context_tokens=0, context_length=None,
        turn_usage={"input_tokens": 1}, api_equivalent_cost_usd="0.001",
        fields=("model", "api_equivalent_cost"), label="AI")
    assert footer == "AI: claude-sonnet-4-6 · API 환산 약 $0.0010 (약 ₩1)"


def test_per_call_cost_is_durable_for_kanban_completion(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    agent = SimpleNamespace(session_id="20260913_test123")
    record_call_cost(agent, usage(1000, 100, 199_000),
                     provider="xai-oauth", model="grok-4.6", prompt_tokens=200_000)
    path = tmp_path / "usage" / "model_calls" / "20260913_test123.jsonl"
    row = json.loads(path.read_text().strip())
    assert row["api_equivalent_cost_usd"] == "0.2042"
    assert row["cache_read_tokens"] == 199_000


def test_verified_turn_cost_recovers_only_exact_priced_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    turn_id = "a" * 32
    agent = SimpleNamespace(session_id="20260913_test123", _usage_probe_turn_id=turn_id)
    record_call_cost(agent, usage(799, 321, 270_336),
                     provider="xai-oauth", model="grok-4.6", prompt_tokens=271_135)
    record_call_cost(agent, usage(755, 598, 271_104),
                     provider="xai-oauth", model="grok-4.6", prompt_tokens=271_859)
    totals = {"api_calls": 2, "input_tokens": 1554, "output_tokens": 919,
              "cache_read_tokens": 541_440, "cache_write_tokens": 0}
    assert verified_turn_cost(tmp_path, agent.session_id, turn_id, totals) == Decimal("0.558684")
    assert verified_turn_cost(tmp_path, agent.session_id, turn_id,
                              {**totals, "cache_read_tokens": 541_439}) is None
    assert verified_turn_cost(tmp_path, agent.session_id, "b" * 32, totals) is None
