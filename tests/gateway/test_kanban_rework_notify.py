"""A rework verdict must reach the project room with its reason.

``changes_requested`` / ``review_reopened`` land the card back in ``ready``.
The generic "[진행]" bucket drops every ready-lane event as a noisy status
tick, which silently swallowed independent QA's only "this is not done"
signal (worldvision t_57f88d63, 2026-09-14). These events carry a human
verdict, so they notify like a review handoff does.
"""

import asyncio

from gateway.kanban_watchers import should_skip_progress_notify
from hermes_cli import kanban_db as kb

from tests.gateway.test_kanban_notifier import (
    RecordingAdapter,
    _make_runner,
    _run_one_notifier_tick,
)


def _task_in_review(conn, *, reviewer="reviewer"):
    tid = kb.create_task(conn, title="rework verdict", assignee="worker")
    claimed = kb.claim_task(conn, tid)
    assert claimed is not None
    assert kb.request_review(
        conn,
        tid,
        reviewer=reviewer,
        summary="implementation handoff",
        expected_run_id=claimed.current_run_id,
    )
    return tid


def test_rework_kinds_are_not_progress_ticks():
    for kind in ("changes_requested", "review_reopened"):
        assert not should_skip_progress_notify(kind=kind, status="ready")
        assert not should_skip_progress_notify(kind=kind, status="todo")


def test_changes_requested_reaches_the_room_with_its_reason(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_DB", str(tmp_path / "rework.db"))
    kb.init_db()

    reason = (
        "판정: 반려\n"
        "결함: QA-BHW-02 — 375×812에서 Print 버튼이 viewport 밖에 남음"
    )
    conn = kb.connect()
    try:
        tid = _task_in_review(conn)
        kb.add_notify_sub(conn, task_id=tid, platform="telegram", chat_id="chat-1")
        review_claim = kb.claim_review_task(conn, tid)
        assert review_claim is not None
        ok, implementer = kb.request_changes(
            conn,
            tid,
            reason=reason,
            expected_run_id=review_claim.current_run_id,
        )
        assert ok, implementer
    finally:
        conn.close()

    adapter = RecordingAdapter()
    runner = _make_runner(adapter)
    asyncio.run(_run_one_notifier_tick(monkeypatch, runner))

    messages = [item["text"] for item in adapter.sent]
    verdict = [text for text in messages if "QA-BHW-02" in text]
    assert verdict, messages
    assert verdict[0].startswith("[결정 필요]")
    assert "수정 반환" in verdict[0]
    # The defect text itself, not just a lane label.
    assert "375×812" in verdict[0]
    # Never demoted to the silent progress template.
    assert not any(text.startswith("[진행]") for text in messages)


def test_review_reopen_reaches_the_room(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_DB", str(tmp_path / "reopen.db"))
    kb.init_db()

    conn = kb.connect()
    try:
        tid = _task_in_review(conn)
        kb.add_notify_sub(conn, task_id=tid, platform="telegram", chat_id="chat-1")
        assert kb.reopen_review_task(conn, tid)
    finally:
        conn.close()

    adapter = RecordingAdapter()
    runner = _make_runner(adapter)
    asyncio.run(_run_one_notifier_tick(monkeypatch, runner))

    messages = [item["text"] for item in adapter.sent]
    reopened = [text for text in messages if "검수 재개" in text]
    assert reopened, messages
    assert reopened[0].startswith("[결정 필요]")


def test_disputed_completion_reaches_the_room_with_its_reason(tmp_path, monkeypatch):
    """The t_57f88d63 shape: pass, then find the defect, then retract."""
    monkeypatch.setenv("HERMES_KANBAN_DB", str(tmp_path / "dispute.db"))
    kb.init_db()

    conn = kb.connect()
    try:
        tid = _task_in_review(conn, reviewer="qa")
        kb.add_notify_sub(conn, task_id=tid, platform="telegram", chat_id="chat-1")
        review_claim = kb.claim_review_task(conn, tid)
        assert review_claim is not None
        assert kb.complete_task(
            conn,
            tid,
            summary="판정: 통과",
            expected_run_id=review_claim.current_run_id,
        )
        ok, _ = kb.dispute_completion(
            conn,
            tid,
            reason="QA-BHW-02 — 375×812에서 Print 버튼이 viewport 밖에 남음",
            expected_run_id=review_claim.current_run_id,
        )
        assert ok
    finally:
        conn.close()

    adapter = RecordingAdapter()
    runner = _make_runner(adapter)
    asyncio.run(_run_one_notifier_tick(monkeypatch, runner))

    messages = [item["text"] for item in adapter.sent]
    # The premature pass is still reported — the log is append-only — but the
    # retraction reaches the same room right behind it.
    assert any(text.startswith("[완료]") for text in messages)
    retraction = [text for text in messages if "QA-BHW-02" in text]
    assert retraction, messages
    assert retraction[0].startswith("[결정 필요]")
    assert "완료 철회" in retraction[0]
    assert messages.index(retraction[0]) > next(
        i for i, text in enumerate(messages) if text.startswith("[완료]")
    )
