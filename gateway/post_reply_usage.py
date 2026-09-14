"""Edit a Telegram reply's usage footer when causally linked work finishes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from gateway.runtime_footer import format_turn_token_breakdown, format_api_equivalent_cost
from decimal import Decimal

logger = logging.getLogger(__name__)


def _gross(usage: dict[str, Any]) -> int:
    return sum(max(0, int(usage.get(key) or 0)) for key in (
        "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens",
    ))


class PostReplyUsage:
    """One turn's delivered footer and completed auxiliary usage.

    Call ``record_from_thread`` with a stable task name once the provider phase
    has finished. A completion before Telegram ACK is held until ``bind``.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._tasks: dict[str, dict[str, Any]] = {}
        self._adapter = None
        self._chat_id = ""
        self._message_id = ""
        self._footer = ""
        self._edit_task: asyncio.Task | None = None
        self.turn_id = ""

    def record_from_thread(self, task: str, usage: dict[str, Any]) -> None:
        if not _gross(usage):
            return
        try:
            self._loop.call_soon_threadsafe(self._record, str(task), dict(usage))
        except RuntimeError:
            logger.debug("Post-reply usage loop closed", exc_info=True)

    def _record(self, task: str, usage: dict[str, Any]) -> None:
        self._tasks[task] = usage
        self._schedule_edit()

    def bind(self, adapter: Any, chat_id: str, message_id: str, footer: str) -> None:
        if not message_id or not footer:
            return
        self._adapter = adapter
        self._chat_id = str(chat_id)
        self._message_id = str(message_id)
        self._footer = footer
        self._schedule_edit()

    def _schedule_edit(self) -> None:
        if not self._message_id or not self._tasks:
            return
        if self._edit_task is None or self._edit_task.done():
            self._edit_task = self._loop.create_task(self._edit())

    async def _edit(self) -> None:
        # Serialize edits so a late second completion cannot overwrite a newer
        # total. The loop re-reads task state after every platform ACK.
        while True:
            snapshot = {key: dict(value) for key, value in self._tasks.items()}
            totals = {
                key: sum(max(0, int(value.get(key) or 0)) for value in snapshot.values())
                for key in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
            }
            task_names = ", ".join(sorted(snapshot))
            line = f"후속 작업: {format_turn_token_breakdown(totals)} ({task_names})"
            cost = (
                None if any(
                    "api_equivalent_cost_usd" not in value
                    or int(value.get("api_equivalent_unknown_calls") or 0)
                    for value in snapshot.values()
                )
                else str(sum((Decimal(str(value.get("api_equivalent_cost_usd") or 0))
                              for value in snapshot.values()), Decimal(0)))
            )
            line += f" · {format_api_equivalent_cost(cost)}"
            try:
                result = await self._adapter.edit_message(
                    self._chat_id, self._message_id,
                    f"{self._footer}\n{line}", finalize=True,
                )
            except Exception:
                logger.warning("Post-reply usage footer edit failed", exc_info=True)
                return
            if not getattr(result, "success", False):
                logger.warning("Post-reply usage footer edit failed: %s", getattr(result, "error", ""))
                return
            if snapshot == self._tasks:
                return
