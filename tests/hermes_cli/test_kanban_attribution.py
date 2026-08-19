from types import SimpleNamespace

from hermes_cli.kanban_attribution import (
    attach_worker_attribution,
    format_worker_attribution,
    resolve_task_model,
    short_model_name,
)


def test_short_model_name_strips_provider_prefix():
    assert short_model_name("gemini-oauth/gemini-3.5-flash") == "gemini-3.5-flash"
    assert short_model_name("gemini-3.5-flash") == "gemini-3.5-flash"
    assert short_model_name("") is None


def test_format_uses_override_not_profile_default(monkeypatch):
    from hermes_cli import kanban_attribution as attr

    monkeypatch.setattr(attr, "_PROFILE_MODEL_CACHE", {})
    task = SimpleNamespace(
        assignee="proposal_lead",
        model_override="grok-4.6",
        provider_override="xai-oauth",
    )
    assert format_worker_attribution(task) == "AI: proposal_lead · grok-4.6"


def test_format_falls_back_to_profile_config(tmp_path, monkeypatch):
    from hermes_cli import kanban_attribution as attr

    profile = tmp_path / "proposal_lead"
    profile.mkdir()
    (profile / "config.yaml").write_text(
        "model:\n  default: gemini-3.5-flash\n  provider: gemini-oauth\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(attr, "_PROFILE_MODEL_CACHE", {})
    monkeypatch.setattr(
        "hermes_cli.profiles.get_profile_dir", lambda name: profile
    )
    task = SimpleNamespace(assignee="proposal_lead", model_override=None)
    assert format_worker_attribution(task) == "AI: proposal_lead · gemini-3.5-flash"


def test_last_run_model_wins_over_pin_and_profile(monkeypatch):
    from hermes_cli import kanban_attribution as attr

    monkeypatch.setattr(attr, "_PROFILE_MODEL_CACHE", {})
    task = SimpleNamespace(
        assignee="proposal_lead",
        model_override="gemini-3.5-flash",
    )
    assert resolve_task_model(
        task, last_run_model="claude-opus-4.6",
    ) == "claude-opus-4.6"
    assert format_worker_attribution(
        task, last_run_model="anthropic/claude-opus-4.6",
    ) == "AI: proposal_lead · claude-opus-4.6"


def test_attach_inserts_after_first_line():
    task = SimpleNamespace(assignee="project_lead", model_override="glm-5.2")
    msg = attach_worker_attribution(
        "[완료] t_abc · 제목\n결과: 배포됨", task
    )
    assert msg.splitlines()[:3] == [
        "[완료] t_abc · 제목",
        "AI: project_lead · glm-5.2",
        "결과: 배포됨",
    ]


def test_complete_stamps_actual_run_model(tmp_path, monkeypatch):
    from hermes_cli import kanban_db as kb
    from hermes_cli.active_runtime_model import note_active_runtime_model

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    kb.init_db()
    note_active_runtime_model("claude-opus-4.6")
    conn = kb.connect()
    try:
        tid = kb.create_task(
            conn, title="model stamp", assignee="worker",
            model_override="gemini-3.5-flash",
        )
        claimed = kb.claim_task(conn, tid)
        assert claimed is not None
        running = kb.latest_run(conn, tid)
        assert running.model == "gemini-3.5-flash"
        assert kb.complete_task(conn, tid, summary="done")
        done = kb.latest_run(conn, tid)
        assert done.model == "claude-opus-4.6"
        assert kb.latest_run_models(conn, [tid])[tid] == "claude-opus-4.6"
    finally:
        conn.close()
        note_active_runtime_model(None)


def test_comment_stamps_writer_model_and_worker_history(tmp_path, monkeypatch):
    from hermes_cli import kanban_db as kb
    from hermes_cli.active_runtime_model import note_active_runtime_model

    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    kb.init_db()
    conn = kb.connect()
    try:
        tid = kb.create_task(
            conn, title="multi writer", assignee="proposal_lead",
            model_override="gemini-3.5-flash",
        )
        claimed = kb.claim_task(conn, tid)
        assert claimed is not None
        note_active_runtime_model("gemini-3.5-flash")
        kb.add_comment(conn, tid, author="proposal_lead", body="drafted the brief")
        note_active_runtime_model("claude-opus-4.6")
        kb.add_comment(conn, tid, author="project_lead", body="rewrote the scope")
        assert kb.complete_task(conn, tid, summary="handoff")
        comments = kb.list_comments(conn, tid)
        assert [c.model for c in comments] == ["gemini-3.5-flash", "claude-opus-4.6"]
        history = kb.task_worker_models(conn, [tid])[tid]
        models = [item["model"] for item in history]
        assert "gemini-3.5-flash" in models
        assert "claude-opus-4.6" in models
        assert models[-1] == "claude-opus-4.6"
    finally:
        conn.close()
        note_active_runtime_model(None)
