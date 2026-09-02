import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from clear_market.commerce import (
    AttributeValue,
    AttributeValueType,
    CatalogAttributeV2,
    CatalogProductV2,
    CatalogSkuV2,
    InventoryLineV2,
    InventorySnapshotV2,
    MerchantCatalogV2,
    ProvenanceLabel,
    canonical_inventory_snapshot_v2_bytes,
    canonical_merchant_catalog_v2_bytes,
)

_CATALOG_ID = "34000000-0000-4000-8000-000000000001"
_OTHER_CATALOG_ID = "34000000-0000-4000-8000-000000000002"
_MERCHANT_ID = "35000000-0000-4000-8000-000000000001"
_OTHER_MERCHANT_ID = "35000000-0000-4000-8000-000000000002"
_SNAPSHOT_ID = "36000000-0000-4000-8000-000000000001"
_OTHER_SNAPSHOT_ID = "36000000-0000-4000-8000-000000000002"
_GENERATED_AT = datetime(2027, 2, 3, 4, 5, 6, 123_456, tzinfo=UTC)
_CAPTURED_AT = datetime(2027, 2, 3, 5, 6, 7, 654_321, tzinfo=UTC)

_GOLDEN_MERCHANT_CATALOG_V2_BYTES = (
    b'{"canonicalization_version":"clear-json-v1","payload":{"catalog_id":"34000000-0000-4000-8000'
    b'-000000000001","generated_at":"2027-02-03T04:05:06.123456Z","merchant_catalog_version":"merc'
    b'hant-catalog-v2","merchant_id":"35000000-0000-4000-8000-000000000001","products":[{"catalog_'
    b'product_version":"catalog-product-v2","description":"Portable caf\xc3\xa9 workstation","di'
    b'splay_name":"Laptop Pro","product_id":"31000000-0000-4000-8000-000000000001","schema_version'
    b'":"2"},{"catalog_product_version":"catalog-product-v2","description":"","display_name":"USB-'
    b'C Dock","product_id":"31000000-0000-4000-8000-000000000002","schema_version":"2"}],"schema_v'
    b'ersion":"2","skus":[{"attributes":[{"attribute_key":"brand","catalog_attribute_version":"cat'
    b'alog-attribute-v2","evidence_reference_id":"33000000-0000-4000-8000-000000000001","provenanc'
    b'e":"CLAIMED","schema_version":"2","value":{"attribute_value_version":"attribute-value-v1","s'
    b'chema_version":"1","value":"Cl\xc3\xa9ar","value_type":"string"}},{"attribute_key":"ram_gb'
    b'","catalog_attribute_version":"catalog-attribute-v2","evidence_reference_id":"33000000-0000-'
    b'4000-8000-000000000002","provenance":"VERIFIED","schema_version":"2","value":{"attribute_val'
    b'ue_version":"attribute-value-v1","schema_version":"1","value":16,"value_type":"integer"}}],"'
    b'catalog_sku_version":"catalog-sku-v2","display_name":"Laptop 16 GB","merchant_sku":"LPT-16",'
    b'"product_id":"31000000-0000-4000-8000-000000000001","schema_version":"2","sku_id":"32000000-'
    b'0000-4000-8000-000000000001"},{"attributes":[{"attribute_key":"ram_gb","catalog_attribute_ve'
    b'rsion":"catalog-attribute-v2","evidence_reference_id":"33000000-0000-4000-8000-000000000003"'
    b',"provenance":"VERIFIED","schema_version":"2","value":{"attribute_value_version":"attribute-'
    b'value-v1","schema_version":"1","value":32,"value_type":"integer"}},{"attribute_key":"refurbi'
    b'shed","catalog_attribute_version":"catalog-attribute-v2","evidence_reference_id":"33000000-0'
    b'000-4000-8000-000000000004","provenance":"CLAIMED","schema_version":"2","value":{"attribute_'
    b'value_version":"attribute-value-v1","schema_version":"1","value":false,"value_type":"boolean'
    b'"}}],"catalog_sku_version":"catalog-sku-v2","display_name":"Laptop 32 GB","merchant_sku":"LP'
    b'T-32","product_id":"31000000-0000-4000-8000-000000000001","schema_version":"2","sku_id":"320'
    b'00000-0000-4000-8000-000000000002"},{"attributes":[{"attribute_key":"ports","catalog_attribu'
    b'te_version":"catalog-attribute-v2","evidence_reference_id":"33000000-0000-4000-8000-00000000'
    b'0005","provenance":"CLAIMED","schema_version":"2","value":{"attribute_value_version":"attrib'
    b'ute-value-v1","schema_version":"1","value":4,"value_type":"integer"}}],"catalog_sku_version"'
    b':"catalog-sku-v2","display_name":"USB-C Dock","merchant_sku":"DOCK-1","product_id":"31000000'
    b'-0000-4000-8000-000000000002","schema_version":"2","sku_id":"32000000-0000-4000-8000-0000000'
    b'00003"}]},"payload_type":"merchant_catalog_v2"}'
)
_GOLDEN_INVENTORY_SNAPSHOT_V2_BYTES = (
    b'{"canonicalization_version":"clear-json-v1","payload":{"captured_at":"2027-02-03T05:06:07.65'
    b'4321Z","catalog_id":"34000000-0000-4000-8000-000000000001","inventory_snapshot_version":"inv'
    b'entory-snapshot-v2","lines":[{"evidence_reference_id":"33000000-0000-4000-8000-000000000065"'
    b',"inventory_line_version":"inventory-line-v2","provenance":"VERIFIED","quantity_available":7'
    b',"schema_version":"2","sku_id":"32000000-0000-4000-8000-000000000001"},{"evidence_reference_'
    b'id":"33000000-0000-4000-8000-000000000066","inventory_line_version":"inventory-line-v2","pro'
    b'venance":"CLAIMED","quantity_available":2,"schema_version":"2","sku_id":"32000000-0000-4000-'
    b'8000-000000000002"},{"evidence_reference_id":"33000000-0000-4000-8000-000000000067","invento'
    b'ry_line_version":"inventory-line-v2","provenance":"CLAIMED","quantity_available":0,"schema_v'
    b'ersion":"2","sku_id":"32000000-0000-4000-8000-000000000003"}],"merchant_id":"35000000-0000-4'
    b'000-8000-000000000001","schema_version":"2","snapshot_id":"36000000-0000-4000-8000-000000000'
    b'001"},"payload_type":"inventory_snapshot_v2"}'
)

_GOLDEN_MERCHANT_CATALOG_V2_SHA256 = (
    "2c773d5f03c879e055150979479214247542b79600d7e898c00b3494a3ac4c04"
)
_GOLDEN_INVENTORY_SNAPSHOT_V2_SHA256 = (
    "35dd433666335a6a0267a8b0486518c1c6d06adc36f71e8b6c52e5a9d663e89d"
)


def _product_id(index: int) -> str:
    return f"31000000-0000-4000-8000-{index:012x}"


def _sku_id(index: int) -> str:
    return f"32000000-0000-4000-8000-{index:012x}"


def _evidence_id(index: int) -> str:
    return f"33000000-0000-4000-8000-{index:012x}"


def _attribute(
    key: str,
    value_type: AttributeValueType,
    value: str | int | bool,
    provenance: ProvenanceLabel,
    evidence_index: int,
) -> CatalogAttributeV2:
    return CatalogAttributeV2(
        attribute_key=key,
        value=AttributeValue(value_type=value_type, value=value),
        provenance=provenance,
        evidence_reference_id=_evidence_id(evidence_index),
    )


def _golden_products() -> tuple[CatalogProductV2, ...]:
    return (
        CatalogProductV2(product_id=_product_id(2), display_name="USB-C Dock", description=""),
        CatalogProductV2(
            product_id=_product_id(1),
            display_name="Laptop Pro",
            description="Portable café workstation",
        ),
    )


def _golden_skus() -> tuple[CatalogSkuV2, ...]:
    return (
        CatalogSkuV2(
            sku_id=_sku_id(3),
            product_id=_product_id(2),
            merchant_sku="DOCK-1",
            display_name="USB-C Dock",
            attributes=(
                _attribute(
                    "ports",
                    AttributeValueType.INTEGER,
                    4,
                    ProvenanceLabel.CLAIMED,
                    5,
                ),
            ),
        ),
        CatalogSkuV2(
            sku_id=_sku_id(2),
            product_id=_product_id(1),
            merchant_sku="LPT-32",
            display_name="Laptop 32 GB",
            attributes=(
                _attribute(
                    "refurbished",
                    AttributeValueType.BOOLEAN,
                    False,
                    ProvenanceLabel.CLAIMED,
                    4,
                ),
                _attribute(
                    "ram_gb",
                    AttributeValueType.INTEGER,
                    32,
                    ProvenanceLabel.VERIFIED,
                    3,
                ),
            ),
        ),
        CatalogSkuV2(
            sku_id=_sku_id(1),
            product_id=_product_id(1),
            merchant_sku="LPT-16",
            display_name="Laptop 16 GB",
            attributes=(
                _attribute(
                    "ram_gb",
                    AttributeValueType.INTEGER,
                    16,
                    ProvenanceLabel.VERIFIED,
                    2,
                ),
                _attribute(
                    "brand",
                    AttributeValueType.STRING,
                    "Cléar",
                    ProvenanceLabel.CLAIMED,
                    1,
                ),
            ),
        ),
    )


def _golden_catalog(**changes: object) -> MerchantCatalogV2:
    values: dict[str, object] = {
        "catalog_id": _CATALOG_ID,
        "merchant_id": _MERCHANT_ID,
        "generated_at": _GENERATED_AT,
        "products": _golden_products(),
        "skus": _golden_skus(),
        **changes,
    }
    return MerchantCatalogV2(**values)


def _golden_lines() -> tuple[InventoryLineV2, ...]:
    return (
        InventoryLineV2(
            sku_id=_sku_id(3),
            quantity_available=0,
            provenance=ProvenanceLabel.CLAIMED,
            evidence_reference_id=_evidence_id(103),
        ),
        InventoryLineV2(
            sku_id=_sku_id(1),
            quantity_available=7,
            provenance=ProvenanceLabel.VERIFIED,
            evidence_reference_id=_evidence_id(101),
        ),
        InventoryLineV2(
            sku_id=_sku_id(2),
            quantity_available=2,
            provenance=ProvenanceLabel.CLAIMED,
            evidence_reference_id=_evidence_id(102),
        ),
    )


def _golden_snapshot(**changes: object) -> InventorySnapshotV2:
    values: dict[str, object] = {
        "snapshot_id": _SNAPSHOT_ID,
        "catalog_id": _CATALOG_ID,
        "merchant_id": _MERCHANT_ID,
        "captured_at": _CAPTURED_AT,
        "lines": _golden_lines(),
        **changes,
    }
    return InventorySnapshotV2(**values)


def test_golden_merchant_catalog_v2_bytes_and_hash_are_frozen() -> None:
    encoded = canonical_merchant_catalog_v2_bytes(_golden_catalog())

    assert encoded == _GOLDEN_MERCHANT_CATALOG_V2_BYTES
    assert len(encoded) == 2_883
    assert hashlib.sha256(encoded).hexdigest() == _GOLDEN_MERCHANT_CATALOG_V2_SHA256


def test_golden_inventory_snapshot_v2_bytes_and_hash_are_frozen() -> None:
    encoded = canonical_inventory_snapshot_v2_bytes(_golden_snapshot())

    assert encoded == _GOLDEN_INVENTORY_SNAPSHOT_V2_BYTES
    assert len(encoded) == 1_057
    assert hashlib.sha256(encoded).hexdigest() == _GOLDEN_INVENTORY_SNAPSHOT_V2_SHA256


@pytest.mark.parametrize(
    ("encoded", "payload_type"),
    [
        (_GOLDEN_MERCHANT_CATALOG_V2_BYTES, "merchant_catalog_v2"),
        (_GOLDEN_INVENTORY_SNAPSHOT_V2_BYTES, "inventory_snapshot_v2"),
    ],
)
def test_catalog_envelopes_are_exact_compact_utf8(encoded: bytes, payload_type: str) -> None:
    envelope = json.loads(encoded)

    assert set(envelope) == {"canonicalization_version", "payload", "payload_type"}
    assert envelope["canonicalization_version"] == "clear-json-v1"
    assert envelope["payload_type"] == payload_type
    assert envelope["payload"]["schema_version"] == "2"
    assert encoded.decode("utf-8").encode("utf-8") == encoded
    assert b": " not in encoded
    assert b", " not in encoded
    assert b"\n" not in encoded


def test_catalog_projection_is_explicit_and_nested() -> None:
    payload = json.loads(canonical_merchant_catalog_v2_bytes(_golden_catalog()))["payload"]

    assert set(payload) == {
        "schema_version",
        "merchant_catalog_version",
        "catalog_id",
        "merchant_id",
        "generated_at",
        "products",
        "skus",
    }
    assert set(payload["products"][0]) == {
        "schema_version",
        "catalog_product_version",
        "product_id",
        "display_name",
        "description",
    }
    assert set(payload["skus"][0]) == {
        "schema_version",
        "catalog_sku_version",
        "sku_id",
        "product_id",
        "merchant_sku",
        "display_name",
        "attributes",
    }
    assert set(payload["skus"][0]["attributes"][0]) == {
        "schema_version",
        "catalog_attribute_version",
        "attribute_key",
        "value",
        "provenance",
        "evidence_reference_id",
    }
    assert set(payload["skus"][0]["attributes"][0]["value"]) == {
        "schema_version",
        "attribute_value_version",
        "value_type",
        "value",
    }
    assert payload["generated_at"] == "2027-02-03T04:05:06.123456Z"


def test_inventory_projection_is_explicit() -> None:
    payload = json.loads(canonical_inventory_snapshot_v2_bytes(_golden_snapshot()))["payload"]

    assert set(payload) == {
        "schema_version",
        "inventory_snapshot_version",
        "snapshot_id",
        "catalog_id",
        "merchant_id",
        "captured_at",
        "lines",
    }
    assert set(payload["lines"][0]) == {
        "schema_version",
        "inventory_line_version",
        "sku_id",
        "quantity_available",
        "provenance",
        "evidence_reference_id",
    }
    assert payload["inventory_snapshot_version"] == "inventory-snapshot-v2"
    assert payload["lines"][0]["inventory_line_version"] == "inventory-line-v2"
    assert payload["captured_at"] == "2027-02-03T05:06:07.654321Z"


def test_catalog_serialization_preserves_utf8_and_uppercase_provenance() -> None:
    encoded = canonical_merchant_catalog_v2_bytes(_golden_catalog())

    assert "café".encode() in encoded
    assert "Cléar".encode() in encoded
    assert b"\\u00e9" not in encoded
    assert b'"provenance":"CLAIMED"' in encoded
    assert b'"provenance":"VERIFIED"' in encoded


def test_catalog_and_inventory_serialization_are_deterministic() -> None:
    catalog = _golden_catalog()
    snapshot = _golden_snapshot()

    assert canonical_merchant_catalog_v2_bytes(catalog) == canonical_merchant_catalog_v2_bytes(
        catalog
    )
    assert canonical_inventory_snapshot_v2_bytes(snapshot) == canonical_inventory_snapshot_v2_bytes(
        snapshot
    )


def test_semantically_unordered_catalog_inputs_produce_identical_bytes() -> None:
    forward = _golden_catalog()
    reverse = _golden_catalog(
        products=tuple(reversed(_golden_products())),
        skus=tuple(reversed(_golden_skus())),
    )

    assert canonical_merchant_catalog_v2_bytes(forward) == canonical_merchant_catalog_v2_bytes(
        reverse
    )


def test_attribute_input_order_does_not_change_catalog_bytes() -> None:
    skus = list(_golden_skus())
    first = skus[-1]
    skus[-1] = CatalogSkuV2(
        sku_id=first.sku_id,
        product_id=first.product_id,
        merchant_sku=first.merchant_sku,
        display_name=first.display_name,
        attributes=tuple(reversed(first.attributes)),
    )
    reordered = _golden_catalog(skus=tuple(skus))

    assert canonical_merchant_catalog_v2_bytes(reordered) == _GOLDEN_MERCHANT_CATALOG_V2_BYTES


def test_inventory_line_input_order_does_not_change_bytes() -> None:
    forward = _golden_snapshot()
    reverse = _golden_snapshot(lines=tuple(reversed(_golden_lines())))

    assert canonical_inventory_snapshot_v2_bytes(forward) == canonical_inventory_snapshot_v2_bytes(
        reverse
    )


def _rebuild_catalog_with_sku(replacement: CatalogSkuV2) -> MerchantCatalogV2:
    skus = tuple(replacement if sku.sku_id == _sku_id(1) else sku for sku in _golden_skus())
    return _golden_catalog(skus=skus)


def _rebuild_catalog_with_product(replacement: CatalogProductV2) -> MerchantCatalogV2:
    products = tuple(
        replacement if product.product_id == replacement.product_id else product
        for product in _golden_products()
    )
    return _golden_catalog(products=products)


def test_every_catalog_top_level_and_product_field_changes_bytes() -> None:
    original = canonical_merchant_catalog_v2_bytes(_golden_catalog())
    product = _golden_catalog().products[0]
    changed = (
        _golden_catalog(catalog_id=_OTHER_CATALOG_ID),
        _golden_catalog(merchant_id=_OTHER_MERCHANT_ID),
        _golden_catalog(generated_at=_GENERATED_AT + timedelta(microseconds=1)),
        _rebuild_catalog_with_product(product.model_copy(update={"display_name": "Other Laptop"})),
        _rebuild_catalog_with_product(
            product.model_copy(update={"description": "Other description"})
        ),
    )

    assert all(canonical_merchant_catalog_v2_bytes(value) != original for value in changed)


def test_every_catalog_sku_field_changes_bytes() -> None:
    original = canonical_merchant_catalog_v2_bytes(_golden_catalog())
    sku = _golden_catalog().skus[0]
    changed = (
        _rebuild_catalog_with_sku(sku.model_copy(update={"sku_id": _sku_id(4)})),
        _rebuild_catalog_with_sku(sku.model_copy(update={"product_id": _product_id(2)})),
        _rebuild_catalog_with_sku(sku.model_copy(update={"merchant_sku": "LPT-16-OTHER"})),
        _rebuild_catalog_with_sku(sku.model_copy(update={"display_name": "Other SKU"})),
    )

    assert all(canonical_merchant_catalog_v2_bytes(value) != original for value in changed)


def test_every_catalog_attribute_field_changes_bytes() -> None:
    original = canonical_merchant_catalog_v2_bytes(_golden_catalog())
    sku = _golden_catalog().skus[0]
    attribute = sku.attributes[0]

    def changed_catalog(replacement: CatalogAttributeV2) -> MerchantCatalogV2:
        changed_sku = sku.model_copy(update={"attributes": (replacement, sku.attributes[1])})
        return _rebuild_catalog_with_sku(changed_sku)

    changed = (
        changed_catalog(attribute.model_copy(update={"attribute_key": "manufacturer"})),
        changed_catalog(
            attribute.model_copy(
                update={"value": AttributeValue(value_type=AttributeValueType.BOOLEAN, value=True)}
            )
        ),
        changed_catalog(
            attribute.model_copy(
                update={
                    "value": AttributeValue(value_type=AttributeValueType.STRING, value="Other")
                }
            )
        ),
        changed_catalog(attribute.model_copy(update={"provenance": ProvenanceLabel.VERIFIED})),
        changed_catalog(attribute.model_copy(update={"evidence_reference_id": _evidence_id(99)})),
    )

    assert all(canonical_merchant_catalog_v2_bytes(value) != original for value in changed)


def test_product_identity_change_with_matching_sku_reference_changes_bytes() -> None:
    original = canonical_merchant_catalog_v2_bytes(_golden_catalog())
    catalog = _golden_catalog()
    product = catalog.products[0]
    new_product_id = "31000000-0000-4000-8000-000000000009"
    changed_products = tuple(
        product.model_copy(update={"product_id": new_product_id}) if item is product else item
        for item in catalog.products
    )
    changed_skus = tuple(
        sku.model_copy(update={"product_id": new_product_id})
        if sku.product_id == product.product_id
        else sku
        for sku in catalog.skus
    )
    changed = _golden_catalog(products=changed_products, skus=changed_skus)

    assert canonical_merchant_catalog_v2_bytes(changed) != original


def test_every_inventory_decision_field_changes_bytes() -> None:
    original = canonical_inventory_snapshot_v2_bytes(_golden_snapshot())
    line = _golden_snapshot().lines[0]

    def changed_line(replacement: InventoryLineV2) -> InventorySnapshotV2:
        lines = tuple(
            replacement if item.sku_id == line.sku_id else item for item in _golden_lines()
        )
        return _golden_snapshot(lines=lines)

    changed = (
        _golden_snapshot(snapshot_id=_OTHER_SNAPSHOT_ID),
        _golden_snapshot(catalog_id=_OTHER_CATALOG_ID),
        _golden_snapshot(merchant_id=_OTHER_MERCHANT_ID),
        _golden_snapshot(captured_at=_CAPTURED_AT + timedelta(microseconds=1)),
        changed_line(line.model_copy(update={"sku_id": _sku_id(4)})),
        changed_line(line.model_copy(update={"quantity_available": 8})),
        changed_line(line.model_copy(update={"provenance": ProvenanceLabel.CLAIMED})),
        changed_line(line.model_copy(update={"evidence_reference_id": _evidence_id(999)})),
    )

    assert all(canonical_inventory_snapshot_v2_bytes(value) != original for value in changed)


class _MerchantCatalogSubclass(MerchantCatalogV2):
    pass


class _InventorySnapshotSubclass(InventorySnapshotV2):
    pass


def _catalog_subclass() -> _MerchantCatalogSubclass:
    return _MerchantCatalogSubclass(
        catalog_id=_CATALOG_ID,
        merchant_id=_MERCHANT_ID,
        generated_at=_GENERATED_AT,
        products=_golden_products(),
        skus=_golden_skus(),
    )


def _snapshot_subclass() -> _InventorySnapshotSubclass:
    return _InventorySnapshotSubclass(
        snapshot_id=_SNAPSHOT_ID,
        catalog_id=_CATALOG_ID,
        merchant_id=_MERCHANT_ID,
        captured_at=_CAPTURED_AT,
        lines=_golden_lines(),
    )


@pytest.mark.parametrize(
    ("serializer", "wrong_value"),
    [
        (canonical_merchant_catalog_v2_bytes, _golden_snapshot()),
        (canonical_merchant_catalog_v2_bytes, _catalog_subclass()),
        (canonical_merchant_catalog_v2_bytes, None),
        (canonical_inventory_snapshot_v2_bytes, _golden_catalog()),
        (canonical_inventory_snapshot_v2_bytes, _snapshot_subclass()),
        (canonical_inventory_snapshot_v2_bytes, {}),
    ],
)
def test_catalog_serializers_reject_wrong_and_subclass_types(
    serializer: Callable[..., bytes],
    wrong_value: object,
) -> None:
    with pytest.raises(TypeError):
        serializer(wrong_value)
