from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, model_validator

from clear_market.domain import (
    CanonicalUUID4,
    Money,
    MoneyOverflowError,
    PositiveQuantity,
)

_LOWERCASE_HEX_DIGITS = frozenset("0123456789abcdef")


def _validate_buyer_policy_commitment(value: object) -> str:
    """Require callers to supply the exact SHA-256 hexadecimal representation."""
    if type(value) is not str:
        raise ValueError("buyer policy commitment must be a string")
    if len(value) != 64 or any(character not in _LOWERCASE_HEX_DIGITS for character in value):
        raise ValueError("buyer policy commitment must be 64 lowercase hexadecimal characters")
    return value


type _BuyerPolicyCommitment = Annotated[
    str,
    BeforeValidator(_validate_buyer_policy_commitment),
]


class AllocationStatus(StrEnum):
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"


class Allocation(BaseModel):
    """Immutable result of the frozen single-winner allocation rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    market_id: CanonicalUUID4
    buyer_policy_commitment_version: Literal["sha256-clear-json-v1"] = "sha256-clear-json-v1"
    buyer_policy_commitment: _BuyerPolicyCommitment
    mechanism_version: Literal["reverse_second_price_v1"] = "reverse_second_price_v1"
    status: AllocationStatus
    winner_merchant_id: CanonicalUUID4 | None = None
    winning_bid_id: CanonicalUUID4 | None = None
    allocated_quantity: PositiveQuantity | None = None
    winning_unit_price: Money | None = None
    payment_unit_price: Money | None = None
    total_payment: Money | None = None

    @model_validator(mode="after")
    def _validate_status_consistency(self) -> Self:
        winner_merchant_id = self.winner_merchant_id
        winning_bid_id = self.winning_bid_id
        allocated_quantity = self.allocated_quantity
        winning_unit_price = self.winning_unit_price
        payment_unit_price = self.payment_unit_price
        total_payment = self.total_payment

        if self.status is AllocationStatus.INFEASIBLE:
            if any(
                value is not None
                for value in (
                    winner_merchant_id,
                    winning_bid_id,
                    allocated_quantity,
                    winning_unit_price,
                    payment_unit_price,
                    total_payment,
                )
            ):
                raise ValueError("infeasible allocation cannot carry winner or payment evidence")
            return self

        if (
            winner_merchant_id is None
            or winning_bid_id is None
            or allocated_quantity is None
            or winning_unit_price is None
            or payment_unit_price is None
            or total_payment is None
        ):
            raise ValueError("feasible allocation requires complete winner and payment evidence")

        if winning_unit_price.amount_paise > payment_unit_price.amount_paise:
            raise ValueError("payment unit price cannot be below the winning unit bid")

        try:
            expected_total = payment_unit_price.checked_multiply(allocated_quantity)
        except MoneyOverflowError as error:
            raise ValueError("allocation total exceeds the Week-2 money ceiling") from error

        if expected_total != total_payment:
            raise ValueError("total payment does not match exact checked multiplication")
        return self
