"""Tests for the Cursor Ultra (cursor-agent) provider client and resolution."""

import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import agent.auxiliary_client as ac
from agent.cursor_client import (
    AsyncCursorClient,
    CursorClient,
    _extract_tool_calls_from_text,
    _format_messages_as_prompt,
    _build_subprocess_env,
)
from agent.agent_runtime_helpers import create_openai_client


class TestCursorClient(unittest.TestCase):
    def test_format_messages_as_prompt_basic(self):
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello world"},
        ]
        prompt = _format_messages_as_prompt(messages, model="composer-2.5")
        self.assertIn("System Prompt:\nYou are a helpful assistant.", prompt)
        self.assertIn("User:\nHello world", prompt)

    def test_extract_tool_calls_from_text(self):
        raw_text = (
            'Here is the call:\n'
            '<tool_call>{"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{\\"path\\": \\"foo.py\\"}"}}</tool_call>\n'
            'Done.'
        )
        calls, cleaned = _extract_tool_calls_from_text(raw_text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].function.name, "read_file")
        self.assertEqual(json.loads(calls[0].function.arguments), {"path": "foo.py"})
        self.assertNotIn("read_file", cleaned)
        self.assertIn("Done.", cleaned)

    def test_cursor_client_create_chat_completion(self):
        client = CursorClient()
        with patch.object(
            client,
            "_run_prompt",
            return_value=("Hello from Cursor!", 100, 20),
        ):
            res = client.chat.completions.create(
                model="composer-2.5",
                messages=[{"role": "user", "content": "Hi"}],
            )

            self.assertEqual(res.choices[0].message.content, "Hello from Cursor!")
            self.assertEqual(res.usage.prompt_tokens, 100)
            self.assertEqual(res.usage.completion_tokens, 20)

    def test_resolve_provider_client_cursor(self):
        with patch(
            "agent.cursor_client.resolve_cursor_runtime_credentials",
            return_value={
                "api_key": "cursor-test-key",
                "base_url": "cursor://agent",
                "command": "cursor-agent",
            },
        ):
            client, model = ac.resolve_provider_client("cursor")
        self.assertIsNotNone(client)
        self.assertIsInstance(client, CursorClient)
        self.assertEqual(model, "composer-2.5")

    def test_resolve_provider_client_cursor_aliases(self):
        for alias in ["cursor-agent", "cursor-ultra"]:
            with patch(
                "agent.cursor_client.resolve_cursor_runtime_credentials",
                return_value={
                    "api_key": "cursor-test-key",
                    "base_url": "cursor://agent",
                    "command": "cursor-agent",
                },
            ):
                client, model = ac.resolve_provider_client(alias)
            self.assertIsNotNone(client)
            self.assertIsInstance(client, CursorClient)

    def test_auxiliary_cursor_uses_runtime_credential_resolver(self):
        with patch(
            "agent.cursor_client.resolve_cursor_runtime_credentials",
            return_value={
                "api_key": "cursor-test-key",
                "base_url": "cursor://agent",
                "command": "cursor-agent",
            },
        ) as resolver:
            client, _ = ac.resolve_provider_client("cursor")
        self.assertIsInstance(client, CursorClient)
        resolver.assert_called_once()

    def test_main_runtime_builds_cursor_client_before_url_validation(self):
        agent = SimpleNamespace(
            provider="cursor",
            model="composer-2.5",
            _client_log_context=lambda: "test",
        )

        client = create_openai_client(
            agent,
            {"api_key": "cursor-test-key", "base_url": "cursor://agent"},
            reason="test",
            shared=True,
        )

        self.assertIsInstance(client, CursorClient)

    def test_explicit_api_key_is_forwarded_only_as_environment(self):
        with patch.dict("os.environ", {}, clear=True):
            env = _build_subprocess_env("cursor-test-key")
        self.assertEqual(env["CURSOR_API_KEY"], "cursor-test-key")
        self.assertEqual(env["AGENT_CLI_CREDENTIAL_STORE"], "file")

    def test_acp_process_command(self):
        client = CursorClient(api_key="cursor-test-key", cursor_bin="cursor-agent")
        proc = MagicMock()
        proc.poll.return_value = None
        proc.stdin = MagicMock()
        proc.stdout = []
        proc.stderr = []
        with (
            patch("subprocess.Popen", return_value=proc) as popen,
            patch.object(client, "_request", return_value={}),
        ):
            self.assertIs(client._start_process("composer-2.5"), proc)
        command = popen.call_args.args[0]
        self.assertEqual(command, ["cursor-agent", "acp", "--model", "composer-2.5"])
        self.assertNotIn("cursor-test-key", command)

    def test_run_prompt_reuses_process_and_creates_fresh_sessions(self):
        client = CursorClient()
        proc = MagicMock()
        session_number = 0

        def fake_request(method, params, **kwargs):
            nonlocal session_number
            if method == "session/new":
                session_number += 1
                return {"sessionId": f"session-{session_number}"}
            if method == "session/prompt":
                kwargs["text_parts"].append(f"reply-{session_number}")
                return {"stopReason": "end_turn"}
            return {}

        with (
            patch.object(client, "_start_process", return_value=proc) as start,
            patch.object(client, "_request", side_effect=fake_request),
        ):
            first = client._run_prompt("one", model="composer-2.5", timeout_seconds=10)
            second = client._run_prompt("two", model="composer-2.5", timeout_seconds=10)

        self.assertEqual(first[0], "reply-1")
        self.assertEqual(second[0], "reply-2")
        self.assertEqual(start.call_count, 2)
        self.assertEqual(session_number, 2)

    def test_idle_process_is_closed(self):
        client = CursorClient(idle_timeout_seconds=0.01)
        proc = MagicMock()
        terminated = threading.Event()
        proc.terminate.side_effect = terminated.set
        with client._active_process_lock:
            client._active_process = proc
        client._schedule_idle_close()
        self.assertTrue(terminated.wait(0.5))
        self.assertIsNone(client._active_process)


if __name__ == "__main__":
    unittest.main()
