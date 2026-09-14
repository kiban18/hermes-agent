"""A reviewer's pass must be backed by evidence the reviewer cannot narrate.

worldvision t_57f88d63 (2026-09-14): a QA worker closed a screen-behaviour
card 19 seconds after claiming it, with a specific and entirely false summary
and nothing attached. Of 48 review-claimed completions on that board, exactly
one carried an artifact.

The gate lives in ``complete_task`` — the domain layer — because the tool is
only one of four callers (CLI, dashboard x2 are the others).
"""

from __future__ import annotations

import hashlib
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


def _card_in_review(conn, workspace: Path):
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
        conn, tid, reviewer="qa", summary="handoff",
        expected_run_id=claimed.current_run_id,
    )
    review = kb.claim_review_task(conn, tid)
    assert review is not None
    return tid, review.current_run_id


def _age_the_claim(conn, tid, seconds):
    """Backdate the review claim so the run looks `seconds` old."""
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE task_events SET created_at = created_at - ? "
            "WHERE task_id = ? AND kind = 'claimed'",
            (seconds, tid),
        )


def _evidence(workspace: Path, name="bhw-375x812.png", data=b"\x89PNG evidence"):
    path = workspace / name
    path.write_bytes(data)
    return path


def _blocked_events(conn, tid):
    rows = conn.execute(
        "SELECT payload FROM task_events WHERE task_id = ? "
        "AND kind = 'completion_blocked_review_evidence' ORDER BY id",
        (tid,),
    ).fetchall()
    return [json.loads(r["payload"]) if r["payload"] else {} for r in rows]


def test_review_pass_without_evidence_is_refused(conn, workspace):
    tid, run_id = _card_in_review(conn, workspace)
    _age_the_claim(conn, tid, kb.REVIEW_EVIDENCE_MIN_SECONDS + 60)

    with pytest.raises(kb.ReviewEvidenceRequiredError):
        kb.complete_task(
            conn, tid, summary="판정: 통과", expected_run_id=run_id
        )

    # The card is untouched and the refusal is auditable.
    assert kb.get_task(conn, tid).status == "running"
    blocked = _blocked_events(conn, tid)
    assert len(blocked) == 1
    assert "evidence" in " ".join(blocked[0]["problems"]).lower() or blocked[0]["problems"]


def test_review_pass_with_evidence_is_allowed(conn, workspace):
    tid, run_id = _card_in_review(conn, workspace)
    _age_the_claim(conn, tid, kb.REVIEW_EVIDENCE_MIN_SECONDS + 60)
    path = _evidence(workspace)

    assert kb.complete_task(
        conn,
        tid,
        summary="판정: 통과",
        metadata={"artifacts": [str(path)]},
        expected_run_id=run_id,
    )
    assert kb.get_task(conn, tid).status == "done"

    run = kb.latest_run(conn, tid)
    recorded = run.metadata["review_evidence"]
    assert len(recorded) == 1
    assert recorded[0]["size"] == path.stat().st_size
    assert recorded[0]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_evidence_outside_the_workspace_does_not_count(conn, workspace, tmp_path):
    """An unvalidated path outside the workspace was the free pass."""
    tid, run_id = _card_in_review(conn, workspace)
    _age_the_claim(conn, tid, kb.REVIEW_EVIDENCE_MIN_SECONDS + 60)
    outside = tmp_path / "elsewhere.png"
    outside.write_bytes(b"not in the workspace")

    with pytest.raises(kb.ReviewEvidenceRequiredError):
        kb.complete_task(
            conn, tid, summary="판정: 통과",
            metadata={"artifacts": [str(outside)]},
            expected_run_id=run_id,
        )
    assert kb.get_task(conn, tid).status == "running"


@pytest.mark.parametrize(
    "artifacts",
    [
        pytest.param(["missing.png"], id="nonexistent"),
        pytest.param([""], id="empty-string"),
        pytest.param("not-a-list", id="not-a-list"),
    ],
)
def test_unusable_evidence_is_refused(conn, workspace, artifacts):
    tid, run_id = _card_in_review(conn, workspace)
    _age_the_claim(conn, tid, kb.REVIEW_EVIDENCE_MIN_SECONDS + 60)
    if artifacts == ["missing.png"]:
        artifacts = [str(workspace / "missing.png")]

    with pytest.raises(kb.ReviewEvidenceRequiredError):
        kb.complete_task(
            conn, tid, summary="판정: 통과",
            metadata={"artifacts": artifacts},
            expected_run_id=run_id,
        )
    assert kb.get_task(conn, tid).status == "running"


def test_empty_file_is_not_evidence(conn, workspace):
    tid, run_id = _card_in_review(conn, workspace)
    _age_the_claim(conn, tid, kb.REVIEW_EVIDENCE_MIN_SECONDS + 60)
    blank = workspace / "blank.png"
    blank.write_bytes(b"")

    with pytest.raises(kb.ReviewEvidenceRequiredError):
        kb.complete_task(
            conn, tid, summary="판정: 통과",
            metadata={"artifacts": [str(blank)]},
            expected_run_id=run_id,
        )


def test_rubber_stamp_is_refused_even_with_evidence(conn, workspace):
    """The measured pattern: 7-30s review claims on screen-behaviour cards."""
    tid, run_id = _card_in_review(conn, workspace)
    path = _evidence(workspace)  # claim is seconds old, not minutes

    with pytest.raises(kb.ReviewEvidenceRequiredError) as excinfo:
        kb.complete_task(
            conn, tid, summary="판정: 통과",
            metadata={"artifacts": [str(path)]},
            expected_run_id=run_id,
        )
    assert kb.get_task(conn, tid).status == "running"
    assert str(kb.REVIEW_EVIDENCE_MIN_SECONDS) in str(excinfo.value)


def test_implementation_runs_are_not_gated(conn, workspace):
    """Only review verdicts need evidence; implementers hand off via review."""
    tid = kb.create_task(
        conn, title="build it", assignee="builder",
        workspace_kind="dir", workspace_path=str(workspace),
    )
    claimed = kb.claim_task(conn, tid)
    assert kb.complete_task(
        conn, tid, summary="구현 완료", expected_run_id=claimed.current_run_id
    )
    assert kb.get_task(conn, tid).status == "done"


def test_human_approval_of_a_parked_review_card_is_not_gated(conn, workspace):
    """No active run means a person is approving from the review lane."""
    tid = kb.create_task(
        conn, title="approve me", assignee="builder",
        workspace_kind="dir", workspace_path=str(workspace),
    )
    claimed = kb.claim_task(conn, tid)
    assert kb.request_review(
        conn, tid, reviewer="qa", summary="handoff",
        expected_run_id=claimed.current_run_id,
    )
    assert kb.get_task(conn, tid).status == "review"

    assert kb.complete_task(conn, tid, summary="리드 승인")
    assert kb.get_task(conn, tid).status == "done"
