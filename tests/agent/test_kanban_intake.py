"""The intake must not become the next place work disappears into.

It exists because the Kanban guard, correctly, refuses a delegate_task child
and left the work nowhere — 753 genuine refusals in a month, each answered with
"별도 채널에서 처리하겠습니다" and then dropped. A queue that silently fills
would reproduce that failure one layer down, so the cases that matter most here
are the ones about staying visible: pending entries are findable, drained ones
stop showing, and an undrained queue goes stale out loud.
"""

from __future__ import annotations

import json
import time

import pytest

from agent import kanban_intake as ki


@pytest.fixture
def home(tmp_path):
    return tmp_path


def _intent(title="카드 하나"):
    return {"board": "kikia", "title": title, "assignee": "project_developer"}


def test_recorded_intent_is_pending_with_a_receipt(home):
    receipt = ki.record(_intent(), session_id="sess-1", home=home)
    assert receipt
    rows = ki.pending("sess-1", home=home)
    assert [r["receipt"] for r in rows] == [receipt]
    assert rows[0]["intent"]["title"] == "카드 하나"


def test_draining_removes_it_from_pending(home):
    receipt = ki.record(_intent(), session_id="sess-1", home=home)
    ki.mark_done("sess-1", [receipt], task_ids={receipt: "t_abc123"}, home=home)
    assert ki.pending("sess-1", home=home) == []


def test_sessions_do_not_see_each_other(home):
    ki.record(_intent("A"), session_id="sess-a", home=home)
    ki.record(_intent("B"), session_id="sess-b", home=home)
    assert [r["intent"]["title"] for r in ki.pending("sess-a", home=home)] == ["A"]
    assert [r["intent"]["title"] for r in ki.pending("sess-b", home=home)] == ["B"]


def test_undrained_entries_go_stale(home):
    ki.record(_intent(), session_id="sess-1", home=home)
    assert ki.stale(older_than_seconds=900, home=home) == []
    # Rewrite the row as if it had been sitting there for an hour.
    path = ki._path_for("sess-1", home)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows[0]["at"] = time.time() - 3600
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    assert len(ki.stale(older_than_seconds=900, home=home)) == 1


def test_drained_entries_never_go_stale(home):
    receipt = ki.record(_intent(), session_id="sess-1", home=home)
    path = ki._path_for("sess-1", home)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows[0]["at"] = time.time() - 3600
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    ki.mark_done("sess-1", [receipt], home=home)
    assert ki.stale(older_than_seconds=900, home=home) == []


def test_a_corrupt_line_does_not_hide_the_rest(home):
    good = ki.record(_intent("살아남아야 함"), session_id="sess-1", home=home)
    path = ki._path_for("sess-1", home)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{ this is not json\n")
    assert [r["receipt"] for r in ki.pending("sess-1", home=home)] == [good]


def test_a_hostile_session_id_stays_inside_the_intake_dir(home):
    """A session id comes from the environment; it must not steer the path."""
    ki.record(_intent(), session_id="../../etc/passwd", home=home)
    written = list(ki.intake_dir(home).glob("*.jsonl"))
    assert len(written) == 1
    assert written[0].parent == ki.intake_dir(home)


def test_reading_an_empty_intake_is_not_an_error(home):
    assert ki.pending("never-used", home=home) == []
    assert ki.stale(home=home) == []
