from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

import clear_market.commerce as commerce
from clear_market.commerce import (
    ATTRIBUTE_VALUE_VERSION,
    PROVENANCE_VERSION,
    AttributeValue,
    AttributeValueType,
    ProvenanceLabel,
)
from clear_market.commerce.primitives import AttributeKey


class _AttributeKeyModel(BaseModel):
    value: AttributeKey


def test_commerce_public_api_is_exact() -> None:
    assert commerce.__all__ == (
        "ATTRIBUTE_VALUE_VERSION",
        "BUYER_POLICY_V2_COMMITMENT_VERSION",
        "BUYER_POLICY_V2_VERSION",
        "CATALOG_ATTRIBUTE_V2_VERSION",
        "CATALOG_PRODUCT_V2_VERSION",
        "CATALOG_SKU_V2_VERSION",
        "CONSTRAINT_PRIMITIVES_VERSION",
        "INVENTORY_LINE_V2_VERSION",
        "INVENTORY_SNAPSHOT_V2_COMMITMENT_VERSION",
        "INVENTORY_SNAPSHOT_V2_VERSION",
        "MARKET_SPEC_V2_VERSION",
        "MERCHANT_CATALOG_V2_COMMITMENT_VERSION",
        "MERCHANT_CATALOG_V2_VERSION",
        "MERCHANT_ECONOMIC_POLICY_V2_VERSION",
        "MERCHANT_OFFER_CANDIDATE_LINE_V2_VERSION",
        "MERCHANT_OFFER_CANDIDATE_V2_VERSION",
        "MERCHANT_OFFER_LINE_V2_VERSION",
        "MERCHANT_OFFER_V2_SIGNATURE_VERSION",
        "MERCHANT_OFFER_V2_VERSION",
        "MERCHANT_SIGNING_IDENTITY_V2_VERSION",
        "MERCHANT_SKU_ECONOMIC_RULE_V2_VERSION",
        "PROVENANCE_VERSION",
        "SIGNED_MERCHANT_OFFER_V2_VERSION",
        "AttributeValue",
        "AttributeValueType",
        "BuyerPolicyV2",
        "CatalogAttributeV2",
        "CatalogProductV2",
        "CatalogSkuV2",
        "ComparisonOperator",
        "HardConstraint",
        "InventoryLineV2",
        "InventorySnapshotV2",
        "MarketSpecV2",
        "MerchantCatalogV2",
        "MerchantEconomicPolicyV2",
        "MerchantOfferBuildError",
        "MerchantOfferBuildErrorCode",
        "MerchantOfferCandidateLineV2",
        "MerchantOfferCandidateV2",
        "MerchantOfferLineV2",
        "MerchantOfferSigningError",
        "MerchantOfferSigningErrorCode",
        "MerchantOfferV2",
        "MerchantOfferVerificationError",
        "MerchantOfferVerificationErrorCode",
        "MerchantSigningIdentityV2",
        "MerchantSkuEconomicRuleV2",
        "ProvenanceLabel",
        "SignedMerchantOfferParseError",
        "SignedMerchantOfferParseFailureCode",
        "SignedMerchantOfferV2",
        "SoftPreference",
        "build_and_sign_merchant_offer_v2",
        "build_merchant_offer_v2",
        "buyer_policy_v2_commitment",
        "canonical_attribute_value_bytes",
        "canonical_buyer_policy_v2_bytes",
        "canonical_hard_constraint_bytes",
        "canonical_inventory_snapshot_v2_bytes",
        "canonical_market_spec_v2_bytes",
        "canonical_merchant_catalog_v2_bytes",
        "canonical_merchant_offer_v2_bytes",
        "canonical_signed_merchant_offer_v2_bytes",
        "canonical_soft_preference_bytes",
        "inventory_snapshot_v2_commitment",
        "merchant_catalog_v2_commitment",
        "parse_canonical_signed_merchant_offer_v2",
        "verify_canonical_signed_merchant_offer_v2",
    )


def test_provenance_contract_is_exact() -> None:
    assert PROVENANCE_VERSION == "provenance-v1"
    assert tuple(ProvenanceLabel) == (
        ProvenanceLabel.VERIFIED,
        ProvenanceLabel.ATTESTED,
        ProvenanceLabel.CLAIMED,
        ProvenanceLabel.DERIVED,
        ProvenanceLabel.PREDICTED,
    )
    assert tuple(label.value for label in ProvenanceLabel) == (
        "VERIFIED",
        "ATTESTED",
        "CLAIMED",
        "DERIVED",
        "PREDICTED",
    )


def test_attribute_value_type_contract_is_exact() -> None:
    assert ATTRIBUTE_VALUE_VERSION == "attribute-value-v1"
    assert tuple(AttributeValueType) == (
        AttributeValueType.STRING,
        AttributeValueType.INTEGER,
        AttributeValueType.BOOLEAN,
    )
    assert tuple(value_type.value for value_type in AttributeValueType) == (
        "string",
        "integer",
        "boolean",
    )


@pytest.mark.parametrize(
    "value",
    [
        "brand",
        "ram_gb",
        "delivery.days",
        "sla-hours",
        "battery_capacity_mah",
        "a",
        "a" + "0" * 127,
    ],
)
def test_attribute_key_accepts_exact_canonical_strings(value: str) -> None:
    validated = _AttributeKeyModel(value=value).value

    assert validated == value
    assert type(validated) is str


@pytest.mark.parametrize(
    "value",
    [
        "",
        " Brand",
        "brand ",
        "Brand",
        "RAM_GB",
        ".brand",
        "brand/value",
        "brand value",
        "bränd",
        "a" + "0" * 128,
        1,
        b"brand",
        None,
    ],
)
def test_attribute_key_rejects_noncanonical_input(value: object) -> None:
    with pytest.raises(ValidationError):
        _AttributeKeyModel(value=value)


@pytest.mark.parametrize(
    ("value_type", "value", "python_type"),
    [
        (AttributeValueType.STRING, "clear", str),
        (AttributeValueType.INTEGER, 16, int),
        (AttributeValueType.BOOLEAN, True, bool),
    ],
)
def test_attribute_value_accepts_exact_declared_scalar(
    value_type: AttributeValueType,
    value: str | int | bool,
    python_type: type[object],
) -> None:
    attribute = AttributeValue(value_type=value_type, value=value)

    assert attribute.schema_version == "1"
    assert attribute.attribute_value_version == "attribute-value-v1"
    assert attribute.value_type is value_type
    assert type(attribute.value) is python_type
    assert attribute.value == value


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        (AttributeValueType.STRING, 1),
        (AttributeValueType.STRING, True),
        (AttributeValueType.INTEGER, "1"),
        (AttributeValueType.INTEGER, True),
        (AttributeValueType.BOOLEAN, 1),
        (AttributeValueType.BOOLEAN, "true"),
    ],
)
def test_attribute_value_rejects_declared_type_mismatch(
    value_type: AttributeValueType,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        AttributeValue(value_type=value_type, value=value)


@pytest.mark.parametrize(
    "value",
    [
        1.0,
        Decimal("1"),
        ["value"],
        ("value",),
        {"value": 1},
        b"value",
        None,
    ],
)
def test_attribute_value_rejects_unsupported_scalars(value: object) -> None:
    with pytest.raises(ValidationError):
        AttributeValue(value_type=AttributeValueType.STRING, value=value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 1),
        ("schema_version", "2"),
        ("attribute_value_version", "attribute-value-v2"),
    ],
)
def test_attribute_value_rejects_invalid_versions(field: str, value: object) -> None:
    values: dict[str, object] = {
        "value_type": AttributeValueType.STRING,
        "value": "clear",
        field: value,
    }

    with pytest.raises(ValidationError):
        AttributeValue(**values)


def test_attribute_value_is_frozen() -> None:
    attribute = AttributeValue(value_type=AttributeValueType.STRING, value="clear")

    with pytest.raises(ValidationError):
        attribute.value = "changed"


def test_attribute_value_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AttributeValue(
            value_type=AttributeValueType.STRING,
            value="clear",
            unit="not-permitted",
        )
