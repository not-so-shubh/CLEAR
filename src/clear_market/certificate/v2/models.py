import re
from enum import StrEnum
from typing import Annotated, Final, Literal, Self, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from clear_market.commerce.authentication import MerchantSigningIdentityV2, SignedMerchantOfferV2
from clear_market.commerce.catalog import InventorySnapshotV2, MerchantCatalogV2
from clear_market.commerce.market import MAX_SOFT_PREFERENCES, BuyerPolicyV2
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
    UTCDateTime,
)

MERCHANT_OFFER_EVIDENCE_V2_VERSION: Final[str] = "merchant-offer-evidence-v2"
ALLOCATION_CERTIFICATE_V2_VERSION: Final[str] = "allocation-certificate-v2"

_MAX_ALLOCATION_CLAIM_LINES: Final[int] = MAX_SELLERS * MAX_OFFER_LINES
_SHA256_HEX_PATTERN = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


class AllocationClaimStatusV2(StrEnum):
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"


class MerchantOfferAdmissionDecisionV2(StrEnum):
    ADMITTED = "ADMITTED"
    REJECTED = "REJECTED"


def _validate_sha256_hex(value: object) -> str:
    if type(value) is not str or _SHA256_HEX_PATTERN.fullmatch(value) is None:
        raise ValueError("commitment must be lowercase SHA-256 hex")
    return value


def _fresh_exact_model(
    value: object,
    expected_type: type[BaseModel],
    message: str,
    *,
    preserve_nested_models: bool = False,
) -> BaseModel:
    if type(value) is not expected_type:
        raise ValueError(message)
    try:
        if preserve_nested_models:
            field_values = {
                field_name: value.__dict__[field_name] for field_name in expected_type.model_fields
            }
        else:
            field_values = value.model_dump(mode="python", warnings=False)
        return expected_type.model_validate(field_values)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError(message) from None


def _fresh_exact_money(value: object) -> Money:
    return cast(
        Money,
        _fresh_exact_model(value, Money, "money must be a valid exact Money value"),
    )


def _fresh_exact_buyer_policy(value: object) -> BuyerPolicyV2:
    return cast(
        BuyerPolicyV2,
        _fresh_exact_model(
            value,
            BuyerPolicyV2,
            "buyer policy must be a valid exact BuyerPolicyV2 value",
        ),
    )


def _fresh_exact_signing_identity(value: object) -> MerchantSigningIdentityV2:
    return cast(
        MerchantSigningIdentityV2,
        _fresh_exact_model(
            value,
            MerchantSigningIdentityV2,
            "signing identity must be a valid exact MerchantSigningIdentityV2 value",
        ),
    )


def _fresh_exact_catalog(value: object) -> MerchantCatalogV2:
    return cast(
        MerchantCatalogV2,
        _fresh_exact_model(
            value,
            MerchantCatalogV2,
            "catalog must be a valid exact MerchantCatalogV2 value",
        ),
    )


def _fresh_exact_inventory(value: object) -> InventorySnapshotV2:
    return cast(
        InventorySnapshotV2,
        _fresh_exact_model(
            value,
            InventorySnapshotV2,
            "inventory must be a valid exact InventorySnapshotV2 value",
        ),
    )


def _fresh_exact_signed_offer(value: object) -> SignedMerchantOfferV2:
    return cast(
        SignedMerchantOfferV2,
        _fresh_exact_model(
            value,
            SignedMerchantOfferV2,
            "signed offer must be a valid exact SignedMerchantOfferV2 value",
        ),
    )


def _fresh_exact_allocation_claim(value: object) -> "AllocationClaimV2":
    return cast(
        AllocationClaimV2,
        _fresh_exact_model(
            value,
            AllocationClaimV2,
            "allocation must be a valid exact AllocationClaimV2 value",
            preserve_nested_models=True,
        ),
    )


def _fresh_allocation_claim_lines(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("allocation claim lines must be supplied as an exact tuple")
    lines = cast(tuple[object, ...], value)
    return tuple(
        cast(
            AllocationClaimLineV2,
            _fresh_exact_model(
                line,
                AllocationClaimLineV2,
                "allocation claim lines must contain valid exact AllocationClaimLineV2 values",
                preserve_nested_models=True,
            ),
        )
        for line in lines
    )


def _fresh_merchant_offer_evidence(value: object) -> "MerchantOfferEvidenceV2":
    return cast(
        MerchantOfferEvidenceV2,
        _fresh_exact_model(
            value,
            MerchantOfferEvidenceV2,
            "evidence must be a valid exact MerchantOfferEvidenceV2 value",
            preserve_nested_models=True,
        ),
    )


def _fresh_evidence_tuple(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("merchant offer evidence must be supplied as an exact tuple")
    evidence_values = cast(tuple[object, ...], value)
    return tuple(_fresh_merchant_offer_evidence(evidence) for evidence in evidence_values)


type _CommitmentSha256 = Annotated[str, BeforeValidator(_validate_sha256_hex)]
type _SoftPreferenceUnitScore = Annotated[
    int,
    Field(strict=True, ge=0, le=MAX_QUANTITY * MAX_SOFT_PREFERENCES),
]
type _WinnerCount = Annotated[int, Field(strict=True, ge=0, le=MAX_SELLERS)]
type _AllocationClaimLines = Annotated[
    tuple["AllocationClaimLineV2", ...],
    BeforeValidator(_fresh_allocation_claim_lines),
    Field(max_length=_MAX_ALLOCATION_CLAIM_LINES),
]
type _MerchantOfferEvidenceTuple = Annotated[
    tuple["MerchantOfferEvidenceV2", ...],
    BeforeValidator(_fresh_evidence_tuple),
]


class AllocationClaimLineV2(BaseModel):
    """Certificate-owned wire claim for one pay-as-bid allocation obligation."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["2"] = "2"
    allocation_line_version: Literal["allocation-line-v2"] = "allocation-line-v2"
    offer_id: CanonicalUUID4
    merchant_id: CanonicalUUID4
    sku_id: CanonicalUUID4
    allocated_quantity: PositiveQuantity
    unit_payment: Money
    line_payment: Money

    @field_validator("unit_payment", "line_payment", mode="before")
    @classmethod
    def _validate_money(cls, value: object) -> Money:
        return _fresh_exact_money(value)

    @model_validator(mode="after")
    def _validate_line_payment(self) -> Self:
        try:
            expected_payment = self.unit_payment.checked_multiply(self.allocated_quantity)
        except MoneyOverflowError as error:
            raise ValueError("allocation claim line payment exceeds the money bound") from error
        if self.line_payment != expected_payment:
            raise ValueError("allocation claim line payment does not match checked multiplication")
        return self


class AllocationClaimV2(BaseModel):
    """Certificate-owned allocation wire claim without production-solver authority."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["2"] = "2"
    allocation_version: Literal["allocation-v2"] = "allocation-v2"
    mechanism_version: Literal["heterogeneous-pay-as-bid-v2"] = "heterogeneous-pay-as-bid-v2"
    objective_version: Literal["quantity-cost-soft-objective-v2"] = (
        "quantity-cost-soft-objective-v2"
    )
    market_id: CanonicalUUID4
    buyer_policy_commitment_version: Literal["sha256-buyer-policy-v2-clear-json-v1"] = (
        "sha256-buyer-policy-v2-clear-json-v1"
    )
    buyer_policy_commitment_sha256: _CommitmentSha256
    status: AllocationClaimStatusV2
    fulfilled_quantity: Quantity
    total_payment: Money
    soft_preference_unit_score: _SoftPreferenceUnitScore
    winner_count: _WinnerCount
    lines: _AllocationClaimLines

    @field_validator("total_payment", mode="before")
    @classmethod
    def _validate_total_payment(cls, value: object) -> Money:
        return _fresh_exact_money(value)

    @field_validator("lines")
    @classmethod
    def _validate_and_normalize_lines(
        cls,
        lines: tuple[AllocationClaimLineV2, ...],
    ) -> tuple[AllocationClaimLineV2, ...]:
        offer_sku_keys = tuple((line.offer_id, line.sku_id) for line in lines)
        merchant_sku_keys = tuple((line.merchant_id, line.sku_id) for line in lines)
        if len(set(offer_sku_keys)) != len(offer_sku_keys):
            raise ValueError("allocation claim lines must use unique offer and SKU pairs")
        if len(set(merchant_sku_keys)) != len(merchant_sku_keys):
            raise ValueError("allocation claim lines must use unique merchant and SKU pairs")

        offers_by_merchant: dict[str, set[str]] = {}
        merchants_by_offer: dict[str, set[str]] = {}
        for line in lines:
            offers_by_merchant.setdefault(line.merchant_id, set()).add(line.offer_id)
            merchants_by_offer.setdefault(line.offer_id, set()).add(line.merchant_id)
        if any(len(offer_ids) != 1 for offer_ids in offers_by_merchant.values()):
            raise ValueError("one claim merchant must map to one offer")
        if any(len(merchant_ids) != 1 for merchant_ids in merchants_by_offer.values()):
            raise ValueError("one claim offer must map to one merchant")

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
            raise ValueError("claimed fulfilled quantity does not match claim lines")

        total_payment_paise = 0
        for line in self.lines:
            total_payment_paise += line.line_payment.amount_paise
            if total_payment_paise > MAX_MONEY_PAISE:
                raise ValueError("claimed total payment exceeds the money bound")
        if self.total_payment.amount_paise != total_payment_paise:
            raise ValueError("claimed total payment does not match claim lines")

        winner_count = len({line.merchant_id for line in self.lines})
        if self.winner_count != winner_count:
            raise ValueError("claimed winner count does not match represented merchants")

        if self.status is AllocationClaimStatusV2.FEASIBLE:
            if not self.lines or self.fulfilled_quantity == 0 or self.winner_count == 0:
                raise ValueError("feasible claim requires positive allocation evidence")
            return self

        if (
            self.fulfilled_quantity != 0
            or self.total_payment != Money(amount_paise=0)
            or self.soft_preference_unit_score != 0
            or self.winner_count != 0
            or self.lines != ()
        ):
            raise ValueError("infeasible claim must have the exact zero result shape")
        return self


class MerchantOfferEvidenceV2(BaseModel):
    """Public offer evidence whose embedded signing identity is a claim, not a trust root.

    A verifier must compare the embedded identity and key with independently trusted identity
    material before treating the signed offer as authenticated. The receipt time and admission
    decision are recorded transcript claims, not authorization. Slice 19B replays them in tuple
    order, treating receipt at the policy deadline as inclusive and later receipt as late.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["2"] = "2"
    merchant_offer_evidence_version: Literal["merchant-offer-evidence-v2"] = (
        "merchant-offer-evidence-v2"
    )
    received_at: UTCDateTime
    admission_decision: MerchantOfferAdmissionDecisionV2
    signing_identity: Annotated[
        MerchantSigningIdentityV2,
        BeforeValidator(_fresh_exact_signing_identity),
    ]
    catalog: Annotated[MerchantCatalogV2, BeforeValidator(_fresh_exact_catalog)]
    inventory: Annotated[InventorySnapshotV2, BeforeValidator(_fresh_exact_inventory)]
    signed_offer: Annotated[SignedMerchantOfferV2, BeforeValidator(_fresh_exact_signed_offer)]


class AllocationCertificateV2(BaseModel):
    """Canonical structured evidence; construction is not verification or financial authority."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["2"] = "2"
    certificate_version: Literal["allocation-certificate-v2"] = "allocation-certificate-v2"
    certificate_id: CanonicalUUID4
    canonicalization_version: Literal["clear-json-v1"] = "clear-json-v1"
    buyer_policy_commitment_version: Literal["sha256-buyer-policy-v2-clear-json-v1"] = (
        "sha256-buyer-policy-v2-clear-json-v1"
    )
    merchant_offer_signature_version: Literal["ed25519-raw-merchant-offer-v2-clear-json-v1"] = (
        "ed25519-raw-merchant-offer-v2-clear-json-v1"
    )
    buyer_policy: Annotated[BuyerPolicyV2, BeforeValidator(_fresh_exact_buyer_policy)]
    buyer_policy_commitment_sha256: _CommitmentSha256
    merchant_offer_evidence: _MerchantOfferEvidenceTuple
    allocation: Annotated[AllocationClaimV2, BeforeValidator(_fresh_exact_allocation_claim)]
