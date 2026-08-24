"""OpenAI-compatible shim that forwards Hermes requests to Cursor ACP.

This adapter lets Hermes treat the Cursor Ultra `cursor-agent` CLI as a
chat-style provider backend. A client keeps one ``cursor-agent acp`` process
alive and creates a fresh ACP session for every Hermes completion, avoiding
repeated CLI startup/authentication without leaking conversation state.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator, Iterator, Optional

from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)

from agent.file_safety import is_write_approval_required
from agent.redact import redact_sensitive_text
from agent.secret_scope import get_secret
from tools.environments.local import hermes_subprocess_env

CURSOR_MARKER_BASE_URL = "cursor://agent"
DEFAULT_CURSOR_MODEL = "composer-2.5"
_DEFAULT_TIMEOUT_SECONDS = 900.0
_DEFAULT_IDLE_TIMEOUT_SECONDS = 180.0

_TOOL_CALL_BLOCK_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_TOOL_CALL_JSON_RE = re.compile(
    r"\{\s*\"id\"\s*:\s*\"[^\"]+\"\s*,\s*\"type\"\s*:\s*\"function\"\s*,\s*\"function\"\s*:\s*\{.*?\}\s*\}",
    re.DOTALL,
)


def _resolve_cursor_bin() -> str:
    env_bin = os.getenv("CURSOR_AGENT_BIN", "").strip()
    if env_bin:
        return env_bin
    default_path = Path.home() / ".local" / "bin" / "cursor-agent"
    if default_path.is_file() and os.access(default_path, os.X_OK):
        return str(default_path)
    return "cursor-agent"


def resolve_cursor_runtime_credentials(
    *,
    explicit_api_key: str | None = None,
    explicit_base_url: str | None = None,
) -> dict[str, str]:
    """Resolve the headless Cursor credential used by Hermes daemons."""
    api_key = (explicit_api_key or "").strip()
    source = "explicit"
    if not api_key:
        for name in ("CURSOR_API_KEY", "CURSOR_AUTH_TOKEN"):
            api_key = (get_secret(name, "") or "").strip()
            if api_key:
                source = name
                break
    if not api_key:
        raise RuntimeError(
            "Cursor daemon credential missing. Set CURSOR_API_KEY in the active profile .env."
        )

    cursor_bin = _resolve_cursor_bin()
    command = shutil.which(cursor_bin)
    if not command and os.path.isfile(cursor_bin) and os.access(cursor_bin, os.X_OK):
        command = cursor_bin
    if not command:
        raise RuntimeError(f"cursor-agent is not executable at {cursor_bin!r}")

    return {
        "api_key": api_key,
        "base_url": (explicit_base_url or CURSOR_MARKER_BASE_URL).rstrip("/"),
        "command": command,
        "source": source,
    }


def _resolve_home_dir() -> str:
    home = os.environ.get("HOME", "").strip()
    if home:
        return home
    return str(Path.home())


def _build_subprocess_env(api_key: str | None = None) -> dict[str, str]:
    env = hermes_subprocess_env(inherit_credentials=True)
    home = _resolve_home_dir()
    env["HOME"] = home
    from hermes_constants import apply_subprocess_home_env

    apply_subprocess_home_env(env)
    for name in ("CURSOR_API_KEY", "CURSOR_AUTH_TOKEN"):
        env.pop(name, None)
    if api_key and api_key != "cursor":
        env["CURSOR_API_KEY"] = api_key
    # Headless macOS gateways cannot unlock the GUI login keychain. Cursor's
    # file store avoids touching it; authentication still comes from the API
    # key above, not from a persisted plaintext login token.
    if env.get("CURSOR_API_KEY") or env.get("CURSOR_AUTH_TOKEN"):
        env["AGENT_CLI_CREDENTIAL_STORE"] = "file"
    return env


def _render_message_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        if "text" in content:
            return str(content.get("text") or "").strip()
        if "content" in content and isinstance(content.get("content"), str):
            return str(content.get("content") or "").strip()
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        return "\n".join(parts).strip()
    return str(content).strip()


def _build_openai_tool_call(
    *,
    call_id: str,
    name: str,
    arguments: str,
) -> ChatCompletionMessageToolCall:
    return ChatCompletionMessageToolCall(
        id=call_id,
        call_id=call_id,
        response_item_id=None,
        type="function",
        function=Function(name=name, arguments=arguments),
    )


def _extract_tool_calls_from_text(text: str) -> tuple[list[ChatCompletionMessageToolCall], str]:
    if not isinstance(text, str) or not text.strip():
        return [], ""

    extracted: list[ChatCompletionMessageToolCall] = []
    consumed_spans: list[tuple[int, int]] = []

    def _try_add_tool_call(raw_json: str) -> None:
        try:
            obj = json.loads(raw_json)
        except Exception:
            return
        if not isinstance(obj, dict):
            return
        fn = obj.get("function")
        if not isinstance(fn, dict):
            return
        fn_name = fn.get("name")
        if not isinstance(fn_name, str) or not fn_name.strip():
            return
        fn_args = fn.get("arguments", "{}")
        if not isinstance(fn_args, str):
            fn_args = json.dumps(fn_args, ensure_ascii=False)
        call_id = obj.get("id")
        if not isinstance(call_id, str) or not call_id.strip():
            call_id = f"cursor_call_{len(extracted)+1}"

        extracted.append(
            _build_openai_tool_call(
                call_id=call_id,
                name=fn_name.strip(),
                arguments=fn_args,
            )
        )

    for match in _TOOL_CALL_BLOCK_RE.finditer(text):
        raw_json = match.group(1).strip()
        before_count = len(extracted)
        _try_add_tool_call(raw_json)
        if len(extracted) > before_count:
            consumed_spans.append(match.span())

    if not extracted:
        for match in _TOOL_CALL_JSON_RE.finditer(text):
            raw_json = match.group(0).strip()
            before_count = len(extracted)
            _try_add_tool_call(raw_json)
            if len(extracted) > before_count:
                consumed_spans.append(match.span())

    if not consumed_spans:
        return extracted, text.strip()

    cleaned_chars: list[str] = []
    last_idx = 0
    for start, end in sorted(consumed_spans, key=lambda s: s[0]):
        cleaned_chars.append(text[last_idx:start])
        last_idx = max(last_idx, end)
    cleaned_chars.append(text[last_idx:])
    cleaned_text = "".join(cleaned_chars).strip()
    return extracted, cleaned_text


def _format_messages_as_prompt(
    messages: list[dict[str, Any]],
    model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
) -> str:
    sections: list[str] = [
        "You are being used as the active agent backend for Hermes via Cursor Ultra.",
        "IMPORTANT: If you decide to take an action with a tool, you MUST output tool calls using <tool_call>{...}</tool_call> blocks with JSON exactly in OpenAI function-call shape.",
        "If no tool is needed, answer normally.",
    ]

    if isinstance(tools, list) and tools:
        tool_specs: list[dict[str, Any]] = []
        for t in tools:
            if not isinstance(t, dict):
                continue
            fn = t.get("function") or {}
            if not isinstance(fn, dict):
                continue
            name = fn.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            tool_specs.append(
                {
                    "name": name.strip(),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {}),
                }
            )
        if tool_specs:
            sections.append(
                "Available tools (OpenAI function schema). "
                "When using a tool, emit ONLY <tool_call>{...}</tool_call> with one JSON object "
                "containing id/type/function{name,arguments}. arguments must be a JSON string.\n"
                + json.dumps(tool_specs, ensure_ascii=False)
            )

    transcript: list[str] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "").strip().lower()
        content = _render_message_content(msg.get("content"))
        if not content and not msg.get("tool_calls"):
            continue

        tool_calls = msg.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            serialized_calls = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    serialized_calls.append(json.dumps(tc, ensure_ascii=False))
                else:
                    fn = getattr(tc, "function", None)
                    fn_name = getattr(fn, "name", "") if fn else ""
                    fn_args = getattr(fn, "arguments", "{}") if fn else "{}"
                    serialized_calls.append(
                        json.dumps(
                            {
                                "id": getattr(tc, "id", "call_unknown"),
                                "type": "function",
                                "function": {"name": fn_name, "arguments": fn_args},
                            },
                            ensure_ascii=False,
                        )
                    )
            rendered = f"{content}\nTool Calls: " + "\n".join(
                f"<tool_call>{c}</tool_call>" for c in serialized_calls
            )
        else:
            rendered = content

        label = {
            "system": "System Prompt",
            "user": "User",
            "assistant": "Assistant",
            "tool": "Tool Result",
            "context": "Context",
        }.get(role, role.title())
        transcript.append(f"{label}:\n{rendered}")

    if transcript:
        sections.append("Conversation transcript:\n\n" + "\n\n".join(transcript))

    sections.append("Continue the conversation from the latest user request.")
    return "\n\n".join(section.strip() for section in sections if section and section.strip())


def _completion_to_stream_chunks(completion: SimpleNamespace) -> list[SimpleNamespace]:
    choice = completion.choices[0]
    message = choice.message
    tool_call_deltas = None
    if message.tool_calls:
        tool_call_deltas = []
        for index, tool_call in enumerate(message.tool_calls):
            tool_call_deltas.append(
                SimpleNamespace(
                    index=index,
                    id=getattr(tool_call, "id", None),
                    type=getattr(tool_call, "type", "function"),
                    function=SimpleNamespace(
                        name=getattr(tool_call.function, "name", None),
                        arguments=getattr(tool_call.function, "arguments", None),
                    ),
                )
            )

    delta = SimpleNamespace(
        role="assistant",
        content=message.content or None,
        tool_calls=tool_call_deltas,
        reasoning_content=message.reasoning_content,
        reasoning=message.reasoning,
    )
    data_chunk = SimpleNamespace(
        choices=[
            SimpleNamespace(
                index=0,
                delta=delta,
                finish_reason=choice.finish_reason,
            )
        ],
        model=completion.model,
        usage=None,
    )
    usage_chunk = SimpleNamespace(
        choices=[],
        model=completion.model,
        usage=completion.usage,
    )
    return [data_chunk, usage_chunk]


class _CursorCompletionsNamespace:
    def __init__(self, client: CursorClient) -> None:
        self._client = client

    def create(self, *args: Any, **kwargs: Any) -> Any:
        return self._client._create_chat_completion(*args, **kwargs)


class _AsyncCursorCompletionsNamespace:
    def __init__(self, client: AsyncCursorClient) -> None:
        self._client = client

    async def create(self, *args: Any, **kwargs: Any) -> Any:
        return await self._client._create_chat_completion(*args, **kwargs)


class CursorClient:
    """Synchronous OpenAI-compatible client for Cursor Ultra CLI."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        cursor_bin: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        default_headers: dict[str, str] | None = None,
        idle_timeout_seconds: float = _DEFAULT_IDLE_TIMEOUT_SECONDS,
        **_: Any,
    ) -> None:
        self.api_key = api_key or "cursor"
        self.cursor_bin = cursor_bin or _resolve_cursor_bin()
        self.default_model = model or DEFAULT_CURSOR_MODEL
        self.base_url = base_url or CURSOR_MARKER_BASE_URL
        self._default_headers = dict(default_headers or {})
        self._custom_headers = dict(default_headers or {})
        self.default_headers = dict(default_headers or {})
        self.chat = SimpleNamespace(completions=_CursorCompletionsNamespace(self))
        self.is_closed = False
        self._active_process: subprocess.Popen[str] | None = None
        self._active_process_lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._inbox: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr_tail: deque[str] = deque(maxlen=40)
        self._next_request_id = 0
        self._process_model: str | None = None
        self._idle_timeout_seconds = max(0.0, float(idle_timeout_seconds))
        self._idle_timer: threading.Timer | None = None

    def _cancel_idle_timer(self) -> None:
        with self._active_process_lock:
            timer = self._idle_timer
            self._idle_timer = None
        if timer is not None:
            timer.cancel()

    def _schedule_idle_close(self) -> None:
        if self._idle_timeout_seconds <= 0:
            return

        def _close_if_idle() -> None:
            # Never terminate an in-flight prompt. If a request owns the lock,
            # it will schedule a fresh timer when it finishes.
            if not self._request_lock.acquire(blocking=False):
                return
            try:
                self.close()
            finally:
                self._request_lock.release()

        self._cancel_idle_timer()
        timer = threading.Timer(self._idle_timeout_seconds, _close_if_idle)
        timer.daemon = True
        with self._active_process_lock:
            self._idle_timer = timer
        timer.start()

    def close(self) -> None:
        self._cancel_idle_timer()
        with self._active_process_lock:
            proc = self._active_process
            self._active_process = None
        self.is_closed = True
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def _start_process(self, model: str) -> subprocess.Popen[str]:
        from hermes_cli._subprocess_compat import windows_hide_flags

        with self._active_process_lock:
            proc = self._active_process
            if proc is not None and proc.poll() is None and self._process_model == model:
                return proc
            if proc is not None:
                self.close()

            try:
                proc = subprocess.Popen(
                    [self.cursor_bin, "acp", "--model", model],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    env=_build_subprocess_env(self.api_key),
                    creationflags=windows_hide_flags(),
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    f"Could not start cursor-agent binary '{self.cursor_bin}'. "
                    "Ensure Cursor CLI is installed at ~/.local/bin/cursor-agent."
                ) from exc
            if proc.stdin is None or proc.stdout is None:
                proc.kill()
                raise RuntimeError("Cursor ACP process did not expose stdin/stdout pipes.")

            self._active_process = proc
            self._process_model = model
            self._inbox = queue.Queue()
            self._stderr_tail.clear()
            self.is_closed = False

            def _read_stdout() -> None:
                assert proc.stdout is not None
                for line in proc.stdout:
                    try:
                        self._inbox.put(json.loads(line))
                    except Exception:
                        self._inbox.put({"raw": line.rstrip("\n")})

            def _read_stderr() -> None:
                if proc.stderr is not None:
                    for line in proc.stderr:
                        self._stderr_tail.append(line.rstrip("\n"))

            threading.Thread(target=_read_stdout, daemon=True).start()
            threading.Thread(target=_read_stderr, daemon=True).start()
            self._request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {},
                    "clientInfo": {
                        "name": "hermes-agent",
                        "title": "Hermes Agent",
                        "version": "0.0.0",
                    },
                },
                timeout_seconds=30.0,
                process=proc,
            )
            return proc

    def _request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout_seconds: float,
        process: subprocess.Popen[str],
        text_parts: list[str] | None = None,
    ) -> Any:
        if process.stdin is None:
            raise RuntimeError("Cursor ACP stdin is unavailable.")
        self._next_request_id += 1
        request_id = self._next_request_id
        process.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": request_id, "method": method, "params": params,
        }) + "\n")
        process.stdin.flush()
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                detail = "\n".join(self._stderr_tail).strip()
                raise RuntimeError(f"Cursor ACP process exited early: {detail or process.returncode}")
            try:
                message = self._inbox.get(timeout=0.1)
            except queue.Empty:
                continue
            method_name = message.get("method")
            if method_name == "session/update":
                update = (message.get("params") or {}).get("update") or {}
                content = update.get("content") or {}
                if (
                    update.get("sessionUpdate") == "agent_message_chunk"
                    and isinstance(content, dict)
                    and text_parts is not None
                ):
                    text_parts.append(str(content.get("text") or ""))
                continue
            if isinstance(method_name, str) and "id" in message:
                # Hermes supplies tools through its prompt protocol; Cursor's
                # own filesystem/shell permissions stay closed.
                process.stdin.write(json.dumps({
                    "jsonrpc": "2.0",
                    "id": message.get("id"),
                    "result": {"outcome": {"outcome": "cancelled"}},
                }) + "\n")
                process.stdin.flush()
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message.get("error") or {}
                raise RuntimeError(f"Cursor ACP {method} failed: {error.get('message') or error}")
            return message.get("result")
        raise TimeoutError(f"Timed out waiting for Cursor ACP response to {method}.")

    def _create_chat_completion(
        self,
        *,
        model: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        stream: bool = False,
        **_: Any,
    ) -> Any:
        prompt_text = _format_messages_as_prompt(
            messages or [],
            model=model or self.default_model,
            tools=tools,
            tool_choice=tool_choice,
        )

        if timeout is None:
            _effective_timeout = _DEFAULT_TIMEOUT_SECONDS
        elif isinstance(timeout, (int, float)):
            _effective_timeout = float(timeout)
        else:
            _candidates = [
                getattr(timeout, attr, None)
                for attr in ("read", "write", "connect", "pool", "timeout")
            ]
            _numeric = [float(v) for v in _candidates if isinstance(v, (int, float))]
            _effective_timeout = max(_numeric) if _numeric else _DEFAULT_TIMEOUT_SECONDS

        effective_model = model or self.default_model
        response_text, input_tokens, output_tokens = self._run_prompt(
            prompt_text,
            model=effective_model,
            timeout_seconds=_effective_timeout,
        )

        tool_calls, cleaned_text = _extract_tool_calls_from_text(response_text)

        usage = SimpleNamespace(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            prompt_tokens_details=SimpleNamespace(cached_tokens=0),
        )
        assistant_message = SimpleNamespace(
            content=cleaned_text,
            tool_calls=tool_calls,
            reasoning=None,
            reasoning_content=None,
            reasoning_details=None,
        )
        finish_reason = "tool_calls" if tool_calls else "stop"
        choice = SimpleNamespace(message=assistant_message, finish_reason=finish_reason)
        completion = SimpleNamespace(
            choices=[choice],
            usage=usage,
            model=effective_model,
        )
        if stream:
            return iter(_completion_to_stream_chunks(completion))
        return completion

    def _run_prompt(
        self,
        prompt_text: str,
        *,
        model: str,
        timeout_seconds: float,
    ) -> tuple[str, int, int]:
        # ACP is a single stdio stream, so serialize calls on this client while
        # retaining the process between calls.
        with self._request_lock:
            self._cancel_idle_timer()
            try:
                proc = self._start_process(model)
                session = self._request(
                    "session/new",
                    {"cwd": os.getcwd(), "mcpServers": []},
                    timeout_seconds=min(timeout_seconds, 30.0),
                    process=proc,
                ) or {}
                session_id = str(session.get("sessionId") or "").strip()
                if not session_id:
                    raise RuntimeError("Cursor ACP did not return a sessionId.")
                text_parts: list[str] = []
                self._request(
                    "session/prompt",
                    {
                        "sessionId": session_id,
                        "prompt": [{"type": "text", "text": prompt_text}],
                    },
                    timeout_seconds=timeout_seconds,
                    process=proc,
                    text_parts=text_parts,
                )
                return "".join(text_parts).strip(), 0, 0
            finally:
                self._schedule_idle_close()


class AsyncCursorClient:
    """Asynchronous OpenAI-compatible client for Cursor Ultra CLI."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        cursor_bin: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        default_headers: dict[str, str] | None = None,
        **_: Any,
    ) -> None:
        self._sync_client = CursorClient(
            api_key=api_key,
            cursor_bin=cursor_bin,
            model=model,
            base_url=base_url,
            default_headers=default_headers,
        )
        self.api_key = self._sync_client.api_key
        self.base_url = self._sync_client.base_url
        self._default_headers = self._sync_client._default_headers
        self._custom_headers = self._sync_client._custom_headers
        self.default_headers = self._sync_client.default_headers
        self.chat = SimpleNamespace(completions=_AsyncCursorCompletionsNamespace(self))
        self.is_closed = False

    def close(self) -> None:
        self._sync_client.close()
        self.is_closed = True

    async def _create_chat_completion(
        self,
        *,
        model: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        res = await asyncio.to_thread(
            self._sync_client._create_chat_completion,
            model=model,
            messages=messages,
            timeout=timeout,
            tools=tools,
            tool_choice=tool_choice,
            stream=stream,
            **kwargs,
        )
        if stream:
            async def _async_gen() -> AsyncIterator[Any]:
                for chunk in res:
                    yield chunk
            return _async_gen()
        return res
