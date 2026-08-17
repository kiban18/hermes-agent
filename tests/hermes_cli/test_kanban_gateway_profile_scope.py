from contextlib import nullcontext
from types import SimpleNamespace

from hermes_cli import kanban


def test_gateway_list_and_stats_are_scoped_to_active_profile(monkeypatch, capsys):
    monkeypatch.setenv("_HERMES_GATEWAY", "1")
    monkeypatch.setattr(kanban, "_profile_author", lambda: "sales-manager")
    monkeypatch.setattr(kanban.kb, "connect_closing", lambda: nullcontext(object()))
    monkeypatch.setattr(kanban.kb, "recompute_ready", lambda _conn: None)
    seen = []

    def list_tasks(_conn, **kwargs):
        seen.append(kwargs["assignee"])
        return []

    monkeypatch.setattr(kanban.kb, "list_tasks", list_tasks)
    common = dict(
        assignee=None, mine=False, status=None, tenant=None, session=None,
        archived=False, sort=None, workflow_template_id=None,
        current_step_key=None, json=True,
    )

    assert kanban._cmd_list(SimpleNamespace(**common)) == 0
    assert kanban._cmd_stats(SimpleNamespace(json=True)) == 0
    assert seen == ["sales-manager", "sales-manager"]
    assert '"assignee": "sales-manager"' in capsys.readouterr().out


def test_agent_kanban_list_defaults_to_active_profile(monkeypatch):
    from tools import kanban_tools

    seen = []

    class FakeBoard:
        def recompute_ready(self, _conn):
            return []

        def list_tasks(self, _conn, **kwargs):
            seen.append(kwargs["assignee"])
            return []

    class FakeConnection:
        def close(self):
            pass

    monkeypatch.setattr(kanban_tools, "_require_orchestrator_tool", lambda _name: None)
    monkeypatch.setattr(
        kanban_tools, "_connect", lambda **_kwargs: (FakeBoard(), FakeConnection())
    )
    monkeypatch.setattr(
        "hermes_cli.profiles.get_active_profile_name", lambda: "sales-manager"
    )

    kanban_tools._handle_list({})

    assert seen == ["sales-manager"]
