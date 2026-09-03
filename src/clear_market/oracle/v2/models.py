import re
from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from clear_market.commerce.market import MAX_SOFT_PREFERENCES
from clear_market.commerce.merchant import MAX_OFFER_LINES
from clear_market.domain import (
    MAX_MONEY_PAISE,
    MAX_QUANTITY,
    MAX_SELLERS,
    CanonicalUUID4,
    Money,
    MoneyOverflowError,
    PositiveQuantity,
    Quantity,
)

HETEROGENEOUS_ORACLE_V2_VERSION: Final[str] = "independent-heterogeneous-oracle-v2"
ORACLE_ALLOCATION_LINE_V2_VERSION: Final[str] = "oracle-allocation-line-v2"
ORACLE_ALLOCATION_V2_VERSION: Final[str] = "oracle-allocation-v2"

_BUYER_POLICY_V2_COMMITMENT_VERSION: Final[Literal["sha256-buyer-policy-v2-clear-json-v1"]] = (
    "sha256-buyer-policy-v2-clear-json-v1"
)
_MAX_ORACLE_ALLOCATION_LINES: Final[int] = MAX_SELLERS * MAX_OFFER_LINES
_SHA256_HEX_PATTERN = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


class OracleV2ErrorCode(StrEnum):
    INVALID_BUYER_POLICY = "INVALID_BUYER_POLICY"
    INVALID_SIGNED_OFFER = "INVALID_SIGNED_OFFER"
    UNSUPPORTED_MECHANISM_VERSION = "UNSUPPORTED_MECHANISM_VERSION"
    UNSUPPORTED_OBJECTIVE_VERSION = "UNSUPPORTED_OBJECTIVE_VERSION"
    DUPLICATE_OFFER_ID = "DUPLICATE_OFFER_ID"
    DUPLICATE_MERCHANT_OFFER = "DUPLICATE_MERCHANT_OFFER"
    MERCHANT_NOT_ELIGIBLE = "MERCHANT_NOT_ELIGIBLE"
    MARKET_ID_MISMATCH = "MARKET_ID_MISMATCH"
    BUYER_POLICY_COMMITMENT_MISMATCH = "BUYER_POLICY_COMMITMENT_MISMATCH"


class OracleV2Error(ValueError):
    """Stable independent-oracle input failure contract."""

    __slots__ = ("_code",)

    def __init__(self, code: OracleV2ErrorCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> OracleV2ErrorCode:
        return self._code


class OracleAllocationStatusV2(StrEnum):
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"


def _validate_sha256_hex(value: object) -> str:
    if type(value) is not str or _SHA256_HEX_PATTERN.fullmatch(value) is None:
        raise ValueError("buyer policy commitment must be lowercase SHA-256 hex")
    return value


def _revalidate_exact_money(value: object) -> Money:
    if type(value) is not Money:
        raise ValueError("money must be supplied as an exact Money value")
    try:
        return Money.model_validate(value.model_dump(mode="python", warnings=False))
    except ValidationError:
        raise ValueError("money must be a valid exact Money value") from None


def _revalidate_oracle_lines(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("oracle allocation lines must be supplied as a tuple")
    validated: list[OracleAllocationLineV2] = []
    for line in value:
        if type(line) is not OracleAllocationLineV2:
            raise ValueError("oracle allocation lines must use exact line values")
        try:
            validated.append(OracleAllocationLineV2.model_validate(line))
        except (AttributeError, ValidationError):
            raise ValueError("oracle allocation lines must be valid exact line values") from None
    return tuple(validated)


type _BuyerPolicyCommitmentSha256 = Annotated[
    str,
    BeforeValidator(_validate_sha256_hex),
]
type _SoftPreferenceUnitScore = Annotated[
    int,
    Field(strict=True, ge=0, le=MAX_QUANTITY * MAX_SOFT_PREFERENCES),
]
type _WinnerCount = Annotated[int, Field(strict=True, ge=0, le=MAX_SELLERS)]
type _OracleAllocationLines = Annotated[
    tuple["OracleAllocationLineV2", ...],
    BeforeValidator(_revalidate_oracle_lines),
    Field(max_length=_MAX_ORACLE_ALLOCATION_LINES),
]


class OracleAllocationLineV2(BaseModel):
    """One immutable pay-as-bid obligation from the independent oracle."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["2"] = "2"
    oracle_allocation_line_version: Literal["oracle-allocation-line-v2"] = (
        "oracle-allocation-line-v2"
    )
    offer_id: CanonicalUUID4
    merchant_id: CanonicalUUID4
    sku_id: CanonicalUUID4
    allocated_quantity: PositiveQuantity
    unit_payment: Money
    line_payment: Money

    @field_validator("unit_payment", "line_payment", mode="before")
    @classmethod
    def _validate_money(cls, value: object) -> Money:
        return _revalidate_exact_money(value)

    @model_validator(mode="after")
    def _validate_line_payment(self) -> Self:
        try:
            expected_payment = self.unit_payment.checked_multiply(self.allocated_quantity)
        except MoneyOverflowError as error:
            raise ValueError("oracle allocation line payment exceeds the money bound") from error
        if self.line_payment != expected_payment:
            raise ValueError("oracle line payment does not match exact checked multiplication")
        return self


class OracleAllocationV2(BaseModel):
    """Independent economic reference result; never financial authorization."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["2"] = "2"
    oracle_allocation_version: Literal["oracle-allocation-v2"] = "oracle-allocation-v2"
    oracle_version: Literal["independent-heterogeneous-oracle-v2"] = (
        "independent-heterogeneous-oracle-v2"
    )
    mechanism_version: Literal["heterogeneous-pay-as-bid-v2"] = "heterogeneous-pay-as-bid-v2"
    objective_version: Literal["quantity-cost-soft-objective-v2"] = (
        "quantity-cost-soft-objective-v2"
    )
    market_id: CanonicalUUID4
    buyer_policy_commitment_version: Literal["sha256-buyer-policy-v2-clear-json-v1"] = (
        _BUYER_POLICY_V2_COMMITMENT_VERSION
    )
    buyer_policy_commitment_sha256: _BuyerPolicyCommitmentSha256
    status: OracleAllocationStatusV2
    fulfilled_quantity: Quantity
    total_payment: Money
    soft_preference_unit_score: _SoftPreferenceUnitScore
    winner_count: _WinnerCount
    lines: _OracleAllocationLines

    @field_validator("total_payment", mode="before")
    @classmethod
    def _validate_total_payment(cls, value: object) -> Money:
        return _revalidate_exact_money(value)

    @field_validator("lines")
    @classmethod
    def _validate_and_normalize_lines(
        cls,
        lines: tuple[OracleAllocationLineV2, ...],
    ) -> tuple[OracleAllocationLineV2, ...]:
        offer_sku_keys = tuple((line.offer_id, line.sku_id) for line in lines)
        merchant_sku_keys = tuple((line.merchant_id, line.sku_id) for line in lines)
        if len(set(offer_sku_keys)) != len(offer_sku_keys):
            raise ValueError("oracle lines must use unique offer and SKU pairs")
        if len(set(merchant_sku_keys)) != len(merchant_sku_keys):
            raise ValueError("oracle lines must use unique merchant and SKU pairs")

        offers_by_merchant: dict[str, set[str]] = {}
        merchants_by_offer: dict[str, set[str]] = {}
        for line in lines:
            offers_by_merchant.setdefault(line.merchant_id, set()).add(line.offer_id)
            merchants_by_offer.setdefault(line.offer_id, set()).add(line.merchant_id)
        if any(len(offer_ids) != 1 for offer_ids in offers_by_merchant.values()):
            raise ValueError("one oracle merchant must map to one offer")
        if any(len(merchant_ids) != 1 for merchant_ids in merchants_by_offer.values()):
            raise ValueError("one oracle offer must map to one merchant")

        return tuple(
            sorted(
                lines,
                key=lambda line: (line.merchant_id, line.sku_id, line.offer_id),
            )
        )

    @model_validator(mode="after")
    def _validate_internal_consistency(self) -> Self:
        fulfilled_quantity = sum(line.allocated_quantity for line in self.lines)
        if self.fulfilled_quantity != fulfilled_quantity:
            raise ValueError("oracle fulfilled quantity does not match allocation lines")

        total_payment_paise = 0
        for line in self.lines:
            total_payment_paise += line.line_payment.amount_paise
            if total_payment_paise > MAX_MONEY_PAISE:
                raise ValueError("oracle total payment exceeds the money bound")
        if self.total_payment.amount_paise != total_payment_paise:
            raise ValueError("oracle total payment does not match allocation lines")

        winner_count = len({line.merchant_id for line in self.lines})
        if self.winner_count != winner_count:
            raise ValueError("oracle winner count does not match distinct allocated merchants")

        if self.status is OracleAllocationStatusV2.FEASIBLE:
            if not self.lines or self.fulfilled_quantity == 0 or self.winner_count == 0:
                raise ValueError("feasible oracle allocation requires positive allocation evidence")
            return self

        if (
            self.fulfilled_quantity != 0
            or self.total_payment != Money(amount_paise=0)
            or self.soft_preference_unit_score != 0
            or self.winner_count != 0
            or self.lines != ()
        ):
            raise ValueError("infeasible oracle allocation must have the exact zero result shape")
        return self
