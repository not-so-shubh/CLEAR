from clear_market.canonical import CANONICALIZATION_VERSION, canonical_json_bytes
from clear_market.commerce.authentication import SignedMerchantOfferV2
from clear_market.commerce.catalog import CatalogAttributeV2
from clear_market.commerce.merchant import MerchantOfferLineV2, MerchantOfferV2
from clear_market.commerce.primitives import AttributeValue


def _attribute_value_payload(value: AttributeValue) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "attribute_value_version": value.attribute_value_version,
        "value_type": value.value_type.value,
        "value": value.value,
    }


def _catalog_attribute_payload(value: CatalogAttributeV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "catalog_attribute_version": value.catalog_attribute_version,
        "attribute_key": value.attribute_key,
        "value": _attribute_value_payload(value.value),
        "provenance": value.provenance.value,
        "evidence_reference_id": value.evidence_reference_id,
    }


def _merchant_offer_line_payload(value: MerchantOfferLineV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "merchant_offer_line_version": value.merchant_offer_line_version,
        "sku_id": value.sku_id,
        "max_offer_quantity": value.max_offer_quantity,
        "unit_price": {
            "amount_paise": value.unit_price.amount_paise,
            "currency": value.unit_price.currency.value,
        },
        "attributes": [_catalog_attribute_payload(attribute) for attribute in value.attributes],
        "inventory_provenance": value.inventory_provenance.value,
        "inventory_evidence_reference_id": value.inventory_evidence_reference_id,
    }


def _merchant_offer_payload(value: MerchantOfferV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "merchant_offer_version": value.merchant_offer_version,
        "offer_id": value.offer_id,
        "market_id": value.market_id,
        "merchant_id": value.merchant_id,
        "catalog_id": value.catalog_id,
        "inventory_snapshot_id": value.inventory_snapshot_id,
        "buyer_policy_commitment_version": value.buyer_policy_commitment_version,
        "buyer_policy_commitment_sha256": value.buyer_policy_commitment_sha256,
        "merchant_catalog_commitment_version": value.merchant_catalog_commitment_version,
        "merchant_catalog_commitment_sha256": value.merchant_catalog_commitment_sha256,
        "inventory_snapshot_commitment_version": value.inventory_snapshot_commitment_version,
        "inventory_snapshot_commitment_sha256": value.inventory_snapshot_commitment_sha256,
        "lines": [_merchant_offer_line_payload(line) for line in value.lines],
    }


def canonical_signed_merchant_offer_v2_bytes(value: SignedMerchantOfferV2) -> bytes:
    """Serialize the signed offer and every nested protected field explicitly."""
    if type(value) is not SignedMerchantOfferV2:
        raise TypeError("value must be exactly a SignedMerchantOfferV2")
    return canonical_json_bytes(
        {
            "canonicalization_version": CANONICALIZATION_VERSION,
            "payload_type": "signed_merchant_offer_v2",
            "payload": {
                "schema_version": value.schema_version,
                "signed_merchant_offer_version": value.signed_merchant_offer_version,
                "signature_version": value.signature_version,
                "offer": _merchant_offer_payload(value.offer),
                "signature_hex": value.signature_hex,
            },
        }
    )
