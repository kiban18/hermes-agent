"""kanban_request_changes must still work after the reviewer completed.

Reproduces worldvision t_57f88d63 (2026-09-14) at the tool surface: the QA
worker passed the card in 19 seconds, kept looking, found the real defect six
minutes later, and both kanban_request_changes and kanban_block were refused
because the card was already done. The verdict survived only as a comment,
which notifies nobody.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def reviewer_env(monkeypatch, tmp_path):
    """A worker session scoped to a card its own run just completed."""
    from hermes_cli import kanban_db as kb

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_PROFILE", "project_qa")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()

    conn = kb.connect()
    try:
        tid = kb.create_task(
            conn, title="print button visible", assignee="project_developer"
        )
        claimed = kb.claim_task(conn, tid)
        assert kb.request_review(
            conn,
            tid,
            reviewer="project_qa",
            summary="implementation handoff",
            expected_run_id=claimed.current_run_id,
        )
        review_claim = kb.claim_review_task(conn, tid)
        assert review_claim is not None
        assert kb.complete_task(
            conn,
            tid,
            summary="판정: 통과",
            expected_run_id=review_claim.current_run_id,
        )
        run_id = review_claim.current_run_id
    finally:
        conn.close()

    monkeypatch.setenv("HERMES_KANBAN_TASK", tid)
    monkeypatch.setenv("HERMES_KANBAN_RUN_ID", str(run_id))
    return tid


def test_late_finding_retracts_the_completion(reviewer_env, monkeypatch):
    from hermes_cli import kanban_db as kb
    from tools import kanban_tools as kt

    out = json.loads(
        kt._handle_request_changes({
            "reason": (
                "QA-BHW-02 — 375×812에서 BHW 선택 뒤 Print 버튼이 "
                "viewport 밖(y=2668px)에 남습니다."
            ),
        })
    )

    assert not out.get("error"), out
    assert out["disputed_completion"] is True
    assert out["status"] in ("ready", "todo")
    assert out["implementer"] == "project_developer"

    conn = kb.connect()
    try:
        task = kb.get_task(conn, reviewer_env)
        assert task.status in ("ready", "todo")
        assert task.assignee == "project_developer"
        rows = conn.execute(
            "SELECT kind, payload FROM task_events WHERE task_id = ? "
            "AND kind = 'completion_disputed'",
            (reviewer_env,),
        ).fetchall()
        assert len(rows) == 1
        assert "QA-BHW-02" in json.loads(rows[0]["payload"])["reason"]
    finally:
        conn.close()


def test_late_finding_still_requires_a_reason(reviewer_env):
    from hermes_cli import kanban_db as kb
    from tools import kanban_tools as kt

    out = json.loads(kt._handle_request_changes({"reason": "  "}))
    assert out["error"]

    conn = kb.connect()
    try:
        assert kb.get_task(conn, reviewer_env).status == "done"
    finally:
        conn.close()


def test_worker_cannot_retract_another_runs_completion(reviewer_env, monkeypatch):
    """The dispute is pinned to the run that closed the card."""
    from hermes_cli import kanban_db as kb
    from tools import kanban_tools as kt

    monkeypatch.setenv("HERMES_KANBAN_RUN_ID", "999999")

    out = json.loads(kt._handle_request_changes({"reason": "남의 판정 철회 시도"}))

    assert out["error"]
    conn = kb.connect()
    try:
        assert kb.get_task(conn, reviewer_env).status == "done"
    finally:
        conn.close()
