"""The session prompt must name the board of the room it is speaking in.

Reported 2026-09-15: asked to resize logos in the worldvision room
(-5515742264), project_lead replied "이 방 소관이 아닙니다. 월드비전 아이콘
작업은 월드비전 방문 일정 방에서 이어가면 됩니다" — telling the user to go to
the room it was already in. The only board it had ever been told about was the
one hardcoded into ORGANIZATION_KANBAN_SCOPE_GUIDANCE, so a room with its own
board always reads as somebody else's work.
"""

from __future__ import annotations

import pytest

from gateway.config import Platform
from gateway.session import SessionContext, SessionSource, build_session_context_prompt


def _ctx(
    chat_name: str | None,
    chat_id: str = "-5515742264",
    chat_type: str = "group",
) -> SessionContext:
    return SessionContext(
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id=chat_id,
            chat_name=chat_name,
            chat_type=chat_type,
        ),
        connected_platforms=[Platform.TELEGRAM],
        home_channels={},
    )


def test_worldvision_room_is_told_its_own_board() -> None:
    prompt = build_session_context_prompt(_ctx("[프로젝트] 월드비전 방문 일정"))
    assert "worldvision" in prompt
    # The org-wide board is not this room's board and must not be implied.
    assert "crazyup-fillgaps" not in prompt


@pytest.mark.parametrize(
    "room,board",
    [
        ("[프로젝트] 충격음", "rs101"),
        ("[프로젝트] 화상영어", "pickclass"),
        ("[프로젝트] 돌봄 키오스크", "wolgok"),
        ("[프로젝트] NEXUS", "crazyup-fillgaps"),
    ],
)
def test_each_room_gets_the_board_it_owns(room: str, board: str) -> None:
    assert board in build_session_context_prompt(_ctx(room))


def test_an_unmapped_room_claims_no_board() -> None:
    """board_for_room returns None rather than guessing; so must the prompt.

    Falling back to the org board is exactly the bug: it is how a room with
    its own work came to be told it owned somebody else's.
    """
    prompt = build_session_context_prompt(_ctx("[프로젝트] 존재하지-않는-방-xyz"))
    assert "Kanban Board" not in prompt
    assert "crazyup-fillgaps" not in prompt


def test_a_dm_claims_no_board() -> None:
    ctx = _ctx(None, chat_id="123", chat_type="dm")
    assert "Kanban Board" not in build_session_context_prompt(ctx)


def test_board_lookup_never_breaks_the_prompt(monkeypatch) -> None:
    """The registry lives outside the repo; a broken one must not kill a turn."""
    import gateway.session as gs

    monkeypatch.setattr(
        gs, "_board_for_chat_name",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("registry exploded")),
    )
    prompt = build_session_context_prompt(_ctx("[프로젝트] 월드비전 방문 일정"))
    assert "Current Session Context" in prompt


def test_room_name_is_still_untrusted_metadata() -> None:
    """A board line must not turn a chat name into a trusted instruction."""
    prompt = build_session_context_prompt(_ctx("[프로젝트] 월드비전 방문 일정"))
    assert "untrusted metadata" in prompt
