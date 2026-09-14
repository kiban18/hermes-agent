"""The opt-in request probe stores only numeric request shape and usage."""

import json

from agent.usage_probe import append_model_call_usage, request_shape


def test_request_shape_partitions_messages_without_content():
    messages = [
        {"role": "system", "content": "system rules " * 20},
        {"role": "user", "content": "question"},
        {"role": "tool", "content": "private tool result " * 20},
    ]
    tools = [{"type": "function", "function": {
        "name": "read_file", "description": "Read a file",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
    }}]
    shape = request_shape(messages, tools)
    assert shape["system_tokens_estimate"] > 0
    assert shape["tool_result_tokens_estimate"] > 0
    assert shape["other_message_tokens_estimate"] > 0
    assert shape["tool_schema_tokens_estimate"] > 0
    assert shape["message_count"] == 3
    assert shape["tool_count"] == 1


def test_model_call_ledger_joins_turn_without_persisting_prompt(tmp_path):
    append_model_call_usage(
        home=tmp_path, turn_id="turn-1", session_id="session-1",
        phase="tobe", profile="project_lead", model="grok-4.6",
        provider="xai-oauth", call_index=1, prompt_tokens=400,
        output_tokens=20, input_tokens=10, cache_read_tokens=390,
        cache_write_tokens=0, duration_seconds=1.5,
        messages=[{"role": "system", "content": "secret system text"},
                  {"role": "tool", "content": "secret tool result"}],
        tools=[{"type": "function", "function": {
            "name": "private_tool", "description": "secret schema text",
            "parameters": {"type": "object"}}}],
    )
    saved = (tmp_path / "logs" / "model_call_usage.jsonl").read_text()
    row = json.loads(saved)
    assert row["turn_id"] == "turn-1"
    assert row["prompt_tokens"] == 400
    assert row["cache_read_tokens"] == 390
    assert row["system_tokens_estimate"] > 0
    for private in ("secret system text", "secret tool result", "secret schema text"):
        assert private not in saved
