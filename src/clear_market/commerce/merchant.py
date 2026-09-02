import re
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Final, Literal, Never, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from clear_market.commerce.catalog import (
    MAX_ATTRIBUTES_PER_SKU,
    CatalogAttributeV2,
    InventorySnapshotV2,
    MerchantCatalogV2,
)
from clear_market.commerce.catalog_serialization import (
    canonical_inventory_snapshot_v2_bytes,
    canonical_merchant_catalog_v2_bytes,
)
from clear_market.commerce.market import BuyerPolicyV2
from clear_market.commerce.market_serialization import canonical_buyer_policy_v2_bytes
from clear_market.commerce.primitives import ProvenanceLabel
from clear_market.domain import MAX_MONEY_PAISE, CanonicalUUID4, Money, PositiveQuantity

MERCHANT_SKU_ECONOMIC_RULE_V2_VERSION: Final[str] = "merchant-sku-economic-rule-v2"
MERCHANT_ECONOMIC_POLICY_V2_VERSION: Final[str] = "merchant-economic-policy-v2"
MERCHANT_OFFER_CANDIDATE_LINE_V2_VERSION: Final[str] = "merchant-offer-candidate-line-v2"
MERCHANT_OFFER_CANDIDATE_V2_VERSION: Final[str] = "merchant-offer-candidate-v2"
MERCHANT_OFFER_LINE_V2_VERSION: Final[str] = "merchant-offer-line-v2"
MERCHANT_OFFER_V2_VERSION: Final[str] = "merchant-offer-v2"

BUYER_POLICY_V2_COMMITMENT_VERSION: Final[str] = "sha256-buyer-policy-v2-clear-json-v1"
MERCHANT_CATALOG_V2_COMMITMENT_VERSION: Final[str] = "sha256-merchant-catalog-v2-clear-json-v1"
INVENTORY_SNAPSHOT_V2_COMMITMENT_VERSION: Final[str] = "sha256-inventory-snapshot-v2-clear-json-v1"

MAX_MERCHANT_ECONOMIC_RULES: Final[int] = 1_024
MAX_OFFER_LINES: Final[int] = 64

_SHA256_HEX_PATTERN = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


def _require_tuple(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("collection must be supplied as a tuple")
    return value


def _validate_sha256_hex(value: object) -> str:
    if type(value) is not str or _SHA256_HEX_PATTERN.fullmatch(value) is None:
        raise ValueError("commitment digest must be lowercase SHA-256 hex")
    return value


type _CommitmentSha256 = Annotated[str, BeforeValidator(_validate_sha256_hex)]
type _MerchantSkuEconomicRules = Annotated[
    tuple["MerchantSkuEconomicRuleV2", ...],
    BeforeValidator(_require_tuple),
    Field(min_length=1, max_length=MAX_MERCHANT_ECONOMIC_RULES),
]
type _MerchantOfferCandidateLines = Annotated[
    tuple["MerchantOfferCandidateLineV2", ...],
    BeforeValidator(_require_tuple),
    Field(min_length=1, max_length=MAX_OFFER_LINES),
]
type _OfferAttributes = Annotated[
    tuple[CatalogAttributeV2, ...],
    BeforeValidator(_require_tuple),
    Field(max_length=MAX_ATTRIBUTES_PER_SKU),
]
type _MerchantOfferLines = Annotated[
    tuple["MerchantOfferLineV2", ...],
    BeforeValidator(_require_tuple),
    Field(min_length=1, max_length=MAX_OFFER_LINES),
]


class MerchantSkuEconomicRuleV2(BaseModel):
    """Internal merchant floor and quantity cap for one permitted SKU."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["2"] = "2"
    merchant_sku_economic_rule_version: Literal["merchant-sku-economic-rule-v2"] = (
        "merchant-sku-economic-rule-v2"
    )
    sku_id: CanonicalUUID4
    unit_cost_basis: Money
    minimum_margin: Money
    max_quantity_per_offer: PositiveQuantity

    @model_validator(mode="after")
    def _validate_floor_bound(self) -> Self:
        if self.unit_cost_basis.amount_paise + self.minimum_margin.amount_paise > MAX_MONEY_PAISE:
            raise ValueError("merchant economic floor exceeds the money bound")
        return self


class MerchantEconomicPolicyV2(BaseModel):
    """Internal merchant SKU allowlist with deterministic economic safety rules."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["2"] = "2"
    merchant_economic_policy_version: Literal["merchant-economic-policy-v2"] = (
        "merchant-economic-policy-v2"
    )
    economic_policy_id: CanonicalUUID4
    merchant_id: CanonicalUUID4
    catalog_id: CanonicalUUID4
    sku_rules: _MerchantSkuEconomicRules

    @field_validator("sku_rules")
    @classmethod
    def _validate_and_normalize_sku_rules(
        cls,
        rules: tuple[MerchantSkuEconomicRuleV2, ...],
    ) -> tuple[MerchantSkuEconomicRuleV2, ...]:
        sku_ids = tuple(rule.sku_id for rule in rules)
        if len(set(sku_ids)) != len(sku_ids):
            raise ValueError("merchant economic rules must use unique SKU IDs")
        return tuple(sorted(rules, key=lambda rule: rule.sku_id))


class MerchantOfferCandidateLineV2(BaseModel):
    """Untrusted proposal values for one SKU."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["2"] = "2"
    merchant_offer_candidate_line_version: Literal["merchant-offer-candidate-line-v2"] = (
        "merchant-offer-candidate-line-v2"
    )
    sku_id: CanonicalUUID4
    proposed_quantity: PositiveQuantity
    proposed_unit_price: Money


class MerchantOfferCandidateV2(BaseModel):
    """Identity-free untrusted proposal whose lines are validated by the builder."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["2"] = "2"
    merchant_offer_candidate_version: Literal["merchant-offer-candidate-v2"] = (
        "merchant-offer-candidate-v2"
    )
    lines: _MerchantOfferCandidateLines

    @field_validator("lines")
    @classmethod
    def _validate_and_normalize_lines(
        cls,
        lines: tuple[MerchantOfferCandidateLineV2, ...],
    ) -> tuple[MerchantOfferCandidateLineV2, ...]:
        sku_ids = tuple(line.sku_id for line in lines)
        if len(set(sku_ids)) != len(sku_ids):
            raise ValueError("candidate lines must use unique SKU IDs")
        return tuple(sorted(lines, key=lambda line: line.sku_id))


class MerchantOfferLineV2(BaseModel):
    """Validated commercial ask with catalog and inventory evidence copied from source state."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["2"] = "2"
    merchant_offer_line_version: Literal["merchant-offer-line-v2"] = "merchant-offer-line-v2"
    sku_id: CanonicalUUID4
    max_offer_quantity: PositiveQuantity
    unit_price: Money
    attributes: _OfferAttributes
    inventory_provenance: ProvenanceLabel
    inventory_evidence_reference_id: CanonicalUUID4

    @field_validator("attributes")
    @classmethod
    def _validate_and_normalize_attributes(
        cls,
        attributes: tuple[CatalogAttributeV2, ...],
    ) -> tuple[CatalogAttributeV2, ...]:
        attribute_keys = tuple(attribute.attribute_key for attribute in attributes)
        if len(set(attribute_keys)) != len(attribute_keys):
            raise ValueError("offer attributes must use unique attribute keys")
        return tuple(sorted(attributes, key=lambda attribute: attribute.attribute_key))


class MerchantOfferV2(BaseModel):
    """Unsigned, source-bound merchant commercial offer."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["2"] = "2"
    merchant_offer_version: Literal["merchant-offer-v2"] = "merchant-offer-v2"
    offer_id: CanonicalUUID4
    market_id: CanonicalUUID4
    merchant_id: CanonicalUUID4
    catalog_id: CanonicalUUID4
    inventory_snapshot_id: CanonicalUUID4
    buyer_policy_commitment_version: Literal["sha256-buyer-policy-v2-clear-json-v1"] = (
        "sha256-buyer-policy-v2-clear-json-v1"
    )
    buyer_policy_commitment_sha256: _CommitmentSha256
    merchant_catalog_commitment_version: Literal["sha256-merchant-catalog-v2-clear-json-v1"] = (
        "sha256-merchant-catalog-v2-clear-json-v1"
    )
    merchant_catalog_commitment_sha256: _CommitmentSha256
    inventory_snapshot_commitment_version: Literal["sha256-inventory-snapshot-v2-clear-json-v1"] = (
        "sha256-inventory-snapshot-v2-clear-json-v1"
    )
    inventory_snapshot_commitment_sha256: _CommitmentSha256
    lines: _MerchantOfferLines

    @field_validator("lines")
    @classmethod
    def _validate_and_normalize_lines(
        cls,
        lines: tuple[MerchantOfferLineV2, ...],
    ) -> tuple[MerchantOfferLineV2, ...]:
        sku_ids = tuple(line.sku_id for line in lines)
        if len(set(sku_ids)) != len(sku_ids):
            raise ValueError("offer lines must use unique SKU IDs")
        return tuple(sorted(lines, key=lambda line: line.sku_id))


class MerchantOfferBuildErrorCode(StrEnum):
    MERCHANT_NOT_ELIGIBLE = "MERCHANT_NOT_ELIGIBLE"
    INVENTORY_MERCHANT_MISMATCH = "INVENTORY_MERCHANT_MISMATCH"
    INVENTORY_CATALOG_MISMATCH = "INVENTORY_CATALOG_MISMATCH"
    ECONOMIC_POLICY_MERCHANT_MISMATCH = "ECONOMIC_POLICY_MERCHANT_MISMATCH"
    ECONOMIC_POLICY_CATALOG_MISMATCH = "ECONOMIC_POLICY_CATALOG_MISMATCH"
    ECONOMIC_POLICY_UNKNOWN_SKU = "ECONOMIC_POLICY_UNKNOWN_SKU"
    CANDIDATE_UNKNOWN_CATALOG_SKU = "CANDIDATE_UNKNOWN_CATALOG_SKU"
    CANDIDATE_MISSING_INVENTORY = "CANDIDATE_MISSING_INVENTORY"
    CANDIDATE_NOT_ALLOWED_BY_POLICY = "CANDIDATE_NOT_ALLOWED_BY_POLICY"
    CANDIDATE_EXCEEDS_INVENTORY = "CANDIDATE_EXCEEDS_INVENTORY"
    CANDIDATE_EXCEEDS_POLICY_QUANTITY = "CANDIDATE_EXCEEDS_POLICY_QUANTITY"
    CANDIDATE_PRICE_BELOW_FLOOR = "CANDIDATE_PRICE_BELOW_FLOOR"


class MerchantOfferBuildError(ValueError):
    """Stable deterministic merchant-offer construction failure."""

    def __init__(self, code: MerchantOfferBuildErrorCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> MerchantOfferBuildErrorCode:
        return self._code


def buyer_policy_v2_commitment(value: BuyerPolicyV2) -> str:
    if type(value) is not BuyerPolicyV2:
        raise TypeError("value must be exactly a BuyerPolicyV2")
    return sha256(canonical_buyer_policy_v2_bytes(value)).hexdigest()


def merchant_catalog_v2_commitment(value: MerchantCatalogV2) -> str:
    if type(value) is not MerchantCatalogV2:
        raise TypeError("value must be exactly a MerchantCatalogV2")
    return sha256(canonical_merchant_catalog_v2_bytes(value)).hexdigest()


def inventory_snapshot_v2_commitment(value: InventorySnapshotV2) -> str:
    if type(value) is not InventorySnapshotV2:
        raise TypeError("value must be exactly an InventorySnapshotV2")
    return sha256(canonical_inventory_snapshot_v2_bytes(value)).hexdigest()


def _raise_build_error(code: MerchantOfferBuildErrorCode) -> Never:
    raise MerchantOfferBuildError(code)


def build_merchant_offer_v2(
    *,
    offer_id: CanonicalUUID4,
    buyer_policy: BuyerPolicyV2,
    catalog: MerchantCatalogV2,
    inventory: InventorySnapshotV2,
    economic_policy: MerchantEconomicPolicyV2,
    candidate: MerchantOfferCandidateV2,
) -> MerchantOfferV2:
    """Build a deterministic source-bound offer after merchant safety validation."""
    if type(buyer_policy) is not BuyerPolicyV2:
        raise TypeError("buyer_policy must be exactly a BuyerPolicyV2")
    if type(catalog) is not MerchantCatalogV2:
        raise TypeError("catalog must be exactly a MerchantCatalogV2")
    if type(inventory) is not InventorySnapshotV2:
        raise TypeError("inventory must be exactly an InventorySnapshotV2")
    if type(economic_policy) is not MerchantEconomicPolicyV2:
        raise TypeError("economic_policy must be exactly a MerchantEconomicPolicyV2")
    if type(candidate) is not MerchantOfferCandidateV2:
        raise TypeError("candidate must be exactly a MerchantOfferCandidateV2")

    if catalog.merchant_id not in buyer_policy.eligible_merchant_ids:
        _raise_build_error(MerchantOfferBuildErrorCode.MERCHANT_NOT_ELIGIBLE)
    if catalog.merchant_id != inventory.merchant_id:
        _raise_build_error(MerchantOfferBuildErrorCode.INVENTORY_MERCHANT_MISMATCH)
    if catalog.catalog_id != inventory.catalog_id:
        _raise_build_error(MerchantOfferBuildErrorCode.INVENTORY_CATALOG_MISMATCH)
    if catalog.merchant_id != economic_policy.merchant_id:
        _raise_build_error(MerchantOfferBuildErrorCode.ECONOMIC_POLICY_MERCHANT_MISMATCH)
    if catalog.catalog_id != economic_policy.catalog_id:
        _raise_build_error(MerchantOfferBuildErrorCode.ECONOMIC_POLICY_CATALOG_MISMATCH)

    catalog_skus = {sku.sku_id: sku for sku in catalog.skus}
    inventory_lines = {line.sku_id: line for line in inventory.lines}
    economic_rules = {rule.sku_id: rule for rule in economic_policy.sku_rules}

    if any(rule.sku_id not in catalog_skus for rule in economic_policy.sku_rules):
        _raise_build_error(MerchantOfferBuildErrorCode.ECONOMIC_POLICY_UNKNOWN_SKU)

    output_lines: list[MerchantOfferLineV2] = []
    for candidate_line in candidate.lines:
        catalog_sku = catalog_skus.get(candidate_line.sku_id)
        if catalog_sku is None:
            _raise_build_error(MerchantOfferBuildErrorCode.CANDIDATE_UNKNOWN_CATALOG_SKU)

        inventory_line = inventory_lines.get(candidate_line.sku_id)
        if inventory_line is None:
            _raise_build_error(MerchantOfferBuildErrorCode.CANDIDATE_MISSING_INVENTORY)

        economic_rule = economic_rules.get(candidate_line.sku_id)
        if economic_rule is None:
            _raise_build_error(MerchantOfferBuildErrorCode.CANDIDATE_NOT_ALLOWED_BY_POLICY)

        if candidate_line.proposed_quantity > inventory_line.quantity_available:
            _raise_build_error(MerchantOfferBuildErrorCode.CANDIDATE_EXCEEDS_INVENTORY)
        if candidate_line.proposed_quantity > economic_rule.max_quantity_per_offer:
            _raise_build_error(MerchantOfferBuildErrorCode.CANDIDATE_EXCEEDS_POLICY_QUANTITY)

        minimum_unit_price = (
            economic_rule.unit_cost_basis.amount_paise + economic_rule.minimum_margin.amount_paise
        )
        if candidate_line.proposed_unit_price.amount_paise < minimum_unit_price:
            _raise_build_error(MerchantOfferBuildErrorCode.CANDIDATE_PRICE_BELOW_FLOOR)

        output_lines.append(
            MerchantOfferLineV2(
                sku_id=candidate_line.sku_id,
                max_offer_quantity=candidate_line.proposed_quantity,
                unit_price=candidate_line.proposed_unit_price,
                attributes=catalog_sku.attributes,
                inventory_provenance=inventory_line.provenance,
                inventory_evidence_reference_id=inventory_line.evidence_reference_id,
            )
        )

    return MerchantOfferV2(
        offer_id=offer_id,
        market_id=buyer_policy.market_spec.market_id,
        merchant_id=catalog.merchant_id,
        catalog_id=catalog.catalog_id,
        inventory_snapshot_id=inventory.snapshot_id,
        buyer_policy_commitment_sha256=buyer_policy_v2_commitment(buyer_policy),
        merchant_catalog_commitment_sha256=merchant_catalog_v2_commitment(catalog),
        inventory_snapshot_commitment_sha256=inventory_snapshot_v2_commitment(inventory),
        lines=tuple(output_lines),
    )
