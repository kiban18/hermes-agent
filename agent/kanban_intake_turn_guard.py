"""Refuse to let a turn end quietly while cards it was handed are still unmade.

The handoff that replaced the dropped-card failure ends at the parent: a child
queues an intent it may not write, the parent is told in the text it acts on,
and it calls ``kanban_create`` with the receipt. Nothing forces that last step.
A parent that reads the notice and answers anyway leaves the card exactly as
lost as before — and for a month that is precisely what happened, 753 times,
with "별도 채널에서 처리하겠습니다" standing in for work that reached no board.

So the turn says so, in the response the person reads, naming each receipt.
Same shape as the file-mutation verifier: a claim about work the turn was asked
to record is settled against the record, at the end, out loud.

It reports and never creates. The parent owns its board; a finalizer writing
cards on its own would be the unaccountable second mutator the Kanban guard
exists to prevent.
"""

from __future__ import annotations

from typing import Any, Iterable

MAX_SHOWN = 10


def pending_intake_for_turn(session_ids: Iterable[str], home=None) -> list[dict[str, Any]]:
    """Queued cards still unmade, for the child sessions this turn delegated to.

    Never raises: an unreadable queue must not cost the turn its answer.
    """
    out: list[dict[str, Any]] = []
    try:
        from agent.kanban_intake import pending
    except Exception:
        return out
    seen: set[str] = set()
    for session_id in session_ids or []:
        sid = str(session_id or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        try:
            out.extend(pending(sid, home=home))
        except Exception:
            continue
    return out


def format_pending_intake_footer(rows: list[dict[str, Any]]) -> str:
    """Render the unmade cards for the end of a response, or "" when there are none."""
    if not rows:
        return ""
    lines = [
        f"⚠️ 칸반 접수 {len(rows)}건이 아직 어느 보드에도 없습니다. "
        "위임한 하위 작업이 만들지 못해 넘긴 카드입니다."
    ]
    for row in rows[:MAX_SHOWN]:
        intent = row.get("intent") or {}
        lines.append(
            f"  • receipt={row.get('receipt')} "
            f"board={intent.get('board') or '?'} "
            f"assignee={intent.get('assignee') or '?'} "
            f"title={intent.get('title') or '?'}"
        )
    if len(rows) > MAX_SHOWN:
        lines.append(f"  • … 외 {len(rows) - MAX_SHOWN}건")
    lines.append(
        "  `kanban_create` 로 만들고 `receipt` 를 넘겨 접수를 닫으세요. "
        "만들지 않으면 그 일은 사라집니다."
    )
    return "\n".join(lines)
