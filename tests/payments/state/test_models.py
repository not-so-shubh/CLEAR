from datetime import UTC, datetime
from enum import StrEnum

import pytest
from pydantic import BaseModel, ValidationError

import clear_market.payments.state as payment_state
from clear_market.domain import Currency, Money
from clear_market.payments.razorpay import (
    RazorpayWebhookEventTypeV1,
    RazorpayWebhookPaymentStatusV1,
)
from clear_market.payments.state import (
    CLEAR_PAYMENT_STATE_MACHINE_V1_VERSION,
    CLEAR_PAYMENT_STATE_SNAPSHOT_V1_VERSION,
    RAZORPAY_PAYMENT_EVIDENCE_V1_VERSION,
    ClearPaymentStateSnapshotV1,
    ClearPaymentStateV1,
    PaymentStateError,
    PaymentStateFailureCode,
    RazorpayPaymentEvidenceV1,
)

_EXECUTION_ID = "e1000000-0000-4000-8000-000000000001"
_EVENT_ID = "e2000000-0000-4000-8000-000000000001"
_ACCOUNT_ID = "acc_CLEARPRIMARY01"
_ORDER_ID = "order_CLEARReview1"
_PAYMENT_ID = "pay_CLEARReview1"
_EVENT_TIME = 1_788_266_600
_PAYMENT_TIME = 1_788_266_590
_CERTIFICATE_SHA = "1" * 64
_RAW_BODY_SHA = "2" * 64


def _validated_copy[ModelT: BaseModel](model: ModelT, **changes: object) -> ModelT:
    fields = {name: model.__dict__[name] for name in type(model).model_fields}
    fields.update(changes)
    return type(model).model_validate(fields)


def _evidence(
    *,
    sequence: int = 1,
    event_id: str = _EVENT_ID,
    execution_id: str = _EXECUTION_ID,
    account_id: str = _ACCOUNT_ID,
    order_id: str = _ORDER_ID,
    payment_id: str = _PAYMENT_ID,
    event_type: RazorpayWebhookEventTypeV1 = RazorpayWebhookEventTypeV1.PAYMENT_CAPTURED,
    amount: Money | None = None,
    event_time: int = _EVENT_TIME,
) -> RazorpayPaymentEvidenceV1:
    ledger_event_type, status, captured = {
        RazorpayWebhookEventTypeV1.PAYMENT_AUTHORIZED: (
            "razorpay.webhook.payment_authorized.v1",
            RazorpayWebhookPaymentStatusV1.AUTHORIZED,
            False,
        ),
        RazorpayWebhookEventTypeV1.PAYMENT_CAPTURED: (
            "razorpay.webhook.payment_captured.v1",
            RazorpayWebhookPaymentStatusV1.CAPTURED,
            True,
        ),
        RazorpayWebhookEventTypeV1.PAYMENT_FAILED: (
            "razorpay.webhook.payment_failed.v1",
            RazorpayWebhookPaymentStatusV1.FAILED,
            False,
        ),
    }[event_type]
    return RazorpayPaymentEvidenceV1(
        ledger_sequence_number=sequence,
        ledger_event_id=event_id,
        execution_id=execution_id,
        ledger_event_type=ledger_event_type,
        occurred_at=datetime.fromtimestamp(event_time, tz=UTC),
        raw_body_digest_version="sha256-razorpay-webhook-raw-body-v1",
        raw_body_sha256=_RAW_BODY_SHA,
        provider_account_id=account_id,
        webhook_event_type=event_type,
        provider_order_id=order_id,
        provider_payment_id=payment_id,
        amount=amount or Money(amount_paise=2_700),
        payment_status=status,
        captured=captured,
        provider_payment_created_at_unix=_PAYMENT_TIME,
        provider_event_created_at_unix=event_time,
    )


def _snapshot(
    *,
    state: ClearPaymentStateV1 = ClearPaymentStateV1.PAYMENT_CAPTURED,
    effective_payment_id: str | None = _PAYMENT_ID,
    evidence: tuple[RazorpayPaymentEvidenceV1, ...] | None = None,
) -> ClearPaymentStateSnapshotV1:
    return ClearPaymentStateSnapshotV1(
        execution_id=_EXECUTION_ID,
        certificate_digest_version="sha256-allocation-certificate-v2-clear-json-v1",
        certificate_digest_sha256=_CERTIFICATE_SHA,
        provider_account_id=_ACCOUNT_ID,
        provider_order_id=_ORDER_ID,
        expected_amount=Money(amount_paise=2_700),
        state=state,
        effective_payment_id=effective_payment_id,
        evidence=(_evidence(),) if evidence is None else evidence,
    )


def test_versions_states_failure_codes_and_public_api_are_exact() -> None:
    assert CLEAR_PAYMENT_STATE_MACHINE_V1_VERSION == "clear-payment-state-machine-v1"
    assert CLEAR_PAYMENT_STATE_SNAPSHOT_V1_VERSION == "clear-payment-state-snapshot-v1"
    assert RAZORPAY_PAYMENT_EVIDENCE_V1_VERSION == "razorpay-payment-evidence-v1"
    assert issubclass(ClearPaymentStateV1, StrEnum)
    assert tuple(ClearPaymentStateV1) == (
        ClearPaymentStateV1.ORDER_CREATED,
        ClearPaymentStateV1.PAYMENT_FAILED_OBSERVED,
        ClearPaymentStateV1.PAYMENT_AUTHORIZED,
        ClearPaymentStateV1.PAYMENT_CAPTURED,
    )
    assert tuple(member.value for member in ClearPaymentStateV1) == (
        "ORDER_CREATED",
        "PAYMENT_FAILED_OBSERVED",
        "PAYMENT_AUTHORIZED",
        "PAYMENT_CAPTURED",
    )
    assert tuple(PaymentStateFailureCode) == tuple(
        PaymentStateFailureCode[name]
        for name in (
            "CERTIFICATE_NOT_VERIFIED",
            "ALLOCATION_NOT_EXECUTABLE",
            "EXECUTION_NOT_FOUND",
            "EXECUTION_BINDING_MISMATCH",
            "ORDER_REFERENCE_MISSING",
            "ORDER_REFERENCE_CONFLICT",
            "PAYMENT_EVIDENCE_INVALID",
            "PAYMENT_ACCOUNT_MISMATCH",
            "PAYMENT_ORDER_MISMATCH",
            "PAYMENT_ECONOMIC_MISMATCH",
            "PAYMENT_REFERENCE_MISSING",
            "PAYMENT_REFERENCE_CONFLICT",
            "INCOMPLETE_PAYMENT_INGRESS",
            "MULTIPLE_ACTIVE_PAYMENTS",
        )
    )
    assert tuple(member.value for member in PaymentStateFailureCode) == tuple(
        member.name for member in PaymentStateFailureCode
    )
    assert payment_state.__all__ == (
        "CLEAR_PAYMENT_STATE_MACHINE_V1_VERSION",
        "CLEAR_PAYMENT_STATE_SNAPSHOT_V1_VERSION",
        "RAZORPAY_PAYMENT_EVIDENCE_V1_VERSION",
        "ClearPaymentStateV1",
        "RazorpayPaymentEvidenceV1",
        "ClearPaymentStateSnapshotV1",
        "PaymentStateFailureCode",
        "PaymentStateError",
        "derive_razorpay_payment_state_v1",
    )


def test_payment_state_error_is_sanitized_and_code_is_read_only() -> None:
    error = PaymentStateError(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID)
    assert error.code is PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID
    assert str(error) == "PAYMENT_EVIDENCE_INVALID"
    with pytest.raises(AttributeError):
        error.code = PaymentStateFailureCode.ORDER_REFERENCE_MISSING  # type: ignore[misc]


def test_evidence_fields_versions_and_values_are_exact() -> None:
    value = _evidence()
    assert tuple(RazorpayPaymentEvidenceV1.model_fields) == (
        "schema_version",
        "razorpay_payment_evidence_version",
        "ledger_sequence_number",
        "ledger_event_id",
        "execution_id",
        "ledger_event_type",
        "occurred_at",
        "raw_body_digest_version",
        "raw_body_sha256",
        "provider_account_id",
        "webhook_event_type",
        "provider_order_id",
        "provider_payment_id",
        "amount",
        "payment_status",
        "captured",
        "provider_payment_created_at_unix",
        "provider_event_created_at_unix",
    )
    assert value.schema_version == "1"
    assert value.razorpay_payment_evidence_version == RAZORPAY_PAYMENT_EVIDENCE_V1_VERSION
    assert value.amount == Money(amount_paise=2_700)
    assert value.occurred_at == datetime.fromtimestamp(_EVENT_TIME, tz=UTC)


def test_snapshot_fields_versions_and_values_are_exact() -> None:
    value = _snapshot()
    assert tuple(ClearPaymentStateSnapshotV1.model_fields) == (
        "schema_version",
        "clear_payment_state_snapshot_version",
        "clear_payment_state_machine_version",
        "execution_id",
        "certificate_digest_version",
        "certificate_digest_sha256",
        "provider_account_id",
        "provider_order_id",
        "expected_amount",
        "state",
        "effective_payment_id",
        "evidence",
    )
    assert value.schema_version == "1"
    assert value.clear_payment_state_snapshot_version == CLEAR_PAYMENT_STATE_SNAPSHOT_V1_VERSION
    assert value.clear_payment_state_machine_version == CLEAR_PAYMENT_STATE_MACHINE_V1_VERSION


@pytest.mark.parametrize("model", [_evidence(), _snapshot()])
def test_models_are_frozen_and_forbid_extras(model: BaseModel) -> None:
    with pytest.raises(ValidationError):
        model.model_copy(update={"schema_version": "2"}).model_validate(
            {**model.__dict__, "schema_version": "2"}
        )
    with pytest.raises(ValidationError):
        type(model).model_validate({**model.__dict__, "unexpected": True})
    with pytest.raises(ValidationError):
        model.schema_version = "1"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "expected_fragment"),
    [
        ({"ledger_sequence_number": 0}, "greater than or equal"),
        ({"ledger_sequence_number": True}, "valid integer"),
        ({"ledger_event_id": "not-a-uuid"}, "UUID input is malformed"),
        ({"execution_id": "not-a-uuid"}, "UUID input is malformed"),
        ({"raw_body_digest_version": "wrong"}, "literal_error"),
        ({"raw_body_sha256": "A" * 64}, "lowercase SHA-256"),
        ({"provider_account_id": "acc_"}, "not canonical"),
        ({"provider_order_id": "order_"}, "not canonical"),
        ({"provider_payment_id": "pay_"}, "not canonical"),
        ({"provider_event_created_at_unix": -1}, "nonnegative integer"),
        ({"provider_event_created_at_unix": True}, "nonnegative integer"),
    ],
)
def test_evidence_rejects_invalid_primitives(
    changes: dict[str, object],
    expected_fragment: str,
) -> None:
    with pytest.raises(ValidationError) as caught:
        _validated_copy(_evidence(), **changes)
    assert expected_fragment in str(caught.value)


@pytest.mark.parametrize(
    "amount",
    [
        {"amount_paise": 2_700, "currency": "INR"},
        Money.model_construct(amount_paise="2700", currency=Currency.INR),
        Money.model_construct(currency=Currency.INR),
    ],
)
def test_evidence_requires_fresh_exact_money(amount: object) -> None:
    with pytest.raises(ValidationError):
        _validated_copy(_evidence(), amount=amount)


@pytest.mark.parametrize(
    ("event_type", "changes"),
    [
        (
            RazorpayWebhookEventTypeV1.PAYMENT_AUTHORIZED,
            {"captured": True},
        ),
        (
            RazorpayWebhookEventTypeV1.PAYMENT_CAPTURED,
            {"payment_status": RazorpayWebhookPaymentStatusV1.AUTHORIZED},
        ),
        (
            RazorpayWebhookEventTypeV1.PAYMENT_FAILED,
            {"ledger_event_type": "razorpay.webhook.payment_captured.v1"},
        ),
    ],
)
def test_evidence_rejects_inconsistent_event_semantics(
    event_type: RazorpayWebhookEventTypeV1,
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="event semantics are inconsistent"):
        _validated_copy(_evidence(event_type=event_type), **changes)


def test_evidence_requires_occurred_at_from_provider_event_time() -> None:
    with pytest.raises(ValidationError, match="occurrence time is inconsistent"):
        _validated_copy(
            _evidence(),
            occurred_at=datetime.fromtimestamp(_EVENT_TIME, tz=UTC).replace(second=1),
        )


@pytest.mark.parametrize("evidence", [[], (_evidence(),), (_evidence(), _evidence())])
def test_snapshot_requires_exact_tuple_with_fresh_exact_evidence(evidence: object) -> None:
    if type(evidence) is tuple and len(evidence) == 1:
        assert _snapshot(evidence=evidence).evidence == evidence
        return
    with pytest.raises(ValidationError):
        _validated_copy(_snapshot(), evidence=evidence)


def test_snapshot_rejects_constructed_malformed_nested_evidence() -> None:
    bad = RazorpayPaymentEvidenceV1.model_construct(schema_version="1")
    with pytest.raises(ValidationError):
        _validated_copy(_snapshot(), evidence=(bad,))


def test_snapshot_preserves_strictly_increasing_ledger_sequence_order() -> None:
    first = _evidence(sequence=2, event_id="e2000000-0000-4000-8000-000000000002")
    second = _evidence(sequence=3, event_id="e2000000-0000-4000-8000-000000000003")
    snapshot = _snapshot(evidence=(first, second))
    assert snapshot.evidence == (first, second)
    with pytest.raises(ValidationError, match="strictly increasing"):
        _snapshot(evidence=(second, first))
    with pytest.raises(ValidationError, match="strictly increasing"):
        _snapshot(evidence=(first, first))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"execution_id": "e1000000-0000-4000-8000-000000000002"}, "execution"),
        ({"provider_account_id": "acc_OTHER"}, "account"),
        ({"provider_order_id": "order_OTHER"}, "order"),
        ({"amount": Money(amount_paise=2_699)}, "amount"),
    ],
)
def test_snapshot_rejects_evidence_binding_mismatch(
    change: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        _snapshot(evidence=(_validated_copy(_evidence(), **change),))


def test_order_created_state_requires_empty_evidence_and_no_payment() -> None:
    value = _snapshot(
        state=ClearPaymentStateV1.ORDER_CREATED,
        effective_payment_id=None,
        evidence=(),
    )
    assert value.evidence == ()
    with pytest.raises(ValidationError, match="order-created"):
        _validated_copy(value, evidence=(_evidence(),))
    with pytest.raises(ValidationError, match="order-created"):
        _validated_copy(value, effective_payment_id=_PAYMENT_ID)


def test_failed_observed_is_explicitly_nonterminal_and_requires_failed_shape() -> None:
    failed = _evidence(event_type=RazorpayWebhookEventTypeV1.PAYMENT_FAILED)
    value = _snapshot(
        state=ClearPaymentStateV1.PAYMENT_FAILED_OBSERVED,
        effective_payment_id=None,
        evidence=(failed,),
    )
    assert value.state is ClearPaymentStateV1.PAYMENT_FAILED_OBSERVED
    assert "PAYMENT_FAILED_OBSERVED is deliberately nonterminal" in (
        ClearPaymentStateV1.__doc__ or ""
    )
    with pytest.raises(ValidationError, match="failed-observed"):
        _validated_copy(value, evidence=())
    with pytest.raises(ValidationError, match="failed-observed"):
        _validated_copy(value, effective_payment_id=_PAYMENT_ID)


@pytest.mark.parametrize(
    "state",
    [ClearPaymentStateV1.PAYMENT_AUTHORIZED, ClearPaymentStateV1.PAYMENT_CAPTURED],
)
def test_active_states_require_an_evidenced_effective_payment(
    state: ClearPaymentStateV1,
) -> None:
    evidence = _evidence()
    assert _snapshot(state=state, evidence=(evidence,)).effective_payment_id == _PAYMENT_ID
    with pytest.raises(ValidationError, match="require an effective"):
        _snapshot(state=state, effective_payment_id=None, evidence=(evidence,))
    with pytest.raises(ValidationError, match="must appear"):
        _snapshot(state=state, effective_payment_id="pay_OTHER", evidence=(evidence,))


def test_snapshot_authority_limitation_is_explicit_and_no_side_effect_api_is_exposed() -> None:
    doc = ClearPaymentStateSnapshotV1.__doc__ or ""
    for text in (
        "not Money Governor authorization",
        "not sufficient authority to capture",
        "transfer",
        "refund",
        "reverse",
        "fulfill",
        "settle",
        "replay/revalidate",
    ):
        assert text in doc
    assert all(
        not name.startswith(("capture", "transfer", "refund", "reverse", "settle"))
        for name in payment_state.__all__
    )


def test_snapshot_rejects_wrong_python_object_types() -> None:
    with pytest.raises(ValidationError):
        _validated_copy(_snapshot(), expected_amount={"amount_paise": 2_700, "currency": "INR"})
    with pytest.raises(ValidationError):
        ClearPaymentStateSnapshotV1.model_validate(
            {**_snapshot().__dict__, "state": "PAYMENT_CAPTURED"}
        )
