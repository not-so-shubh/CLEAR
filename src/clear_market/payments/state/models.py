"""Strict immutable payment evidence and deterministic replay snapshots."""

import re
from datetime import UTC, datetime
from enum import StrEnum
from itertools import pairwise
from typing import Annotated, Final, Literal, Self, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from clear_market.domain import CanonicalUUID4, Currency, Money, UTCDateTime
from clear_market.payments.razorpay.webhook_models import (
    RazorpayWebhookEventTypeV1,
    RazorpayWebhookPaymentStatusV1,
)

CLEAR_PAYMENT_STATE_MACHINE_V1_VERSION: Final[str] = "clear-payment-state-machine-v1"
CLEAR_PAYMENT_STATE_SNAPSHOT_V1_VERSION: Final[str] = "clear-payment-state-snapshot-v1"
RAZORPAY_PAYMENT_EVIDENCE_V1_VERSION: Final[str] = "razorpay-payment-evidence-v1"

_SHA256_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)
_ACCOUNT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"acc_[A-Za-z0-9]{1,14}",
    flags=re.ASCII,
)
_ORDER_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"order_[A-Za-z0-9]{1,128}",
    flags=re.ASCII,
)
_PAYMENT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"pay_[A-Za-z0-9]{1,128}",
    flags=re.ASCII,
)

type _RelevantLedgerEventType = Literal[
    "razorpay.webhook.payment_authorized.v1",
    "razorpay.webhook.payment_captured.v1",
    "razorpay.webhook.payment_failed.v1",
]


def _validate_pattern(value: object, pattern: re.Pattern[str], message: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError(message)
    return value


def _validate_sha256(value: object) -> str:
    return _validate_pattern(value, _SHA256_PATTERN, "digest must be lowercase SHA-256 hex")


def _validate_account_id(value: object) -> str:
    return _validate_pattern(value, _ACCOUNT_ID_PATTERN, "provider account ID is not canonical")


def _validate_order_id(value: object) -> str:
    return _validate_pattern(value, _ORDER_ID_PATTERN, "provider order ID is not canonical")


def _validate_payment_id(value: object) -> str:
    return _validate_pattern(value, _PAYMENT_ID_PATTERN, "provider payment ID is not canonical")


def _validate_optional_payment_id(value: object) -> str | None:
    return None if value is None else _validate_payment_id(value)


def _validate_unix_time(value: object) -> int:
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


def _fresh_evidence(value: object) -> "RazorpayPaymentEvidenceV1":
    if type(value) is not RazorpayPaymentEvidenceV1:
        raise ValueError("evidence must be a valid exact RazorpayPaymentEvidenceV1")
    try:
        fields = {name: value.__dict__[name] for name in RazorpayPaymentEvidenceV1.model_fields}
        return RazorpayPaymentEvidenceV1.model_validate(fields)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError("evidence must be a valid exact RazorpayPaymentEvidenceV1") from None


def _fresh_evidence_tuple(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("evidence must be supplied as an exact tuple")
    return tuple(_fresh_evidence(item) for item in cast(tuple[object, ...], value))


type _Sha256 = Annotated[str, BeforeValidator(_validate_sha256)]
type _AccountId = Annotated[str, BeforeValidator(_validate_account_id)]
type _OrderId = Annotated[str, BeforeValidator(_validate_order_id)]
type _PaymentId = Annotated[str, BeforeValidator(_validate_payment_id)]
type _OptionalPaymentId = Annotated[str | None, BeforeValidator(_validate_optional_payment_id)]
type _UnixTime = Annotated[int, BeforeValidator(_validate_unix_time)]
type _ExactMoney = Annotated[Money, BeforeValidator(_fresh_money)]
type _EvidenceTuple = Annotated[
    tuple["RazorpayPaymentEvidenceV1", ...],
    BeforeValidator(_fresh_evidence_tuple),
]


class ClearPaymentStateV1(StrEnum):
    """Replay states; PAYMENT_FAILED_OBSERVED is deliberately nonterminal."""

    ORDER_CREATED = "ORDER_CREATED"
    PAYMENT_FAILED_OBSERVED = "PAYMENT_FAILED_OBSERVED"
    PAYMENT_AUTHORIZED = "PAYMENT_AUTHORIZED"
    PAYMENT_CAPTURED = "PAYMENT_CAPTURED"


class RazorpayPaymentEvidenceV1(BaseModel):
    """One strict reconstruction of an authenticated immutable 22A ledger observation."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    razorpay_payment_evidence_version: Literal["razorpay-payment-evidence-v1"] = (
        "razorpay-payment-evidence-v1"
    )
    ledger_sequence_number: Annotated[int, Field(strict=True, ge=1)]
    ledger_event_id: CanonicalUUID4
    execution_id: CanonicalUUID4
    ledger_event_type: _RelevantLedgerEventType
    occurred_at: UTCDateTime
    raw_body_digest_version: Literal["sha256-razorpay-webhook-raw-body-v1"]
    raw_body_sha256: _Sha256
    provider_account_id: _AccountId
    webhook_event_type: RazorpayWebhookEventTypeV1
    provider_order_id: _OrderId
    provider_payment_id: _PaymentId
    amount: _ExactMoney
    payment_status: RazorpayWebhookPaymentStatusV1
    captured: bool
    provider_payment_created_at_unix: _UnixTime
    provider_event_created_at_unix: _UnixTime

    @model_validator(mode="after")
    def _validate_event_semantics(self) -> Self:
        expected = {
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
        }[self.webhook_event_type]
        if (self.ledger_event_type, self.payment_status, self.captured) != expected:
            raise ValueError("payment evidence event semantics are inconsistent")
        expected_occurred_at = datetime.fromtimestamp(
            self.provider_event_created_at_unix,
            tz=UTC,
        )
        if self.occurred_at != expected_occurred_at:
            raise ValueError("payment evidence occurrence time is inconsistent")
        return self


class ClearPaymentStateSnapshotV1(BaseModel):
    """A deterministic interpretation of authenticated immutable payment observations.

    This snapshot is not Money Governor authorization and is not sufficient authority to capture,
    transfer, refund, reverse, fulfill, or settle money. Future money-moving code must
    replay/revalidate the required current evidence and authorization rather than trusting direct
    construction of this snapshot.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    clear_payment_state_snapshot_version: Literal["clear-payment-state-snapshot-v1"] = (
        "clear-payment-state-snapshot-v1"
    )
    clear_payment_state_machine_version: Literal["clear-payment-state-machine-v1"] = (
        "clear-payment-state-machine-v1"
    )
    execution_id: CanonicalUUID4
    certificate_digest_version: Literal["sha256-allocation-certificate-v2-clear-json-v1"]
    certificate_digest_sha256: _Sha256
    provider_account_id: _AccountId
    provider_order_id: _OrderId
    expected_amount: _ExactMoney
    state: ClearPaymentStateV1
    effective_payment_id: _OptionalPaymentId
    evidence: _EvidenceTuple

    @model_validator(mode="after")
    def _validate_snapshot(self) -> Self:
        sequences = tuple(item.ledger_sequence_number for item in self.evidence)
        if any(current >= following for current, following in pairwise(sequences)):
            raise ValueError("payment evidence sequence numbers must be strictly increasing")
        if any(item.execution_id != self.execution_id for item in self.evidence):
            raise ValueError("payment evidence execution does not match snapshot")
        if any(item.provider_account_id != self.provider_account_id for item in self.evidence):
            raise ValueError("payment evidence account does not match snapshot")
        if any(item.provider_order_id != self.provider_order_id for item in self.evidence):
            raise ValueError("payment evidence order does not match snapshot")
        if any(item.amount != self.expected_amount for item in self.evidence):
            raise ValueError("payment evidence amount does not match snapshot")

        if self.state is ClearPaymentStateV1.ORDER_CREATED:
            if self.evidence or self.effective_payment_id is not None:
                raise ValueError("order-created state requires no payment evidence")
            return self
        if self.state is ClearPaymentStateV1.PAYMENT_FAILED_OBSERVED:
            if not self.evidence or self.effective_payment_id is not None:
                raise ValueError(
                    "failed-observed state requires evidence without an effective payment"
                )
            return self
        if self.effective_payment_id is None:
            raise ValueError("active payment states require an effective payment ID")
        if self.effective_payment_id not in {item.provider_payment_id for item in self.evidence}:
            raise ValueError("effective payment ID must appear in payment evidence")
        return self
