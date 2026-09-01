from enum import StrEnum
from typing import Annotated, Literal, Self, cast

from pydantic import BaseModel, BeforeValidator, ConfigDict, model_validator

from clear_market.domain import (
    CanonicalUUID4,
    Money,
    MoneyOverflowError,
    PositiveQuantity,
)

_HEX_ALPHABET = frozenset("0123456789abcdef")


def _validate_commitment_hex(value: object) -> str:
    """Accept only the already-canonical SHA-256 hexadecimal representation."""
    if type(value) is not str:
        raise ValueError("policy commitment must be a string")
    if len(value) != 64:
        raise ValueError("policy commitment must contain exactly 64 characters")
    if any(character not in _HEX_ALPHABET for character in value):
        raise ValueError("policy commitment must contain only lowercase hexadecimal characters")
    return value


type _PolicyCommitment = Annotated[str, BeforeValidator(_validate_commitment_hex)]


class OracleAllocationStatus(StrEnum):
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"


class OracleAllocation(BaseModel):
    """Immutable result produced by the independent reference computation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    market_id: CanonicalUUID4
    buyer_policy_commitment_version: Literal["sha256-clear-json-v1"] = "sha256-clear-json-v1"
    buyer_policy_commitment: _PolicyCommitment
    mechanism_version: Literal["reverse_second_price_v1"] = "reverse_second_price_v1"
    status: OracleAllocationStatus
    winner_merchant_id: CanonicalUUID4 | None = None
    winning_bid_id: CanonicalUUID4 | None = None
    allocated_quantity: PositiveQuantity | None = None
    winning_unit_price: Money | None = None
    payment_unit_price: Money | None = None
    total_payment: Money | None = None

    @model_validator(mode="after")
    def _check_evidence_consistency(self) -> Self:
        evidence = (
            self.winner_merchant_id,
            self.winning_bid_id,
            self.allocated_quantity,
            self.winning_unit_price,
            self.payment_unit_price,
            self.total_payment,
        )

        if self.status is OracleAllocationStatus.INFEASIBLE:
            if not all(value is None for value in evidence):
                raise ValueError("infeasible oracle result cannot contain allocation evidence")
            return self

        if any(value is None for value in evidence):
            raise ValueError("feasible oracle result requires complete allocation evidence")

        quantity = cast(int, self.allocated_quantity)
        winning_price = cast(Money, self.winning_unit_price)
        payment_price = cast(Money, self.payment_unit_price)
        supplied_total = cast(Money, self.total_payment)

        if winning_price.amount_paise > payment_price.amount_paise:
            raise ValueError("oracle payment cannot be below the winning bid")

        try:
            calculated_total = payment_price.checked_multiply(quantity)
        except MoneyOverflowError as error:
            raise ValueError("oracle allocation total exceeds the money ceiling") from error

        if calculated_total != supplied_total:
            raise ValueError("oracle total payment is inconsistent")
        return self
