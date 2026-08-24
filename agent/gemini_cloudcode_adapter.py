"""OpenAI-compatible facade over Gemini Code Assist (Cloud Code) OAuth.

Reuses native Gemini request/response translation, but posts the wrapped
Code Assist body that ``gemini`` CLI uses:

    POST https://cloudcode-pa.googleapis.com/v1internal:generateContent
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Iterator, Optional

import httpx

from agent.bounded_response import read_streaming_error_body
from agent.gemini_native_adapter import (
    GeminiAPIError,
    GeminiNativeClient,
    _HERMES_VERSION,
    _iter_sse_events,
    bare_gemini_model_id,
    build_gemini_request,
    gemini_http_error,
    translate_gemini_response,
    translate_stream_event,
)
from agent.gemini_oauth import (
    CODE_ASSIST_ENDPOINT,
    DEFAULT_MODEL,
    resolve_code_assist_project,
    resolve_gemini_oauth_access_token,
)

logger = logging.getLogger(__name__)


def is_code_assist_base_url(base_url: str) -> bool:
    normalized = str(base_url or "").strip().rstrip("/").lower()
    return "cloudcode-pa.googleapis.com" in normalized


def unwrap_cloudcode_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Strip the Code Assist envelope so native Gemini translators apply."""
    if not isinstance(payload, dict):
        return {}
    inner = payload.get("response")
    if isinstance(inner, dict):
        out = dict(inner)
        trace = payload.get("traceId")
        if trace and not out.get("responseId"):
            out["responseId"] = trace
        return out
    return payload


def wrap_cloudcode_request(
    *,
    model: str,
    request: Dict[str, Any],
    project: str,
    user_prompt_id: str,
) -> Dict[str, Any]:
    return {
        "model": model,
        "project": project,
        "user_prompt_id": user_prompt_id,
        "request": request,
    }


class GeminiCloudCodeClient(GeminiNativeClient):
    """GeminiNativeClient transport pointed at Code Assist OAuth."""

    def __init__(
        self,
        *,
        api_key: str = "",
        base_url: Optional[str] = None,
        default_headers: Optional[Dict[str, str]] = None,
        timeout: Any = None,
        http_client: Optional[httpx.Client] = None,
        project_id: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        token = (api_key or "").strip() or resolve_gemini_oauth_access_token()
        super().__init__(
            api_key=token,
            base_url=base_url or CODE_ASSIST_ENDPOINT,
            default_headers=default_headers,
            timeout=timeout,
            http_client=http_client,
            **kwargs,
        )
        self.project_id = (project_id or resolve_code_assist_project()).strip()

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": f"hermes-agent/{_HERMES_VERSION} (gemini-oauth)",
            "X-Goog-Api-Client": f"hermes-agent/{_HERMES_VERSION}",
        }
        headers.update(self._default_headers)
        return headers

    def _refresh_access_token(self) -> None:
        self.api_key = resolve_gemini_oauth_access_token(force_refresh=True)

    def _create_chat_completion(
        self,
        *,
        model: str = DEFAULT_MODEL,
        messages: Optional[list] = None,
        stream: bool = False,
        tools: Any = None,
        tool_choice: Any = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        stop: Any = None,
        extra_body: Optional[Dict[str, Any]] = None,
        timeout: Any = None,
        **_: Any,
    ) -> Any:
        thinking_config = None
        if isinstance(extra_body, dict):
            thinking_config = extra_body.get("thinking_config") or extra_body.get(
                "thinkingConfig"
            )
        request = build_gemini_request(
            messages=messages or [],
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            stop=stop,
            thinking_config=thinking_config,
        )
        model = bare_gemini_model_id(model)
        wrapped = wrap_cloudcode_request(
            model=model,
            request=request,
            project=self.project_id,
            user_prompt_id=f"hermes-{uuid.uuid4().hex[:12]}",
        )
        if stream:
            return self._stream_completion(model=model, request=wrapped, timeout=timeout)
        return self._post_completion(model=model, request=wrapped, timeout=timeout)

    def _post_completion(
        self, *, model: str, request: Dict[str, Any], timeout: Any = None
    ) -> Any:
        url = f"{self.base_url}:generateContent"
        response = self._http.post(
            url, json=request, headers=self._headers(), timeout=timeout
        )
        if response.status_code == 401:
            logger.info("Gemini Code Assist 401 — refreshing OAuth token")
            self._refresh_access_token()
            response = self._http.post(
                url, json=request, headers=self._headers(), timeout=timeout
            )
        if response.status_code != 200:
            raise gemini_http_error(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise GeminiAPIError(
                f"Invalid JSON from Gemini Code Assist: {exc}",
                code="gemini_invalid_json",
                status_code=response.status_code,
                response=response,
            ) from exc
        if not isinstance(payload, dict):
            raise GeminiAPIError(
                "Gemini Code Assist returned a non-object payload",
                code="gemini_invalid_json",
                status_code=response.status_code,
                response=response,
            )
        return translate_gemini_response(unwrap_cloudcode_payload(payload), model=model)

    def _stream_completion(
        self, *, model: str, request: Dict[str, Any], timeout: Any = None
    ) -> Iterator:
        url = f"{self.base_url}:streamGenerateContent?alt=sse"
        stream_headers = dict(self._headers())
        stream_headers["Accept"] = "text/event-stream"

        def _generator():
            try:
                with self._http.stream(
                    "POST",
                    url,
                    json=request,
                    headers=stream_headers,
                    timeout=timeout,
                ) as response:
                    if response.status_code == 401:
                        raise GeminiAPIError(
                            "Gemini Code Assist streaming unauthorized",
                            code="gemini_unauthorized",
                            status_code=401,
                            response=response,
                        )
                    if response.status_code != 200:
                        body_text = read_streaming_error_body(response)
                        raise gemini_http_error(response, body_text=body_text)
                    tool_call_indices: Dict[str, Dict[str, Any]] = {}
                    for event in _iter_sse_events(response):
                        inner = unwrap_cloudcode_payload(event)
                        for chunk in translate_stream_event(
                            inner, model, tool_call_indices
                        ):
                            yield chunk
            except httpx.HTTPError as exc:
                raise GeminiAPIError(
                    f"Gemini Code Assist streaming request failed: {exc}",
                    code="gemini_stream_error",
                ) from exc

        return _generator()
