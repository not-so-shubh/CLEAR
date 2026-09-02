"""Provider-neutral boundary for bounded, correlated advisory model text."""

import re
from enum import StrEnum
from typing import Annotated, Final, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationError

from clear_market.domain import CanonicalUUID4

AI_PROVIDER_REQUEST_V1_VERSION: Final[str] = "ai-provider-request-v1"
AI_PROVIDER_RESPONSE_V1_VERSION: Final[str] = "ai-provider-response-v1"

MAX_AI_INSTRUCTION_BYTES: Final[int] = 32_768
MAX_AI_INPUT_BYTES: Final[int] = 262_144
MAX_AI_OUTPUT_BYTES: Final[int] = 65_536

_PROVIDER_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,63}", flags=re.ASCII)
_MODEL_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", flags=re.ASCII)


class AIProviderTask(StrEnum):
    BUYER_INTENT = "BUYER_INTENT"
    MERCHANT_OFFER = "MERCHANT_OFFER"
    CERTIFICATE_EXPLANATION = "CERTIFICATE_EXPLANATION"


class AIProviderResponseFormat(StrEnum):
    JSON_OBJECT = "JSON_OBJECT"
    TEXT = "TEXT"


class AIProviderFinishReason(StrEnum):
    COMPLETED = "COMPLETED"
    MAX_OUTPUT = "MAX_OUTPUT"
    REFUSED = "REFUSED"
    CONTENT_FILTERED = "CONTENT_FILTERED"


def _validate_provider_name(value: object) -> str:
    if type(value) is not str or _PROVIDER_NAME_PATTERN.fullmatch(value) is None:
        raise ValueError("provider name is not canonical")
    return value


def _validate_model_identifier(value: object) -> str:
    if type(value) is not str or _MODEL_IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError("model identifier is not canonical")
    return value


def _validate_bounded_text(
    value: object,
    *,
    minimum_bytes: int,
    maximum_bytes: int,
) -> str:
    if type(value) is not str:
        raise ValueError("text must be supplied as an exact string")
    if "\x00" in value:
        raise ValueError("text must not contain NUL")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError("text must be valid UTF-8") from error
    if not minimum_bytes <= len(encoded) <= maximum_bytes:
        raise ValueError("text UTF-8 byte length is outside its bound")
    return value


def _validate_instruction_text(value: object) -> str:
    return _validate_bounded_text(
        value,
        minimum_bytes=1,
        maximum_bytes=MAX_AI_INSTRUCTION_BYTES,
    )


def _validate_input_text(value: object) -> str:
    return _validate_bounded_text(
        value,
        minimum_bytes=0,
        maximum_bytes=MAX_AI_INPUT_BYTES,
    )


def _validate_output_text(value: object) -> str:
    return _validate_bounded_text(
        value,
        minimum_bytes=0,
        maximum_bytes=MAX_AI_OUTPUT_BYTES,
    )


def _validate_max_output_bytes(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_AI_OUTPUT_BYTES:
        raise ValueError("maximum output bytes is outside its bound")
    return value


type _ProviderName = Annotated[str, BeforeValidator(_validate_provider_name)]
type _ModelIdentifier = Annotated[str, BeforeValidator(_validate_model_identifier)]
type _InstructionText = Annotated[str, BeforeValidator(_validate_instruction_text)]
type _InputText = Annotated[str, BeforeValidator(_validate_input_text)]
type _OutputText = Annotated[str, BeforeValidator(_validate_output_text)]
type _MaxOutputBytes = Annotated[int, BeforeValidator(_validate_max_output_bytes)]


class AIProviderRequestV1(BaseModel):
    """Immutable bounded request with instructions separated from caller-derived input."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    ai_provider_request_version: Literal["ai-provider-request-v1"] = "ai-provider-request-v1"
    request_id: CanonicalUUID4
    task: AIProviderTask
    provider_name: _ProviderName
    model: _ModelIdentifier
    response_format: AIProviderResponseFormat
    instruction_text: _InstructionText
    input_text: _InputText
    max_output_bytes: _MaxOutputBytes


class AIProviderResponseV1(BaseModel):
    """Correlatable provider output that remains untrusted advisory text."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    ai_provider_response_version: Literal["ai-provider-response-v1"] = "ai-provider-response-v1"
    request_id: CanonicalUUID4
    task: AIProviderTask
    provider_name: _ProviderName
    model: _ModelIdentifier
    response_format: AIProviderResponseFormat
    finish_reason: AIProviderFinishReason
    output_text: _OutputText


class AIProviderErrorCode(StrEnum):
    INVALID_REQUEST = "INVALID_REQUEST"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_AUTHENTICATION_FAILED = "PROVIDER_AUTHENTICATION_FAILED"
    PROVIDER_REQUEST_REJECTED = "PROVIDER_REQUEST_REJECTED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    OUTPUT_TOO_LARGE = "OUTPUT_TOO_LARGE"
    OUTPUT_INCOMPLETE = "OUTPUT_INCOMPLETE"
    OUTPUT_REFUSED = "OUTPUT_REFUSED"


class AIProviderError(RuntimeError):
    """Stable provider-boundary failure without request, output, or implementation details."""

    __slots__ = ("_code",)

    def __init__(self, code: AIProviderErrorCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> AIProviderErrorCode:
        return self._code


@runtime_checkable
class AIProvider(Protocol):
    def complete(self, request: AIProviderRequestV1) -> AIProviderResponseV1: ...


def _provider_error(code: AIProviderErrorCode) -> AIProviderError:
    return AIProviderError(code)


def invoke_ai_provider_v1(
    *,
    provider: AIProvider,
    request: AIProviderRequestV1,
) -> AIProviderResponseV1:
    """Return bounded correlated completion text; domain validity remains downstream."""
    if type(request) is not AIProviderRequestV1:
        raise TypeError("request must be exactly an AIProviderRequestV1")
    try:
        validated_request = AIProviderRequestV1.model_validate(request)
    except ValidationError:
        raise _provider_error(AIProviderErrorCode.INVALID_REQUEST) from None

    if not isinstance(provider, AIProvider):
        raise TypeError("provider must implement AIProvider")

    response = provider.complete(validated_request)
    if type(response) is not AIProviderResponseV1:
        raise _provider_error(AIProviderErrorCode.INVALID_RESPONSE)
    try:
        validated_response = AIProviderResponseV1.model_validate(response)
    except ValidationError:
        raise _provider_error(AIProviderErrorCode.INVALID_RESPONSE) from None

    if validated_response.request_id != validated_request.request_id:
        raise _provider_error(AIProviderErrorCode.INVALID_RESPONSE)
    if validated_response.task is not validated_request.task:
        raise _provider_error(AIProviderErrorCode.INVALID_RESPONSE)
    if validated_response.provider_name != validated_request.provider_name:
        raise _provider_error(AIProviderErrorCode.INVALID_RESPONSE)
    if validated_response.model != validated_request.model:
        raise _provider_error(AIProviderErrorCode.INVALID_RESPONSE)
    if validated_response.response_format is not validated_request.response_format:
        raise _provider_error(AIProviderErrorCode.INVALID_RESPONSE)

    if validated_response.finish_reason is AIProviderFinishReason.MAX_OUTPUT:
        raise _provider_error(AIProviderErrorCode.OUTPUT_INCOMPLETE)
    if validated_response.finish_reason in (
        AIProviderFinishReason.REFUSED,
        AIProviderFinishReason.CONTENT_FILTERED,
    ):
        raise _provider_error(AIProviderErrorCode.OUTPUT_REFUSED)
    if validated_response.output_text == "":
        raise _provider_error(AIProviderErrorCode.INVALID_RESPONSE)
    if len(validated_response.output_text.encode("utf-8")) > validated_request.max_output_bytes:
        raise _provider_error(AIProviderErrorCode.OUTPUT_TOO_LARGE)

    return validated_response
