"""Strict storage facts for the local append-only financial event ledger."""

import re
from enum import StrEnum
from typing import Annotated, Final, Literal, Self, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from clear_market.domain import CanonicalUUID4, UTCDateTime

FINANCIAL_EVENT_LEDGER_V1_VERSION: Final[str] = "financial-event-ledger-v1"

_SQLITE_INT_MIN: Final[int] = -9_223_372_036_854_775_808
_SQLITE_INT_MAX: Final[int] = 9_223_372_036_854_775_807
_EVENT_NAMESPACE_PATTERN = re.compile(r"[a-z][a-z0-9_.:-]{0,127}", flags=re.ASCII)
_PROVIDER_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,63}", flags=re.ASCII)
_FIELD_KEY_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,127}", flags=re.ASCII)
_SHA256_HEX_PATTERN = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


def _validate_pattern(value: object, pattern: re.Pattern[str], message: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError(message)
    return value


def _validate_event_namespace(value: object) -> str:
    return _validate_pattern(value, _EVENT_NAMESPACE_PATTERN, "event namespace is not canonical")


def _validate_provider_name(value: object) -> str:
    return _validate_pattern(value, _PROVIDER_NAME_PATTERN, "provider name is not canonical")


def _validate_field_key(value: object) -> str:
    return _validate_pattern(value, _FIELD_KEY_PATTERN, "field key is not canonical")


def _validate_sha256_hex(value: object) -> str:
    return _validate_pattern(
        value,
        _SHA256_HEX_PATTERN,
        "fingerprint must be lowercase SHA-256 hex",
    )


def _validate_utf8_text(
    value: object,
    *,
    minimum_bytes: int,
    maximum_bytes: int,
    message: str,
) -> str:
    if type(value) is not str or "\x00" in value:
        raise ValueError(message)
    try:
        byte_length = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError:
        raise ValueError(message) from None
    if not minimum_bytes <= byte_length <= maximum_bytes:
        raise ValueError(message)
    return value


def _validate_reference_id(value: object) -> str:
    return _validate_utf8_text(
        value,
        minimum_bytes=1,
        maximum_bytes=512,
        message="reference ID must contain 1..512 valid UTF-8 bytes without NUL",
    )


def _validate_idempotency_key(value: object) -> str:
    return _validate_utf8_text(
        value,
        minimum_bytes=1,
        maximum_bytes=512,
        message="idempotency key must contain 1..512 valid UTF-8 bytes without NUL",
    )


def _validate_ledger_scalar(value: object) -> str | int | bool:
    if type(value) is str:
        return _validate_utf8_text(
            value,
            minimum_bytes=0,
            maximum_bytes=4_096,
            message="string field must be valid UTF-8 without NUL and at most 4096 bytes",
        )
    if type(value) is int:
        if not _SQLITE_INT_MIN <= value <= _SQLITE_INT_MAX:
            raise ValueError("integer field must fit SQLite signed 64-bit storage")
        return value
    if type(value) is bool:
        return value
    raise ValueError("ledger field value must be an exact string, integer, or boolean")


def _fresh_exact_model[ModelT: BaseModel](
    value: object,
    expected_type: type[ModelT],
    message: str,
) -> ModelT:
    if type(value) is not expected_type:
        raise ValueError(message)
    try:
        fields = {name: value.__dict__[name] for name in expected_type.model_fields}
        return expected_type.model_validate(fields)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError(message) from None


type _EventNamespace = Annotated[str, BeforeValidator(_validate_event_namespace)]
type _ProviderName = Annotated[str, BeforeValidator(_validate_provider_name)]
type _FieldKey = Annotated[str, BeforeValidator(_validate_field_key)]
type _Sha256Hex = Annotated[str, BeforeValidator(_validate_sha256_hex)]
type _ReferenceId = Annotated[str, BeforeValidator(_validate_reference_id)]
type _IdempotencyKey = Annotated[str, BeforeValidator(_validate_idempotency_key)]
type _LedgerScalar = Annotated[str | int | bool, BeforeValidator(_validate_ledger_scalar)]


class FinancialLedgerValueType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    BOOLEAN = "boolean"


class FinancialLedgerFieldV1(BaseModel):
    """One deterministic, typed, non-null event field."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    financial_event_ledger_version: Literal["financial-event-ledger-v1"] = (
        "financial-event-ledger-v1"
    )
    field_key: _FieldKey
    value_type: FinancialLedgerValueType
    value: _LedgerScalar

    @model_validator(mode="after")
    def _validate_declared_type(self) -> Self:
        expected_type = {
            FinancialLedgerValueType.STRING: str,
            FinancialLedgerValueType.INTEGER: int,
            FinancialLedgerValueType.BOOLEAN: bool,
        }[self.value_type]
        if type(self.value) is not expected_type:
            raise ValueError("declared ledger value type must exactly match its scalar")
        return self


def _fresh_event_fields(value: object) -> tuple[FinancialLedgerFieldV1, ...]:
    if type(value) is not tuple:
        raise ValueError("event fields must be supplied as an exact tuple")
    fields = tuple(
        _fresh_exact_model(
            field,
            FinancialLedgerFieldV1,
            "event fields must contain valid exact FinancialLedgerFieldV1 values",
        )
        for field in cast(tuple[object, ...], value)
    )
    field_keys = tuple(field.field_key for field in fields)
    if len(set(field_keys)) != len(field_keys):
        raise ValueError("event field keys must be unique")
    return tuple(sorted(fields, key=lambda field: field.field_key))


type _EventFields = Annotated[
    tuple[FinancialLedgerFieldV1, ...],
    BeforeValidator(_fresh_event_fields),
    Field(max_length=64),
]


class ExecutionReservationV1(BaseModel):
    """Durable duplicate-execution fact, never financial authorization.

    A reservation is not proof of certificate verification, buyer authorization, Money Governor
    approval, or provider action. Slice 20B owns the authority governing when one may be stored.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    financial_event_ledger_version: Literal["financial-event-ledger-v1"] = (
        "financial-event-ledger-v1"
    )
    execution_id: CanonicalUUID4
    certificate_digest_version: Literal["sha256-allocation-certificate-v2-clear-json-v1"]
    certificate_digest_sha256: _Sha256Hex
    market_id: CanonicalUUID4
    execution_request_fingerprint_sha256: _Sha256Hex
    reserved_at: UTCDateTime


class ExecutionReservationDispositionV1(StrEnum):
    CREATED = "CREATED"
    EXISTING_SAME = "EXISTING_SAME"
    EXECUTION_ID_CONFLICT = "EXECUTION_ID_CONFLICT"
    CERTIFICATE_ALREADY_RESERVED = "CERTIFICATE_ALREADY_RESERVED"
    MARKET_ALREADY_RESERVED = "MARKET_ALREADY_RESERVED"


def _fresh_reservation(value: object) -> ExecutionReservationV1:
    return _fresh_exact_model(
        value,
        ExecutionReservationV1,
        "stored reservation must be a valid exact ExecutionReservationV1 value",
    )


class ExecutionReservationResultV1(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    financial_event_ledger_version: Literal["financial-event-ledger-v1"] = (
        "financial-event-ledger-v1"
    )
    disposition: ExecutionReservationDispositionV1
    stored_reservation: Annotated[ExecutionReservationV1, BeforeValidator(_fresh_reservation)]


class FinancialLedgerEventV1(BaseModel):
    """Caller-decided immutable event data without payment-state authority."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    financial_event_ledger_version: Literal["financial-event-ledger-v1"] = (
        "financial-event-ledger-v1"
    )
    event_id: CanonicalUUID4
    execution_id: CanonicalUUID4
    event_type: _EventNamespace
    occurred_at: UTCDateTime
    fields: _EventFields


def _fresh_event(value: object) -> FinancialLedgerEventV1:
    return _fresh_exact_model(
        value,
        FinancialLedgerEventV1,
        "event must be a valid exact FinancialLedgerEventV1 value",
    )


class PersistedFinancialLedgerEventV1(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    financial_event_ledger_version: Literal["financial-event-ledger-v1"] = (
        "financial-event-ledger-v1"
    )
    sequence_number: Annotated[int, Field(strict=True, ge=1)]
    event: Annotated[FinancialLedgerEventV1, BeforeValidator(_fresh_event)]


class FinancialLedgerEventAppendDispositionV1(StrEnum):
    CREATED = "CREATED"
    EXISTING_SAME = "EXISTING_SAME"
    EVENT_ID_CONFLICT = "EVENT_ID_CONFLICT"


def _fresh_persisted_event(value: object) -> PersistedFinancialLedgerEventV1:
    return _fresh_exact_model(
        value,
        PersistedFinancialLedgerEventV1,
        "persisted event must be a valid exact PersistedFinancialLedgerEventV1 value",
    )


class FinancialLedgerEventAppendResultV1(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    financial_event_ledger_version: Literal["financial-event-ledger-v1"] = (
        "financial-event-ledger-v1"
    )
    disposition: FinancialLedgerEventAppendDispositionV1
    persisted_event: Annotated[
        PersistedFinancialLedgerEventV1,
        BeforeValidator(_fresh_persisted_event),
    ]


class ProviderReferenceV1(BaseModel):
    """Generic durable provider attribution without provider-specific semantics."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    financial_event_ledger_version: Literal["financial-event-ledger-v1"] = (
        "financial-event-ledger-v1"
    )
    provider_name: _ProviderName
    reference_kind: _EventNamespace
    reference_id: _ReferenceId
    execution_id: CanonicalUUID4
    recorded_at: UTCDateTime


class ProviderReferenceDispositionV1(StrEnum):
    CREATED = "CREATED"
    EXISTING_SAME = "EXISTING_SAME"
    REFERENCE_CONFLICT = "REFERENCE_CONFLICT"


def _fresh_reference(value: object) -> ProviderReferenceV1:
    return _fresh_exact_model(
        value,
        ProviderReferenceV1,
        "stored reference must be a valid exact ProviderReferenceV1 value",
    )


class ProviderReferenceResultV1(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    financial_event_ledger_version: Literal["financial-event-ledger-v1"] = (
        "financial-event-ledger-v1"
    )
    disposition: ProviderReferenceDispositionV1
    stored_reference: Annotated[ProviderReferenceV1, BeforeValidator(_fresh_reference)]


class IdempotencyRecordV1(BaseModel):
    """Opaque request fingerprint claim keyed within a caller-selected namespace."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    financial_event_ledger_version: Literal["financial-event-ledger-v1"] = (
        "financial-event-ledger-v1"
    )
    namespace: _EventNamespace
    idempotency_key: _IdempotencyKey
    request_fingerprint_sha256: _Sha256Hex
    execution_id: CanonicalUUID4 | None
    recorded_at: UTCDateTime


class IdempotencyDispositionV1(StrEnum):
    CREATED = "CREATED"
    EXISTING_SAME = "EXISTING_SAME"
    CONFLICT = "CONFLICT"


def _fresh_idempotency_record(value: object) -> IdempotencyRecordV1:
    return _fresh_exact_model(
        value,
        IdempotencyRecordV1,
        "stored record must be a valid exact IdempotencyRecordV1 value",
    )


class IdempotencyResultV1(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    financial_event_ledger_version: Literal["financial-event-ledger-v1"] = (
        "financial-event-ledger-v1"
    )
    disposition: IdempotencyDispositionV1
    stored_record: Annotated[IdempotencyRecordV1, BeforeValidator(_fresh_idempotency_record)]
