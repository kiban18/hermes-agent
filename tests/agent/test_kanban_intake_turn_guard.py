"""A turn must not end quietly while cards it was handed are still unmade.

The chain that replaced the dropped-card failure ends at the parent: a child
queues an intent, the parent is told in the text it acts on, and it calls
kanban_create with the receipt. Nothing forces that last step. A parent that
reads the notice and answers anyway leaves the card exactly as lost as before,
and the only trace is a log line and a watcher that fires half an hour later.

So the turn says so. Same shape as the file-mutation verifier: the claim is
about work the turn was asked to record, so it is checked against the record at
turn end and stated in the response the person actually reads.

Reporting only — it never creates the card. The parent owns its board, and a
finalizer writing cards on its own is the unaccountable second mutator this
whole guard exists to prevent.
"""

from __future__ import annotations

import pytest

from agent.kanban_intake_turn_guard import (
    format_pending_intake_footer,
    pending_intake_for_turn,
)


def _row(receipt, title="카드", board="kikia", assignee="project_developer"):
    return {"receipt": receipt, "session_id": "child-1",
            "intent": {"board": board, "title": title, "assignee": assignee}}


def test_footer_names_every_card_and_its_receipt():
    footer = format_pending_intake_footer([_row("aaa111", "Stripe 계정")])
    assert "aaa111" in footer
    assert "Stripe 계정" in footer
    assert "kikia" in footer


def test_footer_says_the_work_is_on_no_board():
    """The sentence that was missing for a month."""
    footer = format_pending_intake_footer([_row("aaa111")])
    assert "보드에 없" in footer or "보드에도 없" in footer


def test_no_pending_means_no_footer():
    assert format_pending_intake_footer([]) == ""


def test_many_entries_are_capped_but_counted():
    rows = [_row(f"r{i:03d}", f"카드 {i}") for i in range(12)]
    footer = format_pending_intake_footer(rows)
    assert "12" in footer
    assert footer.count("receipt=") <= 10


def test_pending_lookup_reads_the_sessions_the_turn_delegated_to(tmp_path):
    from agent import kanban_intake as ki

    r1 = ki.record({"board": "kikia", "title": "A"}, session_id="child-1", home=tmp_path)
    ki.record({"board": "kikia", "title": "B"}, session_id="other", home=tmp_path)

    rows = pending_intake_for_turn(["child-1"], home=tmp_path)
    assert [r["receipt"] for r in rows] == [r1]


def test_a_closed_receipt_is_not_reported(tmp_path):
    from agent import kanban_intake as ki

    receipt = ki.record({"board": "kikia", "title": "A"}, session_id="child-1", home=tmp_path)
    ki.mark_done("child-1", [receipt], home=tmp_path)
    assert pending_intake_for_turn(["child-1"], home=tmp_path) == []


def test_unreadable_intake_never_breaks_the_turn(tmp_path):
    assert pending_intake_for_turn(["nope"], home=tmp_path) == []
    assert pending_intake_for_turn([], home=tmp_path) == []
