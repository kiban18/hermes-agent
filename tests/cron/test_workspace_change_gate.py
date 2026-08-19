"""Open detection cards skip the LLM; remaining repos stay in slim context."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_PROFILE", "project_lead")
    kb.init_db()
    return home


def _state(repo: Path, *, dirty_count: int, digest: str, head: str = "abc") -> dict:
    return {
        "branch": "main",
        "dirty_count": dirty_count,
        "dirty_digest": digest,
        "dirty_preview": ["?? extra.py"],
        "head": head,
        "owner": "project_lead",
        "repo": str(repo),
    }


def _snapshot(*states: dict, owner: str = "project_lead") -> str:
    header = json.dumps(
        {"owner": owner, "roots": ["/Users/khlee/work"], "version": 1},
        ensure_ascii=False,
        sort_keys=True,
    )
    lines = [header]
    for state in states:
        lines.append(
            json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    return "\n".join(lines) + "\n"


def test_is_workspace_change_monitor_job():
    from cron.workspace_change_gate import is_workspace_change_monitor_job

    assert is_workspace_change_monitor_job(
        {"monitor_script": "workspace-delivery-monitor.sh"}
    )
    assert is_workspace_change_monitor_job(
        {"monitor_script": "workspace-acquisition-monitor.sh"}
    )
    assert is_workspace_change_monitor_job(
        {"skills": ["workspace-change-reconciler"]}
    )
    assert not is_workspace_change_monitor_job(
        {"monitor_script": "wishket-new-listings-monitor.sh"}
    )


def test_open_detection_card_skips_agent_and_comments(kanban_home, tmp_path):
    from cron.workspace_change_gate import apply_workspace_change_gate

    repo = tmp_path / "g2b-stats"
    repo.mkdir()
    repo_path = str(repo.resolve())
    with kb.connect() as conn:
        tid = kb.create_task(
            conn,
            title="나라장터 — 외부 작업 감지",
            triage=True,
            assignee="project_lead",
            workspace_kind="dir",
            workspace_path=repo_path,
        )

    old = _snapshot(_state(repo.resolve(), dirty_count=39, digest="aaa", head="h1"))
    new = _snapshot(_state(repo.resolve(), dirty_count=40, digest="bbb", head="h1"))
    remaining, handled, context = apply_workspace_change_gate(
        old, new, author="project_lead"
    )
    assert remaining == []
    assert context is None
    assert handled and handled[0]["task_id"] == tid
    assert handled[0]["action"] == "added"

    with kb.connect() as conn:
        comments = kb.list_comments(conn, tid)
        task = kb.get_task(conn, tid)
    assert len(comments) == 1
    assert "digest=bbb" in comments[0].body
    assert "dirty=40" in comments[0].body
    assert task.status == "triage"
    assert task.assignee == "project_lead"

    remaining2, handled2, _ = apply_workspace_change_gate(
        old, new, author="project_lead"
    )
    assert remaining2 == []
    assert handled2[0]["action"] == "duplicate"
    with kb.connect() as conn:
        assert len(kb.list_comments(conn, tid)) == 1


def test_new_repo_without_detection_card_stays_for_agent(kanban_home, tmp_path):
    from cron.workspace_change_gate import apply_workspace_change_gate

    repo = tmp_path / "g2b-stats"
    repo.mkdir()
    other = tmp_path / "other-app"
    other.mkdir()
    with kb.connect() as conn:
        kb.create_task(
            conn,
            title="외부 작업 감지 — g2b-stats",
            triage=True,
            assignee="project_lead",
            workspace_kind="dir",
            workspace_path=str(repo.resolve()),
        )
        kb.create_task(
            conn,
            title="나라장터 배포",
            assignee="project_lead",
            workspace_kind="dir",
            workspace_path=str(other.resolve()),
        )

    old = _snapshot(
        _state(repo.resolve(), dirty_count=1, digest="a1"),
        _state(other.resolve(), dirty_count=0, digest="b0", head="old"),
    )
    new = _snapshot(
        _state(repo.resolve(), dirty_count=2, digest="a2"),
        _state(other.resolve(), dirty_count=1, digest="b1", head="old"),
    )
    remaining, handled, context = apply_workspace_change_gate(
        old, new, author="project_lead"
    )
    assert [item["repo"] for item in remaining] == [str(other.resolve())]
    assert handled and handled[0]["repo"] == str(repo.resolve())
    assert context is not None
    assert str(other.resolve()) in context
    assert str(repo.resolve()) not in context.split("### Changed repositories", 1)[1].split(
        "### Open cards", 1
    )[0]
    assert "나라장터 배포" in context


def test_first_run_is_silent(kanban_home):
    from cron.workspace_change_gate import apply_workspace_change_gate

    remaining, handled, context = apply_workspace_change_gate(
        "", "anything", author="project_lead", first_run=True
    )
    assert remaining == []
    assert handled == [{"action": "baseline"}]
    assert context is None


def test_check_monitor_suppresses_agent_when_detection_card_exists(
    kanban_home, tmp_path, monkeypatch
):
    from cron import monitor as mon
    from cron.jobs import create_job

    repo = tmp_path / "g2b-stats"
    repo.mkdir()
    scripts = Path(kanban_home) / "scripts"
    scripts.mkdir(exist_ok=True)
    snapshot = _snapshot(_state(repo.resolve(), dirty_count=40, digest="live"))
    script = scripts / "workspace-delivery-monitor.sh"
    script.write_text(f"#!/bin/bash\ncat <<'EOF'\n{snapshot}EOF\n", encoding="utf-8")
    script.chmod(0o755)

    with kb.connect() as conn:
        tid = kb.create_task(
            conn,
            title="나라장터 — 외부 작업 감지",
            triage=True,
            assignee="project_lead",
            workspace_kind="dir",
            workspace_path=str(repo.resolve()),
        )

    job = create_job(
        prompt="workspace-change-reconciler",
        schedule="every 15m",
        monitor_script="workspace-delivery-monitor.sh",
        skills=["workspace-change-reconciler"],
        deliver="local",
    )
    first = mon.check_monitor(job)
    assert first.ok is True
    assert first.suppress_agent is True
    assert first.first_run is True

    job["monitor_state"] = {
        "last_output_hash": "deadbeef",
        "last_changed_at": "2026-08-19T00:00:00+09:00",
    }
    mon._write_last_output(job["id"], _snapshot(_state(repo.resolve(), dirty_count=39, digest="prev")))
    second = mon.check_monitor(job)
    assert second.ok is True
    assert second.changed is True
    assert second.suppress_agent is True
    assert second.context_block is None
    with kb.connect() as conn:
        comments = kb.list_comments(conn, tid)
    assert comments
    assert "digest=live" in comments[-1].body


def test_remaining_workspace_job_skips_soul_and_limits_toolsets(
    kanban_home, tmp_path, monkeypatch
):
    import sys

    import cron.scheduler as sched
    from cron.monitor import MonitorOutcome

    observed: dict = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            observed["load_soul_identity"] = kwargs.get("load_soul_identity")
            observed["skip_context_files"] = kwargs.get("skip_context_files")
            observed["enabled_toolsets"] = kwargs.get("enabled_toolsets")
            observed["platform"] = kwargs.get("platform")
            observed["reasoning_config"] = kwargs.get("reasoning_config")

        def run_conversation(self, prompt, *_a, **_kw):
            observed["prompt"] = prompt
            return {"final_response": "[SILENT]", "messages": []}

        def get_activity_summary(self):
            return {"seconds_since_activity": 0.0}

    fake_mod = type(sys)("run_agent")
    fake_mod.AIAgent = FakeAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_mod)
    from hermes_cli import runtime_provider as _rtp
    monkeypatch.setattr(
        _rtp,
        "resolve_runtime_provider",
        lambda **_kw: {
            "provider": "test",
            "api_key": "k",
            "base_url": "http://test.local",
            "api_mode": "chat_completions",
        },
    )
    monkeypatch.setattr(sched, "_resolve_origin", lambda job: None)
    monkeypatch.setattr(sched, "_resolve_delivery_target", lambda job: None)
    monkeypatch.setattr(
        sched,
        "_resolve_cron_enabled_toolsets",
        lambda job, cfg: job.get("enabled_toolsets"),
    )
    monkeypatch.setenv("HERMES_CRON_TIMEOUT", "0")
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *_a, **_kw: True)
    monkeypatch.setattr(
        "cron.monitor.check_monitor",
        lambda job: MonitorOutcome(
            ok=True,
            changed=True,
            context_block="## MONITOR CHANGE DETECTED\nrepo-only",
            suppress_agent=False,
        ),
    )

    job = {
        "id": "14840d139e6d",
        "name": "프로젝트 경로 외부 작업 감지",
        "prompt": "workspace-change-reconciler를 적용한다.",
        "skills": ["workspace-change-reconciler"],
        "monitor_script": "workspace-delivery-monitor.sh",
        "enabled_toolsets": ["kanban", "file"],
        "schedule_display": "every 15m",
        "reasoning_effort": "none",
    }
    success, *_ = sched.run_job(job)
    assert success is True
    assert observed["load_soul_identity"] is False
    assert observed["skip_context_files"] is True
    assert observed["enabled_toolsets"] == ["kanban", "file"]
    assert observed["platform"] == "cron"
    assert "repo-only" in observed["prompt"]
