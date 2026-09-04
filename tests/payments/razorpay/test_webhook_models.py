from enum import StrEnum
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

import clear_market.payments.razorpay as razorpay
from clear_market.domain import Currency, Money
from clear_market.payments.razorpay import (
    RAZORPAY_WEBHOOK_EVENT_V1_VERSION,
    RAZORPAY_WEBHOOK_INGRESS_V1_VERSION,
    RAZORPAY_WEBHOOK_RAW_BODY_DIGEST_V1_VERSION,
    RAZORPAY_WEBHOOK_RESULT_V1_VERSION,
    RazorpayWebhookDispositionV1,
    RazorpayWebhookEventTypeV1,
    RazorpayWebhookEventV1,
    RazorpayWebhookPaymentStatusV1,
    RazorpayWebhookResultV1,
)

_EXECUTION_ID = "e1000000-0000-4000-8000-000000000001"
_DIGEST = "a" * 64
_CONFIG = {
    "frozen": True,
    "extra": "forbid",
    "strict": True,
    "revalidate_instances": "always",
}


def _event(**changes: object) -> RazorpayWebhookEventV1:
    values: dict[str, object] = {
        "raw_body_sha256": _DIGEST,
        "provider_event_id": "provider-event-A",
        "provider_account_id": "acc_CLEARPRIMARY01",
        "event_type": RazorpayWebhookEventTypeV1.PAYMENT_CAPTURED,
        "execution_id": _EXECUTION_ID,
        "provider_order_id": "order_CLEARReview1",
        "provider_payment_id": "pay_CLEARReview1",
        "amount": Money(amount_paise=2_700),
        "payment_status": RazorpayWebhookPaymentStatusV1.CAPTURED,
        "captured": True,
        "provider_payment_created_at_unix": 1_788_262_190,
        "provider_event_created_at_unix": 1_788_262_200,
        **changes,
    }
    return RazorpayWebhookEventV1(**values)


def _result(**changes: object) -> RazorpayWebhookResultV1:
    values: dict[str, object] = {
        "disposition": RazorpayWebhookDispositionV1.RECORDED,
        "event": _event(),
        "ledger_sequence_number": 1,
        **changes,
    }
    return RazorpayWebhookResultV1(**values)


def test_versions_enums_and_public_api_extension_are_exact() -> None:
    assert RAZORPAY_WEBHOOK_INGRESS_V1_VERSION == "razorpay-webhook-ingress-v1"
    assert RAZORPAY_WEBHOOK_EVENT_V1_VERSION == "razorpay-webhook-event-v1"
    assert RAZORPAY_WEBHOOK_RESULT_V1_VERSION == "razorpay-webhook-result-v1"
    assert RAZORPAY_WEBHOOK_RAW_BODY_DIGEST_V1_VERSION == ("sha256-razorpay-webhook-raw-body-v1")
    assert issubclass(RazorpayWebhookEventTypeV1, StrEnum)
    assert tuple(RazorpayWebhookEventTypeV1) == (
        RazorpayWebhookEventTypeV1.PAYMENT_AUTHORIZED,
        RazorpayWebhookEventTypeV1.PAYMENT_CAPTURED,
        RazorpayWebhookEventTypeV1.PAYMENT_FAILED,
    )
    assert tuple(member.value for member in RazorpayWebhookEventTypeV1) == (
        "payment.authorized",
        "payment.captured",
        "payment.failed",
    )
    assert tuple(member.value for member in RazorpayWebhookPaymentStatusV1) == (
        "authorized",
        "captured",
        "failed",
    )
    assert tuple(member.value for member in RazorpayWebhookDispositionV1) == (
        "RECORDED",
        "DUPLICATE",
    )
    assert razorpay.__all__[-14:] == (
        "RAZORPAY_WEBHOOK_INGRESS_V1_VERSION",
        "RAZORPAY_WEBHOOK_EVENT_V1_VERSION",
        "RAZORPAY_WEBHOOK_RESULT_V1_VERSION",
        "RAZORPAY_WEBHOOK_RAW_BODY_DIGEST_V1_VERSION",
        "RazorpayWebhookVerificationConfigV1",
        "RazorpayWebhookEventTypeV1",
        "RazorpayWebhookPaymentStatusV1",
        "RazorpayWebhookDispositionV1",
        "RazorpayWebhookEventV1",
        "RazorpayWebhookResultV1",
        "RazorpayWebhookFailureCode",
        "RazorpayWebhookError",
        "razorpay_webhook_raw_body_digest_v1",
        "authenticate_and_record_razorpay_webhook_v1",
    )


@pytest.mark.parametrize(
    ("model_type", "fields"),
    [
        (
            RazorpayWebhookEventV1,
            (
                "schema_version",
                "razorpay_webhook_event_version",
                "raw_body_digest_version",
                "raw_body_sha256",
                "provider_event_id",
                "provider_account_id",
                "event_type",
                "execution_id",
                "provider_order_id",
                "provider_payment_id",
                "amount",
                "payment_status",
                "captured",
                "provider_payment_created_at_unix",
                "provider_event_created_at_unix",
            ),
        ),
        (
            RazorpayWebhookResultV1,
            (
                "schema_version",
                "razorpay_webhook_result_version",
                "ingress_version",
                "disposition",
                "event",
                "ledger_sequence_number",
            ),
        ),
    ],
)
def test_model_fields_and_configuration_are_exact(
    model_type: type[BaseModel],
    fields: tuple[str, ...],
) -> None:
    assert tuple(model_type.model_fields) == fields
    assert model_type.model_config == _CONFIG


@pytest.mark.parametrize("model", [_event(), _result()])
def test_models_are_frozen_versioned_and_forbid_extra(model: BaseModel) -> None:
    with pytest.raises(ValidationError):
        model.schema_version = "2"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        type(model).model_validate({**model.model_dump(), "extra": True})
    with pytest.raises(ValidationError):
        type(model).model_validate({**model.model_dump(), "schema_version": "2"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("raw_body_sha256", "A" * 64),
        ("raw_body_sha256", "a" * 63),
        ("provider_account_id", "ACC_CLEARPRIMARY01"),
        ("provider_account_id", "acc_0123456789ABCDE"),
        ("provider_order_id", "order_bad-id"),
        ("provider_payment_id", "pay_bad-id"),
        ("execution_id", "E1000000-0000-4000-8000-000000000001"),
    ],
)
def test_digest_account_order_payment_and_execution_ids_are_strict(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        _event(**{field: value})


@pytest.mark.parametrize("value", ["", "bad\x00id", "\ud800", "é" * 257, 1, None])
def test_provider_event_id_is_exact_bounded_utf8(value: object) -> None:
    with pytest.raises(ValidationError):
        _event(provider_event_id=value)


@pytest.mark.parametrize(
    "field", ["provider_payment_created_at_unix", "provider_event_created_at_unix"]
)
@pytest.mark.parametrize("value", [-1, True, 1.0, "1", 10**100])
def test_provider_unix_times_are_strict_nonnegative_and_convertible(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        _event(**{field: value})


def test_event_requires_fresh_exact_money() -> None:
    class MoneySubclass(Money):
        pass

    for amount in (
        {"amount_paise": 2_700, "currency": "INR"},
        MoneySubclass(amount_paise=2_700),
        Money.model_construct(currency=Currency.INR),
        Money.model_construct(amount_paise="2700", currency=Currency.INR),
    ):
        with pytest.raises(ValidationError):
            _event(amount=amount)


@pytest.mark.parametrize(
    ("event_type", "status", "captured"),
    [
        (
            RazorpayWebhookEventTypeV1.PAYMENT_AUTHORIZED,
            RazorpayWebhookPaymentStatusV1.AUTHORIZED,
            False,
        ),
        (
            RazorpayWebhookEventTypeV1.PAYMENT_CAPTURED,
            RazorpayWebhookPaymentStatusV1.CAPTURED,
            True,
        ),
        (
            RazorpayWebhookEventTypeV1.PAYMENT_FAILED,
            RazorpayWebhookPaymentStatusV1.FAILED,
            False,
        ),
    ],
)
def test_exact_event_status_captured_semantics_are_valid(
    event_type: RazorpayWebhookEventTypeV1,
    status: RazorpayWebhookPaymentStatusV1,
    captured: bool,
) -> None:
    assert (
        _event(event_type=event_type, payment_status=status, captured=captured).captured is captured
    )


@pytest.mark.parametrize(
    ("event_type", "status", "captured"),
    [
        (
            RazorpayWebhookEventTypeV1.PAYMENT_AUTHORIZED,
            RazorpayWebhookPaymentStatusV1.CAPTURED,
            False,
        ),
        (
            RazorpayWebhookEventTypeV1.PAYMENT_CAPTURED,
            RazorpayWebhookPaymentStatusV1.CAPTURED,
            False,
        ),
        (
            RazorpayWebhookEventTypeV1.PAYMENT_FAILED,
            RazorpayWebhookPaymentStatusV1.FAILED,
            True,
        ),
    ],
)
def test_inconsistent_event_status_captured_facts_are_rejected(
    event_type: RazorpayWebhookEventTypeV1,
    status: RazorpayWebhookPaymentStatusV1,
    captured: bool,
) -> None:
    with pytest.raises(ValidationError):
        _event(event_type=event_type, payment_status=status, captured=captured)


def test_result_requires_fresh_exact_event_and_positive_sequence() -> None:
    class EventSubclass(RazorpayWebhookEventV1):
        pass

    event = _event()
    for value in (
        event.model_dump(mode="python"),
        EventSubclass.model_construct(**event.__dict__),
        RazorpayWebhookEventV1.model_construct(),
    ):
        with pytest.raises(ValidationError):
            _result(event=value)
    for sequence in (0, -1, True, 1.0, "1"):
        with pytest.raises(ValidationError):
            _result(ledger_sequence_number=sequence)


def test_sanitized_model_documents_authentication_limit_and_excludes_sensitive_fields() -> None:
    doc = " ".join((RazorpayWebhookEventV1.__doc__ or "").split())
    assert "Direct construction does not prove signature verification" in doc
    assert "transport header" in doc
    forbidden = {
        "signature",
        "secret",
        "raw_body",
        "email",
        "contact",
        "notes",
        "bank",
        "wallet",
        "vpa",
        "error_description",
    }
    assert forbidden.isdisjoint(RazorpayWebhookEventV1.model_fields)


def test_enum_inputs_are_strict() -> None:
    with pytest.raises(ValidationError):
        _event(event_type="payment.captured")
    with pytest.raises(ValidationError):
        _event(payment_status="captured")
    with pytest.raises(ValidationError):
        _result(disposition="RECORDED")


def test_model_dump_is_sanitized_and_exact() -> None:
    dumped: dict[str, Any] = _result().model_dump(mode="json")
    assert tuple(dumped) == tuple(RazorpayWebhookResultV1.model_fields)
    assert dumped["event"]["amount"] == {"amount_paise": 2_700, "currency": "INR"}
