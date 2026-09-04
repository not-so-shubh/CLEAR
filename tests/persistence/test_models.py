from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from pydantic import BaseModel, ValidationError

import clear_market.persistence as persistence
from clear_market.persistence import (
    FINANCIAL_EVENT_LEDGER_V1_VERSION,
    SQLITE_FINANCIAL_LEDGER_SCHEMA_VERSION,
    ExecutionReservationDispositionV1,
    ExecutionReservationResultV1,
    ExecutionReservationV1,
    FinancialLedgerEventAppendDispositionV1,
    FinancialLedgerEventAppendResultV1,
    FinancialLedgerEventV1,
    FinancialLedgerFieldV1,
    FinancialLedgerValueType,
    IdempotencyDispositionV1,
    IdempotencyRecordV1,
    IdempotencyResultV1,
    PersistedFinancialLedgerEventV1,
    PersistenceError,
    PersistenceErrorCode,
    ProviderReferenceDispositionV1,
    ProviderReferenceResultV1,
    ProviderReferenceV1,
    SQLiteFinancialLedgerV1,
    open_sqlite_financial_ledger_v1,
)

_TIME = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
_EXECUTION_ID = "d1000000-0000-4000-8000-000000000001"
_OTHER_EXECUTION_ID = "d1000000-0000-4000-8000-000000000002"
_MARKET_ID = "d2000000-0000-4000-8000-000000000001"
_EVENT_ID = "d3000000-0000-4000-8000-000000000001"
_DIGEST = "a" * 64
_FINGERPRINT = "b" * 64
_CONFIG = {
    "frozen": True,
    "extra": "forbid",
    "strict": True,
    "revalidate_instances": "always",
}


def _field(**changes: object) -> FinancialLedgerFieldV1:
    values: dict[str, object] = {
        "field_key": "provider.status",
        "value_type": FinancialLedgerValueType.STRING,
        "value": "accepted",
        **changes,
    }
    return FinancialLedgerFieldV1(**values)


def _reservation(**changes: object) -> ExecutionReservationV1:
    values: dict[str, object] = {
        "execution_id": _EXECUTION_ID,
        "certificate_digest_version": "sha256-allocation-certificate-v2-clear-json-v1",
        "certificate_digest_sha256": _DIGEST,
        "market_id": _MARKET_ID,
        "execution_request_fingerprint_sha256": _FINGERPRINT,
        "reserved_at": _TIME,
        **changes,
    }
    return ExecutionReservationV1(**values)


def _event(**changes: object) -> FinancialLedgerEventV1:
    values: dict[str, object] = {
        "event_id": _EVENT_ID,
        "execution_id": _EXECUTION_ID,
        "event_type": "governor.approved",
        "occurred_at": _TIME,
        "fields": (_field(),),
        **changes,
    }
    return FinancialLedgerEventV1(**values)


def _persisted_event(**changes: object) -> PersistedFinancialLedgerEventV1:
    values: dict[str, object] = {"sequence_number": 1, "event": _event(), **changes}
    return PersistedFinancialLedgerEventV1(**values)


def _reference(**changes: object) -> ProviderReferenceV1:
    values: dict[str, object] = {
        "provider_name": "example-provider",
        "reference_kind": "order",
        "reference_id": "provider-order-1",
        "execution_id": _EXECUTION_ID,
        "recorded_at": _TIME,
        **changes,
    }
    return ProviderReferenceV1(**values)


def _idempotency(**changes: object) -> IdempotencyRecordV1:
    values: dict[str, object] = {
        "namespace": "provider.request",
        "idempotency_key": "request-1",
        "request_fingerprint_sha256": _FINGERPRINT,
        "execution_id": _EXECUTION_ID,
        "recorded_at": _TIME,
        **changes,
    }
    return IdempotencyRecordV1(**values)


def test_versions_and_public_api_are_exact() -> None:
    assert FINANCIAL_EVENT_LEDGER_V1_VERSION == "financial-event-ledger-v1"
    assert SQLITE_FINANCIAL_LEDGER_SCHEMA_VERSION == 1
    assert persistence.__all__ == (
        "FINANCIAL_EVENT_LEDGER_V1_VERSION",
        "SQLITE_FINANCIAL_LEDGER_SCHEMA_VERSION",
        "FinancialLedgerValueType",
        "FinancialLedgerFieldV1",
        "ExecutionReservationV1",
        "ExecutionReservationDispositionV1",
        "ExecutionReservationResultV1",
        "FinancialLedgerEventV1",
        "PersistedFinancialLedgerEventV1",
        "FinancialLedgerEventAppendDispositionV1",
        "FinancialLedgerEventAppendResultV1",
        "ProviderReferenceV1",
        "ProviderReferenceDispositionV1",
        "ProviderReferenceResultV1",
        "IdempotencyRecordV1",
        "IdempotencyDispositionV1",
        "IdempotencyResultV1",
        "PersistenceErrorCode",
        "PersistenceError",
        "SQLiteFinancialLedgerV1",
        "open_sqlite_financial_ledger_v1",
    )


@pytest.mark.parametrize(
    ("enum_type", "names"),
    [
        (FinancialLedgerValueType, ("STRING", "INTEGER", "BOOLEAN")),
        (
            ExecutionReservationDispositionV1,
            (
                "CREATED",
                "EXISTING_SAME",
                "EXECUTION_ID_CONFLICT",
                "CERTIFICATE_ALREADY_RESERVED",
                "MARKET_ALREADY_RESERVED",
            ),
        ),
        (
            FinancialLedgerEventAppendDispositionV1,
            ("CREATED", "EXISTING_SAME", "EVENT_ID_CONFLICT"),
        ),
        (
            ProviderReferenceDispositionV1,
            ("CREATED", "EXISTING_SAME", "REFERENCE_CONFLICT"),
        ),
        (IdempotencyDispositionV1, ("CREATED", "EXISTING_SAME", "CONFLICT")),
        (
            PersistenceErrorCode,
            (
                "DATABASE_OPEN_FAILED",
                "SCHEMA_MISMATCH",
                "DATABASE_OPERATION_FAILED",
                "CORRUPT_STORED_RECORD",
                "UNKNOWN_EXECUTION",
                "CLOSED",
            ),
        ),
    ],
)
def test_enum_order_and_values_are_exact(
    enum_type: type[Any],
    names: tuple[str, ...],
) -> None:
    assert tuple(member.name for member in enum_type) == names
    if enum_type is FinancialLedgerValueType:
        assert tuple(member.value for member in enum_type) == ("string", "integer", "boolean")
    else:
        assert tuple(member.value for member in enum_type) == names


@pytest.mark.parametrize(
    ("model_type", "fields"),
    [
        (
            FinancialLedgerFieldV1,
            (
                "schema_version",
                "financial_event_ledger_version",
                "field_key",
                "value_type",
                "value",
            ),
        ),
        (
            ExecutionReservationV1,
            (
                "schema_version",
                "financial_event_ledger_version",
                "execution_id",
                "certificate_digest_version",
                "certificate_digest_sha256",
                "market_id",
                "execution_request_fingerprint_sha256",
                "reserved_at",
            ),
        ),
        (
            ExecutionReservationResultV1,
            (
                "schema_version",
                "financial_event_ledger_version",
                "disposition",
                "stored_reservation",
            ),
        ),
        (
            FinancialLedgerEventV1,
            (
                "schema_version",
                "financial_event_ledger_version",
                "event_id",
                "execution_id",
                "event_type",
                "occurred_at",
                "fields",
            ),
        ),
        (
            PersistedFinancialLedgerEventV1,
            (
                "schema_version",
                "financial_event_ledger_version",
                "sequence_number",
                "event",
            ),
        ),
        (
            FinancialLedgerEventAppendResultV1,
            (
                "schema_version",
                "financial_event_ledger_version",
                "disposition",
                "persisted_event",
            ),
        ),
        (
            ProviderReferenceV1,
            (
                "schema_version",
                "financial_event_ledger_version",
                "provider_name",
                "reference_kind",
                "reference_id",
                "execution_id",
                "recorded_at",
            ),
        ),
        (
            ProviderReferenceResultV1,
            (
                "schema_version",
                "financial_event_ledger_version",
                "disposition",
                "stored_reference",
            ),
        ),
        (
            IdempotencyRecordV1,
            (
                "schema_version",
                "financial_event_ledger_version",
                "namespace",
                "idempotency_key",
                "request_fingerprint_sha256",
                "execution_id",
                "recorded_at",
            ),
        ),
        (
            IdempotencyResultV1,
            (
                "schema_version",
                "financial_event_ledger_version",
                "disposition",
                "stored_record",
            ),
        ),
    ],
)
def test_model_fields_config_versions_and_freezing_are_exact(
    model_type: type[BaseModel],
    fields: tuple[str, ...],
) -> None:
    assert tuple(model_type.model_fields) == fields
    assert model_type.model_config == _CONFIG


@pytest.mark.parametrize(
    "builder",
    [_field, _reservation, _event, _persisted_event, _reference, _idempotency],
)
def test_models_freeze_versions_and_forbid_extra(builder: Any) -> None:
    model = builder()
    assert model.schema_version == "1"
    assert model.financial_event_ledger_version == "financial-event-ledger-v1"
    with pytest.raises(ValidationError):
        builder(schema_version="2")
    with pytest.raises(ValidationError):
        builder(financial_event_ledger_version="other")
    with pytest.raises(ValidationError):
        builder(extra="forbidden")
    with pytest.raises(ValidationError):
        model.schema_version = "2"


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        (FinancialLedgerValueType.STRING, ""),
        (FinancialLedgerValueType.STRING, "évidence"),
        (FinancialLedgerValueType.INTEGER, -9_223_372_036_854_775_808),
        (FinancialLedgerValueType.INTEGER, 9_223_372_036_854_775_807),
        (FinancialLedgerValueType.BOOLEAN, False),
        (FinancialLedgerValueType.BOOLEAN, True),
    ],
)
def test_ledger_field_accepts_exact_scalar_contract(
    value_type: FinancialLedgerValueType,
    value: str | int | bool,
) -> None:
    assert _field(value_type=value_type, value=value).value == value


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        (FinancialLedgerValueType.STRING, 1),
        (FinancialLedgerValueType.STRING, True),
        (FinancialLedgerValueType.INTEGER, "1"),
        (FinancialLedgerValueType.INTEGER, True),
        (FinancialLedgerValueType.BOOLEAN, 1),
        (FinancialLedgerValueType.BOOLEAN, "true"),
    ],
)
def test_ledger_field_rejects_declared_type_mismatch(
    value_type: FinancialLedgerValueType,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        _field(value_type=value_type, value=value)


@pytest.mark.parametrize(
    "value",
    [
        1.0,
        Decimal("1"),
        None,
        b"value",
        [],
        (),
        {},
        9_223_372_036_854_775_808,
        -9_223_372_036_854_775_809,
    ],
)
def test_ledger_field_rejects_non_scalars_and_integer_overflow(value: object) -> None:
    with pytest.raises(ValidationError):
        _field(value_type=FinancialLedgerValueType.INTEGER, value=value)


@pytest.mark.parametrize("value", ["bad\x00value", "\ud800", "é" * 2_049])
def test_ledger_string_rejects_nul_invalid_unicode_and_more_than_4096_bytes(value: str) -> None:
    with pytest.raises(ValidationError):
        _field(value=value)


@pytest.mark.parametrize(
    "field_key",
    ["", "Field", ".field", "field:value", "field value", "field/value", "évidence"],
)
def test_field_key_grammar_is_strict(field_key: str) -> None:
    with pytest.raises(ValidationError):
        _field(field_key=field_key)


def test_event_fields_require_tuple_are_unique_bounded_and_sorted() -> None:
    first = _field(field_key="zeta")
    second = _field(field_key="alpha")
    assert _event(fields=(first, second)).fields == (second, first)
    with pytest.raises(ValidationError):
        _event(fields=[first])
    with pytest.raises(ValidationError):
        _event(fields=(first, first))
    with pytest.raises(ValidationError):
        _event(fields=tuple(_field(field_key=f"field.{index:02d}") for index in range(65)))


@pytest.mark.parametrize(
    "event_type",
    ["", "Event", ".event", "event/type", "event value", "évent", "e" * 129],
)
def test_event_namespace_grammar_is_strict(event_type: str) -> None:
    with pytest.raises(ValidationError):
        _event(event_type=event_type)


@pytest.mark.parametrize("provider_name", ["", "Provider", ".name", "name:value", "é", "p" * 65])
def test_provider_name_grammar_is_strict(provider_name: str) -> None:
    with pytest.raises(ValidationError):
        _reference(provider_name=provider_name)


@pytest.mark.parametrize("value", ["", "bad\x00id", "\ud800", "é" * 257])
def test_provider_reference_id_is_bounded_utf8(value: str) -> None:
    with pytest.raises(ValidationError):
        _reference(reference_id=value)


@pytest.mark.parametrize("value", ["", "bad\x00key", "\ud800", "é" * 257])
def test_idempotency_key_is_bounded_utf8(value: str) -> None:
    with pytest.raises(ValidationError):
        _idempotency(idempotency_key=value)


@pytest.mark.parametrize(
    "changes",
    [
        {"execution_id": "D1000000-0000-4000-8000-000000000001"},
        {"market_id": "not-a-uuid"},
        {"certificate_digest_sha256": "A" * 64},
        {"certificate_digest_sha256": "a" * 63},
        {"execution_request_fingerprint_sha256": "g" * 64},
        {"certificate_digest_version": "other"},
    ],
)
def test_reservation_identifiers_digests_and_version_are_strict(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _reservation(**changes)


def test_idempotency_execution_id_is_explicitly_optional() -> None:
    assert _idempotency(execution_id=None).execution_id is None
    assert _idempotency().execution_id == _EXECUTION_ID


class _ReservationSubclass(ExecutionReservationV1):
    pass


@pytest.mark.parametrize(
    ("model_type", "values"),
    [
        (
            ExecutionReservationResultV1,
            {
                "disposition": ExecutionReservationDispositionV1.CREATED,
                "stored_reservation": _reservation(),
            },
        ),
        (
            FinancialLedgerEventAppendResultV1,
            {
                "disposition": FinancialLedgerEventAppendDispositionV1.CREATED,
                "persisted_event": _persisted_event(),
            },
        ),
        (
            ProviderReferenceResultV1,
            {
                "disposition": ProviderReferenceDispositionV1.CREATED,
                "stored_reference": _reference(),
            },
        ),
        (
            IdempotencyResultV1,
            {
                "disposition": IdempotencyDispositionV1.CREATED,
                "stored_record": _idempotency(),
            },
        ),
    ],
)
def test_result_models_are_exact_frozen_and_forbid_extra(
    model_type: type[BaseModel],
    values: dict[str, object],
) -> None:
    result = model_type(**values)
    assert result.model_config == _CONFIG
    with pytest.raises(ValidationError):
        model_type(**values, extra="forbidden")
    with pytest.raises(ValidationError):
        result.schema_version = "2"


def test_nested_models_reject_subclasses_dicts_and_constructed_corruption() -> None:
    reservation = _reservation()
    with pytest.raises(ValidationError):
        ExecutionReservationResultV1(
            disposition=ExecutionReservationDispositionV1.CREATED,
            stored_reservation=cast(Any, _ReservationSubclass(**reservation.__dict__)),
        )
    with pytest.raises(ValidationError):
        ExecutionReservationResultV1(
            disposition=ExecutionReservationDispositionV1.CREATED,
            stored_reservation=cast(Any, reservation.model_dump()),
        )

    malformed_field = FinancialLedgerFieldV1.model_construct(
        field_key="field",
        value_type=FinancialLedgerValueType.INTEGER,
        value=True,
    )
    with pytest.raises(ValidationError):
        _event(fields=(malformed_field,))

    malformed_event = FinancialLedgerEventV1.model_construct(
        event_id=_EVENT_ID,
        execution_id=_EXECUTION_ID,
        event_type="event",
        occurred_at=_TIME,
        fields=(),
        schema_version="2",
    )
    with pytest.raises(ValidationError):
        PersistedFinancialLedgerEventV1(sequence_number=1, event=malformed_event)


def test_persisted_sequence_number_is_exact_positive_integer() -> None:
    assert _persisted_event(sequence_number=1).sequence_number == 1
    for value in (0, -1, True, 1.0, "1"):
        with pytest.raises(ValidationError):
            _persisted_event(sequence_number=value)


def test_persistence_error_contract_is_exact_read_only_and_non_sensitive() -> None:
    error = PersistenceError(PersistenceErrorCode.UNKNOWN_EXECUTION)
    assert error.code is PersistenceErrorCode.UNKNOWN_EXECUTION
    assert str(error) == "UNKNOWN_EXECUTION"
    with pytest.raises(AttributeError):
        error.code = PersistenceErrorCode.CLOSED


def test_reservation_is_explicitly_not_governor_approval() -> None:
    assert "not proof" in (ExecutionReservationV1.__doc__ or "")
    assert "Money Governor" in (ExecutionReservationV1.__doc__ or "")
    assert not hasattr(_reservation(), "governor_approved")
    assert not hasattr(_reservation(), "payment_state")


def test_open_factory_and_class_are_public_without_authority_helpers() -> None:
    assert callable(open_sqlite_financial_ledger_v1)
    assert SQLiteFinancialLedgerV1.__name__ == "SQLiteFinancialLedgerV1"
    assert _OTHER_EXECUTION_ID != _EXECUTION_ID
