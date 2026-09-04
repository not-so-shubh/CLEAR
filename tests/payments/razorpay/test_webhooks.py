import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any, cast

import pytest

import clear_market.payments.razorpay.webhooks as webhooks_module
from clear_market.payments.razorpay import (
    RAZORPAY_WEBHOOK_RAW_BODY_DIGEST_V1_VERSION,
    RazorpayWebhookDispositionV1,
    RazorpayWebhookError,
    RazorpayWebhookEventTypeV1,
    RazorpayWebhookFailureCode,
    RazorpayWebhookPaymentStatusV1,
    RazorpayWebhookVerificationConfigV1,
    authenticate_and_record_razorpay_webhook_v1,
    razorpay_webhook_raw_body_digest_v1,
)
from clear_market.persistence import (
    ExecutionReservationV1,
    FinancialLedgerEventAppendDispositionV1,
    IdempotencyDispositionV1,
    IdempotencyRecordV1,
    ProviderReferenceV1,
    SQLiteFinancialLedgerV1,
    open_sqlite_financial_ledger_v1,
)

_SECRET = "clear-review-webhook-secret-v1"
_PREVIOUS_SECRET = "clear-review-webhook-secret-previous"
_ACCOUNT_ID = "acc_CLEARPRIMARY01"
_ORDER_ID = "order_CLEARReview1"
_PAYMENT_ID = "pay_CLEARReview1"
_EXECUTION_ID = "e1000000-0000-4000-8000-000000000001"
_OTHER_EXECUTION_ID = "e1000000-0000-4000-8000-000000000002"
_MARKET_ID = "b1000000-0000-4000-8000-000000000001"
_OTHER_MARKET_ID = "b1000000-0000-4000-8000-000000000002"
_RECEIVED_AT = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
_EVENT_CREATED_AT = 1_788_262_200
_PAYMENT_CREATED_AT = 1_788_262_190
_EVENT_ID = "provider-event-A"
_EVENT_ID_NAMESPACE = "razorpay.webhook.event-id.v1"
_RAW_BODY_NAMESPACE = "razorpay.webhook.raw-body.v1"

_CAPTURED_RAW_BODY = (
    b'{"account_id":"acc_CLEARPRIMARY01","contains":["payment"],'
    b'"created_at":1788262200,"entity":"event","event":"payment.captured",'
    b'"payload":{"payment":{"entity":{"amount":2700,"captured":true,'
    b'"created_at":1788262190,"currency":"INR","entity":"payment",'
    b'"id":"pay_CLEARReview1","order_id":"order_CLEARReview1",'
    b'"status":"captured"}}}}'
)
_CANDIDATE_WEBHOOK_RAW_BODY_BYTE_LENGTH = 327
_CANDIDATE_WEBHOOK_RAW_BODY_SHA256 = (
    "8bf6fb1b1b869afe78310390a846953fa9e62a97a4176c6d5004dd565a6d9894"
)
_CANDIDATE_WEBHOOK_HMAC_SHA256 = "4c6ce39c6e557297e3296d2097401c8cafe8e8699b87589a15e0c91d4806516b"


def _config(*secrets: str) -> RazorpayWebhookVerificationConfigV1:
    return RazorpayWebhookVerificationConfigV1(
        expected_account_id=_ACCOUNT_ID,
        secrets=secrets or (_SECRET,),
    )


def _signature(raw_body: bytes, secret: str = _SECRET) -> str:
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def _body(
    *,
    event_type: str = "payment.captured",
    status: str | None = None,
    captured: bool | None = None,
    event_created_at: object = _EVENT_CREATED_AT,
    payment_created_at: object = _PAYMENT_CREATED_AT,
    payment_id: object = _PAYMENT_ID,
    order_id: object = _ORDER_ID,
    amount: object = 2_700,
    currency: object = "INR",
    root_changes: dict[str, object] | None = None,
    payment_changes: dict[str, object] | None = None,
) -> bytes:
    defaults = {
        "payment.authorized": ("authorized", False),
        "payment.captured": ("captured", True),
        "payment.failed": ("failed", False),
    }
    default_status, default_captured = defaults.get(event_type, ("created", False))
    payment: dict[str, object] = {
        "amount": amount,
        "captured": default_captured if captured is None else captured,
        "created_at": payment_created_at,
        "currency": currency,
        "entity": "payment",
        "id": payment_id,
        "order_id": order_id,
        "status": default_status if status is None else status,
    }
    payment.update(payment_changes or {})
    root: dict[str, object] = {
        "account_id": _ACCOUNT_ID,
        "contains": ["payment"],
        "created_at": event_created_at,
        "entity": "event",
        "event": event_type,
        "payload": {"payment": {"entity": payment}},
    }
    root.update(root_changes or {})
    return json.dumps(root, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _reservation(
    execution_id: str = _EXECUTION_ID,
    market_id: str = _MARKET_ID,
) -> ExecutionReservationV1:
    suffix = 1 if execution_id == _EXECUTION_ID else 2
    return ExecutionReservationV1(
        execution_id=execution_id,
        certificate_digest_version="sha256-allocation-certificate-v2-clear-json-v1",
        certificate_digest_sha256=f"{suffix:064x}",
        market_id=market_id,
        execution_request_fingerprint_sha256=f"{suffix + 10:064x}",
        reserved_at=_RECEIVED_AT,
    )


def _prepare_ledger(
    ledger: SQLiteFinancialLedgerV1,
    *,
    include_order: bool = True,
) -> None:
    ledger.reserve_execution(_reservation())
    if include_order:
        ledger.record_provider_reference(
            ProviderReferenceV1(
                provider_name="razorpay",
                reference_kind="order",
                reference_id=_ORDER_ID,
                execution_id=_EXECUTION_ID,
                recorded_at=_RECEIVED_AT,
            )
        )


def _ingest(
    ledger: SQLiteFinancialLedgerV1,
    *,
    raw_body: bytes = _CAPTURED_RAW_BODY,
    signature_header: str | None = None,
    event_id_header: str = _EVENT_ID,
    verification_config: RazorpayWebhookVerificationConfigV1 | None = None,
    received_at: datetime = _RECEIVED_AT,
) -> Any:
    return authenticate_and_record_razorpay_webhook_v1(
        raw_body=raw_body,
        signature_header=(_signature(raw_body) if signature_header is None else signature_header),
        event_id_header=event_id_header,
        verification_config=verification_config or _config(),
        received_at=received_at,
        ledger=ledger,
    )


def _assert_error(
    code: RazorpayWebhookFailureCode,
    action: Any,
) -> RazorpayWebhookError:
    with pytest.raises(RazorpayWebhookError) as caught:
        action()
    assert caught.value.code is code
    assert str(caught.value) == code.value
    for private in (_SECRET, _ACCOUNT_ID, _ORDER_ID, _PAYMENT_ID, _EVENT_ID, "2700"):
        assert private not in str(caught.value)
    return caught.value


def _assert_no_ingress_writes(
    ledger: SQLiteFinancialLedgerV1,
    *,
    raw_body: bytes,
    event_id: str = _EVENT_ID,
) -> None:
    digest = hashlib.sha256(raw_body).hexdigest()
    assert (
        ledger.get_idempotency_record(
            namespace=_EVENT_ID_NAMESPACE,
            idempotency_key=event_id,
        )
        is None
    )
    assert (
        ledger.get_idempotency_record(
            namespace=_RAW_BODY_NAMESPACE,
            idempotency_key=digest,
        )
        is None
    )
    assert (
        ledger.get_provider_reference(
            provider_name="razorpay",
            reference_kind="payment",
            reference_id=_PAYMENT_ID,
        )
        is None
    )
    assert ledger.list_events(_EXECUTION_ID) == ()


def test_candidate_raw_body_exact_bytes_length_sha_and_hmac() -> None:
    assert _body() == _CAPTURED_RAW_BODY
    assert len(_CAPTURED_RAW_BODY) == _CANDIDATE_WEBHOOK_RAW_BODY_BYTE_LENGTH
    assert hashlib.sha256(_CAPTURED_RAW_BODY).hexdigest() == (_CANDIDATE_WEBHOOK_RAW_BODY_SHA256)
    assert _signature(_CAPTURED_RAW_BODY) == _CANDIDATE_WEBHOOK_HMAC_SHA256
    assert razorpay_webhook_raw_body_digest_v1(_CAPTURED_RAW_BODY) == (
        _CANDIDATE_WEBHOOK_RAW_BODY_SHA256
    )


def test_digest_is_exact_raw_bytes_only_and_grants_no_authentication() -> None:
    changed = _CAPTURED_RAW_BODY + b"\n"
    assert razorpay_webhook_raw_body_digest_v1(changed) == hashlib.sha256(changed).hexdigest()
    assert razorpay_webhook_raw_body_digest_v1(changed) != (
        razorpay_webhook_raw_body_digest_v1(_CAPTURED_RAW_BODY)
    )
    assert "no authentication" in (
        webhooks_module.razorpay_webhook_raw_body_digest_v1.__doc__ or ""
    )


@pytest.mark.parametrize("raw_body", [b"", b"x" * 1_048_577])
def test_raw_body_digest_applies_exact_size_bounds(raw_body: bytes) -> None:
    expected = (
        RazorpayWebhookFailureCode.RAW_BODY_TOO_LARGE
        if raw_body
        else RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD
    )
    _assert_error(expected, lambda: razorpay_webhook_raw_body_digest_v1(raw_body))


@pytest.mark.parametrize("raw_body", [bytearray(b"{}"), memoryview(b"{}"), "{}"])
def test_raw_body_requires_exact_bytes(raw_body: object) -> None:
    _assert_error(
        RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD,
        lambda: razorpay_webhook_raw_body_digest_v1(cast(Any, raw_body)),
    )


def test_exact_body_hmac_and_uppercase_signature_are_accepted(tmp_path: Path) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        result = _ingest(ledger, signature_header=_signature(_CAPTURED_RAW_BODY).upper())
    assert result.disposition is RazorpayWebhookDispositionV1.RECORDED


def test_one_whitespace_byte_change_with_old_signature_is_rejected(tmp_path: Path) -> None:
    changed = _CAPTURED_RAW_BODY + b"\n"
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        _assert_error(
            RazorpayWebhookFailureCode.INVALID_SIGNATURE,
            lambda: _ingest(
                ledger,
                raw_body=changed,
                signature_header=_signature(_CAPTURED_RAW_BODY),
            ),
        )
        _assert_no_ingress_writes(ledger, raw_body=changed)


@pytest.mark.parametrize("signature", ["", "0" * 63, "g" * 64, " 0" + "0" * 63, 1])
def test_signature_representation_is_exact(signature: object, tmp_path: Path) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        _assert_error(
            RazorpayWebhookFailureCode.INVALID_SIGNATURE,
            lambda: _ingest(ledger, signature_header=cast(Any, signature)),
        )
        _assert_no_ingress_writes(ledger, raw_body=_CAPTURED_RAW_BODY)


def test_invalid_signature_prevents_hostile_json_parser_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile = b"{not json"

    def parser_must_not_run(_raw_body: bytes) -> dict[str, object]:
        raise AssertionError("JSON parser ran before HMAC authentication")

    monkeypatch.setattr(webhooks_module, "_parse_json_object", parser_must_not_run)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        _assert_error(
            RazorpayWebhookFailureCode.INVALID_SIGNATURE,
            lambda: _ingest(ledger, raw_body=hostile, signature_header="0" * 64),
        )


@pytest.mark.parametrize("accepted_secret", [_SECRET, _PREVIOUS_SECRET])
def test_current_and_previous_rotated_secrets_verify(
    accepted_secret: str,
    tmp_path: Path,
) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        result = _ingest(
            ledger,
            signature_header=_signature(_CAPTURED_RAW_BODY, accepted_secret),
            verification_config=_config(_SECRET, _PREVIOUS_SECRET),
        )
    assert result.disposition is RazorpayWebhookDispositionV1.RECORDED


def test_rotated_secret_order_does_not_change_result_semantics(tmp_path: Path) -> None:
    results = []
    for index, secrets in enumerate(((_SECRET, _PREVIOUS_SECRET), (_PREVIOUS_SECRET, _SECRET))):
        with open_sqlite_financial_ledger_v1(str(tmp_path / f"ledger-{index}.db")) as ledger:
            _prepare_ledger(ledger)
            results.append(
                _ingest(
                    ledger,
                    verification_config=_config(*secrets),
                    signature_header=_signature(_CAPTURED_RAW_BODY, _PREVIOUS_SECRET),
                )
            )
    assert results[0] == results[1]


def test_wrong_rotated_secret_fails_without_disclosure(tmp_path: Path) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        error = _assert_error(
            RazorpayWebhookFailureCode.INVALID_SIGNATURE,
            lambda: _ingest(
                ledger,
                signature_header=_signature(_CAPTURED_RAW_BODY, "wrong-secret"),
                verification_config=_config(_SECRET, _PREVIOUS_SECRET),
            ),
        )
    assert _PREVIOUS_SECRET not in str(error)
    assert "wrong-secret" not in str(error)


def test_every_configured_secret_is_evaluated_even_when_first_matches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_signature = _signature(_CAPTURED_RAW_BODY)
    original_digest = hmac.digest
    evaluated: list[bytes] = []

    def observed_digest(key: bytes, msg: bytes, digest: str) -> bytes:
        evaluated.append(key)
        return original_digest(key, msg, digest)

    monkeypatch.setattr(webhooks_module.hmac, "digest", observed_digest)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        result = _ingest(
            ledger,
            signature_header=expected_signature,
            verification_config=_config(_SECRET, _PREVIOUS_SECRET),
        )
    assert result.disposition is RazorpayWebhookDispositionV1.RECORDED
    assert evaluated == [_SECRET.encode(), _PREVIOUS_SECRET.encode()]


@pytest.mark.parametrize("event_id", ["", "bad\x00id", "\ud800", "é" * 257, 1])
def test_event_id_header_is_exact_bounded_utf8_after_hmac(
    event_id: object,
    tmp_path: Path,
) -> None:
    malformed = b"{"
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        _assert_error(
            RazorpayWebhookFailureCode.INVALID_EVENT_ID,
            lambda: _ingest(
                ledger,
                raw_body=malformed,
                signature_header=_signature(malformed),
                event_id_header=cast(Any, event_id),
            ),
        )


def _hostile_bodies() -> tuple[bytes, ...]:
    missing_payment = _body(root_changes={"payload": {}})
    wrong_payment_container = _body(root_changes={"payload": {"payment": []}})
    invalid_payment_timestamp = _body(payment_created_at=10**100)
    invalid_event_timestamp = _body(event_created_at=10**100)
    return (
        b"\xff",
        _CAPTURED_RAW_BODY + b"\x00",
        b"{",
        b'{"entity":"event","entity":"event"}',
        (
            b'{"account_id":"acc_CLEARPRIMARY01","contains":["payment"],'
            b'"created_at":1788262200,"entity":"event","event":"payment.captured",'
            b'"payload":{"payment":{"entity":{"amount":2700,"amount":2700}}}}'
        ),
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":-Infinity}',
        b"[]",
        missing_payment,
        wrong_payment_container,
        _body(amount=True),
        _body(amount=2_700.0),
        _body(payment_changes={"entity": "order"}),
        _body(currency="USD"),
        _body(payment_id="payment_bad"),
        _body(order_id="order_bad-id"),
        _body(event_created_at=True),
        _body(payment_created_at=True),
        invalid_event_timestamp,
        invalid_payment_timestamp,
        _body(root_changes={"entity": "payment"}),
        _body(root_changes={"contains": []}),
    )


@pytest.mark.parametrize("raw_body", _hostile_bodies())
def test_validly_signed_hostile_json_fails_closed_without_persistence(
    raw_body: bytes,
    tmp_path: Path,
) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        _assert_error(
            RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD,
            lambda: _ingest(ledger, raw_body=raw_body),
        )
        _assert_no_ingress_writes(ledger, raw_body=raw_body)


def test_validly_signed_deep_json_recursion_fails_closed(tmp_path: Path) -> None:
    raw_body = b'{"nested":' + b"[" * 10_000 + b"0" + b"]" * 10_000 + b"}"
    assert len(raw_body) < 1_048_576
    with pytest.raises(RecursionError):
        json.loads(raw_body)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        _assert_error(
            RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD,
            lambda: _ingest(ledger, raw_body=raw_body),
        )
        _assert_no_ingress_writes(ledger, raw_body=raw_body)


def test_validly_signed_integer_conversion_value_error_fails_closed(tmp_path: Path) -> None:
    raw_body = b'{"integer":' + b"9" * 5_000 + b"}"
    assert len(raw_body) < 1_048_576
    with pytest.raises(ValueError):
        json.loads(raw_body)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        _assert_error(
            RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD,
            lambda: _ingest(ledger, raw_body=raw_body),
        )
        _assert_no_ingress_writes(ledger, raw_body=raw_body)


def test_account_mismatch_precedes_supported_event_and_writes_nothing(tmp_path: Path) -> None:
    raw_body = _body(
        event_type="order.paid",
        root_changes={"account_id": "acc_OTHER00000001"},
    )
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        _assert_error(
            RazorpayWebhookFailureCode.ACCOUNT_MISMATCH, lambda: _ingest(ledger, raw_body=raw_body)
        )
        _assert_no_ingress_writes(ledger, raw_body=raw_body)


def test_unsupported_event_writes_nothing(tmp_path: Path) -> None:
    raw_body = _body(event_type="order.paid")
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        _assert_error(
            RazorpayWebhookFailureCode.UNSUPPORTED_EVENT, lambda: _ingest(ledger, raw_body=raw_body)
        )
        _assert_no_ingress_writes(ledger, raw_body=raw_body)


@pytest.mark.parametrize(
    ("event_type", "status", "captured"),
    [
        ("payment.authorized", "authorized", False),
        ("payment.captured", "captured", True),
        ("payment.failed", "failed", False),
    ],
)
def test_supported_event_semantics_are_independently_recorded(
    event_type: str,
    status: str,
    captured: bool,
    tmp_path: Path,
) -> None:
    raw_body = _body(event_type=event_type, status=status, captured=captured)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        result = _ingest(ledger, raw_body=raw_body)
        persisted = ledger.list_events(_EXECUTION_ID)
    assert result.disposition is RazorpayWebhookDispositionV1.RECORDED
    assert result.event.event_type.value == event_type
    assert result.event.payment_status.value == status
    assert result.event.captured is captured
    assert len(persisted) == 1


@pytest.mark.parametrize(
    ("event_type", "status", "captured"),
    [
        ("payment.authorized", "captured", False),
        ("payment.authorized", "authorized", True),
        ("payment.captured", "authorized", True),
        ("payment.captured", "captured", False),
        ("payment.failed", "captured", False),
        ("payment.failed", "failed", True),
    ],
)
def test_event_status_and_captured_mismatch_is_invalid_payload(
    event_type: str,
    status: str,
    captured: bool,
    tmp_path: Path,
) -> None:
    raw_body = _body(event_type=event_type, status=status, captured=captured)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        _assert_error(
            RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD,
            lambda: _ingest(ledger, raw_body=raw_body),
        )
        _assert_no_ingress_writes(ledger, raw_body=raw_body)


def test_unknown_order_reference_writes_no_financial_history(tmp_path: Path) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger, include_order=False)
        _assert_error(RazorpayWebhookFailureCode.UNKNOWN_ORDER_REFERENCE, lambda: _ingest(ledger))
        _assert_no_ingress_writes(ledger, raw_body=_CAPTURED_RAW_BODY)


def test_standard_duplicate_is_successful_and_idempotent(tmp_path: Path) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        first = _ingest(ledger)
        second = _ingest(ledger)
        events = ledger.list_events(_EXECUTION_ID)
        payment_references = tuple(
            reference
            for reference in ledger.list_provider_references(_EXECUTION_ID)
            if reference.reference_kind == "payment"
        )
    assert first.disposition is RazorpayWebhookDispositionV1.RECORDED
    assert second.disposition is RazorpayWebhookDispositionV1.DUPLICATE
    assert first.ledger_sequence_number == second.ledger_sequence_number == 1
    assert len(events) == 1
    assert len(payment_references) == 1


def test_changed_unsigned_event_id_cannot_bypass_raw_body_dedupe(tmp_path: Path) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        first = _ingest(ledger, event_id_header="provider-event-A")
        second = _ingest(ledger, event_id_header="provider-event-B")
        events = ledger.list_events(_EXECUTION_ID)
        first_claim = ledger.get_idempotency_record(
            namespace=_EVENT_ID_NAMESPACE,
            idempotency_key="provider-event-A",
        )
        second_claim = ledger.get_idempotency_record(
            namespace=_EVENT_ID_NAMESPACE,
            idempotency_key="provider-event-B",
        )
        body_claim = ledger.get_idempotency_record(
            namespace=_RAW_BODY_NAMESPACE,
            idempotency_key=_CANDIDATE_WEBHOOK_RAW_BODY_SHA256,
        )
    assert first.disposition is RazorpayWebhookDispositionV1.RECORDED
    assert second.disposition is RazorpayWebhookDispositionV1.DUPLICATE
    assert first.ledger_sequence_number == second.ledger_sequence_number
    assert len(events) == 1
    assert first_claim is not None and second_claim is not None and body_claim is not None
    assert events[0].event.fields == events[0].event.fields
    assert all(field.field_key != "provider_event_id" for field in events[0].event.fields)


def test_event_id_conflict_stops_second_body_before_body_claim_or_payment_reference(
    tmp_path: Path,
) -> None:
    changed = _body(
        payment_id="pay_CLEARReview2",
        event_created_at=_EVENT_CREATED_AT + 1,
    )
    changed_digest = hashlib.sha256(changed).hexdigest()
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        _ingest(ledger)
        _assert_error(
            RazorpayWebhookFailureCode.EVENT_ID_CONFLICT,
            lambda: _ingest(ledger, raw_body=changed),
        )
        assert (
            ledger.get_idempotency_record(
                namespace=_RAW_BODY_NAMESPACE,
                idempotency_key=changed_digest,
            )
            is None
        )
        assert (
            ledger.get_provider_reference(
                provider_name="razorpay",
                reference_kind="payment",
                reference_id="pay_CLEARReview2",
            )
            is None
        )
        assert len(ledger.list_events(_EXECUTION_ID)) == 1


def test_preexisting_raw_body_claim_for_another_execution_is_a_body_conflict(
    tmp_path: Path,
) -> None:
    digest = hashlib.sha256(_CAPTURED_RAW_BODY).hexdigest()
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        ledger.reserve_execution(_reservation(_OTHER_EXECUTION_ID, _OTHER_MARKET_ID))
        assert (
            ledger.claim_idempotency(
                IdempotencyRecordV1(
                    namespace=_RAW_BODY_NAMESPACE,
                    idempotency_key=digest,
                    request_fingerprint_sha256=digest,
                    execution_id=_OTHER_EXECUTION_ID,
                    recorded_at=_RECEIVED_AT,
                )
            ).disposition
            is IdempotencyDispositionV1.CREATED
        )
        _assert_error(
            RazorpayWebhookFailureCode.WEBHOOK_BODY_CONFLICT,
            lambda: _ingest(ledger),
        )
        assert (
            ledger.get_provider_reference(
                provider_name="razorpay",
                reference_kind="payment",
                reference_id=_PAYMENT_ID,
            )
            is None
        )
        assert ledger.list_events(_EXECUTION_ID) == ()


def test_preexisting_payment_reference_conflict_precedes_dedupe(tmp_path: Path) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        ledger.reserve_execution(_reservation(_OTHER_EXECUTION_ID, _OTHER_MARKET_ID))
        ledger.record_provider_reference(
            ProviderReferenceV1(
                provider_name="razorpay",
                reference_kind="payment",
                reference_id=_PAYMENT_ID,
                execution_id=_OTHER_EXECUTION_ID,
                recorded_at=_RECEIVED_AT,
            )
        )
        _assert_error(
            RazorpayWebhookFailureCode.PAYMENT_REFERENCE_CONFLICT,
            lambda: _ingest(ledger),
        )
        assert (
            ledger.get_idempotency_record(
                namespace=_EVENT_ID_NAMESPACE,
                idempotency_key=_EVENT_ID,
            )
            is None
        )
        assert (
            ledger.get_idempotency_record(
                namespace=_RAW_BODY_NAMESPACE,
                idempotency_key=_CANDIDATE_WEBHOOK_RAW_BODY_SHA256,
            )
            is None
        )
        assert ledger.list_events(_EXECUTION_ID) == ()


def test_payment_failed_then_captured_are_both_immutable_observations(tmp_path: Path) -> None:
    failed = _body(event_type="payment.failed", event_created_at=_EVENT_CREATED_AT)
    captured = _body(event_type="payment.captured", event_created_at=_EVENT_CREATED_AT + 1)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        failed_result = _ingest(ledger, raw_body=failed, event_id_header="event-failed")
        captured_result = _ingest(ledger, raw_body=captured, event_id_header="event-captured")
        events = ledger.list_events(_EXECUTION_ID)
    assert failed_result.disposition is RazorpayWebhookDispositionV1.RECORDED
    assert captured_result.disposition is RazorpayWebhookDispositionV1.RECORDED
    assert [persisted.event.event_type for persisted in events] == [
        "razorpay.webhook.payment_failed.v1",
        "razorpay.webhook.payment_captured.v1",
    ]


def test_captured_then_authorized_are_not_rejected_by_arrival_order(tmp_path: Path) -> None:
    captured = _body(event_type="payment.captured", event_created_at=_EVENT_CREATED_AT)
    authorized = _body(event_type="payment.authorized", event_created_at=_EVENT_CREATED_AT - 10)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        first = _ingest(ledger, raw_body=captured, event_id_header="event-captured")
        second = _ingest(ledger, raw_body=authorized, event_id_header="event-authorized")
        events = ledger.list_events(_EXECUTION_ID)
    assert first.disposition is second.disposition is RazorpayWebhookDispositionV1.RECORDED
    assert len(events) == 2


def test_exact_idempotency_payment_reference_and_financial_event_are_recorded(
    tmp_path: Path,
) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        result = _ingest(ledger)
        event_claim = ledger.get_idempotency_record(
            namespace=_EVENT_ID_NAMESPACE,
            idempotency_key=_EVENT_ID,
        )
        body_claim = ledger.get_idempotency_record(
            namespace=_RAW_BODY_NAMESPACE,
            idempotency_key=result.event.raw_body_sha256,
        )
        payment_reference = ledger.get_provider_reference(
            provider_name="razorpay",
            reference_kind="payment",
            reference_id=_PAYMENT_ID,
        )
        persisted = ledger.list_events(_EXECUTION_ID)[0]
    assert event_claim == IdempotencyRecordV1(
        namespace=_EVENT_ID_NAMESPACE,
        idempotency_key=_EVENT_ID,
        request_fingerprint_sha256=_CANDIDATE_WEBHOOK_RAW_BODY_SHA256,
        execution_id=_EXECUTION_ID,
        recorded_at=_RECEIVED_AT,
    )
    assert body_claim == IdempotencyRecordV1(
        namespace=_RAW_BODY_NAMESPACE,
        idempotency_key=_CANDIDATE_WEBHOOK_RAW_BODY_SHA256,
        request_fingerprint_sha256=_CANDIDATE_WEBHOOK_RAW_BODY_SHA256,
        execution_id=_EXECUTION_ID,
        recorded_at=_RECEIVED_AT,
    )
    assert payment_reference == ProviderReferenceV1(
        provider_name="razorpay",
        reference_kind="payment",
        reference_id=_PAYMENT_ID,
        execution_id=_EXECUTION_ID,
        recorded_at=_RECEIVED_AT,
    )
    assert persisted.sequence_number == result.ledger_sequence_number == 1
    assert persisted.event.occurred_at == datetime.fromtimestamp(_EVENT_CREATED_AT, tz=UTC)
    assert tuple(field.field_key for field in persisted.event.fields) == (
        "amount_paise",
        "captured",
        "currency",
        "payment_status",
        "provider_account_id",
        "provider_event_created_at_unix",
        "provider_event_type",
        "provider_order_id",
        "provider_payment_created_at_unix",
        "provider_payment_id",
        "raw_body_digest_version",
        "raw_body_sha256",
    )
    values = {field.field_key: field.value for field in persisted.event.fields}
    assert values == {
        "amount_paise": 2_700,
        "captured": True,
        "currency": "INR",
        "payment_status": "captured",
        "provider_account_id": _ACCOUNT_ID,
        "provider_event_created_at_unix": _EVENT_CREATED_AT,
        "provider_event_type": "payment.captured",
        "provider_order_id": _ORDER_ID,
        "provider_payment_created_at_unix": _PAYMENT_CREATED_AT,
        "provider_payment_id": _PAYMENT_ID,
        "raw_body_digest_version": RAZORPAY_WEBHOOK_RAW_BODY_DIGEST_V1_VERSION,
        "raw_body_sha256": _CANDIDATE_WEBHOOK_RAW_BODY_SHA256,
    }


def test_precreated_claims_continue_crash_repair_to_first_event(tmp_path: Path) -> None:
    digest = hashlib.sha256(_CAPTURED_RAW_BODY).hexdigest()
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        for namespace, key in (
            (_EVENT_ID_NAMESPACE, _EVENT_ID),
            (_RAW_BODY_NAMESPACE, digest),
        ):
            assert (
                ledger.claim_idempotency(
                    IdempotencyRecordV1(
                        namespace=namespace,
                        idempotency_key=key,
                        request_fingerprint_sha256=digest,
                        execution_id=_EXECUTION_ID,
                        recorded_at=_RECEIVED_AT,
                    )
                ).disposition
                is IdempotencyDispositionV1.CREATED
            )
        result = _ingest(ledger)
        payment = ledger.get_provider_reference(
            provider_name="razorpay",
            reference_kind="payment",
            reference_id=_PAYMENT_ID,
        )
        events = ledger.list_events(_EXECUTION_ID)
    assert result.disposition is RazorpayWebhookDispositionV1.RECORDED
    assert payment is not None
    assert len(events) == 1


def test_ledger_event_conflict_fails_closed(tmp_path: Path) -> None:
    digest = hashlib.sha256(_CAPTURED_RAW_BODY).hexdigest()
    event_id = webhooks_module._body_event_id(digest)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        conflicting = webhooks_module.FinancialLedgerEventV1(
            event_id=event_id,
            execution_id=_EXECUTION_ID,
            event_type="razorpay.webhook.payment_captured.v1",
            occurred_at=datetime.fromtimestamp(_EVENT_CREATED_AT, tz=UTC),
            fields=(),
        )
        assert ledger.append_event(conflicting).disposition is (
            FinancialLedgerEventAppendDispositionV1.CREATED
        )
        _assert_error(RazorpayWebhookFailureCode.LOCAL_EVENT_CONFLICT, lambda: _ingest(ledger))


def test_sensitive_provider_payload_fields_are_never_projected_or_persisted(tmp_path: Path) -> None:
    sensitive_values = {
        "email": "private@example.com",
        "contact": "+910000000000",
        "notes": {"secret": "private-note"},
        "bank": "private-bank",
        "wallet": "private-wallet",
        "vpa": "private@upi",
        "error_description": "private-error",
        "card": {"last4": "1234"},
    }
    raw_body = _body(payment_changes=sensitive_values)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        result = _ingest(ledger, raw_body=raw_body)
        persisted = ledger.list_events(_EXECUTION_ID)[0]
    result_text = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    persisted_text = repr(persisted)
    for value in (
        "private@example.com",
        "+910000000000",
        "private-note",
        "private-bank",
        "private-wallet",
        "private@upi",
        "private-error",
        "1234",
    ):
        assert value not in result_text
        assert value not in persisted_text
    assert "raw_body" not in type(result.event).model_fields
    assert "provider_event_id" not in {field.field_key for field in persisted.event.fields}


def test_received_at_is_explicit_utc_observation_time_not_provider_event_time(
    tmp_path: Path,
) -> None:
    offset_time = datetime(2026, 9, 4, 17, 30, tzinfo=UTC) + timedelta(hours=1)
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        result = _ingest(ledger, received_at=offset_time)
        claim = ledger.get_idempotency_record(
            namespace=_EVENT_ID_NAMESPACE,
            idempotency_key=_EVENT_ID,
        )
        persisted = ledger.list_events(_EXECUTION_ID)[0]
    assert result.disposition is RazorpayWebhookDispositionV1.RECORDED
    assert claim is not None and claim.recorded_at == offset_time
    assert persisted.event.occurred_at == datetime.fromtimestamp(_EVENT_CREATED_AT, tz=UTC)
    assert "received_at" not in {field.field_key for field in persisted.event.fields}


@pytest.mark.parametrize("received_at", [datetime(2026, 9, 4, 12), "2026-09-04T12:00:00Z", None])
def test_received_at_must_be_an_aware_datetime(received_at: object, tmp_path: Path) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        with pytest.raises(ValueError, match=r"^received_at must be an aware datetime$"):
            _ingest(ledger, received_at=cast(Any, received_at))
        _assert_no_ingress_writes(ledger, raw_body=_CAPTURED_RAW_BODY)


def test_concurrent_identical_delivery_records_one_event(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        _prepare_ledger(ledger)
    barrier = Barrier(2)

    def run() -> Any:
        barrier.wait()
        with open_sqlite_financial_ledger_v1(str(path)) as ledger:
            return _ingest(ledger)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _index: run(), range(2)))
    assert sorted(result.disposition.value for result in results) == ["DUPLICATE", "RECORDED"]
    assert results[0].ledger_sequence_number == results[1].ledger_sequence_number
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        assert len(ledger.list_events(_EXECUTION_ID)) == 1
        assert (
            len(
                tuple(
                    reference
                    for reference in ledger.list_provider_references(_EXECUTION_ID)
                    if reference.reference_kind == "payment"
                )
            )
            == 1
        )


def test_concurrent_same_body_changed_event_ids_records_one_event(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        _prepare_ledger(ledger)
    barrier = Barrier(2)

    def run(event_id: str) -> Any:
        barrier.wait()
        with open_sqlite_financial_ledger_v1(str(path)) as ledger:
            return _ingest(ledger, event_id_header=event_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(run, ("provider-event-A", "provider-event-B")))
    assert sorted(result.disposition.value for result in results) == ["DUPLICATE", "RECORDED"]
    with open_sqlite_financial_ledger_v1(str(path)) as ledger:
        assert len(ledger.list_events(_EXECUTION_ID)) == 1


def test_error_enum_order_message_and_read_only_code_are_exact() -> None:
    expected = (
        "RAW_BODY_TOO_LARGE",
        "INVALID_SIGNATURE",
        "INVALID_EVENT_ID",
        "INVALID_WEBHOOK_PAYLOAD",
        "ACCOUNT_MISMATCH",
        "UNSUPPORTED_EVENT",
        "UNKNOWN_ORDER_REFERENCE",
        "PAYMENT_REFERENCE_CONFLICT",
        "EVENT_ID_CONFLICT",
        "WEBHOOK_BODY_CONFLICT",
        "LOCAL_EVENT_CONFLICT",
    )
    assert tuple(member.name for member in RazorpayWebhookFailureCode) == expected
    assert tuple(member.value for member in RazorpayWebhookFailureCode) == expected
    error = RazorpayWebhookError(RazorpayWebhookFailureCode.INVALID_SIGNATURE)
    assert error.code is RazorpayWebhookFailureCode.INVALID_SIGNATURE
    assert str(error) == "INVALID_SIGNATURE"
    with pytest.raises(AttributeError):
        error.code = RazorpayWebhookFailureCode.INVALID_WEBHOOK_PAYLOAD  # type: ignore[misc]


def test_result_dump_is_sanitized_exact_and_has_no_state_transition(tmp_path: Path) -> None:
    with open_sqlite_financial_ledger_v1(str(tmp_path / "ledger.db")) as ledger:
        _prepare_ledger(ledger)
        result = _ingest(ledger)
    assert result.model_dump(mode="json") == {
        "schema_version": "1",
        "razorpay_webhook_result_version": "razorpay-webhook-result-v1",
        "ingress_version": "razorpay-webhook-ingress-v1",
        "disposition": "RECORDED",
        "event": {
            "schema_version": "1",
            "razorpay_webhook_event_version": "razorpay-webhook-event-v1",
            "raw_body_digest_version": "sha256-razorpay-webhook-raw-body-v1",
            "raw_body_sha256": _CANDIDATE_WEBHOOK_RAW_BODY_SHA256,
            "provider_event_id": _EVENT_ID,
            "provider_account_id": _ACCOUNT_ID,
            "event_type": "payment.captured",
            "execution_id": _EXECUTION_ID,
            "provider_order_id": _ORDER_ID,
            "provider_payment_id": _PAYMENT_ID,
            "amount": {"amount_paise": 2_700, "currency": "INR"},
            "payment_status": "captured",
            "captured": True,
            "provider_payment_created_at_unix": _PAYMENT_CREATED_AT,
            "provider_event_created_at_unix": _EVENT_CREATED_AT,
        },
        "ledger_sequence_number": 1,
    }
    assert result.event.event_type is RazorpayWebhookEventTypeV1.PAYMENT_CAPTURED
    assert result.event.payment_status is RazorpayWebhookPaymentStatusV1.CAPTURED
    forbidden = {"clear_payment_state", "terminal", "settled", "authorized_transition"}
    assert forbidden.isdisjoint(result.model_dump())
