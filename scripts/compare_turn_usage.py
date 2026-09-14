#!/usr/bin/env python3
"""Compare measured Hermes gateway turns across named AS-IS/TO-BE phases.

Reads content-free logs/turn_usage.jsonl from each profile. Optional quality
labels CSV columns: turn_id,accurate,complete,action_appropriate (1 or 0).
Labels require an independent acceptance check; this script never infers them.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import median


def summarize(root: Path, labels_path: Path | None = None,
              profile: str | None = None) -> list[dict]:
    groups = defaultdict(lambda: defaultdict(int))
    turn_totals = defaultdict(list)
    measured_turns = {}
    call_shapes = defaultdict(list)
    for path in [root / "logs" / "turn_usage.jsonl", *root.glob("profiles/*/logs/turn_usage.jsonl")]:
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            phase = row.get("phase") or "unlabeled"
            row_profile = row.get("profile") or ("main" if path.parent.parent == root else path.parent.parent.name)
            if profile and row_profile != profile:
                continue
            task = row.get("task") or "foreground"
            group_key = (phase, row_profile, task)
            if row.get("turn_id"):
                measured_turns[row["turn_id"]] = group_key
            group = groups[group_key]
            group["turns"] += 1
            group["failed"] += bool(row.get("failed"))
            if row.get("elapsed_seconds") is not None:
                group["elapsed_seconds"] += float(row["elapsed_seconds"])
                group["timed_turns"] += 1
            for key in ("api_calls", "input_tokens", "cache_read_tokens",
                        "cache_write_tokens", "output_tokens",
                        "last_prompt_tokens", "tool_schema_tokens_estimate"):
                group[key] += int(row.get(key) or 0)
            total = sum(int(row.get(key) or 0) for key in (
                "input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens"
            ))
            turn_totals[group_key].append(total)
    calls_by_turn = defaultdict(list)
    for path in [root / "logs" / "model_call_usage.jsonl",
                 *root.glob("profiles/*/logs/model_call_usage.jsonl")]:
        if not path.is_file():
            continue
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            turn_id = row.get("turn_id")
            if turn_id in measured_turns:
                calls_by_turn[turn_id].append(row)
    for turn_id, calls in calls_by_turn.items():
        group_key = measured_turns[turn_id]
        if group_key[2] != "foreground":
            continue
        calls.sort(key=lambda row: (int(row.get("call_index") or 0),
                                    float(row.get("timestamp") or 0)))
        first, last = calls[0], calls[-1]
        groups[group_key]["instrumented_turns"] += 1
        groups[group_key]["instrumented_calls"] += len(calls)
        if first.get("system_tokens_estimate") is not None:
            groups[group_key]["shape_instrumented_turns"] += 1
        call_shapes[group_key].append({
            "first_prompt_tokens": int(first.get("prompt_tokens") or 0),
            "last_prompt_tokens_exact": int(last.get("prompt_tokens") or 0),
            "peak_prompt_tokens": max(int(call.get("prompt_tokens") or 0)
                                      for call in calls),
            "prompt_growth_tokens": int(last.get("prompt_tokens") or 0)
                                    - int(first.get("prompt_tokens") or 0),
            "first_system_tokens_estimate": (
                int(first["system_tokens_estimate"])
                if first.get("system_tokens_estimate") is not None else None),
            "first_tool_schema_tokens_estimate": (
                int(first["tool_schema_tokens_estimate"])
                if first.get("tool_schema_tokens_estimate") is not None else None),
            "first_tool_result_tokens_estimate": (
                int(first["tool_result_tokens_estimate"])
                if first.get("tool_result_tokens_estimate") is not None else None),
            "first_other_message_tokens_estimate": (
                int(first["other_message_tokens_estimate"])
                if first.get("other_message_tokens_estimate") is not None else None),
        })
    if labels_path and labels_path.is_file():
        with labels_path.open(newline="") as stream:
            for row in csv.DictReader(stream):
                group_key = measured_turns.get(row.get("turn_id"))
                if group_key is None or group_key[2] != "foreground":
                    continue
                group = groups[group_key]
                for label in ("accurate", "complete", "action_appropriate"):
                    if row.get(label) in ("0", "1"):
                        group[f"{label}_reviewed"] += 1
                        group[f"{label}_passed"] += int(row[label])
    result = []
    for (phase, row_profile, task), totals in sorted(groups.items()):
        n = totals["turns"]
        gross = sum(turn_totals[(phase, row_profile, task)])
        noncached = totals["input_tokens"] + totals["cache_write_tokens"] + totals["output_tokens"]
        item = {"phase": phase, "profile": row_profile, "task": task,
                **totals, "gross_tokens": gross, "noncached_tokens": noncached,
                "median_gross_tokens": int(median(turn_totals[(phase, row_profile, task)])),
                "mean_api_calls": round(totals["api_calls"] / n, 2),
                "mean_elapsed_seconds": (
                    round(totals["elapsed_seconds"] / totals["timed_turns"], 2)
                    if totals["timed_turns"] else None
                )}
        for label, pct_name in (("accurate", "accuracy_pct"),
                                ("complete", "completeness_pct"),
                                ("action_appropriate", "action_appropriateness_pct")):
            reviewed = item.get(f"{label}_reviewed", 0)
            if reviewed:
                item[pct_name] = round(100 * item[f"{label}_passed"] / reviewed, 2)
        for metric in ("first_prompt_tokens", "last_prompt_tokens_exact",
                       "peak_prompt_tokens", "prompt_growth_tokens",
                       "first_system_tokens_estimate",
                       "first_tool_schema_tokens_estimate",
                       "first_tool_result_tokens_estimate",
                       "first_other_message_tokens_estimate"):
            samples = [sample[metric] for sample in call_shapes[(phase, row_profile, task)]
                       if sample[metric] is not None]
            if samples:
                item[f"median_{metric}"] = int(median(samples))
        result.append(item)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="Hermes home containing profiles/")
    parser.add_argument("--labels", type=Path, help="independently checked quality CSV")
    parser.add_argument("--profile", help="only show one Hermes profile")
    args = parser.parse_args()
    for row in summarize(args.root, args.labels, args.profile):
        print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
