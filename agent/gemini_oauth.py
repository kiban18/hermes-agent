"""Load and refresh Gemini CLI / Code Assist OAuth tokens.

Tokens live in ``~/.gemini/oauth_creds.json`` (the official Gemini CLI
store). Client id/secret are the public installed-app credentials from
``@google/gemini-cli`` — they are not treated as user secrets.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from agent.secret_scope import get_secret

logger = logging.getLogger(__name__)

CODE_ASSIST_ENDPOINT = "https://cloudcode-pa.googleapis.com/v1internal"
DEFAULT_CLOUD_PROJECT = "numeric-habitat-487420-i6"
DEFAULT_MODEL = "gemini-2.5-flash"
_REFRESH_SKEW_SECONDS = 120


def _resolve_oauth_client_credentials() -> tuple[str, str]:
    client_id = (get_secret("GEMINI_CLI_CLIENT_ID", "") or "").strip()
    client_secret = (get_secret("GEMINI_CLI_CLIENT_SECRET", "") or "").strip()
    if not client_id or not client_secret:
        raise RuntimeError(
            "Gemini CLI OAuth client credentials missing. Set "
            "GEMINI_CLI_CLIENT_ID and GEMINI_CLI_CLIENT_SECRET in the active profile .env."
        )
    return client_id, client_secret


def gemini_oauth_creds_path() -> Path:
    override = os.environ.get("GEMINI_OAUTH_CREDS", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".gemini" / "oauth_creds.json"


def resolve_code_assist_project() -> str:
    for key in ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_PROJECT_ID"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    env_path = Path.home() / ".gemini" / ".env"
    if env_path.is_file():
        try:
            for line in env_path.read_text().splitlines():
                if line.startswith("GOOGLE_CLOUD_PROJECT=") or line.startswith(
                    "GOOGLE_CLOUD_PROJECT_ID="
                ):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if value:
                        return value
        except OSError:
            pass
    return DEFAULT_CLOUD_PROJECT


def _load_creds(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("oauth_creds.json is not an object")
    return data


def _expiry_unix(creds: Dict[str, Any]) -> float:
    raw = creds.get("expiry_date")
    if isinstance(raw, (int, float)) and raw > 0:
        return float(raw) / 1000.0 if raw > 10_000_000_000 else float(raw)
    raw = creds.get("expires_at")
    if isinstance(raw, (int, float)) and raw > 0:
        return float(raw)
    return 0.0


def _needs_refresh(creds: Dict[str, Any]) -> bool:
    token = str(creds.get("access_token") or "").strip()
    if not token:
        return True
    expiry = _expiry_unix(creds)
    if not expiry:
        return False
    return time.time() >= (expiry - _REFRESH_SKEW_SECONDS)


def _persist_creds(path: Path, creds: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(creds, indent=2) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def refresh_gemini_oauth_creds(
    creds: Dict[str, Any],
    *,
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    refresh_token = str(creds.get("refresh_token") or "").strip()
    if not refresh_token:
        raise RuntimeError("Gemini CLI oauth_creds.json has no refresh_token")
    client_id, client_secret = _resolve_oauth_client_credentials()
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=body,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:240]
        raise RuntimeError(
            f"Gemini Code Assist token refresh failed HTTP {exc.code}: {detail}"
        ) from exc
    access = str(payload.get("access_token") or "").strip()
    if not access:
        raise RuntimeError("Gemini Code Assist token refresh returned no access_token")
    updated = dict(creds)
    updated["access_token"] = access
    expires_in = payload.get("expires_in")
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        updated["expiry_date"] = int((time.time() + float(expires_in)) * 1000)
    if payload.get("id_token"):
        updated["id_token"] = payload["id_token"]
    if payload.get("refresh_token"):
        updated["refresh_token"] = payload["refresh_token"]
    if path is not None:
        try:
            _persist_creds(path, updated)
        except OSError as exc:
            logger.warning("Could not persist refreshed Gemini OAuth creds: %s", exc)
    return updated


def resolve_gemini_oauth_access_token(*, force_refresh: bool = False) -> str:
    path = gemini_oauth_creds_path()
    if not path.is_file():
        raise RuntimeError(
            f"Gemini CLI OAuth store missing: {path}. "
            "A person must run `gemini` and sign in as khlee@crazyupinc.com."
        )
    creds = _load_creds(path)
    if force_refresh or _needs_refresh(creds):
        creds = refresh_gemini_oauth_creds(creds, path=path)
    token = str(creds.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("Gemini CLI OAuth store has no access_token")
    return token


def resolve_gemini_oauth_runtime_credentials() -> Dict[str, str]:
    token = resolve_gemini_oauth_access_token()
    return {
        "api_key": token,
        "base_url": CODE_ASSIST_ENDPOINT,
        "source": "gemini-cli",
        "project": resolve_code_assist_project(),
    }
