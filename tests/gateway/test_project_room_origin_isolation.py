"""RED tests for immutable async-origin routing and fail-closed chat isolation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.config import Platform
from gateway.run import GatewayRunner
from gateway.session import SessionSource


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
