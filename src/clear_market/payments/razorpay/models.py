"""Strict sanitized projections for Razorpay Test Mode Orders."""

import re
from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationError, model_validator

from clear_market.domain import CanonicalUUID4, Currency, Money

RAZORPAY_TEST_ORDER_ADAPTER_V1_VERSION: Final[str] = "razorpay-test-order-adapter-v1"
RAZORPAY_ORDER_V1_VERSION: Final[str] = "razorpay-order-v1"
RAZORPAY_ORDER_RESULT_V1_VERSION: Final[str] = "razorpay-order-result-v1"
RAZORPAY_ORDER_CREATE_INTENT_V1_VERSION: Final[str] = "razorpay-order-create-intent-v1"
RAZORPAY_ORDER_CREATE_FINGERPRINT_V1_VERSION: Final[str] = (
    "sha256-razorpay-order-create-intent-v1-clear-json-v1"
)

_PROVIDER_ORDER_ID_PATTERN = re.compile(r"order_[A-Za-z0-9]{1,128}", flags=re.ASCII)


class RazorpayOrderStatusV1(StrEnum):
    CREATED = "created"
    ATTEMPTED = "attempted"
    PAID = "paid"


class RazorpayOrderResolutionV1(StrEnum):
    CREATED = "CREATED"
    EXISTING = "EXISTING"


def _provider_order_id(value: object) -> str:
    if type(value) is not str or _PROVIDER_ORDER_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("provider order ID is not canonical")
    return value


def _fresh_money(value: object) -> Money:
    if type(value) is not Money:
        raise ValueError("amount must be a valid exact Money value")
    try:
        amount_paise = value.__dict__["amount_paise"]
        currency = value.__dict__["currency"]
    except (AttributeError, KeyError, ValidationError):
        raise ValueError("amount must be a valid exact Money value") from None
    if type(amount_paise) is not int or type(currency) is not Currency:
        raise ValueError("amount must be a valid exact Money value")
    try:
        return Money.model_validate(
            {
                "amount_paise": amount_paise,
                "currency": currency,
            }
        )
    except ValidationError:
        raise ValueError("amount must be a valid exact Money value") from None


class RazorpayOrderV1(BaseModel):
    """Sanitized provider-reported order facts, not payment or fulfillment proof.

    This model does not prove payment authorization, capture, settlement, merchant transfer,
    fulfillment, refund, or reversal.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    razorpay_order_version: Literal["razorpay-order-v1"] = "razorpay-order-v1"
    execution_id: CanonicalUUID4
    provider_order_id: Annotated[str, BeforeValidator(_provider_order_id)]
    amount: Annotated[Money, BeforeValidator(_fresh_money)]
    currency: Literal["INR"] = "INR"
    receipt: CanonicalUUID4
    status: RazorpayOrderStatusV1

    @model_validator(mode="after")
    def _validate_bindings(self) -> Self:
        if self.amount.currency is not Currency.INR:
            raise ValueError("order amount currency must be INR")
        if self.receipt != self.execution_id:
            raise ValueError("order receipt must equal execution ID")
        return self


def _fresh_order(value: object) -> RazorpayOrderV1:
    if type(value) is not RazorpayOrderV1:
        raise ValueError("order must be a valid exact RazorpayOrderV1")
    try:
        fields = {name: value.__dict__[name] for name in RazorpayOrderV1.model_fields}
        return RazorpayOrderV1.model_validate(fields)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError("order must be a valid exact RazorpayOrderV1") from None


class RazorpayOrderResultV1(BaseModel):
    """Sanitized result of one governor-gated create or validated existing-order fetch."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    razorpay_order_result_version: Literal["razorpay-order-result-v1"] = "razorpay-order-result-v1"
    adapter_version: Literal["razorpay-test-order-adapter-v1"] = "razorpay-test-order-adapter-v1"
    resolution: RazorpayOrderResolutionV1
    order: Annotated[RazorpayOrderV1, BeforeValidator(_fresh_order)]
