from types import SimpleNamespace

import gateway.run as gateway_run
from gateway.config import Platform
from gateway.platforms.base import MessageEvent, MessageType
from gateway.session import SessionSource
from plugins.platforms.telegram.adapter import TelegramAdapter


def _event(text: str) -> MessageEvent:
    return MessageEvent(
        text=text,
        message_type=MessageType.TEXT,
        source=SessionSource(platform=Platform.TELEGRAM, chat_id="123", chat_type="dm"),
    )


def test_gateway_drops_whitespace_equivalent_inflight_followup():
    runner = object.__new__(gateway_run.GatewayRunner)
    runner._in_flight_user_text = {}
    runner._peek_session_state = lambda _key: None
    runner._remember_in_flight_user_text("session", "전화, 문자")

    adapter = SimpleNamespace(_pending_messages={})

    assert runner._is_duplicate_busy_followup("session", _event("전화,문자"), adapter)
    assert not runner._is_duplicate_busy_followup("session", _event("다른 요청"), adapter)


def test_telegram_adapter_drops_recent_whitespace_equivalent_dispatch():
    adapter = object.__new__(TelegramAdapter)
    adapter._recent_text_dispatches = {}
    adapter._remember_dispatched_text("session", "전화, 문자")

    assert adapter._is_recent_duplicate_text("session", "전화,문자")
    assert not adapter._is_recent_duplicate_text("session", "다른 요청")
