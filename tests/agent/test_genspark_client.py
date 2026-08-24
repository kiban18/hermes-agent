import asyncio
from types import SimpleNamespace
import unittest
from unittest import mock

from agent.error_classifier import FailoverReason, classify_api_error
from agent.genspark_client import (
    AsyncGensparkClient,
    GensparkClient,
    GensparkCreditExhaustedError,
    is_genspark_credit_exhaustion_message,
)
from agent.agent_runtime_helpers import create_openai_client


class FakeMessage:
    def __init__(self, content: str):
        self.content = content


class FakeChoice:
    def __init__(self, content: str = None, delta_content: str = None):
        if content is not None:
            self.message = FakeMessage(content)
        if delta_content is not None:
            self.delta = SimpleNamespace(content=delta_content)


class FakeResponse:
    def __init__(self, content: str):
        self.choices = [FakeChoice(content=content)]


class FakeStreamChunk:
    def __init__(self, delta_content: str = None):
        self.choices = [FakeChoice(delta_content=delta_content)]


class FakeCompletions:
    def __init__(self, response_or_chunks, is_stream: bool = False):
        self.response_or_chunks = response_or_chunks
        self.is_stream = is_stream

    def create(self, *args, **kwargs):
        if kwargs.get("stream", False):
            return iter(self.response_or_chunks)
        return self.response_or_chunks


class FakeAsyncCompletions:
    def __init__(self, response_or_chunks, is_stream: bool = False):
        self.response_or_chunks = response_or_chunks
        self.is_stream = is_stream

    async def create(self, *args, **kwargs):
        if kwargs.get("stream", False):
            async def _gen():
                for c in self.response_or_chunks:
                    yield c
            return _gen()
        return self.response_or_chunks


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeRawClient:
    def __init__(self, completions, is_async: bool = False):
        self.chat = FakeChat(completions)
        self.api_key = "test-api-key"
        self.base_url = "https://www.genspark.ai/api/llm_proxy/v1"
        self.default_headers = {}


class GensparkClientTests(unittest.TestCase):
    def test_main_runtime_wraps_openai_client(self):
        raw = FakeRawClient(FakeCompletions(FakeResponse("Normal response")))
        agent = SimpleNamespace(
            provider="genspark",
            model="kimi-k3",
            _build_keepalive_http_client=lambda *a, **k: None,
            _client_log_context=lambda: "test",
        )
        with mock.patch("run_agent.OpenAI", return_value=raw):
            client = create_openai_client(
                agent,
                {
                    "api_key": "genspark-test-key",
                    "base_url": "https://www.genspark.ai/api/llm_proxy/v1",
                },
                reason="test",
                shared=True,
            )

        self.assertIsInstance(client, GensparkClient)

    def test_detection_patterns(self):
        msg1 = (
            "Your Genspark credits have been exhausted. "
            "Please visit https://www.genspark.ai/pricing?fromurl=credit_exhausted to purchase more credits."
        )
        msg2 = "Hello world! How can I help you today?"
        self.assertTrue(is_genspark_credit_exhaustion_message(msg1))
        self.assertFalse(is_genspark_credit_exhaustion_message(msg2))
        self.assertFalse(is_genspark_credit_exhaustion_message(None))

    def test_sync_non_streaming_success(self):
        raw = FakeRawClient(FakeCompletions(FakeResponse("Normal response")))
        client = GensparkClient(raw)
        res = client.chat.completions.create(model="kimi-k3", messages=[])
        self.assertEqual(res.choices[0].message.content, "Normal response")

    def test_sync_non_streaming_credit_exhausted(self):
        exhausted_text = "Your Genspark credits have been exhausted. Please purchase more credits."
        raw = FakeRawClient(FakeCompletions(FakeResponse(exhausted_text)))
        client = GensparkClient(raw)
        with self.assertRaises(GensparkCreditExhaustedError):
            client.chat.completions.create(model="kimi-k3", messages=[])

    def test_sync_streaming_success(self):
        chunks = [FakeStreamChunk("Hello "), FakeStreamChunk("world")]
        raw = FakeRawClient(FakeCompletions(chunks, is_stream=True))
        client = GensparkClient(raw)
        stream = client.chat.completions.create(model="kimi-k3", messages=[], stream=True)
        collected = [c.choices[0].delta.content for c in stream]
        self.assertEqual(collected, ["Hello ", "world"])

    def test_sync_streaming_credit_exhausted(self):
        chunks = [
            FakeStreamChunk("Your Genspark credits have been exhausted. "),
            FakeStreamChunk("Please purchase more credits."),
        ]
        raw = FakeRawClient(FakeCompletions(chunks, is_stream=True))
        client = GensparkClient(raw)
        stream = client.chat.completions.create(model="kimi-k3", messages=[], stream=True)
        with self.assertRaises(GensparkCreditExhaustedError):
            list(stream)

    def test_async_non_streaming_credit_exhausted(self):
        async def _run():
            exhausted_text = "Your Genspark credits have been exhausted."
            raw = FakeRawClient(FakeAsyncCompletions(FakeResponse(exhausted_text)), is_async=True)
            client = AsyncGensparkClient(raw)
            with self.assertRaises(GensparkCreditExhaustedError):
                await client.chat.completions.create(model="kimi-k3", messages=[])
        asyncio.run(_run())

    def test_error_classifier_integration(self):
        err = GensparkCreditExhaustedError(
            "Your Genspark credits have been exhausted. "
            "Please visit https://www.genspark.ai/pricing?fromurl=credit_exhausted to purchase more credits."
        )
        classified = classify_api_error(err, provider="genspark", model="kimi-k3")
        self.assertEqual(classified.reason, FailoverReason.billing)
        self.assertTrue(classified.should_fallback)
        self.assertFalse(classified.retryable)


if __name__ == "__main__":
    unittest.main()
