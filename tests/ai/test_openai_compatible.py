import http.client
import json
import math
from collections.abc import Mapping
from typing import cast

import pytest
from pydantic import ValidationError

from clear_market.ai import (
    AIProvider,
    AIProviderError,
    AIProviderErrorCode,
    AIProviderFinishReason,
    AIProviderRequestV1,
    AIProviderResponseFormat,
    AIProviderTask,
    invoke_ai_provider_v1,
)
from clear_market.ai.openai_compatible import (
    MAX_HTTP_RESPONSE_BYTES,
    OpenAICompatibleProvider,
)
from clear_market.ai.provider import MAX_AI_OUTPUT_BYTES

_REQUEST_ID = "71000000-0000-4000-8000-000000000001"
_CREDENTIAL = "credential-value-for-test"


def _request(**changes: object) -> AIProviderRequestV1:
    values: dict[str, object] = {
        "request_id": _REQUEST_ID,
        "task": AIProviderTask.BUYER_INTENT,
        "provider_name": "gateway.test",
        "model": "model.v1:test/path",
        "response_format": AIProviderResponseFormat.JSON_OBJECT,
        "instruction_text": "Return one advisory candidate.",
        "input_text": "Buyer wants a suitable item.",
        "max_output_bytes": 1_024,
        **changes,
    }
    return AIProviderRequestV1(**values)


def _completion(
    content: object = "{}",
    finish_reason: object = "stop",
    **message_changes: object,
) -> dict[str, object]:
    message: dict[str, object] = {
        "role": "assistant",
        "content": content,
        **message_changes,
    }
    return {"choices": [{"index": 0, "message": message, "finish_reason": finish_reason}]}


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class _FakeTransport:
    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.status = status
        self.body = _json_bytes(_completion()) if body is None else body
        self.error = error
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> tuple[int, bytes]:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.status, self.body


def _provider(
    transport: _FakeTransport | None = None,
    **changes: object,
) -> OpenAICompatibleProvider:
    fake = _FakeTransport() if transport is None else transport
    values: dict[str, object] = {
        "base_url": "https://EXAMPLE.invalid/v1///",
        "api_key": _CREDENTIAL,
        "timeout_seconds": 3,
        "transport": fake,
        **changes,
    }
    return OpenAICompatibleProvider(**values)  # type: ignore[arg-type]


def _call(provider: OpenAICompatibleProvider, request: AIProviderRequestV1 | None = None):
    return provider.complete(_request() if request is None else request)


def _assert_error(
    provider: OpenAICompatibleProvider,
    expected: AIProviderErrorCode,
    request: AIProviderRequestV1 | None = None,
) -> AIProviderError:
    with pytest.raises(AIProviderError) as caught:
        _call(provider, request)
    assert caught.value.code is expected
    return caught.value


def test_configuration_normalizes_url_and_hides_credential() -> None:
    provider = _provider()

    assert provider.base_url == "https://example.invalid/v1"
    assert provider.endpoint_url == "https://example.invalid/v1/chat/completions"
    assert provider.timeout_seconds == 3.0
    assert _CREDENTIAL not in repr(provider)
    assert _CREDENTIAL not in str(provider)


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "example.invalid/v1",
        "http://example.invalid/v1",
        "https://",
        "https://example.invalid/v1?token=not-allowed",
        "https://example.invalid/v1#fragment",
        "https://user:password@example.invalid/v1",
        "https://example.invalid/v1 path",
        "https://example.invalid/v1\n",
    ],
)
def test_configuration_rejects_invalid_base_urls(base_url: str) -> None:
    with pytest.raises(ValueError):
        _provider(base_url=base_url)


@pytest.mark.parametrize("api_key", ["", "   ", "credential\nvalue", "credential\tvalue", None, 3])
def test_configuration_rejects_missing_or_unsafe_credentials(api_key: object) -> None:
    with pytest.raises(ValueError):
        _provider(api_key=api_key)


@pytest.mark.parametrize(
    "timeout_seconds",
    [0, -1, math.inf, math.nan, True, False, "3", None],
)
def test_configuration_requires_finite_positive_timeout(timeout_seconds: object) -> None:
    with pytest.raises(ValueError):
        _provider(timeout_seconds=timeout_seconds)


def test_request_mapping_is_compact_and_deterministic() -> None:
    transport = _FakeTransport()
    provider = _provider(transport)
    _call(provider)

    call = transport.calls[0]
    assert call["host"] == "example.invalid"
    assert call["port"] == 443
    assert call["path"] == "/v1/chat/completions"
    assert call["timeout_seconds"] == 3.0
    assert call["max_response_bytes"] == MAX_HTTP_RESPONSE_BYTES
    assert call["headers"] == {
        "Authorization": f"Bearer {_CREDENTIAL}",
        "Content-Type": "application/json",
    }
    body = cast(bytes, call["body"])
    assert body == (
        b'{"model":"model.v1:test/path","messages":[{"role":"system",'
        b'"content":"Return one advisory candidate."},{"role":"user",'
        b'"content":"Buyer wants a suitable item."}],"response_format":{"type":"json_object"}}'
    )
    assert _CREDENTIAL.encode() not in body


def test_text_request_omits_json_mode_and_other_invented_controls() -> None:
    transport = _FakeTransport()
    provider = _provider(transport)
    _call(provider, _request(response_format=AIProviderResponseFormat.TEXT))

    payload = json.loads(cast(bytes, transport.calls[0]["body"]))
    assert set(payload) == {"model", "messages"}
    assert "temperature" not in payload
    assert "max_tokens" not in payload
    assert payload["messages"][0] == {
        "role": "system",
        "content": "Return one advisory candidate.",
    }
    assert payload["messages"][1] == {
        "role": "user",
        "content": "Buyer wants a suitable item.",
    }


def test_success_preserves_unicode_and_request_correlation() -> None:
    transport = _FakeTransport(body=_json_bytes(_completion("Advisory 日本語 ✅")))
    provider = _provider(transport)
    request = _request(response_format=AIProviderResponseFormat.TEXT)
    response = _call(provider, request)

    assert response.output_text == "Advisory 日本語 ✅"
    assert response.request_id == request.request_id
    assert response.task is request.task
    assert response.provider_name == request.provider_name
    assert response.model == request.model
    assert response.response_format is request.response_format
    assert response.finish_reason is AIProviderFinishReason.COMPLETED


@pytest.mark.parametrize(
    ("finish_reason", "expected"),
    [
        ("stop", AIProviderFinishReason.COMPLETED),
        ("length", AIProviderFinishReason.MAX_OUTPUT),
        ("content_filter", AIProviderFinishReason.CONTENT_FILTERED),
        ("refusal", AIProviderFinishReason.REFUSED),
    ],
)
def test_finish_reason_mapping(finish_reason: str, expected: AIProviderFinishReason) -> None:
    transport = _FakeTransport(body=_json_bytes(_completion(finish_reason=finish_reason)))
    response = _call(_provider(transport))
    assert response.finish_reason is expected


def test_message_refusal_representation_maps_to_refused() -> None:
    transport = _FakeTransport(body=_json_bytes(_completion("No", refusal="unsafe request")))
    response = _call(_provider(transport))
    assert response.finish_reason is AIProviderFinishReason.REFUSED


def test_json_object_mode_accepts_a_strict_top_level_object() -> None:
    response = _call(_provider())
    assert response.finish_reason is AIProviderFinishReason.COMPLETED
    assert response.output_text == "{}"


@pytest.mark.parametrize(
    "content",
    [
        "plain text",
        "[1,2]",
        "1",
        '{"key":1,"key":2}',
        '{"value":NaN}',
        '{"value":Infinity}',
    ],
)
def test_json_object_mode_rejects_non_object_or_non_strict_content(content: str) -> None:
    body = _json_bytes(_completion(content))
    _assert_error(_provider(_FakeTransport(body=body)), AIProviderErrorCode.INVALID_RESPONSE)


def test_text_mode_accepts_arbitrary_plain_text() -> None:
    request = _request(response_format=AIProviderResponseFormat.TEXT)
    body = _json_bytes(_completion("plain text"))
    response = _call(_provider(_FakeTransport(body=body)), request)
    assert response.output_text == "plain text"
    assert response.response_format is AIProviderResponseFormat.TEXT


def test_completed_utf8_output_at_request_bound_is_accepted() -> None:
    content = "é"
    request = _request(
        response_format=AIProviderResponseFormat.TEXT,
        max_output_bytes=len(content.encode("utf-8")),
    )
    body = _json_bytes(_completion(content))
    response = _call(_provider(_FakeTransport(body=body)), request)
    assert response.output_text == content


def test_completed_utf8_output_over_request_bound_is_rejected_by_provider() -> None:
    content = "éa"
    request = _request(response_format=AIProviderResponseFormat.TEXT, max_output_bytes=2)
    body = _json_bytes(_completion(content))
    _assert_error(
        _provider(_FakeTransport(body=body)),
        AIProviderErrorCode.OUTPUT_TOO_LARGE,
        request,
    )


def test_completed_output_over_global_bound_uses_request_error_semantics() -> None:
    content = "x" * (MAX_AI_OUTPUT_BYTES - 1) + "é"
    assert len(content.encode("utf-8")) == MAX_AI_OUTPUT_BYTES + 1
    request = _request(
        response_format=AIProviderResponseFormat.TEXT,
        max_output_bytes=MAX_AI_OUTPUT_BYTES,
    )
    body = _json_bytes(_completion(content))
    _assert_error(
        _provider(_FakeTransport(body=body)),
        AIProviderErrorCode.OUTPUT_TOO_LARGE,
        request,
    )


def test_completed_utf8_output_over_request_bound_is_rejected_by_invoke() -> None:
    content = "éa"
    request = _request(response_format=AIProviderResponseFormat.TEXT, max_output_bytes=2)
    body = _json_bytes(_completion(content))
    error = _assert_error_via_invoke(
        _provider(_FakeTransport(body=body)),
        request,
    )
    assert error.code is AIProviderErrorCode.OUTPUT_TOO_LARGE


@pytest.mark.parametrize(
    ("finish_reason", "message_changes", "expected"),
    [
        ("stop", {"refusal": "unsafe request"}, AIProviderFinishReason.REFUSED),
        ("content_filter", {}, AIProviderFinishReason.CONTENT_FILTERED),
        ("length", {}, AIProviderFinishReason.MAX_OUTPUT),
    ],
)
def test_terminal_finish_reasons_allow_missing_content(
    finish_reason: str,
    message_changes: dict[str, object],
    expected: AIProviderFinishReason,
) -> None:
    body = _json_bytes(_completion(content=None, finish_reason=finish_reason, **message_changes))
    response = _call(_provider(_FakeTransport(body=body)))
    assert response.finish_reason is expected
    assert response.output_text == ""


def test_normal_completion_requires_textual_content() -> None:
    body = _json_bytes(_completion(content=None, finish_reason="stop"))
    _assert_error(_provider(_FakeTransport(body=body)), AIProviderErrorCode.INVALID_RESPONSE)


@pytest.mark.parametrize("field", ["tool_calls", "function_call"])
def test_tool_and_function_calls_are_rejected_even_with_text(field: str) -> None:
    body = _json_bytes(_completion("{}", finish_reason="stop", **{field: {"name": "ignored"}}))
    _assert_error(_provider(_FakeTransport(body=body)), AIProviderErrorCode.INVALID_RESPONSE)


def test_null_tool_calls_are_accepted_for_compatibility() -> None:
    body = _json_bytes(_completion("{}", tool_calls=None))
    response = _call(_provider(_FakeTransport(body=body)))
    assert response.output_text == "{}"


@pytest.mark.parametrize(
    ("finish_reason", "message_changes", "expected"),
    [
        ("stop", {"refusal": "unsafe request"}, AIProviderErrorCode.OUTPUT_REFUSED),
        ("content_filter", {}, AIProviderErrorCode.OUTPUT_REFUSED),
        ("length", {}, AIProviderErrorCode.OUTPUT_INCOMPLETE),
    ],
)
def test_invoke_maps_empty_terminal_outputs_to_stable_errors(
    finish_reason: str,
    message_changes: dict[str, object],
    expected: AIProviderErrorCode,
) -> None:
    body = _json_bytes(_completion(content=None, finish_reason=finish_reason, **message_changes))
    error = _assert_error_via_invoke(
        _provider(_FakeTransport(body=body)),
        _request(),
    )
    assert error.code is expected


@pytest.mark.parametrize(
    ("finish_reason", "message_changes", "expected"),
    [
        ("stop", {"refusal": "unsafe request"}, AIProviderFinishReason.REFUSED),
        ("content_filter", {}, AIProviderFinishReason.CONTENT_FILTERED),
        ("length", {}, AIProviderFinishReason.MAX_OUTPUT),
    ],
)
def test_oversized_terminal_content_preserves_terminal_semantics(
    finish_reason: str,
    message_changes: dict[str, object],
    expected: AIProviderFinishReason,
) -> None:
    content = "x" * (MAX_HTTP_RESPONSE_BYTES // 2)
    body = _json_bytes(_completion(content, finish_reason=finish_reason, **message_changes))
    response = _call(_provider(_FakeTransport(body=body)))
    assert response.finish_reason is expected
    assert response.output_text == ""


def test_unknown_finish_reason_is_invalid_response() -> None:
    transport = _FakeTransport(body=_json_bytes(_completion(finish_reason="tool_calls")))
    _assert_error(_provider(transport), AIProviderErrorCode.INVALID_RESPONSE)


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        _json_bytes({"choices": []}),
        _json_bytes({"choices": [{}, {}]}),
        _json_bytes({"choices": [{"message": {"content": None}, "finish_reason": "stop"}]}),
        _json_bytes({"choices": [{"message": {"tool_calls": []}, "finish_reason": "stop"}]}),
        b'{"choices":[{"message":{"content":"x"},"finish_reason":"stop"}],'
        b'"choices":[{"message":{"content":"y"},"finish_reason":"stop"}]}',
    ],
)
def test_incompatible_response_shapes_are_rejected(body: bytes) -> None:
    _assert_error(_provider(_FakeTransport(body=body)), AIProviderErrorCode.INVALID_RESPONSE)


def test_multiple_choices_are_not_concatenated() -> None:
    payload = {
        "choices": [
            {"message": {"content": "first"}, "finish_reason": "stop"},
            {"message": {"content": "second"}, "finish_reason": "stop"},
        ]
    }
    _assert_error(
        _provider(_FakeTransport(body=_json_bytes(payload))),
        AIProviderErrorCode.INVALID_RESPONSE,
    )


def test_oversized_and_invalid_utf8_responses_are_rejected() -> None:
    oversized = b"{" + b"x" * MAX_HTTP_RESPONSE_BYTES
    invalid_utf8 = b"\xff"
    for body in (oversized, invalid_utf8):
        _assert_error(_provider(_FakeTransport(body=body)), AIProviderErrorCode.INVALID_RESPONSE)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, AIProviderErrorCode.PROVIDER_AUTHENTICATION_FAILED),
        (429, AIProviderErrorCode.PROVIDER_RATE_LIMITED),
        (408, AIProviderErrorCode.PROVIDER_TIMEOUT),
        (400, AIProviderErrorCode.PROVIDER_REQUEST_REJECTED),
        (404, AIProviderErrorCode.PROVIDER_REQUEST_REJECTED),
        (409, AIProviderErrorCode.PROVIDER_REQUEST_REJECTED),
        (422, AIProviderErrorCode.PROVIDER_REQUEST_REJECTED),
        (500, AIProviderErrorCode.PROVIDER_UNAVAILABLE),
        (503, AIProviderErrorCode.PROVIDER_UNAVAILABLE),
        (302, AIProviderErrorCode.PROVIDER_REQUEST_REJECTED),
    ],
)
def test_http_status_mapping(status: int, expected: AIProviderErrorCode) -> None:
    error = _assert_error(_provider(_FakeTransport(status=status)), expected)
    assert _CREDENTIAL not in str(error)


@pytest.mark.parametrize(
    ("transport_error", "expected"),
    [
        (TimeoutError(), AIProviderErrorCode.PROVIDER_TIMEOUT),
        (OSError("unreachable"), AIProviderErrorCode.PROVIDER_UNAVAILABLE),
        (ConnectionError("unreachable"), AIProviderErrorCode.PROVIDER_UNAVAILABLE),
    ],
)
def test_transport_failures_are_stable_and_sanitized(
    transport_error: BaseException,
    expected: AIProviderErrorCode,
) -> None:
    error = _assert_error(_provider(_FakeTransport(error=transport_error)), expected)
    assert str(error) == expected.value
    assert _CREDENTIAL not in repr(error)
    assert "unreachable" not in str(error)


def test_injected_transport_must_return_bytes_and_status() -> None:
    class _WrongTransport:
        def __call__(self, **_kwargs: object) -> tuple[object, object]:
            return True, "body"

    provider = OpenAICompatibleProvider(
        base_url="https://example.invalid/v1",
        api_key=_CREDENTIAL,
        timeout_seconds=1,
        transport=_WrongTransport(),  # type: ignore[arg-type]
    )
    _assert_error(provider, AIProviderErrorCode.INVALID_RESPONSE)


def test_default_https_transport_is_bounded_and_does_not_follow_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class _Response:
        status = 200

        def read(self, amount: int) -> bytes:
            observed["read_amount"] = amount
            return _json_bytes(_completion())

    class _Connection:
        def __init__(self, host: str, port: int, **kwargs: object) -> None:
            observed.update(host=host, port=port, **kwargs)

        def request(self, method: str, path: str, **kwargs: object) -> None:
            observed.update(method=method, path=path, **kwargs)

        def getresponse(self) -> _Response:
            return _Response()

        def close(self) -> None:
            observed["closed"] = True

    monkeypatch.setattr(http.client, "HTTPSConnection", _Connection)
    provider = OpenAICompatibleProvider(
        base_url="https://example.invalid/v1",
        api_key=_CREDENTIAL,
        timeout_seconds=2.5,
    )
    response = _call(provider)

    assert response.output_text == "{}"
    assert observed["host"] == "example.invalid"
    assert observed["port"] == 443
    assert observed["timeout"] == 2.5
    assert observed["method"] == "POST"
    assert observed["path"] == "/v1/chat/completions"
    assert observed["read_amount"] == MAX_HTTP_RESPONSE_BYTES + 1
    assert observed["closed"] is True
    headers = cast(Mapping[str, str], observed["headers"])
    assert headers["Authorization"] == f"Bearer {_CREDENTIAL}"
    assert headers["Content-Type"] == "application/json"


def test_provider_protocol_and_downstream_bound_are_preserved() -> None:
    transport = _FakeTransport(body=_json_bytes(_completion()))
    provider = _provider(transport)
    assert isinstance(provider, AIProvider)

    request = _request(max_output_bytes=1)
    error = _assert_error_via_invoke(provider, request)
    assert error.code is AIProviderErrorCode.OUTPUT_TOO_LARGE


def _assert_error_via_invoke(
    provider: OpenAICompatibleProvider,
    request: AIProviderRequestV1,
) -> AIProviderError:
    with pytest.raises(AIProviderError) as caught:
        invoke_ai_provider_v1(provider=provider, request=request)
    return caught.value


def test_invalid_request_is_safely_rejected() -> None:
    provider = _provider()
    with pytest.raises(AIProviderError) as caught:
        provider.complete(cast(AIProviderRequestV1, object()))
    assert caught.value.code is AIProviderErrorCode.INVALID_REQUEST


def test_invalid_response_duplicate_json_keys_are_rejected() -> None:
    body = b'{"choices":[{"message":{"content":"x"},"finish_reason":"stop",'
    body += b'"finish_reason":"length"}]}'
    _assert_error(_provider(_FakeTransport(body=body)), AIProviderErrorCode.INVALID_RESPONSE)


def test_transport_mapping_does_not_expose_response_body() -> None:
    body = b"provider-private-error-body"
    error = _assert_error(
        _provider(_FakeTransport(status=400, body=body)),
        AIProviderErrorCode.PROVIDER_REQUEST_REJECTED,
    )
    assert body.decode() not in str(error)


def test_transport_type_is_not_a_public_ai_api_export() -> None:
    import clear_market.ai as ai

    assert not hasattr(ai, "OpenAICompatibleProvider")
    assert "OpenAICompatibleProvider" not in ai.__all__
    with pytest.raises(ValidationError):
        _request(api_key="not-a-request-field")


def test_mapping_type_annotation_is_only_for_test_introspection() -> None:
    transport = _FakeTransport()
    _call(_provider(transport))
    headers = cast(Mapping[str, str], transport.calls[0]["headers"])
    assert headers["Content-Type"] == "application/json"
