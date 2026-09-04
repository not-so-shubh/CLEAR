"""Strict sanitized models for authenticated Razorpay webhook observations."""

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from clear_market.domain import CanonicalUUID4, Currency, Money

RAZORPAY_WEBHOOK_INGRESS_V1_VERSION: Final[str] = "razorpay-webhook-ingress-v1"
RAZORPAY_WEBHOOK_EVENT_V1_VERSION: Final[str] = "razorpay-webhook-event-v1"
RAZORPAY_WEBHOOK_RESULT_V1_VERSION: Final[str] = "razorpay-webhook-result-v1"
RAZORPAY_WEBHOOK_RAW_BODY_DIGEST_V1_VERSION: Final[str] = "sha256-razorpay-webhook-raw-body-v1"

_SHA256_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
_ACCOUNT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"acc_[A-Za-z0-9]{1,14}", flags=re.ASCII)
_ORDER_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"order_[A-Za-z0-9]{1,128}", flags=re.ASCII)
_PAYMENT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"pay_[A-Za-z0-9]{1,128}", flags=re.ASCII)


def _pattern(value: object, pattern: re.Pattern[str], message: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError(message)
    return value


def _sha256(value: object) -> str:
    return _pattern(value, _SHA256_PATTERN, "digest must be lowercase SHA-256 hex")


def _account_id(value: object) -> str:
    return _pattern(value, _ACCOUNT_ID_PATTERN, "provider account ID is not canonical")


def _order_id(value: object) -> str:
    return _pattern(value, _ORDER_ID_PATTERN, "provider order ID is not canonical")


def _payment_id(value: object) -> str:
    return _pattern(value, _PAYMENT_ID_PATTERN, "provider payment ID is not canonical")


def _event_id(value: object) -> str:
    if type(value) is not str or "\x00" in value:
        raise ValueError("provider event ID must contain 1..512 valid UTF-8 bytes without NUL")
    try:
        length = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError:
        raise ValueError(
            "provider event ID must contain 1..512 valid UTF-8 bytes without NUL"
        ) from None
    if not 1 <= length <= 512:
        raise ValueError("provider event ID must contain 1..512 valid UTF-8 bytes without NUL")
    return value


def _unix_time(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("provider Unix time must be an exact nonnegative integer")
    try:
        datetime.fromtimestamp(value, tz=UTC)
    except (OSError, OverflowError, ValueError):
        raise ValueError("provider Unix time must be convertible to UTC") from None
    return value


def _fresh_money(value: object) -> Money:
    if type(value) is not Money:
        raise ValueError("amount must be a valid exact Money value")
    try:
        amount_paise = value.__dict__["amount_paise"]
        currency = value.__dict__["currency"]
    except (AttributeError, KeyError):
        raise ValueError("amount must be a valid exact Money value") from None
    if type(amount_paise) is not int or type(currency) is not Currency:
        raise ValueError("amount must be a valid exact Money value")
    try:
        return Money.model_validate(
            {"amount_paise": amount_paise, "currency": currency},
            strict=True,
        )
    except ValidationError:
        raise ValueError("amount must be a valid exact Money value") from None


def _fresh_event(value: object) -> "RazorpayWebhookEventV1":
    if type(value) is not RazorpayWebhookEventV1:
        raise ValueError("event must be a valid exact RazorpayWebhookEventV1")
    try:
        fields = {name: value.__dict__[name] for name in RazorpayWebhookEventV1.model_fields}
        return RazorpayWebhookEventV1.model_validate(fields)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError("event must be a valid exact RazorpayWebhookEventV1") from None


type _Sha256 = Annotated[str, BeforeValidator(_sha256)]
type _AccountId = Annotated[str, BeforeValidator(_account_id)]
type _OrderId = Annotated[str, BeforeValidator(_order_id)]
type _PaymentId = Annotated[str, BeforeValidator(_payment_id)]
type _EventId = Annotated[str, BeforeValidator(_event_id)]
type _UnixTime = Annotated[int, BeforeValidator(_unix_time)]
type _ExactMoney = Annotated[Money, BeforeValidator(_fresh_money)]


class RazorpayWebhookEventTypeV1(StrEnum):
    PAYMENT_AUTHORIZED = "payment.authorized"
    PAYMENT_CAPTURED = "payment.captured"
    PAYMENT_FAILED = "payment.failed"


class RazorpayWebhookPaymentStatusV1(StrEnum):
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"


class RazorpayWebhookDispositionV1(StrEnum):
    RECORDED = "RECORDED"
    DUPLICATE = "DUPLICATE"


class RazorpayWebhookEventV1(BaseModel):
    """Sanitized authenticated-body projection when returned by the ingress path.

    Direct construction does not prove signature verification. ``provider_event_id`` is delivery
    metadata from a transport header; Razorpay's documented HMAC authenticates the body, not that
    header.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    razorpay_webhook_event_version: Literal["razorpay-webhook-event-v1"] = (
        "razorpay-webhook-event-v1"
    )
    raw_body_digest_version: Literal["sha256-razorpay-webhook-raw-body-v1"] = (
        "sha256-razorpay-webhook-raw-body-v1"
    )
    raw_body_sha256: _Sha256
    provider_event_id: _EventId
    provider_account_id: _AccountId
    event_type: RazorpayWebhookEventTypeV1
    execution_id: CanonicalUUID4
    provider_order_id: _OrderId
    provider_payment_id: _PaymentId
    amount: _ExactMoney
    payment_status: RazorpayWebhookPaymentStatusV1
    captured: bool
    provider_payment_created_at_unix: _UnixTime
    provider_event_created_at_unix: _UnixTime

    @model_validator(mode="after")
    def _event_semantics(self) -> Self:
        expected = {
            RazorpayWebhookEventTypeV1.PAYMENT_AUTHORIZED: (
                RazorpayWebhookPaymentStatusV1.AUTHORIZED,
                False,
            ),
            RazorpayWebhookEventTypeV1.PAYMENT_CAPTURED: (
                RazorpayWebhookPaymentStatusV1.CAPTURED,
                True,
            ),
            RazorpayWebhookEventTypeV1.PAYMENT_FAILED: (
                RazorpayWebhookPaymentStatusV1.FAILED,
                False,
            ),
        }[self.event_type]
        if (self.payment_status, self.captured) != expected:
            raise ValueError("webhook event and payment facts are inconsistent")
        return self


class RazorpayWebhookResultV1(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    razorpay_webhook_result_version: Literal["razorpay-webhook-result-v1"] = (
        "razorpay-webhook-result-v1"
    )
    ingress_version: Literal["razorpay-webhook-ingress-v1"] = "razorpay-webhook-ingress-v1"
    disposition: RazorpayWebhookDispositionV1
    event: Annotated[RazorpayWebhookEventV1, BeforeValidator(_fresh_event)]
    ledger_sequence_number: Annotated[int, Field(strict=True, ge=1)]
