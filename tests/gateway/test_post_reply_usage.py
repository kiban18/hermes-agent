"""Causal follow-up usage edits the acknowledged Telegram footer."""

import asyncio
import threading
from types import SimpleNamespace

from gateway.post_reply_usage import PostReplyUsage


def test_usage_before_and_after_delivery_edits_same_footer_once_per_completion():
    async def scenario():
        edits = []

        class Adapter:
            async def edit_message(self, chat_id, message_id, content, *, finalize):
                edits.append((chat_id, message_id, content, finalize))
                return SimpleNamespace(success=True)

        tracker = PostReplyUsage(asyncio.get_running_loop())
        thread = threading.Thread(target=lambda: tracker.record_from_thread(
            "background_review",
            {"input_tokens": 20, "output_tokens": 30,
             "cache_read_tokens": 800_000, "cache_write_tokens": 10},
        ))
        thread.start()
        thread.join()
        await asyncio.sleep(0)
        assert edits == []

        tracker.bind(Adapter(), "chat", "message", "AI: project_lead · grok-4.6 · 1,000 tokens")
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(edits) == 1
        assert edits[0][:2] == ("chat", "message")
        assert (
            "후속 작업: 비캐시 입력 20 · 비캐시 출력 30"
            " · 캐시 읽기 입력 800,000 · 캐시 저장 입력 10 (background_review)"
        ) in edits[0][2]
        assert edits[0][3] is True

        # Re-reporting the same task replaces its final snapshot; it does not
        # count the same fork twice.
        tracker.record_from_thread("background_review", {
            "input_tokens": 20, "output_tokens": 40,
            "cache_read_tokens": 800_000, "cache_write_tokens": 10,
        })
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(edits) == 2
        assert "비캐시 출력 40 · 캐시 읽기 입력 800,000" in edits[-1][2]

    asyncio.run(scenario())
