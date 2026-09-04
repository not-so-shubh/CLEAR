import hashlib
import hmac
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from clear_market.certificate.v2 import (
    ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION,
    AllocationCertificateV2,
    AllocationClaimStatusV2,
    AllocationClaimV2,
    allocation_certificate_v2_digest,
)
from clear_market.commerce import MerchantSigningIdentityV2, buyer_policy_v2_commitment
from clear_market.domain import Money
from clear_market.payments.razorpay import (
    RazorpayWebhookVerificationConfigV1,
    authenticate_and_record_razorpay_webhook_v1,
)
from clear_market.payments.state import (
    ClearPaymentStateV1,
    PaymentStateError,
    PaymentStateFailureCode,
    derive_razorpay_payment_state_v1,
)
from clear_market.persistence import (
    ExecutionReservationV1,
    FinancialLedgerEventV1,
    FinancialLedgerFieldV1,
    FinancialLedgerValueType,
    IdempotencyRecordV1,
    ProviderReferenceV1,
    SQLiteFinancialLedgerV1,
    open_sqlite_financial_ledger_v1,
)
from tests.certificate.v2.test_serialization import (
    _certificate,
    _identity,
    _policy,
    _validated_copy,
)

_EXECUTION_ID = "e1000000-0000-4000-8000-000000000001"
_OTHER_EXECUTION_ID = "e1000000-0000-4000-8000-000000000002"
_ACCOUNT_ID = "acc_CLEARPRIMARY01"
_OTHER_ACCOUNT_ID = "acc_CLEAROTHER01"
_ORDER_ID = "order_CLEARReview1"
_OTHER_ORDER_ID = "order_CLEARReview2"
_PAYMENT_A = "pay_CLEARReview1"
_PAYMENT_B = "pay_CLEARReview2"
_SECRET = "clear-review-webhook-secret-v1"
_TIME = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
_CERTIFICATE = _certificate()
_TRUSTED_IDENTITIES = (_identity(1), _identity(2))
_CERTIFICATE_DIGEST = allocation_certificate_v2_digest(_CERTIFICATE)


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[SQLiteFinancialLedgerV1]:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as value:
        yield value


def _reservation(
    *,
    execution_id: str = _EXECUTION_ID,
    digest: str = _CERTIFICATE_DIGEST,
    market_id: str | None = None,
) -> ExecutionReservationV1:
    return ExecutionReservationV1(
        execution_id=execution_id,
        certificate_digest_version=ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION,
        certificate_digest_sha256=digest,
        market_id=market_id or _CERTIFICATE.buyer_policy.market_spec.market_id,
        execution_request_fingerprint_sha256="9" * 64,
        reserved_at=_TIME,
    )


def _reference(
    *,
    kind: str,
    reference_id: str,
    execution_id: str = _EXECUTION_ID,
    provider_name: str = "razorpay",
) -> ProviderReferenceV1:
    return ProviderReferenceV1(
        provider_name=provider_name,
        reference_kind=kind,
        reference_id=reference_id,
        execution_id=execution_id,
        recorded_at=_TIME,
    )


def _prepare(
    ledger: SQLiteFinancialLedgerV1,
    *,
    include_reservation: bool = True,
    include_order: bool = True,
    reservation: ExecutionReservationV1 | None = None,
) -> None:
    if include_reservation:
        ledger.reserve_execution(reservation or _reservation())
    if include_order:
        ledger.record_provider_reference(_reference(kind="order", reference_id=_ORDER_ID))


def _body(
    *,
    event_type: str,
    event_time: int,
    payment_id: str = _PAYMENT_A,
    payment_time: int | None = None,
    account_id: str = _ACCOUNT_ID,
    order_id: str = _ORDER_ID,
    amount: int = 2_700,
    currency: str = "INR",
) -> bytes:
    status, captured = {
        "payment.authorized": ("authorized", False),
        "payment.captured": ("captured", True),
        "payment.failed": ("failed", False),
    }[event_type]
    value = {
        "account_id": account_id,
        "contains": ["payment"],
        "created_at": event_time,
        "entity": "event",
        "event": event_type,
        "payload": {
            "payment": {
                "entity": {
                    "amount": amount,
                    "captured": captured,
                    "created_at": payment_time if payment_time is not None else event_time - 1,
                    "currency": currency,
                    "entity": "payment",
                    "id": payment_id,
                    "order_id": order_id,
                    "status": status,
                }
            }
        },
    }
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _ingest(
    ledger: SQLiteFinancialLedgerV1,
    *,
    event_type: str,
    event_time: int,
    payment_id: str = _PAYMENT_A,
    account_id: str = _ACCOUNT_ID,
    order_id: str = _ORDER_ID,
    amount: int = 2_700,
    currency: str = "INR",
    event_id: str | None = None,
) -> None:
    raw_body = _body(
        event_type=event_type,
        event_time=event_time,
        payment_id=payment_id,
        account_id=account_id,
        order_id=order_id,
        amount=amount,
        currency=currency,
    )
    signature = hmac.new(_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    authenticate_and_record_razorpay_webhook_v1(
        raw_body=raw_body,
        signature_header=signature,
        event_id_header=event_id or f"event-{event_type}-{payment_id}-{event_time}",
        verification_config=RazorpayWebhookVerificationConfigV1(
            expected_account_id=account_id,
            secrets=(_SECRET,),
        ),
        received_at=_TIME,
        ledger=ledger,
    )


def _derive(
    ledger: SQLiteFinancialLedgerV1,
    *,
    certificate: AllocationCertificateV2 = _CERTIFICATE,
    trusted_identities: tuple[MerchantSigningIdentityV2, ...] = _TRUSTED_IDENTITIES,
    execution_id: str = _EXECUTION_ID,
    account_id: str = _ACCOUNT_ID,
):
    return derive_razorpay_payment_state_v1(
        certificate=certificate,
        trusted_signing_identities=trusted_identities,
        execution_id=execution_id,
        expected_razorpay_account_id=account_id,
        ledger=ledger,
    )


def _assert_error(
    code: PaymentStateFailureCode,
    action: Any,
) -> PaymentStateError:
    with pytest.raises(PaymentStateError) as caught:
        action()
    assert caught.value.code is code
    assert str(caught.value) == code.value
    for private in (
        _EXECUTION_ID,
        _ACCOUNT_ID,
        _ORDER_ID,
        _PAYMENT_A,
        "2700",
        _CERTIFICATE_DIGEST,
    ):
        assert private not in str(caught.value)
    return caught.value


def _field(key: str, value_type: FinancialLedgerValueType, value: str | int | bool):
    return FinancialLedgerFieldV1(field_key=key, value_type=value_type, value=value)


def _manual_event(
    *,
    index: int,
    event_type: str = "razorpay.webhook.payment_captured.v1",
    event_time: int = 1_788_266_600,
    payment_id: str = _PAYMENT_A,
    account_id: str = _ACCOUNT_ID,
    order_id: str = _ORDER_ID,
    amount: int = 2_700,
    currency: str = "INR",
    field_changes: dict[str, tuple[FinancialLedgerValueType, str | int | bool]] | None = None,
    missing_field: str | None = None,
    extra_field: bool = False,
    occurred_at: datetime | None = None,
) -> FinancialLedgerEventV1:
    provider_type, status, captured = {
        "razorpay.webhook.payment_authorized.v1": ("payment.authorized", "authorized", False),
        "razorpay.webhook.payment_captured.v1": ("payment.captured", "captured", True),
        "razorpay.webhook.payment_failed.v1": ("payment.failed", "failed", False),
    }[event_type]
    values: dict[str, tuple[FinancialLedgerValueType, str | int | bool]] = {
        "amount_paise": (FinancialLedgerValueType.INTEGER, amount),
        "captured": (FinancialLedgerValueType.BOOLEAN, captured),
        "currency": (FinancialLedgerValueType.STRING, currency),
        "payment_status": (FinancialLedgerValueType.STRING, status),
        "provider_account_id": (FinancialLedgerValueType.STRING, account_id),
        "provider_event_created_at_unix": (FinancialLedgerValueType.INTEGER, event_time),
        "provider_event_type": (FinancialLedgerValueType.STRING, provider_type),
        "provider_order_id": (FinancialLedgerValueType.STRING, order_id),
        "provider_payment_created_at_unix": (
            FinancialLedgerValueType.INTEGER,
            event_time - 1,
        ),
        "provider_payment_id": (FinancialLedgerValueType.STRING, payment_id),
        "raw_body_digest_version": (
            FinancialLedgerValueType.STRING,
            "sha256-razorpay-webhook-raw-body-v1",
        ),
        "raw_body_sha256": (FinancialLedgerValueType.STRING, f"{index:064x}"),
    }
    values.update(field_changes or {})
    if missing_field is not None:
        values.pop(missing_field)
    if extra_field:
        values["unexpected"] = (FinancialLedgerValueType.STRING, "value")
    return FinancialLedgerEventV1(
        event_id=f"e4000000-0000-4000-8000-{index:012x}",
        execution_id=_EXECUTION_ID,
        event_type=event_type,
        occurred_at=occurred_at or datetime.fromtimestamp(event_time, tz=UTC),
        fields=tuple(_field(key, *typed_value) for key, typed_value in values.items()),
    )


def _append_manual_with_reference(
    ledger: SQLiteFinancialLedgerV1,
    event: FinancialLedgerEventV1,
    payment_id: str = _PAYMENT_A,
) -> None:
    ledger.record_provider_reference(_reference(kind="payment", reference_id=payment_id))
    ledger.append_event(event)


def _unrelated_event(index: int) -> FinancialLedgerEventV1:
    return FinancialLedgerEventV1(
        event_id=f"e3000000-0000-4000-8000-{index:012x}",
        execution_id=_EXECUTION_ID,
        event_type="unrelated.observation.v1",
        occurred_at=_TIME,
        fields=(),
    )


def test_order_created_snapshot_is_exact_and_replay_is_deterministic(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _prepare(ledger)
    first = _derive(ledger)
    second = _derive(ledger)
    assert first == second
    assert first.model_dump(mode="json") == {
        "schema_version": "1",
        "clear_payment_state_snapshot_version": "clear-payment-state-snapshot-v1",
        "clear_payment_state_machine_version": "clear-payment-state-machine-v1",
        "execution_id": _EXECUTION_ID,
        "certificate_digest_version": ALLOCATION_CERTIFICATE_V2_DIGEST_VERSION,
        "certificate_digest_sha256": _CERTIFICATE_DIGEST,
        "provider_account_id": _ACCOUNT_ID,
        "provider_order_id": _ORDER_ID,
        "expected_amount": {"amount_paise": 2_700, "currency": "INR"},
        "state": "ORDER_CREATED",
        "effective_payment_id": None,
        "evidence": [],
    }


def test_payment_failed_is_observed_but_explicitly_nonterminal(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _prepare(ledger)
    _ingest(ledger, event_type="payment.failed", event_time=200)
    snapshot = _derive(ledger)
    assert snapshot.state is ClearPaymentStateV1.PAYMENT_FAILED_OBSERVED
    assert snapshot.effective_payment_id is None
    assert len(snapshot.evidence) == 1


@pytest.mark.parametrize("delivery_order", [("failed", "authorized"), ("authorized", "failed")])
def test_failed_then_authorized_uses_provider_time_not_delivery_order(
    ledger: SQLiteFinancialLedgerV1,
    delivery_order: tuple[str, str],
) -> None:
    _prepare(ledger)
    facts = {
        "failed": ("payment.failed", 200),
        "authorized": ("payment.authorized", 300),
    }
    for name in delivery_order:
        event_type, event_time = facts[name]
        _ingest(ledger, event_type=event_type, event_time=event_time)
    snapshot = _derive(ledger)
    assert snapshot.state is ClearPaymentStateV1.PAYMENT_AUTHORIZED
    assert snapshot.effective_payment_id == _PAYMENT_A


@pytest.mark.parametrize("delivery_order", [("failed", "captured"), ("captured", "failed")])
def test_failed_then_captured_is_independent_of_delivery_order(
    ledger: SQLiteFinancialLedgerV1,
    delivery_order: tuple[str, str],
) -> None:
    _prepare(ledger)
    facts = {
        "failed": ("payment.failed", 200),
        "captured": ("payment.captured", 300),
    }
    for name in delivery_order:
        event_type, event_time = facts[name]
        _ingest(ledger, event_type=event_type, event_time=event_time)
    snapshot = _derive(ledger)
    assert snapshot.state is ClearPaymentStateV1.PAYMENT_CAPTURED
    assert snapshot.effective_payment_id == _PAYMENT_A


def test_captured_delivery_then_older_authorized_remains_captured(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _prepare(ledger)
    _ingest(ledger, event_type="payment.captured", event_time=300)
    _ingest(ledger, event_type="payment.authorized", event_time=200)
    assert _derive(ledger).state is ClearPaymentStateV1.PAYMENT_CAPTURED


def test_captured_evidence_dominates_a_later_failure_observation(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _prepare(ledger)
    _ingest(ledger, event_type="payment.captured", event_time=200)
    _ingest(ledger, event_type="payment.failed", event_time=300)
    assert _derive(ledger).state is ClearPaymentStateV1.PAYMENT_CAPTURED


def test_authorized_wins_same_provider_timestamp_tie_with_failure(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _prepare(ledger)
    _ingest(ledger, event_type="payment.failed", event_time=200)
    _ingest(ledger, event_type="payment.authorized", event_time=200)
    assert _derive(ledger).state is ClearPaymentStateV1.PAYMENT_AUTHORIZED


def test_multiple_failed_payment_attempts_are_valid(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _prepare(ledger)
    _ingest(ledger, event_type="payment.failed", event_time=200, payment_id=_PAYMENT_A)
    _ingest(ledger, event_type="payment.failed", event_time=300, payment_id=_PAYMENT_B)
    snapshot = _derive(ledger)
    assert snapshot.state is ClearPaymentStateV1.PAYMENT_FAILED_OBSERVED
    assert snapshot.effective_payment_id is None
    assert {item.provider_payment_id for item in snapshot.evidence} == {_PAYMENT_A, _PAYMENT_B}


def test_failed_attempt_a_and_captured_attempt_b_selects_b(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _prepare(ledger)
    _ingest(ledger, event_type="payment.failed", event_time=200, payment_id=_PAYMENT_A)
    _ingest(ledger, event_type="payment.captured", event_time=300, payment_id=_PAYMENT_B)
    snapshot = _derive(ledger)
    assert snapshot.state is ClearPaymentStateV1.PAYMENT_CAPTURED
    assert snapshot.effective_payment_id == _PAYMENT_B


def test_multiple_active_payments_fail_closed(ledger: SQLiteFinancialLedgerV1) -> None:
    _prepare(ledger)
    _ingest(ledger, event_type="payment.authorized", event_time=200, payment_id=_PAYMENT_A)
    _ingest(ledger, event_type="payment.captured", event_time=300, payment_id=_PAYMENT_B)
    _assert_error(PaymentStateFailureCode.MULTIPLE_ACTIVE_PAYMENTS, lambda: _derive(ledger))


@pytest.mark.parametrize(
    ("amount", "currency"),
    [(0, "INR"), (2_699, "INR"), (2_700, "USD")],
)
def test_authenticated_provider_fact_must_match_verified_economics(
    ledger: SQLiteFinancialLedgerV1,
    amount: int,
    currency: str,
) -> None:
    _prepare(ledger)
    if currency == "INR" and amount > 0:
        _ingest(
            ledger,
            event_type="payment.captured",
            event_time=200,
            amount=amount,
        )
    else:
        _append_manual_with_reference(
            ledger,
            _manual_event(index=30, amount=amount, currency=currency),
        )
    _assert_error(PaymentStateFailureCode.PAYMENT_ECONOMIC_MISMATCH, lambda: _derive(ledger))


def test_payment_account_must_match_trusted_application_configuration(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _prepare(ledger)
    _ingest(
        ledger,
        event_type="payment.captured",
        event_time=200,
        account_id=_OTHER_ACCOUNT_ID,
    )
    _assert_error(PaymentStateFailureCode.PAYMENT_ACCOUNT_MISMATCH, lambda: _derive(ledger))


def test_payment_order_must_match_unique_durable_order_reference(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _prepare(ledger)
    _append_manual_with_reference(
        ledger,
        _manual_event(index=31, order_id=_OTHER_ORDER_ID),
    )
    _assert_error(PaymentStateFailureCode.PAYMENT_ORDER_MISMATCH, lambda: _derive(ledger))


@pytest.mark.parametrize("trusted", [(), (_identity(2),)])
def test_certificate_verification_failure_occurs_before_ledger_reads(
    ledger: SQLiteFinancialLedgerV1,
    trusted: tuple[MerchantSigningIdentityV2, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ledger read occurred before certificate verification")

    monkeypatch.setattr(ledger, "get_execution_reservation", forbidden)
    _assert_error(
        PaymentStateFailureCode.CERTIFICATE_NOT_VERIFIED,
        lambda: _derive(ledger, trusted_identities=trusted),
    )


def test_altered_trusted_key_rejects_certificate_before_ledger_reads(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    altered = MerchantSigningIdentityV2(
        merchant_id=_identity(1).merchant_id,
        ed25519_public_key_hex=_identity(2).ed25519_public_key_hex,
    )

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("ledger read occurred before certificate verification")

    monkeypatch.setattr(ledger, "get_execution_reservation", forbidden)
    _assert_error(
        PaymentStateFailureCode.CERTIFICATE_NOT_VERIFIED,
        lambda: _derive(ledger, trusted_identities=(altered, _identity(2))),
    )


def test_tampered_allocation_is_not_payment_authority(ledger: SQLiteFinancialLedgerV1) -> None:
    line = _CERTIFICATE.allocation.lines[0]
    changed_line = _validated_copy(
        line,
        unit_payment=Money(amount_paise=line.unit_payment.amount_paise + 1),
        line_payment=Money(
            amount_paise=(line.unit_payment.amount_paise + 1) * line.allocated_quantity
        ),
    )
    changed_lines = (changed_line, *_CERTIFICATE.allocation.lines[1:])
    changed_total = sum(item.line_payment.amount_paise for item in changed_lines)
    changed_allocation = _validated_copy(
        _CERTIFICATE.allocation,
        lines=changed_lines,
        total_payment=Money(amount_paise=changed_total),
    )
    tampered = _validated_copy(_CERTIFICATE, allocation=changed_allocation)
    _assert_error(
        PaymentStateFailureCode.CERTIFICATE_NOT_VERIFIED,
        lambda: _derive(ledger, certificate=tampered),
    )


def test_verified_infeasible_allocation_is_not_executable(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    policy = _policy()
    allocation = AllocationClaimV2(
        market_id=policy.market_spec.market_id,
        buyer_policy_commitment_sha256=buyer_policy_v2_commitment(policy),
        status=AllocationClaimStatusV2.INFEASIBLE,
        fulfilled_quantity=0,
        total_payment=Money(amount_paise=0),
        soft_preference_unit_score=0,
        winner_count=0,
        lines=(),
    )
    certificate = _certificate(policy=policy, evidence=(), allocation=allocation)
    _assert_error(
        PaymentStateFailureCode.ALLOCATION_NOT_EXECUTABLE,
        lambda: _derive(ledger, certificate=certificate),
    )


def test_missing_execution_reservation_fails(ledger: SQLiteFinancialLedgerV1) -> None:
    _assert_error(PaymentStateFailureCode.EXECUTION_NOT_FOUND, lambda: _derive(ledger))


@pytest.mark.parametrize(
    "reservation",
    [
        _reservation(digest="8" * 64),
        _reservation(market_id="e5000000-0000-4000-8000-000000000001"),
    ],
)
def test_execution_reservation_must_bind_certificate_and_market(
    ledger: SQLiteFinancialLedgerV1,
    reservation: ExecutionReservationV1,
) -> None:
    _prepare(ledger, reservation=reservation, include_order=False)
    _assert_error(PaymentStateFailureCode.EXECUTION_BINDING_MISMATCH, lambda: _derive(ledger))


def test_execution_reservation_is_identity_binding_not_approval(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    old = _reservation().model_copy(update={"reserved_at": datetime(2000, 1, 1, tzinfo=UTC)})
    _prepare(ledger, reservation=old)
    snapshot = _derive(ledger)
    assert snapshot.state is ClearPaymentStateV1.ORDER_CREATED
    assert "reserved_at" not in type(snapshot).model_fields
    assert ledger.get_execution_reservation(_EXECUTION_ID) == old


def test_zero_order_references_fails(ledger: SQLiteFinancialLedgerV1) -> None:
    _prepare(ledger, include_order=False)
    _assert_error(PaymentStateFailureCode.ORDER_REFERENCE_MISSING, lambda: _derive(ledger))


def test_multiple_order_references_fail(ledger: SQLiteFinancialLedgerV1) -> None:
    _prepare(ledger)
    ledger.record_provider_reference(_reference(kind="order", reference_id=_OTHER_ORDER_ID))
    _assert_error(PaymentStateFailureCode.ORDER_REFERENCE_CONFLICT, lambda: _derive(ledger))


def test_noncanonical_razorpay_order_reference_fails_as_conflict(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _prepare(ledger, include_order=False)
    ledger.record_provider_reference(_reference(kind="order", reference_id="not-an-order"))
    _assert_error(PaymentStateFailureCode.ORDER_REFERENCE_CONFLICT, lambda: _derive(ledger))


def test_order_reference_after_1000_unrelated_references_is_found(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _prepare(ledger, include_order=False)
    for index in range(1_000):
        ledger.record_provider_reference(
            _reference(
                kind="unrelated",
                reference_id=f"filler-{index:04d}",
                provider_name="aaa",
            )
        )
    ledger.record_provider_reference(_reference(kind="order", reference_id=_ORDER_ID))
    assert _derive(ledger).state is ClearPaymentStateV1.ORDER_CREATED


def test_relevant_event_after_1000_unrelated_events_is_replayed(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _prepare(ledger)
    for index in range(1, 1_001):
        ledger.append_event(_unrelated_event(index))
    _ingest(ledger, event_type="payment.failed", event_time=200)
    snapshot = _derive(ledger)
    assert snapshot.state is ClearPaymentStateV1.PAYMENT_FAILED_OBSERVED
    assert snapshot.evidence[0].ledger_sequence_number == 1_001


@pytest.mark.parametrize(
    "event",
    [
        _manual_event(index=1, missing_field="raw_body_sha256"),
        _manual_event(index=2, extra_field=True),
        _manual_event(
            index=3,
            field_changes={
                "amount_paise": (FinancialLedgerValueType.STRING, "2700"),
            },
        ),
        _manual_event(
            index=4,
            field_changes={
                "provider_event_type": (FinancialLedgerValueType.STRING, "payment.failed"),
            },
        ),
        _manual_event(
            index=5,
            field_changes={
                "payment_status": (FinancialLedgerValueType.STRING, "authorized"),
            },
        ),
        _manual_event(
            index=6,
            field_changes={"captured": (FinancialLedgerValueType.BOOLEAN, False)},
        ),
        _manual_event(index=7, occurred_at=datetime(2026, 9, 4, 12, 0, tzinfo=UTC)),
        _manual_event(
            index=8,
            field_changes={
                "raw_body_digest_version": (FinancialLedgerValueType.STRING, "wrong"),
            },
        ),
        _manual_event(
            index=9,
            field_changes={
                "provider_payment_id": (FinancialLedgerValueType.STRING, "invalid"),
            },
        ),
        _manual_event(
            index=10,
            field_changes={
                "raw_body_sha256": (FinancialLedgerValueType.STRING, "A" * 64),
            },
        ),
    ],
)
def test_malformed_relevant_stored_evidence_fails_closed(
    ledger: SQLiteFinancialLedgerV1,
    event: FinancialLedgerEventV1,
) -> None:
    _prepare(ledger)
    ledger.append_event(event)
    _assert_error(PaymentStateFailureCode.PAYMENT_EVIDENCE_INVALID, lambda: _derive(ledger))


def test_evidence_without_payment_reference_fails(ledger: SQLiteFinancialLedgerV1) -> None:
    _prepare(ledger)
    ledger.append_event(_manual_event(index=20))
    _assert_error(PaymentStateFailureCode.PAYMENT_REFERENCE_MISSING, lambda: _derive(ledger))


def test_payment_reference_bound_to_another_execution_fails(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _prepare(ledger)
    ledger.reserve_execution(
        _reservation(
            execution_id=_OTHER_EXECUTION_ID,
            digest="7" * 64,
            market_id="e5000000-0000-4000-8000-000000000002",
        )
    )
    ledger.record_provider_reference(
        _reference(kind="payment", reference_id=_PAYMENT_A, execution_id=_OTHER_EXECUTION_ID)
    )
    ledger.append_event(_manual_event(index=21))
    _assert_error(PaymentStateFailureCode.PAYMENT_REFERENCE_CONFLICT, lambda: _derive(ledger))


def test_extra_payment_reference_without_completed_event_is_incomplete_ingress(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    _prepare(ledger)
    ledger.record_provider_reference(_reference(kind="payment", reference_id=_PAYMENT_A))
    _assert_error(PaymentStateFailureCode.INCOMPLETE_PAYMENT_INGRESS, lambda: _derive(ledger))


def test_read_only_derivation_calls_no_ledger_write_api(
    ledger: SQLiteFinancialLedgerV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare(ledger)
    marker = IdempotencyRecordV1(
        namespace="test.marker",
        idempotency_key="unchanged",
        request_fingerprint_sha256="6" * 64,
        execution_id=_EXECUTION_ID,
        recorded_at=_TIME,
    )
    ledger.claim_idempotency(marker)
    reservation_before = ledger.get_execution_reservation(_EXECUTION_ID)
    references_before = ledger.list_provider_references(_EXECUTION_ID, limit=1_000)
    events_before = ledger.list_events(_EXECUTION_ID, limit=1_000)
    idempotency_before = ledger.get_idempotency_record(
        namespace=marker.namespace,
        idempotency_key=marker.idempotency_key,
    )

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("payment-state replay attempted a ledger write")

    for name in (
        "reserve_execution",
        "claim_idempotency",
        "record_provider_reference",
        "append_event",
    ):
        monkeypatch.setattr(ledger, name, forbidden)

    assert _derive(ledger).state is ClearPaymentStateV1.ORDER_CREATED
    assert ledger.get_execution_reservation(_EXECUTION_ID) == reservation_before
    assert ledger.list_provider_references(_EXECUTION_ID, limit=1_000) == references_before
    assert ledger.list_events(_EXECUTION_ID, limit=1_000) == events_before
    assert (
        ledger.get_idempotency_record(
            namespace=marker.namespace,
            idempotency_key=marker.idempotency_key,
        )
        == idempotency_before
    )


@pytest.mark.parametrize(
    ("execution_id", "account_id"),
    [
        ("not-a-uuid", _ACCOUNT_ID),
        (_EXECUTION_ID, "acc_"),
        (_EXECUTION_ID, " acc_CLEARPRIMARY01"),
    ],
)
def test_explicit_application_inputs_are_strict(
    ledger: SQLiteFinancialLedgerV1,
    execution_id: str,
    account_id: str,
) -> None:
    with pytest.raises(ValueError):
        _derive(ledger, execution_id=execution_id, account_id=account_id)


def test_reducer_requires_exact_certificate_and_ledger_types(
    ledger: SQLiteFinancialLedgerV1,
) -> None:
    certificate_subclass = type("CertificateSubclass", (AllocationCertificateV2,), {})
    with pytest.raises(TypeError):
        _derive(ledger, certificate=certificate_subclass.model_construct(**_CERTIFICATE.__dict__))
    with pytest.raises(TypeError):
        derive_razorpay_payment_state_v1(
            certificate=_CERTIFICATE,
            trusted_signing_identities=_TRUSTED_IDENTITIES,
            execution_id=_EXECUTION_ID,
            expected_razorpay_account_id=_ACCOUNT_ID,
            ledger=object(),  # type: ignore[arg-type]
        )


def test_expected_account_input_limitation_is_documented() -> None:
    doc = derive_razorpay_payment_state_v1.__doc__ or ""
    assert "trusted explicit application configuration" in doc
    assert "not cryptographic proof of ownership" in doc
