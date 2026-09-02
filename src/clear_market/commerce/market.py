import re
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from clear_market.commerce.constraints import HardConstraint, SoftPreference
from clear_market.domain import (
    MAX_SELLERS,
    MIN_SELLERS,
    CanonicalUUID4,
    Money,
    PositiveQuantity,
    UTCDateTime,
)

MARKET_SPEC_V2_VERSION: Final[str] = "market-spec-v2"
BUYER_POLICY_V2_VERSION: Final[str] = "buyer-policy-v2"

MAX_HARD_CONSTRAINTS: Final[int] = 64
MAX_SOFT_PREFERENCES: Final[int] = 64

_VERSION_IDENTIFIER_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,127}", flags=re.ASCII)


def _validate_version_identifier(value: object) -> str:
    if type(value) is not str or _VERSION_IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError("version identifier is not canonical")
    return value


type _VersionIdentifier = Annotated[str, BeforeValidator(_validate_version_identifier)]


def _require_tuple(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("collection must be supplied as a tuple")
    return value


type _HardConstraints = Annotated[
    tuple[HardConstraint, ...],
    BeforeValidator(_require_tuple),
    Field(max_length=MAX_HARD_CONSTRAINTS),
]
type _SoftPreferences = Annotated[
    tuple[SoftPreference, ...],
    BeforeValidator(_require_tuple),
    Field(max_length=MAX_SOFT_PREFERENCES),
]
type _MaxWinners = Annotated[int, Field(strict=True, ge=1, le=MAX_SELLERS)]
type _EligibleMerchantIds = Annotated[
    tuple[CanonicalUUID4, ...],
    BeforeValidator(_require_tuple),
    Field(min_length=MIN_SELLERS, max_length=MAX_SELLERS),
]


class MarketSpecV2(BaseModel):
    """Immutable heterogeneous buyer demand without allocation implementation."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["2"] = "2"
    market_spec_version: Literal["market-spec-v2"] = "market-spec-v2"
    market_id: CanonicalUUID4
    buyer_id: CanonicalUUID4
    requested_quantity: PositiveQuantity
    minimum_acceptable_quantity: PositiveQuantity
    max_winners: _MaxWinners
    hard_constraints: _HardConstraints
    soft_preferences: _SoftPreferences

    @field_validator("hard_constraints")
    @classmethod
    def _validate_and_normalize_hard_constraints(
        cls,
        constraints: tuple[HardConstraint, ...],
    ) -> tuple[HardConstraint, ...]:
        constraint_ids = tuple(constraint.constraint_id for constraint in constraints)
        if len(set(constraint_ids)) != len(constraint_ids):
            raise ValueError("hard constraint IDs must be unique")
        return tuple(sorted(constraints, key=lambda constraint: constraint.constraint_id))

    @field_validator("soft_preferences")
    @classmethod
    def _validate_and_normalize_soft_preferences(
        cls,
        preferences: tuple[SoftPreference, ...],
    ) -> tuple[SoftPreference, ...]:
        preference_ids = tuple(preference.preference_id for preference in preferences)
        if len(set(preference_ids)) != len(preference_ids):
            raise ValueError("soft preference IDs must be unique")
        return tuple(sorted(preferences, key=lambda preference: preference.preference_id))

    @model_validator(mode="after")
    def _validate_market_bounds_and_rule_namespace(self) -> Self:
        if self.minimum_acceptable_quantity > self.requested_quantity:
            raise ValueError("minimum acceptable quantity exceeds requested quantity")
        if self.max_winners > self.requested_quantity:
            raise ValueError("maximum winner count exceeds requested quantity")

        hard_ids = {constraint.constraint_id for constraint in self.hard_constraints}
        soft_ids = {preference.preference_id for preference in self.soft_preferences}
        if hard_ids & soft_ids:
            raise ValueError("hard constraints and soft preferences must use distinct rule IDs")
        return self


class BuyerPolicyV2(BaseModel):
    """Immutable V2 buyer policy whose economic identifiers remain opaque."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["2"] = "2"
    buyer_policy_version: Literal["buyer-policy-v2"] = "buyer-policy-v2"
    market_spec: MarketSpecV2
    max_total_payment: Money
    eligible_merchant_ids: _EligibleMerchantIds
    offer_deadline: UTCDateTime
    mechanism_version: _VersionIdentifier
    objective_version: _VersionIdentifier

    @field_validator("eligible_merchant_ids")
    @classmethod
    def _validate_and_normalize_merchant_ids(
        cls,
        merchant_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        if len(set(merchant_ids)) != len(merchant_ids):
            raise ValueError("eligible merchant IDs must be unique")
        return tuple(sorted(merchant_ids))

    @model_validator(mode="after")
    def _validate_winner_population(self) -> Self:
        if self.market_spec.max_winners > len(self.eligible_merchant_ids):
            raise ValueError("maximum winner count exceeds eligible merchant count")
        return self
