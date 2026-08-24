from hermes_cli import auth
from hermes_cli.auth_commands import _usage_verification
from hermes_cli.config import OPTIONAL_ENV_VARS


def test_cursor_daemon_key_is_exposed_as_protected_provider_config():
    assert OPTIONAL_ENV_VARS["CURSOR_API_KEY"]["category"] == "provider"
    assert OPTIONAL_ENV_VARS["CURSOR_API_KEY"]["password"] is True


def test_gemini_oauth_client_secret_is_protected_provider_config():
    assert OPTIONAL_ENV_VARS["GEMINI_CLI_CLIENT_SECRET"]["category"] == "provider"
    assert OPTIONAL_ENV_VARS["GEMINI_CLI_CLIENT_SECRET"]["password"] is True


def test_gemini_status_uses_runtime_resolver(monkeypatch):
    monkeypatch.setattr(
        "agent.gemini_oauth.resolve_gemini_oauth_runtime_credentials",
        lambda: {
            "api_key": "gemini-test-token",
            "base_url": "https://cloudcode-pa.googleapis.com/v1internal",
            "source": "gemini-cli",
        },
    )

    status = auth.get_auth_status("gemini-oauth")

    assert status["configured"] is True
    assert status["authenticated"] is True
    assert status["usable"] is True
    assert status["live_verified"] is False
    assert status["provider"] == "gemini-oauth"


def test_genspark_status_uses_runtime_resolver(monkeypatch):
    monkeypatch.setattr(
        "agent.genspark_auth.resolve_genspark_runtime_credentials",
        lambda: {
            "api_key": "genspark-test-key",
            "base_url": "https://www.genspark.ai/api/llm_proxy/v1",
            "source": "gsk-cli",
        },
    )

    status = auth.get_auth_status("genspark")

    assert status["authenticated"] is True
    assert status["usable"] is True
    assert status["source"] == "gsk-cli"


def test_cursor_status_fails_closed_without_daemon_key(monkeypatch):
    monkeypatch.setattr(
        "agent.cursor_client.resolve_cursor_runtime_credentials",
        lambda: (_ for _ in ()).throw(RuntimeError("CURSOR_API_KEY missing")),
    )

    status = auth.get_auth_status("cursor")

    assert status["configured"] is False
    assert status["authenticated"] is False
    assert status["usable"] is False
    assert status["live_verified"] is False


def test_live_verification_rejects_fallback_provider():
    status = _usage_verification(
        "cursor",
        "composer-2.5",
        {
            "provider": "xai",
            "model": "grok-4.1-fast",
            "completed": True,
            "failed": False,
        },
        returncode=0,
    )

    assert status["live_verified"] is False
    assert status["usable"] is False
    assert status["actual_provider"] == "xai"
    assert status["actual_model"] == "grok-4.1-fast"
    assert status["live_error"] == "provider mismatch: requested cursor, got xai"


def test_live_verification_rejects_fallback_model():
    status = _usage_verification(
        "cursor",
        "composer-2.5",
        {
            "provider": "cursor",
            "model": "auto",
            "completed": True,
            "failed": False,
        },
        returncode=0,
    )

    assert status["live_verified"] is False
    assert status["usable"] is False
    assert status["actual_provider"] == "cursor"
    assert status["actual_model"] == "auto"
    assert status["live_error"] == "model mismatch: requested composer-2.5, got auto"
