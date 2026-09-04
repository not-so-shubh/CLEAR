"""Strict provider-fact models for Razorpay payment-transfer reconciliation."""

import re
from datetime import UTC, datetime
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

from clear_market.domain import MAX_MONEY_PAISE, CanonicalUUID4, Currency, Money

RAZORPAY_PAYMENT_TRANSFER_EXECUTION_V1_VERSION: Final[str] = (
    "razorpay-payment-transfer-execution-v1"
)
RAZORPAY_TRANSFER_OBSERVATION_V1_VERSION: Final[str] = "razorpay-transfer-observation-v1"
RAZORPAY_TRANSFER_BATCH_RESULT_V1_VERSION: Final[str] = "razorpay-transfer-batch-result-v1"
RAZORPAY_TRANSFER_REQUEST_FINGERPRINT_V1_VERSION: Final[str] = (
    "sha256-razorpay-payment-transfer-request-v1-clear-json-v1"
)

_TRANSFER_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"trf_[A-Za-z0-9]{1,128}",
    flags=re.ASCII,
)
_PAYMENT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"pay_[A-Za-z0-9]{1,128}",
    flags=re.ASCII,
)
_ORDER_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"order_[A-Za-z0-9]{1,128}",
    flags=re.ASCII,
)
_ACCOUNT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"acc_[A-Za-z0-9]{1,14}",
    flags=re.ASCII,
)
_SHA256_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


def _pattern(value: object, pattern: re.Pattern[str], message: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError(message)
    return value


def _transfer_id(value: object) -> str:
    return _pattern(value, _TRANSFER_ID_PATTERN, "provider transfer ID is not canonical")


def _payment_id(value: object) -> str:
    return _pattern(value, _PAYMENT_ID_PATTERN, "provider payment ID is not canonical")


def _order_id(value: object) -> str:
    return _pattern(value, _ORDER_ID_PATTERN, "provider order ID is not canonical")


def _account_id(value: object) -> str:
    return _pattern(value, _ACCOUNT_ID_PATTERN, "Razorpay account ID is not canonical")


def _sha256(value: object) -> str:
    return _pattern(value, _SHA256_PATTERN, "fingerprint must be lowercase SHA-256 hex")


def _unix_time(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("created_at_unix must be an exact nonnegative integer")
    try:
        datetime.fromtimestamp(value, tz=UTC)
    except (OSError, OverflowError, ValueError):
        raise ValueError("created_at_unix must be convertible to UTC") from None
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


def _fresh_observation(value: object) -> "RazorpayTransferObservationV1":
    if type(value) is not RazorpayTransferObservationV1:
        raise ValueError("transfers must contain valid exact observations")
    try:
        fields = {name: value.__dict__[name] for name in RazorpayTransferObservationV1.model_fields}
        return RazorpayTransferObservationV1.model_validate(fields)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError("transfers must contain valid exact observations") from None


def _fresh_observations(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("transfers must be supplied as an exact tuple")
    return tuple(_fresh_observation(item) for item in cast(tuple[object, ...], value))


type _TransferId = Annotated[str, BeforeValidator(_transfer_id)]
type _PaymentId = Annotated[str, BeforeValidator(_payment_id)]
type _OrderId = Annotated[str, BeforeValidator(_order_id)]
type _AccountId = Annotated[str, BeforeValidator(_account_id)]
type _Sha256 = Annotated[str, BeforeValidator(_sha256)]
type _UnixTime = Annotated[int, BeforeValidator(_unix_time)]
type _ExactMoney = Annotated[Money, BeforeValidator(_fresh_money)]
type _LineIndex = Annotated[int, Field(strict=True, ge=0)]
type _NonnegativeAmount = Annotated[int, Field(strict=True, ge=0, le=MAX_MONEY_PAISE)]
type _Observations = Annotated[
    tuple["RazorpayTransferObservationV1", ...],
    BeforeValidator(_fresh_observations),
    Field(min_length=1),
]


class RazorpayTransferStatusV1(StrEnum):
    CREATED = "created"
    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"
    REVERSED = "reversed"
    PARTIALLY_REVERSED = "partially_reversed"


class RazorpaySettlementStatusV1(StrEnum):
    PENDING = "pending"
    ON_HOLD = "on_hold"
    SETTLED = "settled"


class RazorpayTransferBatchDispositionV1(StrEnum):
    CREATED = "CREATED"
    RECOVERED = "RECOVERED"
    EXISTING = "EXISTING"


class RazorpayTransferObservationV1(BaseModel):
    """One immutable observation of mutable Razorpay provider transfer facts.

    Direct construction grants no money, reversal, or settlement authority.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    razorpay_transfer_observation_version: Literal["razorpay-transfer-observation-v1"] = (
        "razorpay-transfer-observation-v1"
    )
    allocation_line_index: _LineIndex
    provider_transfer_id: _TransferId
    provider_payment_id: _PaymentId
    razorpay_account_id: _AccountId
    amount: _ExactMoney
    transfer_status: RazorpayTransferStatusV1
    settlement_status: RazorpaySettlementStatusV1 | None
    amount_reversed: _NonnegativeAmount
    created_at_unix: _UnixTime

    @model_validator(mode="after")
    def _validate_reversal_amount(self) -> Self:
        if self.amount_reversed > self.amount.amount_paise:
            raise ValueError("reversed amount exceeds transfer amount")
        return self


class RazorpayTransferBatchResultV1(BaseModel):
    """Provider creation/reconciliation facts, never settlement or governor authority.

    CREATED records that provider transfer records were created and durably bound. RECOVERED
    records reconciliation of prior provider records. EXISTING records revalidation of already
    known records. None proves bank settlement, fulfillment, irreversibility, or impossibility of
    a future refund or reversal.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    razorpay_transfer_batch_result_version: Literal["razorpay-transfer-batch-result-v1"] = (
        "razorpay-transfer-batch-result-v1"
    )
    transfer_execution_version: Literal["razorpay-payment-transfer-execution-v1"] = (
        "razorpay-payment-transfer-execution-v1"
    )
    disposition: RazorpayTransferBatchDispositionV1
    execution_id: CanonicalUUID4
    provider_order_id: _OrderId
    provider_payment_id: _PaymentId
    transfer_request_fingerprint_version: Literal[
        "sha256-razorpay-payment-transfer-request-v1-clear-json-v1"
    ] = "sha256-razorpay-payment-transfer-request-v1-clear-json-v1"
    transfer_request_fingerprint_sha256: _Sha256
    route_mapping_fingerprint_version: Literal[
        "sha256-razorpay-route-mapping-request-v1-clear-json-v1"
    ]
    route_mapping_fingerprint_sha256: _Sha256
    transfers: _Observations

    @model_validator(mode="after")
    def _validate_batch(self) -> Self:
        indices = tuple(item.allocation_line_index for item in self.transfers)
        if indices != tuple(range(len(self.transfers))):
            raise ValueError("transfer indices must be exact, contiguous, and ordered")
        if any(item.provider_payment_id != self.provider_payment_id for item in self.transfers):
            raise ValueError("transfer payment IDs must match the batch")
        transfer_ids = tuple(item.provider_transfer_id for item in self.transfers)
        if len(set(transfer_ids)) != len(transfer_ids):
            raise ValueError("provider transfer IDs must be unique")
        total = 0
        for item in self.transfers:
            total += item.amount.amount_paise
            if total > MAX_MONEY_PAISE:
                raise ValueError("transfer batch total exceeds the money bound")
        return self
