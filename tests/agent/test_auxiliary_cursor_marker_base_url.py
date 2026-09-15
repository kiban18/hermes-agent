"""A ``cursor://`` base URL means the CLI, so it must never reach httpx.

``cursor://agent`` is a marker, not an endpoint. The main agent path already
reads it that way — ``agent_runtime_helpers`` builds a ``CursorClient`` when
either the provider is ``cursor`` or the base URL starts with ``cursor://`` —
but the auxiliary path only checked the provider string. An auxiliary call
(title generation, compression, summarisation) that inherited the main
runtime's base URL while resolving its own provider therefore built an OpenAI
client pointed at ``cursor://agent``:

    httpcore.UnsupportedProtocol: Request URL has an unsupported protocol
    'cursor://'.

Observed 2026-09-15 in project_lead after cursor became the profile's primary:
main-agent turns worked, every auxiliary call on the same runtime raised.
"""

from __future__ import annotations

import agent.auxiliary_client as aux


def _resolve(monkeypatch, provider, base_url):
    """Call resolve_provider_client with the cursor client stubbed out."""
    import sys
    import types

    took = {}

    class _FakeCursorClient:
        def __init__(self, **kwargs):
            took["kwargs"] = kwargs

    stub = types.ModuleType("agent.cursor_client")
    stub.AsyncCursorClient = _FakeCursorClient
    stub.CursorClient = _FakeCursorClient
    stub.DEFAULT_CURSOR_MODEL = "auto"
    stub.resolve_cursor_runtime_credentials = lambda **kw: {
        "api_key": "test-key", "command": "/usr/bin/true",
        "base_url": base_url or "cursor://agent", "source": "test",
    }
    monkeypatch.setitem(sys.modules, "agent.cursor_client", stub)

    client, model = aux.resolve_provider_client(
        provider=provider, model="auto",
        explicit_base_url=base_url, explicit_api_key=None, async_mode=True,
    )
    return client, model, took


def test_cursor_marker_base_url_routes_to_the_cli_client(monkeypatch):
    """The reported failure: provider not named, base URL carries the marker."""
    client, _model, took = _resolve(monkeypatch, "", "cursor://agent")
    assert took, "resolution never reached the cursor branch"
    assert type(client).__name__ == "_FakeCursorClient"


def test_explicit_cursor_provider_still_works(monkeypatch):
    client, _model, took = _resolve(monkeypatch, "cursor", "cursor://agent")
    assert took
    assert type(client).__name__ == "_FakeCursorClient"


def test_marker_wins_even_when_another_provider_is_named(monkeypatch):
    """The base URL is the stronger signal: nothing else can serve cursor://."""
    client, _model, took = _resolve(monkeypatch, "openai", "cursor://agent")
    assert took
    assert type(client).__name__ == "_FakeCursorClient"


def test_ordinary_base_url_is_untouched(monkeypatch):
    """No cursor marker, no cursor branch."""
    _client, _model, took = _resolve(monkeypatch, "openai", "https://api.openai.com/v1")
    assert not took
