"""Genspark Plus official LLM proxy — billed to the gsk login."""

from providers import register_provider
from providers.base import ProviderProfile

genspark = ProviderProfile(
    name="genspark",
    aliases=("gsk", "genspark-llm-proxy", "genspark-plus"),
    api_mode="chat_completions",
    env_vars=("GSK_API_KEY",),
    base_url="https://www.genspark.ai/api/llm_proxy/v1",
    auth_type="api_key",
    default_aux_model="kimi-k3",
)

register_provider(genspark)
