from clear_market.canonical import (
    CANONICALIZATION_VERSION,
    canonical_json_bytes,
    canonical_utc_datetime,
)
from clear_market.commerce.catalog import (
    CatalogAttributeV2,
    CatalogProductV2,
    CatalogSkuV2,
    InventoryLineV2,
    InventorySnapshotV2,
    MerchantCatalogV2,
)
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


def _inventory_line_payload(value: InventoryLineV2) -> dict[str, object]:
    return {
        "schema_version": value.schema_version,
        "inventory_line_version": value.inventory_line_version,
        "sku_id": value.sku_id,
        "quantity_available": value.quantity_available,
        "provenance": value.provenance.value,
        "evidence_reference_id": value.evidence_reference_id,
    }


def canonical_merchant_catalog_v2_bytes(value: MerchantCatalogV2) -> bytes:
    """Serialize every catalog identity, text, attribute, and evidence field explicitly."""
    if type(value) is not MerchantCatalogV2:
        raise TypeError("value must be exactly a MerchantCatalogV2")
    return canonical_json_bytes(
        {
            "canonicalization_version": CANONICALIZATION_VERSION,
            "payload_type": "merchant_catalog_v2",
            "payload": {
                "schema_version": value.schema_version,
                "merchant_catalog_version": value.merchant_catalog_version,
                "catalog_id": value.catalog_id,
                "merchant_id": value.merchant_id,
                "generated_at": canonical_utc_datetime(value.generated_at),
                "products": [_catalog_product_payload(product) for product in value.products],
                "skus": [_catalog_sku_payload(sku) for sku in value.skus],
            },
        }
    )


def canonical_inventory_snapshot_v2_bytes(value: InventorySnapshotV2) -> bytes:
    """Serialize every inventory identity, quantity, provenance, and evidence field explicitly."""
    if type(value) is not InventorySnapshotV2:
        raise TypeError("value must be exactly an InventorySnapshotV2")
    return canonical_json_bytes(
        {
            "canonicalization_version": CANONICALIZATION_VERSION,
            "payload_type": "inventory_snapshot_v2",
            "payload": {
                "schema_version": value.schema_version,
                "inventory_snapshot_version": value.inventory_snapshot_version,
                "snapshot_id": value.snapshot_id,
                "catalog_id": value.catalog_id,
                "merchant_id": value.merchant_id,
                "captured_at": canonical_utc_datetime(value.captured_at),
                "lines": [_inventory_line_payload(line) for line in value.lines],
            },
        }
    )
