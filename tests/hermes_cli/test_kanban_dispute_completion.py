"""A reviewer must be able to retract its own premature completion.

``request_changes`` needs a live review run. Once ``complete_task`` lands
there is no run left, so a reviewer that kept looking and only then found the
defect had no verb at all — worldvision ``t_57f88d63`` passed in 19 seconds
and the real defect (Print button off-viewport at 375x812) arrived six
minutes later as a comment that notifies nobody.

``dispute_completion`` is the retraction: the ``completed`` event stays and a
``completion_disputed`` event is appended after it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb


@pytest.fixture
def conn(tmp_path: Path):
    db = kb.connect(tmp_path / "kanban.db")
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def workspace(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


def _reviewed_and_completed(conn, workspace, *, summary="판정: 통과"):
    """Drive a card through implement -> review -> reviewer completes it.

    The pass clears the evidence gate (see
    test_kanban_review_evidence_gate.py) — this is the Goodhart case the gate
    cannot reach: a file was attached and time was spent, and the verdict is
    still wrong. Retraction is what covers it.
    """
    tid = kb.create_task(
        conn,
        title="print button visible",
        assignee="builder",
        workspace_kind="dir",
        workspace_path=str(workspace),
    )
    claimed = kb.claim_task(conn, tid)
    assert claimed is not None
    assert kb.request_review(
        conn,
        tid,
        reviewer="qa",
        summary="implementation handoff",
        expected_run_id=claimed.current_run_id,
    )
    review_claim = kb.claim_review_task(conn, tid)
    assert review_claim is not None
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE task_events SET created_at = created_at - ? "
            "WHERE task_id = ? AND kind = 'claimed'",
            (kb.REVIEW_EVIDENCE_MIN_SECONDS + 60, tid),
        )
    shot = workspace / "bhw-375x812.png"
    shot.write_bytes(b"\x89PNG evidence")
    assert kb.complete_task(
        conn,
        tid,
        summary=summary,
        metadata={"artifacts": [str(shot)]},
        expected_run_id=review_claim.current_run_id,
    )
    return tid, review_claim.current_run_id


def _events(conn, tid, kind):
    rows = conn.execute(
        "SELECT payload FROM task_events WHERE task_id = ? AND kind = ? "
        "ORDER BY id",
        (tid, kind),
    ).fetchall()
    return [json.loads(r["payload"]) if r["payload"] else {} for r in rows]


def test_dispute_returns_the_card_to_its_implementer(conn, workspace):
    tid, run_id = _reviewed_and_completed(conn, workspace)
    reason = "QA-BHW-02 — 375x812에서 Print 버튼이 viewport 밖에 남음"

    ok, implementer = kb.dispute_completion(
        conn, tid, reason=reason, expected_run_id=run_id
    )

    assert ok
    assert implementer == "builder"
    task = kb.get_task(conn, tid)
    assert task.status in ("ready", "todo")
    assert task.assignee == "builder"
    assert task.completed_at is None


def test_dispute_appends_rather_than_erasing_the_completion(conn, workspace):
    tid, run_id = _reviewed_and_completed(conn, workspace, summary="판정: 통과")

    ok, _ = kb.dispute_completion(
        conn, tid, reason="결함 발견", expected_run_id=run_id
    )
    assert ok

    # The original verdict is still in the log — this is a retraction, not a
    # rewind — and the dispute follows it.
    kinds = [
        r["kind"]
        for r in conn.execute(
            "SELECT kind FROM task_events WHERE task_id = ? ORDER BY id", (tid,)
        ).fetchall()
    ]
    assert "completed" in kinds
    assert kinds.index("completed") < kinds.index("completion_disputed")

    disputed = _events(conn, tid, "completion_disputed")
    assert len(disputed) == 1
    assert disputed[0]["reason"] == "결함 발견"
    assert disputed[0]["implementer"] == "builder"
    assert disputed[0]["reviewer"] == "qa"


def test_dispute_requires_a_reason(conn, workspace):
    tid, run_id = _reviewed_and_completed(conn, workspace)
    ok, detail = kb.dispute_completion(
        conn, tid, reason="   ", expected_run_id=run_id
    )
    assert not ok
    assert detail == "reason is required"
    assert kb.get_task(conn, tid).status == "done"


def test_dispute_is_pinned_to_the_run_that_closed_the_card(conn, workspace):
    tid, run_id = _reviewed_and_completed(conn, workspace)

    ok, detail = kb.dispute_completion(
        conn, tid, reason="다른 실행이 쓴 판정", expected_run_id=run_id + 1000
    )

    assert not ok
    assert detail == "run_id mismatch"
    assert kb.get_task(conn, tid).status == "done"


def test_dispute_rejects_a_card_that_is_not_done(conn):
    tid = kb.create_task(conn, title="still open", assignee="builder")
    ok, detail = kb.dispute_completion(conn, tid, reason="아직 진행 중")
    assert not ok
    assert "not done" in detail


def test_dispute_retracts_descendants_built_on_the_result(conn, workspace):
    tid, run_id = _reviewed_and_completed(conn, workspace)
    child = kb.create_task(
        conn, title="follow-up", assignee="builder", parents=[tid]
    )
    assert kb.complete_task(conn, child)

    ok, _ = kb.dispute_completion(
        conn, tid, reason="전제가 철회됨", expected_run_id=run_id
    )
    assert ok

    # The child assumed a result that no longer holds.
    assert kb.get_task(conn, child).status == "todo"
    assert _events(conn, child, "descendant_invalidated")
