"""Resolve Genspark Plus credentials for the official LLM proxy.

The Plus login lives in ``~/.genspark-tool-cli/config.json`` (written by
``gsk login``). Do not print the key.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict

from agent.secret_scope import get_secret

GENSPARK_LLM_BASE_URL = "https://www.genspark.ai/api/llm_proxy/v1"
DEFAULT_MODEL = "kimi-k3"


def genspark_config_path() -> Path:
    override = os.environ.get("GSK_CONFIG", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".genspark-tool-cli" / "config.json"


def resolve_genspark_api_key() -> str:
    env_key = (get_secret("GSK_API_KEY", "") or "").strip()
    if env_key:
        return env_key
    path = genspark_config_path()
    if not path.is_file():
        raise RuntimeError(
            f"Genspark login missing: {path}. A person must run `gsk login`."
        )
    data = json.loads(path.read_text())
    key = str((data or {}).get("api_key") or "").strip()
    if not key:
        raise RuntimeError(
            f"Genspark config has no api_key: {path}. A person must run `gsk login`."
        )
    return key


def resolve_genspark_runtime_credentials() -> Dict[str, str]:
    return {
        "api_key": resolve_genspark_api_key(),
        "base_url": (get_secret("GSK_LLM_BASE_URL", "") or "").strip()
        or GENSPARK_LLM_BASE_URL,
        "source": "gsk-cli",
    }
