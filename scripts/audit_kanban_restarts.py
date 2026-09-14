#!/usr/bin/env python3
"""Read-only audit of repeated Kanban worker runs for one profile.

Flags only objective anomalies.  A retry after a crash, block, rate limit,
review request, or explicit reopen is not called a duplicate.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


def audit(root: Path, profile: str) -> dict:
    outcomes = Counter()
    card_count = run_count = repeated_cards = 0
    anomalies = []
    for db in sorted((root / "kanban" / "boards").glob("*/kanban.db")):
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            groups = defaultdict(list)
            for row in conn.execute(
                "SELECT id,task_id,status,outcome,started_at,ended_at "
                "FROM task_runs WHERE profile=? ORDER BY task_id,id", (profile,)
            ):
                groups[row[1]].append(row)
                outcomes[row[3] or row[2]] += 1
            for task_id, runs in groups.items():
                card_count += 1
                run_count += len(runs)
                repeated_cards += len(runs) > 1
                for previous, current in zip(runs, runs[1:]):
                    reason = None
                    if previous[5] is None or (current[4] and previous[5] and current[4] < previous[5]):
                        reason = "overlapping_or_unclosed_run"
                    elif previous[3] == "completed":
                        # An explicit status transition to ready/review is a
                        # new work request; the subsequent run is legitimate.
                        previous_event = conn.execute(
                            "SELECT max(id) FROM task_events WHERE run_id=? AND kind='completed'",
                            (previous[0],),
                        ).fetchone()[0]
                        current_event = conn.execute(
                            "SELECT min(id) FROM task_events WHERE run_id=? AND kind='claimed'",
                            (current[0],),
                        ).fetchone()[0]
                        if previous_event is not None and current_event is not None:
                            reopened = conn.execute(
                                "SELECT 1 FROM task_events WHERE task_id=? AND id>? AND id<? "
                                "AND kind IN ('status','assigned','unblocked','changes_requested') LIMIT 1",
                                (task_id, previous_event, current_event),
                            ).fetchone()
                            if not reopened:
                                reason = "completed_without_recorded_reopen"
                    if reason:
                        anomalies.append({"board": db.parent.name, "task_id": task_id,
                                          "previous_run": previous[0], "current_run": current[0],
                                          "reason": reason})
        finally:
            conn.close()
    return {"profile": profile, "cards": card_count, "runs": run_count,
            "repeated_cards": repeated_cards, "outcomes": dict(outcomes),
            "candidate_anomalies": anomalies}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--profile", default="project_developer")
    args = parser.parse_args()
    print(json.dumps(audit(args.root, args.profile), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
