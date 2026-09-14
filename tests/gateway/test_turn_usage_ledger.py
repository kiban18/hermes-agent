import json

from gateway.turn_usage_ledger import append_turn_usage, usage_phase_from_home


def test_turn_usage_ledger_records_turn_without_message_content(tmp_path):
    append_turn_usage(
        home=tmp_path, session_id="s1", source="telegram",
        profile="project_lead", model="glm-5.3",
        usage={"input_tokens": 100, "cache_read_tokens": 200,
               "cache_write_tokens": 0, "output_tokens": 30,
               "api_calls": 2},
        failed=False, elapsed_seconds=3.2, phase="asis",
        last_prompt_tokens=230, context_length=1000,
        tool_count=2, tool_schema_tokens_estimate=65,
        turn_id="turn-1",
    )
    path = tmp_path / "logs" / "turn_usage.jsonl"
    row = json.loads(path.read_text())
    assert row["phase"] == "asis"
    assert row["turn_id"] == "turn-1"
    assert row["input_tokens"] == 100
    assert row["cache_read_tokens"] == 200
    assert row["api_calls"] == 2
    assert row["task"] == "foreground"
    assert row["last_prompt_tokens"] == 230
    assert row["tool_count"] == 2
    assert row["tool_schema_tokens_estimate"] == 65
    assert "content" not in row and "chat_id" not in row


def test_usage_phase_reads_profile_config(tmp_path):
    (tmp_path / "config.yaml").write_text("usage_evaluation:\n  phase: tobe\n")
    assert usage_phase_from_home(tmp_path) == "tobe"
    (tmp_path / "config.yaml").write_text("usage_evaluation:\n  phase: invalid\n")
    assert usage_phase_from_home(tmp_path) is None
