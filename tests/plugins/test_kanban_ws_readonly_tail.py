"""The kanban events WS must tail boards without writing to them.

2026-10-15: the "All boards" live feed opened every board with the
writable ``kanban_db.connect`` on every 0.3 s poll. Each close deleted the
board's -wal/-shm and the next poll recreated them. That came to ~100 file
events per second, which kept the macOS fseventsd daemon growing until the host
was swapping. These tests pin down the replacement:

* no writable open from the tail;
* no SQLite open at all while a board's files are unchanged;
* no event lost or repeated when a backlog is larger than one page.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb


def _load_plugin_module():
    repo_root = Path(__file__).resolve().parents[2]
    plugin_file = repo_root / "plugins" / "kanban" / "dashboard" / "plugin_api.py"
    spec = importlib.util.spec_from_file_location(
        "hermes_dashboard_plugin_kanban_readonly_tail_test", plugin_file,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fresh_home(tmp_path, monkeypatch):
    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    for var in ("HERMES_KANBAN_DB", "HERMES_KANBAN_WORKSPACES_ROOT",
                "HERMES_KANBAN_HOME", "HERMES_KANBAN_BOARD"):
        monkeypatch.delenv(var, raising=False)
    try:
        import hermes_constants
        hermes_constants._cached_default_hermes_root = None  # type: ignore[attr-defined]
    except Exception:
        pass
    kb._INITIALIZED_PATHS.clear()
    return home


class _ScriptedWebSocket:
    """Runs one scripted step per ``receive()`` and then idles past the poll
    interval, so the handler polls exactly once per step. Disconnects when
    the script is exhausted."""

    def __init__(self, query: dict, steps: list):
        self.query_params = query
        self.steps = list(steps)
        self.sent: list[dict] = []

    async def accept(self):
        pass

    async def close(self, code=None):
        pass

    async def send_json(self, payload):
        self.sent.append(payload)

    async def receive(self):
        if not self.steps:
            return {"type": "websocket.disconnect"}
        step = self.steps.pop(0)
        if step is not None:
            step()
        await asyncio.sleep(10)  # cancelled by the poll timeout


def _add_task(board: str, title: str) -> None:
    with kb.connect_closing(board=board) as conn:
        kb.create_task(conn, title=title, assignee="dev")


def _all_event_ids(board: str) -> list[int]:
    with kb.connect_closing(board=board) as conn:
        return [r["id"] for r in conn.execute("SELECT id FROM task_events ORDER BY id")]


def _prepare(monkeypatch, mod):
    monkeypatch.setattr(mod, "_ws_upgrade_authorized", lambda ws: True)
    monkeypatch.setattr(mod, "_EVENT_POLL_SECONDS", 0.01)
    # The tail may only resolve paths; any writable open is a regression.
    def _no_writable_connect(*a, **k):
        raise AssertionError("event tail opened a board with kanban_db.connect")
    proxy = types.SimpleNamespace(
        kanban_db_path=kb.kanban_db_path,
        _normalize_board_slug=kb._normalize_board_slug,
        connect=_no_writable_connect,
    )
    monkeypatch.setattr(mod, "kanban_db", proxy)
    opens = {"n": 0}
    real_open = mod._open_event_db_readonly

    def _counting_open(path):
        opens["n"] += 1
        return real_open(path)

    monkeypatch.setattr(mod, "_open_event_db_readonly", _counting_open)
    return opens


def test_all_boards_tail_is_readonly_and_skips_unchanged_boards(fresh_home, monkeypatch):
    kb.create_board("alpha")
    kb.create_board("beta")
    _add_task("alpha", "before the stream")
    _add_task("beta", "before the stream")

    mod = _load_plugin_module()
    opens = _prepare(monkeypatch, mod)
    seen: list[int] = []

    def mark():
        seen.append(opens["n"])

    ws = _ScriptedWebSocket(
        {"board": "*", "since": "0"},
        # settle, settle, idle, write to alpha, idle, idle
        [mark, mark, mark, lambda: (mark(), _add_task("alpha", "live")), mark, mark],
    )
    asyncio.run(asyncio.wait_for(mod.stream_events(ws), timeout=10))

    events = [e for batch in ws.sent for e in batch["events"]]
    assert events, "the live write to alpha was not delivered"
    assert {e["board_slug"] for e in events} == {"alpha"}
    assert all(e["id"] > 0 for e in events)

    # seen[i] is the open count just before poll i. Idle polls after the
    # boards settled must not open SQLite; the poll after the write must.
    idle_after_settle = seen[2] - seen[1]
    after_write = seen[4] - seen[3]
    idle_after_write = opens["n"] - seen[5]
    assert idle_after_settle == 0
    assert after_write >= 1
    assert idle_after_write == 0


def test_backlog_larger_than_a_page_is_delivered_once_each(fresh_home, monkeypatch):
    kb.create_board("alpha")
    for i in range(4):
        _add_task("alpha", f"t{i}")
    expected = _all_event_ids("alpha")
    assert len(expected) > 3

    mod = _load_plugin_module()
    _prepare(monkeypatch, mod)
    monkeypatch.setattr(mod, "_EVENT_FETCH_LIMIT", 2)

    ws = _ScriptedWebSocket({"board": "alpha", "since": "0"}, [None] * (len(expected) + 2))
    asyncio.run(asyncio.wait_for(mod.stream_events(ws), timeout=10))

    delivered = [e["id"] for batch in ws.sent for e in batch["events"]]
    assert delivered == expected


def test_board_without_a_db_is_not_created_by_the_tail(fresh_home, monkeypatch):
    kb.create_board("alpha")
    _add_task("alpha", "x")
    mod = _load_plugin_module()
    _prepare(monkeypatch, mod)
    ghost = kb.kanban_db_path(board="ghost")

    ws = _ScriptedWebSocket({"board": "ghost", "since": "0"}, [None, None])
    asyncio.run(asyncio.wait_for(mod.stream_events(ws), timeout=10))

    assert ws.sent == []
    assert not ghost.exists()
