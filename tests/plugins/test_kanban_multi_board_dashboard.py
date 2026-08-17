"""Dashboard multi-board view: GET /board?board=* and the All boards switcher."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli import kanban_aggregator as ka
from hermes_cli import kanban_db as kb
from tests.plugins.test_kanban_dashboard_plugin import _load_plugin_router


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


@pytest.fixture
def client(kanban_home):
    app = FastAPI()
    app.include_router(_load_plugin_router(), prefix="/api/plugins/kanban")
    return TestClient(app)


def _titles(payload: dict) -> set[str]:
    return {
        task["title"]
        for col in payload["columns"]
        for task in col["tasks"]
    }


def test_boards_omits_virtual_when_only_default(client):
    data = client.get("/api/plugins/kanban/boards").json()
    slugs = [b["slug"] for b in data["boards"]]
    assert "*" not in slugs
    assert "default" in slugs


def test_boards_lists_all_boards_when_multiple_exist(client):
    kb.create_board("alpha", name="Alpha")
    data = client.get("/api/plugins/kanban/boards").json()
    slugs = [b["slug"] for b in data["boards"]]
    assert slugs[0] == "*"
    all_row = data["boards"][0]
    assert all_row["virtual"] is True
    assert all_row["name"] == "All boards"
    assert "alpha" in slugs
    assert "default" in slugs


def test_board_star_merges_cards_and_slugs(client):
    kb.create_board("alpha")
    kb.create_board("beta")
    a = client.post(
        "/api/plugins/kanban/tasks?board=alpha",
        json={"title": "alpha-card", "assignee": "dev"},
    ).json()["task"]
    b = client.post(
        "/api/plugins/kanban/tasks?board=beta",
        json={"title": "beta-card", "assignee": "dev"},
    ).json()["task"]

    single = client.get("/api/plugins/kanban/board?board=alpha").json()
    assert "alpha-card" in _titles(single)
    assert "beta-card" not in _titles(single)

    merged = client.get("/api/plugins/kanban/board?board=*").json()
    assert merged["view"] == "all"
    assert set(merged["boards"]) >= {"alpha", "beta"}
    assert _titles(merged) >= {"alpha-card", "beta-card"}
    by_title = {
        task["title"]: task
        for col in merged["columns"]
        for task in col["tasks"]
    }
    assert by_title["alpha-card"]["board_slug"] == "alpha"
    assert by_title["beta-card"]["board_slug"] == "beta"
    assert by_title["alpha-card"]["id"] == a["id"]
    assert by_title["beta-card"]["id"] == b["id"]


def test_get_and_patch_task_with_star_resolves_owner(client):
    kb.create_board("alpha")
    created = client.post(
        "/api/plugins/kanban/tasks?board=alpha",
        json={"title": "move-me", "assignee": "dev"},
    ).json()["task"]
    tid = created["id"]

    detail = client.get(f"/api/plugins/kanban/tasks/{tid}?board=*")
    assert detail.status_code == 200, detail.text
    assert detail.json()["task"]["title"] == "move-me"
    assert detail.json()["task"]["board_slug"] == "alpha"

    patched = client.patch(
        f"/api/plugins/kanban/tasks/{tid}?board=*",
        json={"priority": 4},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["task"]["priority"] == 4
    reread = client.get(f"/api/plugins/kanban/tasks/{tid}?board=alpha").json()["task"]
    assert reread["priority"] == 4


def test_create_on_star_lands_on_current_board(client):
    kb.create_board("alpha")
    kb.set_current_board("alpha")
    created = client.post(
        "/api/plugins/kanban/tasks?board=*",
        json={"title": "from-all-view", "assignee": "dev"},
    )
    assert created.status_code == 200, created.text
    tid = created.json()["task"]["id"]
    assert ka.find_task_board(tid) == "alpha"


def test_multi_board_alias_matches_star_board(client):
    kb.create_board("alpha")
    client.post(
        "/api/plugins/kanban/tasks?board=alpha",
        json={"title": "alias-card", "assignee": "dev"},
    )
    via_star = client.get("/api/plugins/kanban/board?board=*").json()
    via_alias = client.get("/api/plugins/kanban/multi-board?boards=*").json()
    assert _titles(via_alias) == _titles(via_star)


def test_dashboard_bundle_has_all_boards_switcher():
    repo_root = Path(__file__).resolve().parents[2]
    js = (repo_root / "plugins" / "kanban" / "dashboard" / "dist" / "index.js").read_text()
    assert "const ALL_BOARDS_SLUG = \"*\";" in js
    assert "function isAllBoards(slug)" in js
    assert "hermes-kanban-board-slug" in js
    assert "t.board_slug" in js
