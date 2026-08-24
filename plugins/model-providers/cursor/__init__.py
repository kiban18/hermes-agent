"""Cursor Composer via the headless cursor-agent ACP process."""

from providers import register_provider
from providers.base import ProviderProfile

cursor = ProviderProfile(
    name="cursor",
    aliases=("cursor-agent", "cursor-ultra"),
    display_name="Cursor Composer",
    api_mode="chat_completions",
    env_vars=("CURSOR_API_KEY", "CURSOR_AUTH_TOKEN"),
    base_url="cursor://agent",
    auth_type="external_process",
    supports_health_check=False,
    fallback_models=("composer-2.5",),
    default_aux_model="composer-2.5",
)

register_provider(cursor)
