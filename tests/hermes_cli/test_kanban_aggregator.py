"""Tests for hermes_cli.kanban_aggregator — multi-board task queries."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import kanban_aggregator as ka
from hermes_cli import kanban_db as kb


@pytest.fixture
def fresh_home(tmp_path, monkeypatch):
    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    for var in (
        "HERMES_KANBAN_DB",
        "HERMES_KANBAN_WORKSPACES_ROOT",
        "HERMES_KANBAN_HOME",
        "HERMES_KANBAN_BOARD",
    ):
        monkeypatch.delenv(var, raising=False)
    try:
        import hermes_constants
        hermes_constants._cached_default_hermes_root = None  # type: ignore[attr-defined]
    except Exception:
        pass
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    return home


def test_get_all_board_slugs_includes_default_and_named(fresh_home: Path):
    kb.create_board("alpha")
    slugs = ka.get_all_board_slugs()
    assert slugs[0] == "default"
    assert "alpha" in slugs


def test_query_multiple_boards_annotates_slug(fresh_home: Path):
    kb.create_board("alpha")
    kb.create_board("beta")
    with kb.connect(board="alpha") as conn:
        kb.create_task(conn, title="on-alpha", assignee="dev")
    with kb.connect(board="beta") as conn:
        kb.create_task(conn, title="on-beta", assignee="dev")

    tasks = ka.query_multiple_boards(["*"])
    titles = {t.title: t.board_slug for t in tasks}
    assert titles["on-alpha"] == "alpha"
    assert titles["on-beta"] == "beta"


def test_query_respects_named_subset(fresh_home: Path):
    kb.create_board("alpha")
    kb.create_board("beta")
    with kb.connect(board="alpha") as conn:
        kb.create_task(conn, title="on-alpha", assignee="dev")
    with kb.connect(board="beta") as conn:
        kb.create_task(conn, title="on-beta", assignee="dev")

    tasks = ka.query_multiple_boards(["beta"])
    assert [t.title for t in tasks] == ["on-beta"]
    assert tasks[0].board_slug == "beta"


def test_query_text_filter(fresh_home: Path):
    kb.create_board("alpha")
    with kb.connect(board="alpha") as conn:
        kb.create_task(conn, title="ship invoice", assignee="dev")
        kb.create_task(conn, title="unrelated", assignee="dev")
    tasks = ka.query_multiple_boards(["*"], query="invoice")
    assert [t.title for t in tasks] == ["ship invoice"]


def test_find_task_board(fresh_home: Path):
    kb.create_board("alpha")
    with kb.connect(board="alpha") as conn:
        tid = kb.create_task(conn, title="hidden", assignee="dev")
    assert ka.find_task_board(tid) == "alpha"
    assert ka.find_task_board("t_does_not_exist") is None
