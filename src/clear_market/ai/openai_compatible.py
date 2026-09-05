"""OpenAI-compatible Chat Completions transport for untrusted advisory text."""

import http.client
import json
import math
import ssl
from collections.abc import Mapping
from typing import Final, Protocol, cast
from urllib.parse import SplitResult, urlsplit, urlunsplit

from pydantic import ValidationError

from clear_market.ai.provider import (
    MAX_AI_OUTPUT_BYTES,
    AIProviderError,
    AIProviderErrorCode,
    AIProviderFinishReason,
    AIProviderRequestV1,
    AIProviderResponseFormat,
    AIProviderResponseV1,
)

MAX_HTTP_RESPONSE_BYTES: Final[int] = 262_144
_CHAT_COMPLETIONS_SUFFIX: Final[str] = "/chat/completions"
_HTTPS_SCHEME: Final[str] = "https"
_DEFAULT_HTTPS_PORT: Final[int] = 443
_SUCCESS_FINISH_REASONS: Final[frozenset[str]] = frozenset({"stop", "completed", "eos", "end_turn"})


def _has_forbidden_control(value: str) -> bool:
    return any(ord(character) <= 0x20 or ord(character) == 0x7F for character in value)


class _DuplicateKeyError(ValueError):
    pass


class _InvalidResponse(ValueError):
    pass


class _HTTPTransport(Protocol):
    def __call__(
        self,
        *,
        host: str,
        port: int,
        path: str,
        body: bytes,
        headers: Mapping[str, str],
        timeout_seconds: float,
        max_response_bytes: int,
    ) -> tuple[int, bytes]: ...


def _provider_error(code: AIProviderErrorCode) -> AIProviderError:
    return AIProviderError(code)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_nonstandard_constant(_value: str) -> object:
    raise _InvalidResponse


def _strict_response_object(data: bytes) -> dict[str, object]:
    if type(data) is not bytes or len(data) > MAX_HTTP_RESPONSE_BYTES:
        raise _InvalidResponse
    try:
        text = data.decode("utf-8", errors="strict")
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_constant,
        )
    except (
        UnicodeDecodeError,
        _DuplicateKeyError,
        _InvalidResponse,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ):
        raise _InvalidResponse from None
    if type(parsed) is not dict:
        raise _InvalidResponse
    return cast(dict[str, object], parsed)


def _normalize_base_url(value: object) -> tuple[str, str, int, str]:
    if type(value) is not str or value == "" or value.strip() != value:
        raise ValueError("base_url is invalid")
    if _has_forbidden_control(value):
        raise ValueError("base_url is invalid")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("base_url is invalid") from None
    if parsed.scheme.lower() != _HTTPS_SCHEME or not parsed.netloc or not hostname:
        raise ValueError("base_url must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base_url is invalid")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url is invalid")
    try:
        hostname.encode("ascii")
    except UnicodeEncodeError:
        raise ValueError("base_url is invalid") from None
    if port is not None and not 1 <= port <= 65_535:
        raise ValueError("base_url is invalid")

    normalized_host = hostname.lower()
    authority = normalized_host
    if ":" in normalized_host:
        authority = f"[{normalized_host}]"
    if port is not None:
        authority = f"{authority}:{port}"

    path = parsed.path.rstrip("/")
    normalized = urlunsplit(SplitResult(_HTTPS_SCHEME, authority, path, "", ""))
    endpoint = f"{normalized}{_CHAT_COMPLETIONS_SUFFIX}"
    connection_path = f"{path}{_CHAT_COMPLETIONS_SUFFIX}"
    if not connection_path.startswith("/"):
        connection_path = f"/{connection_path}"
    return normalized, endpoint, port or _DEFAULT_HTTPS_PORT, connection_path


def _validate_api_key(value: object) -> str:
    if type(value) is not str or value == "" or value.strip() == "":
        raise ValueError("api_key is invalid")
    if _has_forbidden_control(value):
        raise ValueError("api_key is invalid")
    return value


def _validate_timeout(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("timeout_seconds is invalid")
    timeout = float(value)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout_seconds is invalid")
    return timeout


def _stdlib_http_transport(
    *,
    host: str,
    port: int,
    path: str,
    body: bytes,
    headers: Mapping[str, str],
    timeout_seconds: float,
    max_response_bytes: int,
) -> tuple[int, bytes]:
    """Perform one HTTPS request without redirect handling or retries."""
    connection = http.client.HTTPSConnection(
        host,
        port,
        timeout=timeout_seconds,
        context=ssl.create_default_context(),
    )
    try:
        connection.request("POST", path, body=body, headers=dict(headers))
        response = connection.getresponse()
        data = response.read(max_response_bytes + 1)
        if type(data) is not bytes:
            raise _InvalidResponse
        return response.status, data
    finally:
        connection.close()


def _request_body(request: AIProviderRequestV1) -> bytes:
    payload: dict[str, object] = {
        "model": request.model,
        "messages": [
            {"role": "system", "content": request.instruction_text},
            {"role": "user", "content": request.input_text},
        ],
    }
    if request.response_format is AIProviderResponseFormat.JSON_OBJECT:
        payload["response_format"] = {"type": "json_object"}
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (UnicodeEncodeError, TypeError, ValueError):
        raise _provider_error(AIProviderErrorCode.INVALID_REQUEST) from None


def _response_finish_reason(
    *,
    choice: dict[str, object],
    message: dict[str, object],
) -> AIProviderFinishReason:
    finish_reason = choice.get("finish_reason")
    if type(finish_reason) is not str:
        raise _InvalidResponse

    refusal = message.get("refusal")
    if refusal is not None and type(refusal) is not str:
        raise _InvalidResponse
    if type(refusal) is str and refusal != "":
        return AIProviderFinishReason.REFUSED

    if finish_reason in _SUCCESS_FINISH_REASONS:
        return AIProviderFinishReason.COMPLETED
    if finish_reason == "length":
        return AIProviderFinishReason.MAX_OUTPUT
    if finish_reason == "content_filter":
        return AIProviderFinishReason.CONTENT_FILTERED
    if finish_reason == "refusal":
        return AIProviderFinishReason.REFUSED
    raise _InvalidResponse


def _validate_json_object_content(content: str) -> None:
    try:
        encoded = content.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise _InvalidResponse from None
    _strict_response_object(encoded)


def _response_content(
    data: bytes,
    *,
    response_format: AIProviderResponseFormat,
) -> tuple[AIProviderFinishReason, str]:
    payload = _strict_response_object(data)
    choices = payload.get("choices")
    if type(choices) is not list or len(choices) != 1:
        raise _InvalidResponse
    choice = choices[0]
    if type(choice) is not dict:
        raise _InvalidResponse
    choice_object = cast(dict[str, object], choice)
    message = choice_object.get("message")
    if type(message) is not dict:
        raise _InvalidResponse
    message_object = cast(dict[str, object], message)

    if message_object.get("tool_calls") is not None:
        raise _InvalidResponse
    if message_object.get("function_call") is not None:
        raise _InvalidResponse

    finish_reason = _response_finish_reason(choice=choice_object, message=message_object)
    content = message_object.get("content")
    if finish_reason is AIProviderFinishReason.COMPLETED:
        if type(content) is not str:
            raise _InvalidResponse
        if response_format is AIProviderResponseFormat.JSON_OBJECT:
            _validate_json_object_content(content)
        return finish_reason, content

    if content is None:
        return finish_reason, ""
    if type(content) is not str:
        raise _InvalidResponse
    return finish_reason, content


class OpenAICompatibleProvider:
    """Synchronous, credential-bearing transport for an externally supplied HTTPS endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: int | float,
        transport: _HTTPTransport | None = None,
    ) -> None:
        normalized, endpoint, port, path = _normalize_base_url(base_url)
        self._api_key = _validate_api_key(api_key)
        self._timeout_seconds = _validate_timeout(timeout_seconds)
        self._base_url = normalized
        self._endpoint_url = endpoint
        host = urlsplit(normalized).hostname
        if host is None:
            raise ValueError("base_url is invalid")
        self._host = host
        self._port = port
        self._path = path
        self._transport = _stdlib_http_transport if transport is None else transport

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def endpoint_url(self) -> str:
        return self._endpoint_url

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleProvider(base_url={self._base_url!r}, "
            f"timeout_seconds={self._timeout_seconds!r})"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def complete(self, request: AIProviderRequestV1) -> AIProviderResponseV1:
        if type(request) is not AIProviderRequestV1:
            raise _provider_error(AIProviderErrorCode.INVALID_REQUEST)
        try:
            validated_request = AIProviderRequestV1.model_validate(request)
        except ValidationError:
            raise _provider_error(AIProviderErrorCode.INVALID_REQUEST) from None

        body = _request_body(validated_request)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            status, data = self._transport(
                host=self._host,
                port=self._port,
                path=self._path,
                body=body,
                headers=headers,
                timeout_seconds=self._timeout_seconds,
                max_response_bytes=MAX_HTTP_RESPONSE_BYTES,
            )
        except _InvalidResponse:
            raise _provider_error(AIProviderErrorCode.INVALID_RESPONSE) from None
        except AIProviderError:
            raise
        except TimeoutError:
            raise _provider_error(AIProviderErrorCode.PROVIDER_TIMEOUT) from None
        except (OSError, http.client.HTTPException, ssl.SSLError):
            raise _provider_error(AIProviderErrorCode.PROVIDER_UNAVAILABLE) from None
        except Exception:
            raise _provider_error(AIProviderErrorCode.PROVIDER_UNAVAILABLE) from None

        if isinstance(status, bool) or not isinstance(status, int) or type(data) is not bytes:
            raise _provider_error(AIProviderErrorCode.INVALID_RESPONSE)
        if status == 401:
            raise _provider_error(AIProviderErrorCode.PROVIDER_AUTHENTICATION_FAILED)
        if status == 429:
            raise _provider_error(AIProviderErrorCode.PROVIDER_RATE_LIMITED)
        if status == 408:
            raise _provider_error(AIProviderErrorCode.PROVIDER_TIMEOUT)
        if 500 <= status <= 599:
            raise _provider_error(AIProviderErrorCode.PROVIDER_UNAVAILABLE)
        if not 200 <= status <= 299:
            raise _provider_error(AIProviderErrorCode.PROVIDER_REQUEST_REJECTED)
        if len(data) > MAX_HTTP_RESPONSE_BYTES:
            raise _provider_error(AIProviderErrorCode.INVALID_RESPONSE)

        try:
            finish_reason, output_text = _response_content(
                data,
                response_format=validated_request.response_format,
            )
            if finish_reason is AIProviderFinishReason.COMPLETED:
                try:
                    output_bytes = output_text.encode("utf-8", errors="strict")
                except UnicodeEncodeError:
                    raise _provider_error(AIProviderErrorCode.INVALID_RESPONSE) from None
                if len(output_bytes) > validated_request.max_output_bytes:
                    raise _provider_error(AIProviderErrorCode.OUTPUT_TOO_LARGE)
            else:
                try:
                    terminal_output_bytes = output_text.encode("utf-8", errors="strict")
                except UnicodeEncodeError:
                    output_text = ""
                else:
                    if len(terminal_output_bytes) > MAX_AI_OUTPUT_BYTES:
                        output_text = ""
            response = AIProviderResponseV1(
                request_id=validated_request.request_id,
                task=validated_request.task,
                provider_name=validated_request.provider_name,
                model=validated_request.model,
                response_format=validated_request.response_format,
                finish_reason=finish_reason,
                output_text=output_text,
            )
        except (ValidationError, _InvalidResponse):
            raise _provider_error(AIProviderErrorCode.INVALID_RESPONSE) from None
        return response


__all__ = ("OpenAICompatibleProvider",)
