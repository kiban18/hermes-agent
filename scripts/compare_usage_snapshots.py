#!/usr/bin/env python3
"""Print measured usage delta between two snapshot indices (0-based)."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

METRICS = ("api_call_count", "input_tokens", "output_tokens",
           "cache_read_tokens", "cache_write_tokens", "reasoning_tokens")


def totals(snapshot: dict) -> dict:
    result = defaultdict(lambda: defaultdict(int))
    for row in snapshot["rows"]:
        bucket = result[(row["profile"], row["source"], row["provider"], row["model"])]
        for metric in METRICS:
            bucket[metric] += int(row.get(metric) or 0)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("start", type=int)
    parser.add_argument("end", type=int)
    args = parser.parse_args()
    snapshots = [json.loads(line) for line in args.file.read_text().splitlines()]
    before, after = snapshots[args.start], snapshots[args.end]
    a, b = totals(before), totals(after)
    print(json.dumps({"start": before["timestamp"], "end": after["timestamp"],
                      "phase": after["phase"]}))
    for key in sorted(set(a) | set(b)):
        delta = {metric: b[key][metric] - a[key][metric] for metric in METRICS}
        if any(delta.values()):
            print(json.dumps({"profile": key[0], "source": key[1],
                              "provider": key[2], "model": key[3], **delta},
                             ensure_ascii=False))


if __name__ == "__main__":
    main()
