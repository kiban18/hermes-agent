"""Gemini Code Assist OAuth provider — Gemini CLI tokens, Hermes tools."""

from typing import Any

from providers import register_provider
from providers.base import ProviderProfile


class GeminiOauthProfile(ProviderProfile):
    """Code Assist OAuth — same thinking_config extra_body as native Gemini."""

    def build_extra_body(
        self, *, session_id: str | None = None, **context: Any
    ) -> dict[str, Any]:
        from agent.transports.chat_completions import _build_gemini_thinking_config

        model = context.get("model") or ""
        reasoning_config = context.get("reasoning_config")
        raw_thinking_config = _build_gemini_thinking_config(model, reasoning_config)
        if not raw_thinking_config:
            return {}
        return {"thinking_config": raw_thinking_config}


gemini_oauth = GeminiOauthProfile(
    name="gemini-oauth",
    aliases=("google-gemini-cli", "gemini-code-assist", "gca"),
    api_mode="chat_completions",
    env_vars=("GEMINI_CLI_CLIENT_ID", "GEMINI_CLI_CLIENT_SECRET"),
    base_url="https://cloudcode-pa.googleapis.com/v1internal",
    auth_type="oauth_external",
    default_aux_model="gemini-2.5-flash",
)

register_provider(gemini_oauth)
