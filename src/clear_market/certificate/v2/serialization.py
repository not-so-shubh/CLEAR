from clear_market.canonical import (
    CANONICALIZATION_VERSION,
    canonical_json_bytes,
    canonical_utc_datetime,
)
from clear_market.certificate.v2.models import (
    AllocationCertificateV2,
    AllocationClaimLineV2,
    AllocationClaimV2,
    MerchantOfferEvidenceV2,
)
from clear_market.commerce.authentication import MerchantSigningIdentityV2, SignedMerchantOfferV2
from clear_market.commerce.catalog import (
    CatalogAttributeV2,
    CatalogProductV2,
    CatalogSkuV2,
    InventoryLineV2,
    InventorySnapshotV2,
    MerchantCatalogV2,
)
from clear_market.commerce.constraints import HardConstraint, SoftPreference
from clear_market.commerce.market import BuyerPolicyV2, MarketSpecV2
from clear_market.commerce.merchant import MerchantOfferLineV2, MerchantOfferV2
from clear_market.commerce.primitives import AttributeValue
from clear_market.domain import Money


def _money_payload(value: Money) -> dict[str, object]:
    return {
        "amount_paise": value.amount_paise,
        "currency": value.currency.value,
    }


def _attribute_value_payload(value: AttributeValue) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "attribute_value_version": value.attribute_value_version,
        "value_type": value.value_type.value,
        "value": value.value,
    }


def _hard_constraint_payload(value: HardConstraint) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "constraint_primitives_version": value.constraint_primitives_version,
        "constraint_id": value.constraint_id,
        "attribute_key": value.attribute_key,
        "operator": value.operator.value,
        "operand": _attribute_value_payload(value.operand),
        "allowed_provenance": [label.value for label in value.allowed_provenance],
    }


def _soft_preference_payload(value: SoftPreference) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "constraint_primitives_version": value.constraint_primitives_version,
        "preference_id": value.preference_id,
        "attribute_key": value.attribute_key,
        "operator": value.operator.value,
        "operand": _attribute_value_payload(value.operand),
        "allowed_provenance": [label.value for label in value.allowed_provenance],
    }


def _market_spec_payload(value: MarketSpecV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "market_spec_version": value.market_spec_version,
        "market_id": value.market_id,
        "buyer_id": value.buyer_id,
        "requested_quantity": value.requested_quantity,
        "minimum_acceptable_quantity": value.minimum_acceptable_quantity,
        "max_winners": value.max_winners,
        "hard_constraints": [
            _hard_constraint_payload(constraint) for constraint in value.hard_constraints
        ],
        "soft_preferences": [
            _soft_preference_payload(preference) for preference in value.soft_preferences
        ],
    }


def _buyer_policy_payload(value: BuyerPolicyV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "buyer_policy_version": value.buyer_policy_version,
        "market_spec": _market_spec_payload(value.market_spec),
        "max_total_payment": _money_payload(value.max_total_payment),
        "eligible_merchant_ids": list(value.eligible_merchant_ids),
        "offer_deadline": canonical_utc_datetime(value.offer_deadline),
        "mechanism_version": value.mechanism_version,
        "objective_version": value.objective_version,
    }


def _signing_identity_payload(value: MerchantSigningIdentityV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "merchant_signing_identity_version": value.merchant_signing_identity_version,
        "merchant_id": value.merchant_id,
        "ed25519_public_key_hex": value.ed25519_public_key_hex,
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


def _catalog_product_payload(value: CatalogProductV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "catalog_product_version": value.catalog_product_version,
        "product_id": value.product_id,
        "display_name": value.display_name,
        "description": value.description,
    }


def _catalog_sku_payload(value: CatalogSkuV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "catalog_sku_version": value.catalog_sku_version,
        "sku_id": value.sku_id,
        "product_id": value.product_id,
        "merchant_sku": value.merchant_sku,
        "display_name": value.display_name,
        "attributes": [_catalog_attribute_payload(attribute) for attribute in value.attributes],
    }


def _catalog_payload(value: MerchantCatalogV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "merchant_catalog_version": value.merchant_catalog_version,
        "catalog_id": value.catalog_id,
        "merchant_id": value.merchant_id,
        "generated_at": canonical_utc_datetime(value.generated_at),
        "products": [_catalog_product_payload(product) for product in value.products],
        "skus": [_catalog_sku_payload(sku) for sku in value.skus],
    }


def _inventory_line_payload(value: InventoryLineV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "inventory_line_version": value.inventory_line_version,
        "sku_id": value.sku_id,
        "quantity_available": value.quantity_available,
        "provenance": value.provenance.value,
        "evidence_reference_id": value.evidence_reference_id,
    }


def _inventory_payload(value: InventorySnapshotV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "inventory_snapshot_version": value.inventory_snapshot_version,
        "snapshot_id": value.snapshot_id,
        "catalog_id": value.catalog_id,
        "merchant_id": value.merchant_id,
        "captured_at": canonical_utc_datetime(value.captured_at),
        "lines": [_inventory_line_payload(line) for line in value.lines],
    }


def _merchant_offer_line_payload(value: MerchantOfferLineV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "merchant_offer_line_version": value.merchant_offer_line_version,
        "sku_id": value.sku_id,
        "max_offer_quantity": value.max_offer_quantity,
        "unit_price": _money_payload(value.unit_price),
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


def _signed_offer_payload(value: SignedMerchantOfferV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "signed_merchant_offer_version": value.signed_merchant_offer_version,
        "signature_version": value.signature_version,
        "offer": _merchant_offer_payload(value.offer),
        "signature_hex": value.signature_hex,
    }


def _evidence_payload(value: MerchantOfferEvidenceV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "merchant_offer_evidence_version": value.merchant_offer_evidence_version,
        "received_at": canonical_utc_datetime(value.received_at),
        "admission_decision": value.admission_decision.value,
        "signing_identity": _signing_identity_payload(value.signing_identity),
        "catalog": _catalog_payload(value.catalog),
        "inventory": _inventory_payload(value.inventory),
        "signed_offer": _signed_offer_payload(value.signed_offer),
    }


def _allocation_claim_line_payload(value: AllocationClaimLineV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "allocation_line_version": value.allocation_line_version,
        "offer_id": value.offer_id,
        "merchant_id": value.merchant_id,
        "sku_id": value.sku_id,
        "allocated_quantity": value.allocated_quantity,
        "unit_payment": _money_payload(value.unit_payment),
        "line_payment": _money_payload(value.line_payment),
    }


def _allocation_claim_payload(value: AllocationClaimV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "allocation_version": value.allocation_version,
        "mechanism_version": value.mechanism_version,
        "objective_version": value.objective_version,
        "market_id": value.market_id,
        "buyer_policy_commitment_version": value.buyer_policy_commitment_version,
        "buyer_policy_commitment_sha256": value.buyer_policy_commitment_sha256,
        "status": value.status.value,
        "fulfilled_quantity": value.fulfilled_quantity,
        "total_payment": _money_payload(value.total_payment),
        "soft_preference_unit_score": value.soft_preference_unit_score,
        "winner_count": value.winner_count,
        "lines": [_allocation_claim_line_payload(line) for line in value.lines],
    }


def canonical_allocation_certificate_v2_bytes(certificate: AllocationCertificateV2) -> bytes:
    """Serialize the complete V2 evidence container without granting it semantic authority."""
    if type(certificate) is not AllocationCertificateV2:
        raise TypeError("certificate must be exactly an AllocationCertificateV2")
    payload = {
        "schema_version": certificate.schema_version,
        "certificate_version": certificate.certificate_version,
        "certificate_id": certificate.certificate_id,
        "canonicalization_version": certificate.canonicalization_version,
        "buyer_policy_commitment_version": certificate.buyer_policy_commitment_version,
        "merchant_offer_signature_version": certificate.merchant_offer_signature_version,
        "buyer_policy": _buyer_policy_payload(certificate.buyer_policy),
        "buyer_policy_commitment_sha256": certificate.buyer_policy_commitment_sha256,
        "merchant_offer_evidence": [
            _evidence_payload(evidence) for evidence in certificate.merchant_offer_evidence
        ],
        "allocation": _allocation_claim_payload(certificate.allocation),
    }
    return canonical_json_bytes(
        {
            "canonicalization_version": CANONICALIZATION_VERSION,
            "payload_type": "allocation_certificate_v2",
            "payload": payload,
        }
    )
