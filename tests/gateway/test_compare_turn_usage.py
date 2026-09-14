"""AS-IS/TO-BE reports must not hide auxiliary usage in reply totals."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "compare_turn_usage.py"
spec = importlib.util.spec_from_file_location("compare_turn_usage", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_summarize_separates_foreground_review_and_quality(tmp_path):
    log = tmp_path / "profiles" / "project_lead" / "logs" / "turn_usage.jsonl"
    log.parent.mkdir(parents=True)
    rows = [
        {"turn_id": "a", "phase": "asis", "profile": "project_lead",
         "input_tokens": 10, "cache_read_tokens": 90, "cache_write_tokens": 20,
         "output_tokens": 5, "api_calls": 2, "elapsed_seconds": 3},
        {"turn_id": "b", "phase": "asis", "profile": "project_lead",
         "task": "background_review", "input_tokens": 1,
         "cache_read_tokens": 199, "api_calls": 4},
        {"turn_id": "c", "phase": "tobe", "profile": "project_lead",
         "task": "foreground", "input_tokens": 10,
         "cache_read_tokens": 30, "output_tokens": 5, "api_calls": 1},
    ]
    log.write_text("".join(json.dumps(row) + "\n" for row in rows))
    calls = log.with_name("model_call_usage.jsonl")
    calls.write_text("".join(json.dumps(row) + "\n" for row in [
        {"turn_id": "a", "call_index": 1, "prompt_tokens": 100,
         "source": "legacy_agent_log"},
        {"turn_id": "c", "call_index": 1, "prompt_tokens": 40,
         "system_tokens_estimate": 12, "tool_schema_tokens_estimate": 20,
         "tool_result_tokens_estimate": 0, "other_message_tokens_estimate": 8},
        {"turn_id": "c", "call_index": 2, "prompt_tokens": 50,
         "system_tokens_estimate": 12, "tool_schema_tokens_estimate": 20,
         "tool_result_tokens_estimate": 10, "other_message_tokens_estimate": 8},
    ]))
    labels = tmp_path / "labels.csv"
    with labels.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            "turn_id", "accurate", "complete", "action_appropriate"
        ])
        writer.writeheader()
        writer.writerows([
            {"turn_id": "a", "accurate": "1", "complete": "1",
             "action_appropriate": "0"},
            {"turn_id": "c", "accurate": "0", "complete": "1",
             "action_appropriate": "1"},
        ])

    result = module.summarize(tmp_path, labels, "project_lead")
    by_key = {(row["phase"], row["task"]): row for row in result}
    assert by_key[("asis", "foreground")]["gross_tokens"] == 125
    assert by_key[("asis", "foreground")]["noncached_tokens"] == 35
    assert by_key[("asis", "foreground")]["accuracy_pct"] == 100
    assert by_key[("asis", "foreground")]["action_appropriateness_pct"] == 0
    assert by_key[("asis", "background_review")]["gross_tokens"] == 200
    assert by_key[("tobe", "foreground")]["median_gross_tokens"] == 45
    assert by_key[("tobe", "foreground")]["accuracy_pct"] == 0
    assert by_key[("tobe", "foreground")]["completeness_pct"] == 100
    assert by_key[("tobe", "foreground")]["instrumented_calls"] == 2
    assert by_key[("tobe", "foreground")]["shape_instrumented_turns"] == 1
    assert by_key[("tobe", "foreground")]["median_first_prompt_tokens"] == 40
    assert by_key[("tobe", "foreground")]["median_prompt_growth_tokens"] == 10
    assert by_key[("tobe", "foreground")]["median_first_tool_schema_tokens_estimate"] == 20
    assert by_key[("asis", "foreground")]["median_first_prompt_tokens"] == 100
    assert by_key[("asis", "foreground")].get("shape_instrumented_turns", 0) == 0
    assert "median_first_tool_schema_tokens_estimate" not in by_key[("asis", "foreground")]
