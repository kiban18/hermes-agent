"""RED tests for immutable async-origin routing and fail-closed chat isolation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest

from gateway.config import Platform
from gateway.run import GatewayRunner
from gateway.session import SessionSource
from tools.process_registry import ProcessRegistry, ProcessSession


class _Entries:
    def __init__(self, entries=None):
        self._entries = entries or {}

    def _ensure_loaded(self):
        return None


def _runner(adapter=None, entries=None):
    runner = object.__new__(GatewayRunner)
    runner.adapters = {Platform.TELEGRAM: adapter or SimpleNamespace(handle_message=AsyncMock())}
    runner.session_store = _Entries(entries)
    runner._session_source_cache = {}
    return runner


def _strict_event(**overrides):
    event = {
        "type": "async_delegation",
        "origin_envelope_version": 1,
        "session_key": "agent:main:telegram:group:-5272812362",
        "origin_session_key": "agent:main:telegram:group:-5272812362",
        "origin_chat_id": "-5272812362",
        "origin_profile": "project_lead",
        "origin_board": "wolgok",
        "origin_project": "돌봄 키오스크",
    }
    event.update(overrides)
    return event


def test_capture_routing_origin_seals_chat_profile_board_and_project(monkeypatch):
    import tools.async_delegation as delegation
    from gateway.session_context import clear_session_vars, set_session_vars

    monkeypatch.setenv("HERMES_KANBAN_BOARD", "wolgok")
    tokens = set_session_vars(
        platform="telegram",
        chat_id="-5272812362",
        chat_type="group",
        chat_name="[프로젝트] 돌봄 키오스크",
        session_key="agent:main:telegram:group:-5272812362",
        profile="project_lead",
    )
    try:
        origin = delegation._capture_routing_origin()
    finally:
        clear_session_vars(tokens)

    assert origin == {
        "origin_envelope_version": 1,
        "origin_chat_id": "-5272812362",
        "origin_session_key": "agent:main:telegram:group:-5272812362",
        "origin_profile": "project_lead",
        "origin_board": "wolgok",
        "origin_project": "[프로젝트] 돌봄 키오스크",
    }


def test_stale_session_store_origin_conflicting_with_envelope_is_quarantined():
    stale = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="-5413942079",
        chat_type="group",
        user_id="representative",
    )
    runner = _runner(entries={
        "agent:main:telegram:group:-5272812362": SimpleNamespace(origin=stale)
    })

    assert runner._build_process_event_source(_strict_event()) is None


def test_strict_async_event_without_origin_chat_id_is_quarantined():
    runner = _runner()
    event = _strict_event()
    event.pop("origin_chat_id")

    assert runner._build_process_event_source(event) is None


@pytest.mark.asyncio
async def test_injected_completion_carries_immutable_origin_metadata():
    adapter = SimpleNamespace(handle_message=AsyncMock())
    runner = _runner(adapter=adapter)
    event = _strict_event(parent_session_id="parent-session")

    result = await runner._inject_watch_notification("[IMPORTANT: done]", event)

    assert result is True
    injected = adapter.handle_message.await_args.args[0]
    assert injected.source.chat_id == "-5272812362"
    assert injected.metadata["gateway_session_key"] == event["origin_session_key"]
    assert injected.metadata["origin_chat_id"] == "-5272812362"
    assert injected.metadata["origin_profile"] == "project_lead"
    assert injected.metadata["origin_board"] == "wolgok"
    assert injected.metadata["origin_project"] == "돌봄 키오스크"


@pytest.mark.asyncio
async def test_quarantine_cannot_fall_through_to_api_self_post(monkeypatch):
    api_adapter = SimpleNamespace(handle_message=AsyncMock())
    stale = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="-5413942079",
        chat_type="group",
        user_id="representative",
    )
    runner = _runner(
        entries={
            "agent:main:telegram:group:-5272812362": SimpleNamespace(origin=stale)
        }
    )
    runner.adapters[Platform.API_SERVER] = api_adapter
    self_posts = []

    async def fake_deliver_wake(*args, **kwargs):
        self_posts.append((args, kwargs))

    monkeypatch.setattr("gateway.wake.deliver_wake", fake_deliver_wake)
    event = _strict_event(origin_session_id="raw-api-session")

    result = await runner._inject_watch_notification("[IMPORTANT: done]", event)

    assert result is None
    assert self_posts == []


def test_async_group_key_and_enrichment_use_immutable_origin():
    runner = _runner()
    first = _strict_event(chat_id="-5413942079", platform="telegram")
    second = _strict_event(
        origin_chat_id="-5338066929",
        origin_session_key="agent:main:telegram:group:-5338066929",
        chat_id="-5413942079",
        platform="telegram",
    )

    runner._enrich_async_delegation_routing(first)

    assert first["chat_id"] == "-5272812362"
    assert runner._async_delegation_group_key(first) != runner._async_delegation_group_key(second)


def test_cross_room_completion_never_reaches_adapter_or_agent():
    adapter = SimpleNamespace(handle_message=AsyncMock())
    stale = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="-5413942079",
        chat_type="group",
        user_id="representative",
    )
    runner = _runner(
        adapter=adapter,
        entries={
            "agent:main:telegram:group:-5272812362": SimpleNamespace(origin=stale)
        },
    )

    result = asyncio.run(
        runner._inject_watch_notification("[IMPORTANT: wolgok done]", _strict_event())
    )

    assert result is None
    adapter.handle_message.assert_not_awaited()


def test_background_process_completion_preserves_the_origin_envelope(tmp_path, monkeypatch):
    import tools.process_registry as process_module

    monkeypatch.setattr(process_module, "CHECKPOINT_PATH", tmp_path / "processes.json")
    registry = ProcessRegistry()
    session = ProcessSession(
        id="proc_origin",
        command="true",
        session_key="agent:main:telegram:group:-5272812362",
        started_at=1.0,
        exited=True,
        exit_code=0,
        notify_on_complete=True,
        origin_envelope_version=1,
        origin_chat_id="-5272812362",
        origin_session_key="agent:main:telegram:group:-5272812362",
        origin_profile="project_lead",
        origin_board="wolgok",
        origin_project="[프로젝트] 돌봄 키오스크",
    )
    registry._running[session.id] = session

    registry._move_to_finished(session)

    event = registry.completion_queue.get_nowait()
    assert event["origin_envelope_version"] == 1
    assert event["origin_chat_id"] == "-5272812362"
    assert event["origin_session_key"] == session.session_key
    assert event["origin_profile"] == "project_lead"
    assert event["origin_board"] == "wolgok"
    assert event["origin_project"] == "[프로젝트] 돌봄 키오스크"


def test_pre_llm_hook_receives_gateway_origin_metadata():
    from tests.agent.test_api_content_sidecar import _FakeAgent, _build

    agent = _FakeAgent()
    agent._gateway_event_metadata = {
        "origin_chat_id": "-5272812362",
        "origin_profile": "project_lead",
        "origin_board": "wolgok",
        "origin_project": "[프로젝트] 돌봄 키오스크",
    }
    captured = {}

    def invoke(_name, **kwargs):
        captured.update(kwargs)
        return []

    with patch("hermes_cli.plugins.invoke_hook", side_effect=invoke):
        _build(agent)

    assert captured["extra"] == agent._gateway_event_metadata
