"""Genspark LLM Proxy client adapter.

Intercepts responses from Genspark's LLM proxy endpoint. When Genspark returns
an HTTP 200 OK response containing a credit exhaustion notice instead of an
HTTP error code (e.g. 402/429), this adapter detects the message and raises
a GensparkCreditExhaustedError. This allows Hermes error classification and
fallback mechanisms to treat credit exhaustion as a billing failure and
automatically switch to the next fallback provider.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Iterator, Optional

GENSPARK_CREDIT_EXHAUSTED_PATTERNS = (
    "your genspark credits have been exhausted",
    "credits have been exhausted",
    "genspark.ai/pricing?fromurl=credit_exhausted",
    "insufficient credits",
)


def is_genspark_credit_exhaustion_message(text: Optional[str]) -> bool:
    """Return True if the text indicates Genspark credit exhaustion."""
    if not text or not isinstance(text, str):
        return False
    lowered = text.lower()
    return any(pattern in lowered for pattern in GENSPARK_CREDIT_EXHAUSTED_PATTERNS)


class GensparkCreditExhaustedError(RuntimeError):
    """Raised when Genspark LLM proxy returns HTTP 200 OK with credit exhaustion text."""

    def __init__(
        self,
        message: str = (
            "Your Genspark credits have been exhausted. "
            "Please visit https://www.genspark.ai/pricing?fromurl=credit_exhausted to purchase more credits."
        ),
    ):
        super().__init__(message)


class GensparkCompletions:
    """Wrapper around sync chat.completions to catch credit exhaustion in responses."""

    def __init__(self, raw_completions: Any):
        self._raw = raw_completions

    def create(self, *args: Any, **kwargs: Any) -> Any:
        is_stream = bool(kwargs.get("stream", False))
        if not is_stream:
            res = self._raw.create(*args, **kwargs)
            choices = getattr(res, "choices", None)
            if choices and len(choices) > 0:
                first_choice = choices[0]
                message = getattr(first_choice, "message", None)
                content = getattr(message, "content", None) or ""
                if is_genspark_credit_exhaustion_message(content):
                    raise GensparkCreditExhaustedError(content)
            return res

        raw_stream = self._raw.create(*args, **kwargs)
        return self._stream_wrapper(raw_stream)

    def _stream_wrapper(self, stream_iter: Iterator[Any]) -> Iterator[Any]:
        accumulated_text: list[str] = []
        for chunk in stream_iter:
            choices = getattr(chunk, "choices", None)
            if choices and len(choices) > 0:
                delta = getattr(choices[0], "delta", None)
                delta_content = getattr(delta, "content", None)
                if delta_content and isinstance(delta_content, str):
                    accumulated_text.append(delta_content)
                    joined = "".join(accumulated_text)
                    if is_genspark_credit_exhaustion_message(joined):
                        raise GensparkCreditExhaustedError(joined)
            yield chunk


class GensparkChat:
    def __init__(self, raw_chat: Any):
        self._raw = raw_chat
        self.completions = GensparkCompletions(raw_chat.completions)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw, name)


class GensparkClient:
    """OpenAI-compatible client wrapper for Genspark Plus LLM Proxy."""

    def __init__(self, raw_client: Any):
        self._raw_client = raw_client
        self.chat = GensparkChat(raw_client.chat)
        self.api_key = getattr(raw_client, "api_key", "")
        self.base_url = getattr(raw_client, "base_url", "")
        self.default_headers = getattr(
            raw_client, "_custom_headers", getattr(raw_client, "default_headers", {})
        )
        self._custom_headers = self.default_headers

    def close(self) -> None:
        if hasattr(self._raw_client, "close") and callable(self._raw_client.close):
            self._raw_client.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw_client, name)


class AsyncGensparkCompletions:
    """Wrapper around async chat.completions to catch credit exhaustion in responses."""

    def __init__(self, raw_completions: Any):
        self._raw = raw_completions

    async def create(self, *args: Any, **kwargs: Any) -> Any:
        is_stream = bool(kwargs.get("stream", False))
        if not is_stream:
            res = await self._raw.create(*args, **kwargs)
            choices = getattr(res, "choices", None)
            if choices and len(choices) > 0:
                first_choice = choices[0]
                message = getattr(first_choice, "message", None)
                content = getattr(message, "content", None) or ""
                if is_genspark_credit_exhaustion_message(content):
                    raise GensparkCreditExhaustedError(content)
            return res

        raw_stream = await self._raw.create(*args, **kwargs)
        return self._stream_wrapper(raw_stream)

    async def _stream_wrapper(self, stream_iter: AsyncIterator[Any]) -> AsyncIterator[Any]:
        accumulated_text: list[str] = []
        async for chunk in stream_iter:
            choices = getattr(chunk, "choices", None)
            if choices and len(choices) > 0:
                delta = getattr(choices[0], "delta", None)
                delta_content = getattr(delta, "content", None)
                if delta_content and isinstance(delta_content, str):
                    accumulated_text.append(delta_content)
                    joined = "".join(accumulated_text)
                    if is_genspark_credit_exhaustion_message(joined):
                        raise GensparkCreditExhaustedError(joined)
            yield chunk


class AsyncGensparkChat:
    def __init__(self, raw_chat: Any):
        self._raw = raw_chat
        self.completions = AsyncGensparkCompletions(raw_chat.completions)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw, name)


class AsyncGensparkClient:
    """Async OpenAI-compatible client wrapper for Genspark Plus LLM Proxy."""

    def __init__(self, sync_or_async_client: Any):
        if isinstance(sync_or_async_client, GensparkClient):
            from openai import AsyncOpenAI

            sync_raw = sync_or_async_client._raw_client
            async_raw = AsyncOpenAI(
                api_key=sync_or_async_client.api_key,
                base_url=str(sync_or_async_client.base_url),
                max_retries=0,
            )
            self._raw_client = async_raw
        else:
            self._raw_client = sync_or_async_client

        self.chat = AsyncGensparkChat(self._raw_client.chat)
        self.api_key = getattr(self._raw_client, "api_key", "")
        self.base_url = getattr(self._raw_client, "base_url", "")
        self.default_headers = getattr(
            self._raw_client,
            "_custom_headers",
            getattr(self._raw_client, "default_headers", {}),
        )
        self._custom_headers = self.default_headers

    async def close(self) -> None:
        if hasattr(self._raw_client, "close") and callable(self._raw_client.close):
            res = self._raw_client.close()
            if asyncio.iscoroutine(res):
                await res

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw_client, name)
