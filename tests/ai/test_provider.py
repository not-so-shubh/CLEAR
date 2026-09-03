from collections.abc import Callable
from typing import cast

import pytest
from pydantic import ValidationError

import clear_market.ai as ai
from clear_market.ai import (
    AI_PROVIDER_REQUEST_V1_VERSION,
    AI_PROVIDER_RESPONSE_V1_VERSION,
    AIProvider,
    AIProviderError,
    AIProviderErrorCode,
    AIProviderFinishReason,
    AIProviderRequestV1,
    AIProviderResponseFormat,
    AIProviderResponseV1,
    AIProviderTask,
    invoke_ai_provider_v1,
)
from clear_market.ai.provider import (
    MAX_AI_INPUT_BYTES,
    MAX_AI_INSTRUCTION_BYTES,
    MAX_AI_OUTPUT_BYTES,
)

_REQUEST_ID = "71000000-0000-4000-8000-000000000001"
_OTHER_REQUEST_ID = "71000000-0000-4000-8000-000000000002"


def _request(**changes: object) -> AIProviderRequestV1:
    values: dict[str, object] = {
        "request_id": _REQUEST_ID,
        "task": AIProviderTask.BUYER_INTENT,
        "provider_name": "test-provider",
        "model": "model.v1:test/path",
        "response_format": AIProviderResponseFormat.JSON_OBJECT,
        "instruction_text": "Return one advisory candidate.",
        "input_text": "Buyer wants a suitable item.",
        "max_output_bytes": 1_024,
        **changes,
    }
    return AIProviderRequestV1(**values)


def _response(
    request: AIProviderRequestV1 | None = None,
    **changes: object,
) -> AIProviderResponseV1:
    correlated = _request() if request is None else request
    values: dict[str, object] = {
        "request_id": correlated.request_id,
        "task": correlated.task,
        "provider_name": correlated.provider_name,
        "model": correlated.model,
        "response_format": correlated.response_format,
        "finish_reason": AIProviderFinishReason.COMPLETED,
        "output_text": "advisory output",
        **changes,
    }
    return AIProviderResponseV1(**values)


def _request_construct(**changes: object) -> AIProviderRequestV1:
    valid = _request()
    values = {field: getattr(valid, field) for field in AIProviderRequestV1.model_fields}
    values.update(changes)
    return AIProviderRequestV1.model_construct(**values)


def _response_construct(**changes: object) -> AIProviderResponseV1:
    valid = _response()
    values = {field: getattr(valid, field) for field in AIProviderResponseV1.model_fields}
    values.update(changes)
    return AIProviderResponseV1.model_construct(**values)


class _StaticProvider:
    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[AIProviderRequestV1] = []

    def complete(self, request: AIProviderRequestV1) -> AIProviderResponseV1:
        self.requests.append(request)
        return cast(AIProviderResponseV1, self.response)


class _ErrorProvider:
    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.requests: list[AIProviderRequestV1] = []

    def complete(self, request: AIProviderRequestV1) -> AIProviderResponseV1:
        self.requests.append(request)
        raise self.error


class _RequestSubclass(AIProviderRequestV1):
    pass


class _ResponseSubclass(AIProviderResponseV1):
    pass


def _request_subclass() -> _RequestSubclass:
    request = _request()
    return _RequestSubclass(
        request_id=request.request_id,
        task=request.task,
        provider_name=request.provider_name,
        model=request.model,
        response_format=request.response_format,
        instruction_text=request.instruction_text,
        input_text=request.input_text,
        max_output_bytes=request.max_output_bytes,
    )


def _response_subclass() -> _ResponseSubclass:
    response = _response()
    return _ResponseSubclass(
        request_id=response.request_id,
        task=response.task,
        provider_name=response.provider_name,
        model=response.model,
        response_format=response.response_format,
        finish_reason=response.finish_reason,
        output_text=response.output_text,
    )


def _assert_provider_error(
    expected: AIProviderErrorCode,
    *,
    provider: AIProvider,
    request: AIProviderRequestV1 | None = None,
) -> AIProviderError:
    with pytest.raises(AIProviderError) as caught:
        invoke_ai_provider_v1(provider=provider, request=_request() if request is None else request)
    assert caught.value.code is expected
    assert str(caught.value) == expected.value
    return caught.value


def test_versions_are_exact() -> None:
    assert AI_PROVIDER_REQUEST_V1_VERSION == "ai-provider-request-v1"
    assert AI_PROVIDER_RESPONSE_V1_VERSION == "ai-provider-response-v1"


def test_task_contract_is_exact() -> None:
    assert tuple(AIProviderTask) == (
        AIProviderTask.BUYER_INTENT,
        AIProviderTask.MERCHANT_OFFER,
        AIProviderTask.CERTIFICATE_EXPLANATION,
    )
    assert tuple(value.value for value in AIProviderTask) == (
        "BUYER_INTENT",
        "MERCHANT_OFFER",
        "CERTIFICATE_EXPLANATION",
    )


def test_response_format_contract_is_exact() -> None:
    assert tuple(AIProviderResponseFormat) == (
        AIProviderResponseFormat.JSON_OBJECT,
        AIProviderResponseFormat.TEXT,
    )


def test_finish_reason_contract_is_exact() -> None:
    assert tuple(AIProviderFinishReason) == (
        AIProviderFinishReason.COMPLETED,
        AIProviderFinishReason.MAX_OUTPUT,
        AIProviderFinishReason.REFUSED,
        AIProviderFinishReason.CONTENT_FILTERED,
    )


def test_error_code_contract_is_exact() -> None:
    assert tuple(AIProviderErrorCode) == (
        AIProviderErrorCode.INVALID_REQUEST,
        AIProviderErrorCode.PROVIDER_UNAVAILABLE,
        AIProviderErrorCode.PROVIDER_TIMEOUT,
        AIProviderErrorCode.PROVIDER_RATE_LIMITED,
        AIProviderErrorCode.PROVIDER_AUTHENTICATION_FAILED,
        AIProviderErrorCode.PROVIDER_REQUEST_REJECTED,
        AIProviderErrorCode.INVALID_RESPONSE,
        AIProviderErrorCode.OUTPUT_TOO_LARGE,
        AIProviderErrorCode.OUTPUT_INCOMPLETE,
        AIProviderErrorCode.OUTPUT_REFUSED,
    )
    assert tuple(code.value for code in AIProviderErrorCode) == tuple(
        code.name for code in AIProviderErrorCode
    )


def test_public_api_is_exact() -> None:
    assert ai.__all__ == (
        "AI_PROVIDER_REQUEST_V1_VERSION",
        "AI_PROVIDER_RESPONSE_V1_VERSION",
        "BUYER_INTENT_CANDIDATE_V1_VERSION",
        "BUYER_INTENT_INSTRUCTION_V1_VERSION",
        "BUYER_INTENT_RULE_CANDIDATE_V1_VERSION",
        "BUYER_POLICY_FREEZE_CONTEXT_V1_VERSION",
        "CERTIFICATE_EXPLANATION_CANDIDATE_V1_VERSION",
        "CERTIFICATE_EXPLANATION_CLAIM_V1_VERSION",
        "CERTIFICATE_EXPLANATION_CONTEXT_V1_VERSION",
        "CERTIFICATE_EXPLANATION_INSTRUCTION_V1_VERSION",
        "CERTIFICATE_EXPLANATION_V1_VERSION",
        "MERCHANT_AI_CONTEXT_V1_VERSION",
        "MERCHANT_OFFER_INSTRUCTION_V1_VERSION",
        "MERCHANT_OFFER_PROPOSAL_LINE_V1_VERSION",
        "MERCHANT_OFFER_PROPOSAL_V1_VERSION",
        "AIProvider",
        "AIProviderError",
        "AIProviderErrorCode",
        "AIProviderFinishReason",
        "AIProviderRequestV1",
        "AIProviderResponseFormat",
        "AIProviderResponseV1",
        "AIProviderTask",
        "BuyerIntentCandidateV1",
        "BuyerIntentFreezeError",
        "BuyerIntentFreezeErrorCode",
        "BuyerIntentParseError",
        "BuyerIntentParseFailureCode",
        "BuyerIntentRuleCandidateV1",
        "BuyerPolicyFreezeContextV1",
        "CertificateExplanationCandidateV1",
        "CertificateExplanationClaimV1",
        "CertificateExplanationError",
        "CertificateExplanationErrorCode",
        "CertificateExplanationParseError",
        "CertificateExplanationParseFailureCode",
        "CertificateExplanationV1",
        "MerchantAIContextError",
        "MerchantAIContextErrorCode",
        "MerchantOfferProposalDecision",
        "MerchantOfferProposalFreezeError",
        "MerchantOfferProposalFreezeErrorCode",
        "MerchantOfferProposalLineV1",
        "MerchantOfferProposalParseError",
        "MerchantOfferProposalParseFailureCode",
        "MerchantOfferProposalV1",
        "explain_verified_allocation_certificate_v1",
        "freeze_buyer_policy_v2",
        "freeze_merchant_offer_proposal_v1",
        "interpret_buyer_intent_v1",
        "invoke_ai_provider_v1",
        "parse_buyer_intent_candidate_v1",
        "parse_certificate_explanation_candidate_v1",
        "parse_merchant_offer_proposal_v1",
        "propose_merchant_offer_candidate_v1",
    )
    for private_name in (
        "MAX_AI_INSTRUCTION_BYTES",
        "MAX_AI_INPUT_BYTES",
        "MAX_AI_OUTPUT_BYTES",
        "OpenAIProvider",
        "AnthropicProvider",
    ):
        assert private_name not in ai.__all__
        assert not hasattr(ai, private_name)


def test_request_has_exact_fields_versions_and_config() -> None:
    request = _request()

    assert tuple(AIProviderRequestV1.model_fields) == (
        "schema_version",
        "ai_provider_request_version",
        "request_id",
        "task",
        "provider_name",
        "model",
        "response_format",
        "instruction_text",
        "input_text",
        "max_output_bytes",
    )
    assert request.schema_version == "1"
    assert request.ai_provider_request_version == "ai-provider-request-v1"
    assert AIProviderRequestV1.model_config["frozen"] is True
    assert AIProviderRequestV1.model_config["extra"] == "forbid"
    assert AIProviderRequestV1.model_config["strict"] is True
    assert AIProviderRequestV1.model_config["revalidate_instances"] == "always"


def test_request_excludes_credentials_authority_and_time() -> None:
    fields = set(AIProviderRequestV1.model_fields)
    assert fields.isdisjoint(
        {
            "api_key",
            "secret",
            "credential",
            "temperature",
            "financial_authority",
            "payment_metadata",
            "private_key",
            "provider_account",
            "generated_at",
        }
    )


@pytest.mark.parametrize(
    "provider_name",
    ["openai", "anthropic", "local", "test-provider", "provider.v1", "a", "a" + "0" * 63],
)
def test_provider_name_accepts_exact_grammar(provider_name: str) -> None:
    assert _request(provider_name=provider_name).provider_name == provider_name
    assert _response(provider_name=provider_name).provider_name == provider_name


@pytest.mark.parametrize(
    "provider_name",
    [
        "",
        "OpenAI",
        " provider",
        "provider ",
        "1provider",
        "provider/name",
        "prøvider",
        "a" + "0" * 64,
        1,
        b"provider",
        None,
    ],
)
def test_provider_name_rejects_noncanonical_values(provider_name: object) -> None:
    with pytest.raises(ValidationError):
        _request(provider_name=provider_name)
    with pytest.raises(ValidationError):
        _response(provider_name=provider_name)


@pytest.mark.parametrize(
    "model",
    ["a", "Model-1", "model.v1", "vendor/model:v1", "A_1.2:/-", "a" + "0" * 127],
)
def test_model_identifier_accepts_exact_grammar(model: str) -> None:
    assert _request(model=model).model == model
    assert _response(model=model).model == model


@pytest.mark.parametrize(
    "model",
    [
        "",
        " model",
        "model ",
        "-model",
        ":model",
        "model value",
        "modèl",
        "a" + "0" * 128,
        1,
        b"model",
        None,
    ],
)
def test_model_identifier_rejects_noncanonical_values(model: object) -> None:
    with pytest.raises(ValidationError):
        _request(model=model)
    with pytest.raises(ValidationError):
        _response(model=model)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("instruction_text", 1),
        ("instruction_text", b"instruction"),
        ("instruction_text", None),
        ("input_text", 1),
        ("input_text", b"input"),
        ("input_text", None),
    ],
)
def test_request_text_requires_exact_builtin_string(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _request(**{field: value})


def test_request_instruction_nonempty_and_input_may_be_empty() -> None:
    with pytest.raises(ValidationError):
        _request(instruction_text="")
    request = _request(input_text="")
    assert request.input_text == ""


@pytest.mark.parametrize("field", ["instruction_text", "input_text"])
@pytest.mark.parametrize("value", ["before\x00after", "\ud800"])
def test_request_text_rejects_nul_and_lone_surrogate(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        _request(**{field: value})


def test_request_preserves_safe_unicode_without_trimming_or_normalization() -> None:
    instruction = "  Café e\u0301  "
    input_text = "\n東京\t"
    request = _request(instruction_text=instruction, input_text=input_text)

    assert request.instruction_text == instruction
    assert request.input_text == input_text


def test_instruction_utf8_byte_bound_is_exact() -> None:
    exact = "é" * (MAX_AI_INSTRUCTION_BYTES // 2)
    one_over = "a" * (MAX_AI_INSTRUCTION_BYTES - 1) + "é"

    assert len(_request(instruction_text=exact).instruction_text.encode("utf-8")) == (
        MAX_AI_INSTRUCTION_BYTES
    )
    with pytest.raises(ValidationError):
        _request(instruction_text=one_over)


def test_input_utf8_byte_bound_is_exact() -> None:
    exact = "a" * MAX_AI_INPUT_BYTES
    one_over = exact + "a"

    assert len(_request(input_text=exact).input_text.encode("utf-8")) == MAX_AI_INPUT_BYTES
    with pytest.raises(ValidationError):
        _request(input_text=one_over)


@pytest.mark.parametrize("value", [True, False, 1.0, "1", None])
def test_max_output_bytes_requires_exact_integer(value: object) -> None:
    with pytest.raises(ValidationError):
        _request(max_output_bytes=value)


@pytest.mark.parametrize("value", [0, -1, MAX_AI_OUTPUT_BYTES + 1])
def test_max_output_bytes_rejects_values_outside_bound(value: int) -> None:
    with pytest.raises(ValidationError):
        _request(max_output_bytes=value)


@pytest.mark.parametrize("value", [1, MAX_AI_OUTPUT_BYTES])
def test_max_output_bytes_accepts_exact_bounds(value: int) -> None:
    assert _request(max_output_bytes=value).max_output_bytes == value


def test_request_is_frozen_and_forbids_extra_fields() -> None:
    request = _request()
    with pytest.raises(ValidationError):
        request.input_text = "changed"
    with pytest.raises(ValidationError):
        _request(api_key="secret")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2"),
        ("ai_provider_request_version", "ai-provider-request-v2"),
        ("task", "BUYER_INTENT"),
        ("response_format", "JSON_OBJECT"),
    ],
)
def test_request_versions_and_enums_are_strict(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _request(**{field: value})


def test_response_has_exact_fields_versions_and_config() -> None:
    response = _response()

    assert tuple(AIProviderResponseV1.model_fields) == (
        "schema_version",
        "ai_provider_response_version",
        "request_id",
        "task",
        "provider_name",
        "model",
        "response_format",
        "finish_reason",
        "output_text",
    )
    assert response.schema_version == "1"
    assert response.ai_provider_response_version == "ai-provider-response-v1"
    assert AIProviderResponseV1.model_config["frozen"] is True
    assert AIProviderResponseV1.model_config["extra"] == "forbid"
    assert AIProviderResponseV1.model_config["strict"] is True
    assert AIProviderResponseV1.model_config["revalidate_instances"] == "always"


def test_response_is_advisory_and_excludes_authority_metadata() -> None:
    fields = set(AIProviderResponseV1.model_fields)
    assert fields.isdisjoint(
        {
            "confidence",
            "truth_score",
            "verified",
            "provenance",
            "winner",
            "payment",
            "tool_result_authority",
            "credential",
            "raw_provider_object",
        }
    )


def test_response_allows_empty_output_at_schema_layer() -> None:
    assert (
        _response(
            finish_reason=AIProviderFinishReason.REFUSED,
            output_text="",
        ).output_text
        == ""
    )


@pytest.mark.parametrize("value", [1, b"output", None, "before\x00after", "\ud800"])
def test_response_output_rejects_invalid_text(value: object) -> None:
    with pytest.raises(ValidationError):
        _response(output_text=value)


def test_response_output_global_utf8_byte_bound_is_exact() -> None:
    exact = "é" * (MAX_AI_OUTPUT_BYTES // 2)
    one_over = "a" * (MAX_AI_OUTPUT_BYTES - 1) + "é"

    assert len(_response(output_text=exact).output_text.encode("utf-8")) == MAX_AI_OUTPUT_BYTES
    with pytest.raises(ValidationError):
        _response(output_text=one_over)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2"),
        ("ai_provider_response_version", "ai-provider-response-v2"),
        ("task", "BUYER_INTENT"),
        ("response_format", "JSON_OBJECT"),
        ("finish_reason", "COMPLETED"),
    ],
)
def test_response_versions_and_enums_are_strict(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _response(**{field: value})


def test_response_is_frozen_and_forbids_extra_fields() -> None:
    response = _response()
    with pytest.raises(ValidationError):
        response.output_text = "changed"
    with pytest.raises(ValidationError):
        _response(raw_provider_object={})


def test_provider_protocol_is_runtime_checkable() -> None:
    assert isinstance(_StaticProvider(_response()), AIProvider)
    assert not isinstance(object(), AIProvider)


@pytest.mark.parametrize(
    ("response_format", "output_text"),
    [
        (AIProviderResponseFormat.JSON_OBJECT, "{not parsed in this boundary"),
        (AIProviderResponseFormat.TEXT, "Human-readable advisory text."),
    ],
)
def test_successful_invocation_returns_correlated_output_unchanged(
    response_format: AIProviderResponseFormat,
    output_text: str,
) -> None:
    request = _request(response_format=response_format)
    provider = _StaticProvider(_response(request, output_text=output_text))
    before = request.model_copy()

    returned = invoke_ai_provider_v1(provider=provider, request=request)

    assert provider.requests == [request]
    assert returned == _response(request, output_text=output_text)
    assert returned.output_text == output_text
    assert request == before
    assert "verified" not in AIProviderResponseV1.model_fields


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("request_id", _OTHER_REQUEST_ID),
        ("task", AIProviderTask.MERCHANT_OFFER),
        ("provider_name", "other-provider"),
        ("model", "other/model"),
        ("response_format", AIProviderResponseFormat.TEXT),
    ],
)
def test_response_correlation_mismatch_is_invalid_response(
    field: str,
    wrong_value: object,
) -> None:
    request = _request()
    provider = _StaticProvider(_response(request, **{field: wrong_value}))

    _assert_provider_error(AIProviderErrorCode.INVALID_RESPONSE, provider=provider, request=request)


@pytest.mark.parametrize(
    ("finish_reason", "expected"),
    [
        (AIProviderFinishReason.MAX_OUTPUT, AIProviderErrorCode.OUTPUT_INCOMPLETE),
        (AIProviderFinishReason.REFUSED, AIProviderErrorCode.OUTPUT_REFUSED),
        (AIProviderFinishReason.CONTENT_FILTERED, AIProviderErrorCode.OUTPUT_REFUSED),
    ],
)
def test_noncompleted_finish_reasons_fail_closed(
    finish_reason: AIProviderFinishReason,
    expected: AIProviderErrorCode,
) -> None:
    request = _request()
    provider = _StaticProvider(_response(request, finish_reason=finish_reason))

    _assert_provider_error(expected, provider=provider, request=request)


def test_completed_empty_output_is_invalid_response() -> None:
    request = _request()
    provider = _StaticProvider(_response(request, output_text=""))

    _assert_provider_error(AIProviderErrorCode.INVALID_RESPONSE, provider=provider, request=request)


def test_completed_nonempty_output_succeeds() -> None:
    request = _request()
    response = _response(request, output_text="x")
    assert invoke_ai_provider_v1(provider=_StaticProvider(response), request=request) == response


def test_per_request_output_byte_bound_is_inclusive_and_utf8_based() -> None:
    exact_request = _request(max_output_bytes=4)
    exact_response = _response(exact_request, output_text="éé")
    assert (
        invoke_ai_provider_v1(
            provider=_StaticProvider(exact_response),
            request=exact_request,
        )
        == exact_response
    )

    too_small_request = _request(max_output_bytes=3)
    provider = _StaticProvider(_response(too_small_request, output_text="éé"))
    _assert_provider_error(
        AIProviderErrorCode.OUTPUT_TOO_LARGE,
        provider=provider,
        request=too_small_request,
    )


@pytest.mark.parametrize(
    "code",
    [
        AIProviderErrorCode.PROVIDER_UNAVAILABLE,
        AIProviderErrorCode.PROVIDER_TIMEOUT,
        AIProviderErrorCode.PROVIDER_RATE_LIMITED,
        AIProviderErrorCode.PROVIDER_AUTHENTICATION_FAILED,
        AIProviderErrorCode.PROVIDER_REQUEST_REJECTED,
    ],
)
def test_provider_errors_propagate_as_same_instance(code: AIProviderErrorCode) -> None:
    error = AIProviderError(code)
    provider = _ErrorProvider(error)

    caught = _assert_provider_error(code, provider=provider)

    assert caught is error
    assert str(caught) == code.value


def test_unexpected_provider_exception_propagates_unchanged() -> None:
    error = RuntimeError("implementation failure")
    provider = _ErrorProvider(error)

    with pytest.raises(RuntimeError) as caught:
        invoke_ai_provider_v1(provider=provider, request=_request())

    assert caught.value is error


def test_provider_error_code_is_read_only_and_message_contains_only_code() -> None:
    error = AIProviderError(AIProviderErrorCode.PROVIDER_AUTHENTICATION_FAILED)
    assert str(error) == "PROVIDER_AUTHENTICATION_FAILED"
    with pytest.raises(AttributeError):
        error.code = AIProviderErrorCode.PROVIDER_UNAVAILABLE


@pytest.mark.parametrize("provider", [None, object(), "provider", {}])
def test_wrong_provider_object_is_type_error(provider: object) -> None:
    with pytest.raises(TypeError):
        invoke_ai_provider_v1(provider=provider, request=_request())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "response",
    [None, {}, "response", _request(), _response_subclass()],
)
def test_wrong_response_type_is_invalid_response(response: object) -> None:
    _assert_provider_error(
        AIProviderErrorCode.INVALID_RESPONSE,
        provider=_StaticProvider(response),
    )


@pytest.mark.parametrize("wrong_request", [None, {}, "request", _request_subclass()])
def test_wrong_request_type_is_type_error(wrong_request: object) -> None:
    provider = _StaticProvider(_response())
    with pytest.raises(TypeError):
        invoke_ai_provider_v1(provider=provider, request=wrong_request)  # type: ignore[arg-type]
    assert provider.requests == []


@pytest.mark.parametrize(
    "invalid_request",
    [
        _request_construct(provider_name="Invalid"),
        _request_construct(max_output_bytes=MAX_AI_OUTPUT_BYTES + 1),
        _request_construct(instruction_text="\ud800"),
    ],
)
def test_model_construct_cannot_bypass_request_validation(
    invalid_request: AIProviderRequestV1,
) -> None:
    provider = _StaticProvider(_response())

    _assert_provider_error(
        AIProviderErrorCode.INVALID_REQUEST,
        provider=provider,
        request=invalid_request,
    )
    assert provider.requests == []


@pytest.mark.parametrize(
    "invalid_response",
    [
        _response_construct(provider_name="Invalid"),
        _response_construct(output_text="before\x00after"),
        _response_construct(ai_provider_response_version="ai-provider-response-v2"),
    ],
)
def test_model_construct_cannot_bypass_response_validation(
    invalid_response: AIProviderResponseV1,
) -> None:
    provider = _StaticProvider(invalid_response)

    _assert_provider_error(AIProviderErrorCode.INVALID_RESPONSE, provider=provider)
    assert provider.requests == [_request()]


def test_invalid_request_precedes_provider_failure() -> None:
    provider = _ErrorProvider(AIProviderError(AIProviderErrorCode.PROVIDER_TIMEOUT))

    _assert_provider_error(
        AIProviderErrorCode.INVALID_REQUEST,
        provider=provider,
        request=_request_construct(provider_name="Invalid"),
    )
    assert provider.requests == []


def test_correlation_mismatch_precedes_incomplete_finish_reason() -> None:
    request = _request()
    provider = _StaticProvider(
        _response(
            request,
            request_id=_OTHER_REQUEST_ID,
            finish_reason=AIProviderFinishReason.MAX_OUTPUT,
        )
    )

    _assert_provider_error(AIProviderErrorCode.INVALID_RESPONSE, provider=provider, request=request)


def test_incomplete_finish_reason_precedes_output_size() -> None:
    request = _request(max_output_bytes=1)
    provider = _StaticProvider(
        _response(
            request,
            finish_reason=AIProviderFinishReason.MAX_OUTPUT,
            output_text="oversized",
        )
    )

    _assert_provider_error(
        AIProviderErrorCode.OUTPUT_INCOMPLETE, provider=provider, request=request
    )


def test_refused_finish_reason_precedes_empty_output() -> None:
    request = _request()
    provider = _StaticProvider(
        _response(request, finish_reason=AIProviderFinishReason.REFUSED, output_text="")
    )

    _assert_provider_error(AIProviderErrorCode.OUTPUT_REFUSED, provider=provider, request=request)


def test_completed_empty_output_precedes_size_question() -> None:
    request = _request(max_output_bytes=1)
    provider = _StaticProvider(_response(request, output_text=""))

    _assert_provider_error(AIProviderErrorCode.INVALID_RESPONSE, provider=provider, request=request)


def test_completed_nonempty_oversized_output_is_output_too_large() -> None:
    request = _request(max_output_bytes=1)
    provider = _StaticProvider(_response(request, output_text="xx"))

    _assert_provider_error(AIProviderErrorCode.OUTPUT_TOO_LARGE, provider=provider, request=request)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: AIProviderRequestV1(
            request_id=_REQUEST_ID,
            task=AIProviderTask.BUYER_INTENT,
            provider_name="test-provider",
            model="model-v1",
            response_format=AIProviderResponseFormat.JSON_OBJECT,
            instruction_text="instruction",
            input_text="input",
            max_output_bytes=1,
            api_key="secret",
        ),
        lambda: AIProviderResponseV1(
            request_id=_REQUEST_ID,
            task=AIProviderTask.BUYER_INTENT,
            provider_name="test-provider",
            model="model-v1",
            response_format=AIProviderResponseFormat.JSON_OBJECT,
            finish_reason=AIProviderFinishReason.COMPLETED,
            output_text="output",
            verified=True,
        ),
    ],
)
def test_models_forbid_authority_or_credential_extras(factory: Callable[[], object]) -> None:
    with pytest.raises(ValidationError):
        factory()
