from gateway.kanban_watchers import should_skip_progress_notify


def test_skips_todo_ready_running_scheduled():
    for status in ("todo", "ready", "running", "scheduled"):
        assert should_skip_progress_notify(kind="status", status=status)
        assert should_skip_progress_notify(kind="claimed", status=status)


def test_keeps_blocked_review_human_and_terminals():
    assert not should_skip_progress_notify(kind="blocked", status="blocked")
    assert not should_skip_progress_notify(kind="status", status="blocked")
    assert not should_skip_progress_notify(kind="review_requested", status="review")
    assert not should_skip_progress_notify(kind="completed", status="done")
    assert not should_skip_progress_notify(
        kind="status",
        status="ready",
        title="RS101 — 👤 USB 마이크 재연결",
    )
    assert not should_skip_progress_notify(kind="status", status="triage")
