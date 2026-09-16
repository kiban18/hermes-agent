"""Hold a card a delegate_task child cannot write, until its parent can.

A delegated child must not mutate the board — it inherits the meaning of
``HERMES_KANBAN_TASK`` through ``kanban_complete``'s default ``task_id``, so a
child that could write would close its parent's task and overwrite real
results. That guard stays. What was missing is anywhere for the work to go once
it fires: between 2026-08-16 and 2026-09-16 it refused 1,228 times, 753 of them
from genuine children, and each time the agent answered "별도 채널에서
처리하겠습니다" and the card simply ceased to exist.

So the child records an *intent* in a file it owns, and the parent — which does
own the board — creates the card. The trust boundary is untouched: nothing here
writes to Kanban. It only makes the refusal survivable.

Deliberately a plain JSONL append per session:

* Append-only, so a crashed child leaves a readable record rather than a
  half-written queue.
* Per-session file, so a drain never has to filter someone else's rows and two
  children can never contend on one file.
* Readable by hand. When this misbehaves, the person debugging it should be
  able to ``cat`` the queue, which is exactly what the month of silent drops
  denied them.

Every entry carries a receipt id so the child can tell the room "queued as
<id>" instead of inventing a channel that does not exist, and ``pending`` /
``stale`` exist so an undrained queue is loud rather than another silent hole.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

INTAKE_DIRNAME = "kanban-intake"


def intake_dir(home: str | os.PathLike[str] | None = None) -> Path:
    root = Path(home or os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
    return root / "monitoring" / INTAKE_DIRNAME


def _path_for(session_id: str, home=None) -> Path:
    # A session id reaches this from the environment, so it is never trusted as
    # a path component: anything that could walk out of the directory is
    # flattened rather than rejected, because losing the card to a naming rule
    # is the failure this module exists to prevent.
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in (session_id or "unknown"))
    return intake_dir(home) / f"{safe or 'unknown'}.jsonl"


def record(intent: dict[str, Any], *, session_id: str, home=None) -> str:
    """Append *intent* for later creation by the parent; return its receipt id."""
    receipt = uuid.uuid4().hex[:12]
    row = {
        "receipt": receipt,
        "at": time.time(),
        "session_id": session_id,
        "state": "pending",
        "intent": intent,
    }
    path = _path_for(session_id, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return receipt


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            # One malformed line must not hide every other card in the file.
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def pending(session_id: str, home=None) -> list[dict[str, Any]]:
    """Entries still waiting for a parent to create them."""
    latest: dict[str, dict[str, Any]] = {}
    for row in _rows(_path_for(session_id, home)):
        receipt = row.get("receipt")
        if receipt:
            latest[receipt] = row  # a later state line supersedes the original
    return [r for r in latest.values() if r.get("state") == "pending"]


def mark_done(session_id: str, receipts: Iterable[str], *, task_ids=None, home=None) -> int:
    """Record that *receipts* were created, optionally naming the cards made."""
    receipts = [r for r in receipts if r]
    if not receipts:
        return 0
    ids = dict(task_ids or {})
    path = _path_for(session_id, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for receipt in receipts:
            fh.write(json.dumps(
                {"receipt": receipt, "at": time.time(), "session_id": session_id,
                 "state": "done", "task_id": ids.get(receipt)},
                ensure_ascii=False) + "\n")
    return len(receipts)


def stale(older_than_seconds: float = 900.0, home=None) -> list[dict[str, Any]]:
    """Pending entries old enough that nobody is coming for them.

    The point of the whole module is that blocked work stops being invisible;
    an intake that fills up while no parent drains it would recreate the
    original failure one layer down.
    """
    cutoff = time.time() - older_than_seconds
    out: list[dict[str, Any]] = []
    directory = intake_dir(home)
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.jsonl")):
        session_id = path.stem
        for row in pending(session_id, home):
            if float(row.get("at") or 0) <= cutoff:
                out.append(row)
    return out
