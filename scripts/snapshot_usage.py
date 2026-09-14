#!/usr/bin/env python3
"""Snapshot cumulative usage for all Hermes profiles without message content.

Two snapshots can be subtracted to measure an interval even for resumed,
long-lived sessions.  Run once before a change and periodically afterward.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

METRICS = ("api_call_count", "input_tokens", "output_tokens",
           "cache_read_tokens", "cache_write_tokens", "reasoning_tokens")


def collect(root: Path, phase: str) -> dict:
    rows = []
    for db in [root / "state.db", *root.glob("profiles/*/state.db")]:
        if not db.is_file():
            continue
        profile = "main" if db.parent == root else db.parent.name
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            columns = ",".join(f"coalesce(sum(u.{name}),0)" for name in METRICS)
            query = ("select s.source,u.model,u.billing_provider," + columns +
                     " from session_model_usage u join sessions s on s.id=u.session_id "
                     "group by s.source,u.model,u.billing_provider")
            for values in conn.execute(query):
                source, model, provider, *totals = values
                rows.append({"profile": profile, "source": source,
                             "model": model, "provider": provider,
                             **dict(zip(METRICS, totals))})
        finally:
            conn.close()
    return {"timestamp": time.time(), "phase": phase, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--phase", choices=("asis", "tobe"), default="asis")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    data = collect(args.root, args.phase)
    output = args.out or args.root / "reports" / "usage-snapshots.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a") as stream:
        stream.write(json.dumps(data, ensure_ascii=False) + "\n")
    print(f"{len(data['rows'])} usage groups recorded in {output}")


if __name__ == "__main__":
    main()
