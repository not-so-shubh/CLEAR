"""Strict sanitized results for Razorpay order reconciliation."""

import re
from enum import StrEnum
from typing import Annotated, Final, Literal, Self, cast

from pydantic import BaseModel, BeforeValidator, ConfigDict, ValidationError, model_validator

from clear_market.domain import CanonicalUUID4
from clear_market.payments.razorpay import (
    RAZORPAY_ORDER_CREATE_FINGERPRINT_V1_VERSION,
    RazorpayOrderV1,
)

RAZORPAY_ORDER_RECOVERY_V1_VERSION: Final[str] = "razorpay-order-recovery-v1"
RAZORPAY_ORDER_RECOVERY_RESULT_V1_VERSION: Final[str] = "razorpay-order-recovery-result-v1"

_SHA256_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


class RazorpayOrderRecoveryDispositionV1(StrEnum):
    RECOVERED = "RECOVERED"
    EXISTING = "EXISTING"
    NOT_FOUND = "NOT_FOUND"


def _sha256(value: object) -> str:
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError("fingerprint must be lowercase SHA-256 hex")
    return value


def _fresh_optional_order(value: object) -> RazorpayOrderV1 | None:
    if value is None:
        return None
    if type(value) is not RazorpayOrderV1:
        raise ValueError("order must be a valid exact RazorpayOrderV1")
    try:
        fields = {name: value.__dict__[name] for name in RazorpayOrderV1.model_fields}
        return RazorpayOrderV1.model_validate(fields)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError("order must be a valid exact RazorpayOrderV1") from None


type _Sha256 = Annotated[str, BeforeValidator(_sha256)]
type _OptionalOrder = Annotated[
    RazorpayOrderV1 | None,
    BeforeValidator(_fresh_optional_order),
]


class RazorpayOrderRecoveryResultV1(BaseModel):
    """Sanitized reconciliation outcome without money or provider-action authority.

    This result records reconciliation outcome. It is not Money Governor authority and does not
    authorize payment, capture, transfer, refund, reversal, fulfillment, or settlement.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    razorpay_order_recovery_result_version: Literal["razorpay-order-recovery-result-v1"] = (
        "razorpay-order-recovery-result-v1"
    )
    recovery_version: Literal["razorpay-order-recovery-v1"] = "razorpay-order-recovery-v1"
    disposition: RazorpayOrderRecoveryDispositionV1
    execution_id: CanonicalUUID4
    order_create_fingerprint_version: Literal[
        "sha256-razorpay-order-create-intent-v1-clear-json-v1"
    ] = cast(
        Literal["sha256-razorpay-order-create-intent-v1-clear-json-v1"],
        RAZORPAY_ORDER_CREATE_FINGERPRINT_V1_VERSION,
    )
    order_create_fingerprint_sha256: _Sha256
    order: _OptionalOrder

    @model_validator(mode="after")
    def _validate_disposition(self) -> Self:
        if self.disposition is RazorpayOrderRecoveryDispositionV1.NOT_FOUND:
            if self.order is not None:
                raise ValueError("not-found recovery result must not contain an order")
            return self
        if self.order is None:
            raise ValueError("successful order recovery result must contain an order")
        if self.order.execution_id != self.execution_id:
            raise ValueError("recovered order execution does not match result")
        return self
