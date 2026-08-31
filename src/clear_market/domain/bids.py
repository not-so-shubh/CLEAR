from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from clear_market.domain.constants import MAX_MONEY_PAISE
from clear_market.domain.money import Currency
from clear_market.domain.primitives import CanonicalUUID4, Quantity, UTCDateTime

_LOWERCASE_HEX_DIGITS = frozenset("0123456789abcdef")


def _validate_buyer_policy_commitment(value: object) -> str:
    """Require the exact lowercase representation supplied by the committing protocol."""
    if type(value) is not str:
        raise ValueError("buyer policy commitment must be a string")
    if len(value) != 64 or any(character not in _LOWERCASE_HEX_DIGITS for character in value):
        raise ValueError("buyer policy commitment must be 64 lowercase hexadecimal characters")
    return value


def _validate_signature_hex(value: object) -> str:
    """Require the exact detached Ed25519 evidence representation without normalizing it."""
    if type(value) is not str:
        raise ValueError("signature must be a string")
    if len(value) != 128 or any(character not in _LOWERCASE_HEX_DIGITS for character in value):
        raise ValueError("signature must be 128 lowercase hexadecimal characters")
    return value


type _BuyerPolicyCommitment = Annotated[
    str,
    BeforeValidator(_validate_buyer_policy_commitment),
]
type _UnitPricePaise = Annotated[
    int,
    Field(strict=True, ge=0, le=MAX_MONEY_PAISE),
]
type _SignatureHex = Annotated[
    str,
    BeforeValidator(_validate_signature_hex),
]


class MerchantBid(BaseModel):
    """Immutable merchant economic message before admission or lifecycle processing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    bid_id: CanonicalUUID4
    market_id: CanonicalUUID4
    merchant_id: CanonicalUUID4
    buyer_policy_commitment_version: Literal["sha256-clear-json-v1"] = "sha256-clear-json-v1"
    buyer_policy_commitment: _BuyerPolicyCommitment
    quantity_available: Quantity
    unit_price_paise: _UnitPricePaise
    currency: Currency = Currency.INR
    submitted_at: UTCDateTime


class SignedMerchantBid(BaseModel):
    """Immutable MerchantBid paired only with its detached Ed25519 evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bid: MerchantBid
    signature_hex: _SignatureHex
