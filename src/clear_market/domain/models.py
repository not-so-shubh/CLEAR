from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from clear_market.domain.constants import MAX_SELLERS, MIN_SELLERS
from clear_market.domain.money import Money, MoneyOverflowError
from clear_market.domain.primitives import CanonicalUUID4, PositiveQuantity, UTCDateTime

_LOWERCASE_HEX_DIGITS = frozenset("0123456789abcdef")


def _validate_ed25519_public_key_hex(value: object) -> str:
    """Require callers to provide the exact deterministic 32-byte key encoding."""
    if type(value) is not str:
        raise ValueError("public key input must be a string")
    if len(value) != 64 or any(character not in _LOWERCASE_HEX_DIGITS for character in value):
        raise ValueError("public key input must be 64 lowercase hexadecimal characters")
    return value


type _Ed25519PublicKeyHex = Annotated[
    str,
    BeforeValidator(_validate_ed25519_public_key_hex),
]


class MarketSpec(BaseModel):
    """Immutable identity and quantity for one standardized contract instance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    market_id: CanonicalUUID4
    buyer_id: CanonicalUUID4
    requested_quantity: PositiveQuantity


class MerchantIdentity(BaseModel):
    """Immutable binding between a merchant ID and exact public-key bytes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    merchant_id: CanonicalUUID4
    ed25519_public_key_hex: _Ed25519PublicKeyHex


class BuyerPolicy(BaseModel):
    """Immutable snapshot of every allocation-relevant buyer constraint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    market_spec: MarketSpec
    max_total_payment: Money
    reserve_unit_price: Money
    eligible_merchants: Annotated[
        tuple[MerchantIdentity, ...],
        Field(min_length=MIN_SELLERS, max_length=MAX_SELLERS),
    ]
    bid_deadline: UTCDateTime
    mechanism_version: Literal["reverse_second_price_v1"] = "reverse_second_price_v1"
    tie_break_rule: Literal["merchant_id_lexicographic_ascending"] = (
        "merchant_id_lexicographic_ascending"
    )

    @field_validator("eligible_merchants")
    @classmethod
    def _validate_and_normalize_merchants(
        cls,
        merchants: tuple[MerchantIdentity, ...],
    ) -> tuple[MerchantIdentity, ...]:
        merchant_ids = tuple(merchant.merchant_id for merchant in merchants)
        if len(set(merchant_ids)) != len(merchant_ids):
            raise ValueError("eligible merchant IDs must be unique")
        return tuple(sorted(merchants, key=lambda merchant: merchant.merchant_id))

    @model_validator(mode="after")
    def _validate_reserve_feasibility(self) -> Self:
        try:
            reserve_total = self.reserve_unit_price.checked_multiply(
                self.market_spec.requested_quantity
            )
        except MoneyOverflowError as error:
            raise ValueError("reserve total exceeds the Week-2 money ceiling") from error

        if reserve_total.amount_paise > self.max_total_payment.amount_paise:
            raise ValueError("reserve total exceeds the buyer payment ceiling")
        return self
