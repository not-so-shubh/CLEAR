from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from clear_market.commerce import (
    CATALOG_ATTRIBUTE_V2_VERSION,
    CATALOG_PRODUCT_V2_VERSION,
    CATALOG_SKU_V2_VERSION,
    INVENTORY_LINE_V2_VERSION,
    INVENTORY_SNAPSHOT_V2_VERSION,
    MERCHANT_CATALOG_V2_VERSION,
    AttributeValue,
    AttributeValueType,
    CatalogAttributeV2,
    CatalogProductV2,
    CatalogSkuV2,
    InventoryLineV2,
    InventorySnapshotV2,
    MerchantCatalogV2,
    ProvenanceLabel,
)
from clear_market.commerce.catalog import (
    MAX_ATTRIBUTES_PER_SKU,
    MAX_CATALOG_PRODUCTS,
    MAX_CATALOG_SKUS,
    MAX_MERCHANT_SKU_CHARS,
    MAX_PRODUCT_DESCRIPTION_CHARS,
    MAX_PRODUCT_NAME_CHARS,
    MAX_SKU_NAME_CHARS,
)
from clear_market.domain import MAX_QUANTITY

_CATALOG_ID = "34000000-0000-4000-8000-000000000001"
_OTHER_CATALOG_ID = "34000000-0000-4000-8000-000000000002"
_MERCHANT_ID = "35000000-0000-4000-8000-000000000001"
_OTHER_MERCHANT_ID = "35000000-0000-4000-8000-000000000002"
_SNAPSHOT_ID = "36000000-0000-4000-8000-000000000001"
_GENERATED_AT = datetime(2027, 2, 3, 4, 5, 6, 123_456, tzinfo=UTC)
_CAPTURED_AT = datetime(2027, 2, 3, 5, 6, 7, 654_321, tzinfo=UTC)


def _product_id(index: int) -> str:
    return f"31000000-0000-4000-8000-{index:012x}"


def _sku_id(index: int) -> str:
    return f"32000000-0000-4000-8000-{index:012x}"


def _evidence_id(index: int) -> str:
    return f"33000000-0000-4000-8000-{index:012x}"


def _attribute(
    attribute_key: str = "ram_gb",
    *,
    value: AttributeValue | None = None,
    provenance: ProvenanceLabel = ProvenanceLabel.VERIFIED,
    evidence_index: int = 1,
) -> CatalogAttributeV2:
    return CatalogAttributeV2(
        attribute_key=attribute_key,
        value=value or AttributeValue(value_type=AttributeValueType.INTEGER, value=16),
        provenance=provenance,
        evidence_reference_id=_evidence_id(evidence_index),
    )


def _product(index: int = 1, **changes: object) -> CatalogProductV2:
    values: dict[str, object] = {
        "product_id": _product_id(index),
        "display_name": f"Product {index}",
        "description": "Untrusted merchant description",
        **changes,
    }
    return CatalogProductV2(**values)


def _sku(
    index: int = 1,
    *,
    product_id: str | None = None,
    attributes: tuple[CatalogAttributeV2, ...] = (),
    **changes: object,
) -> CatalogSkuV2:
    values: dict[str, object] = {
        "sku_id": _sku_id(index),
        "product_id": product_id or _product_id(1),
        "merchant_sku": f"SKU-{index}",
        "display_name": f"SKU {index}",
        "attributes": attributes,
        **changes,
    }
    return CatalogSkuV2(**values)


def _catalog(**changes: object) -> MerchantCatalogV2:
    values: dict[str, object] = {
        "catalog_id": _CATALOG_ID,
        "merchant_id": _MERCHANT_ID,
        "generated_at": _GENERATED_AT,
        "products": (_product(),),
        "skus": (_sku(),),
        **changes,
    }
    return MerchantCatalogV2(**values)


def _line(
    index: int = 1,
    *,
    quantity: int = 7,
    provenance: ProvenanceLabel = ProvenanceLabel.VERIFIED,
    evidence_index: int | None = None,
) -> InventoryLineV2:
    return InventoryLineV2(
        sku_id=_sku_id(index),
        quantity_available=quantity,
        provenance=provenance,
        evidence_reference_id=_evidence_id(evidence_index or 100 + index),
    )


def _snapshot(**changes: object) -> InventorySnapshotV2:
    values: dict[str, object] = {
        "snapshot_id": _SNAPSHOT_ID,
        "catalog_id": _CATALOG_ID,
        "merchant_id": _MERCHANT_ID,
        "captured_at": _CAPTURED_AT,
        "lines": (_line(),),
        **changes,
    }
    return InventorySnapshotV2(**values)


def test_catalog_versions_are_exact() -> None:
    assert CATALOG_ATTRIBUTE_V2_VERSION == "catalog-attribute-v2"
    assert CATALOG_PRODUCT_V2_VERSION == "catalog-product-v2"
    assert CATALOG_SKU_V2_VERSION == "catalog-sku-v2"
    assert MERCHANT_CATALOG_V2_VERSION == "merchant-catalog-v2"
    assert INVENTORY_LINE_V2_VERSION == "inventory-line-v2"
    assert INVENTORY_SNAPSHOT_V2_VERSION == "inventory-snapshot-v2"


def test_catalog_attribute_has_exact_fields_and_versions() -> None:
    attribute = _attribute()

    assert attribute.schema_version == "2"
    assert attribute.catalog_attribute_version == "catalog-attribute-v2"
    assert tuple(CatalogAttributeV2.model_fields) == (
        "schema_version",
        "catalog_attribute_version",
        "attribute_key",
        "value",
        "provenance",
        "evidence_reference_id",
    )


@pytest.mark.parametrize("missing", ["provenance", "evidence_reference_id"])
def test_catalog_attribute_requires_provenance_and_evidence(missing: str) -> None:
    values: dict[str, object] = {
        "attribute_key": "brand",
        "value": AttributeValue(value_type=AttributeValueType.STRING, value="Clear"),
        "provenance": ProvenanceLabel.CLAIMED,
        "evidence_reference_id": _evidence_id(1),
    }
    del values[missing]

    with pytest.raises(ValidationError):
        CatalogAttributeV2(**values)


def test_catalog_attribute_preserves_explicit_predicted_provenance() -> None:
    attribute = _attribute(provenance=ProvenanceLabel.PREDICTED)

    assert attribute.provenance is ProvenanceLabel.PREDICTED


@pytest.mark.parametrize(
    ("value_type", "value"),
    [
        (AttributeValueType.STRING, "Clear"),
        (AttributeValueType.INTEGER, 16),
        (AttributeValueType.BOOLEAN, True),
    ],
)
def test_catalog_attribute_accepts_every_attribute_scalar(
    value_type: AttributeValueType,
    value: str | int | bool,
) -> None:
    attribute = _attribute(value=AttributeValue(value_type=value_type, value=value))

    assert attribute.value.value_type is value_type
    assert attribute.value.value == value


@pytest.mark.parametrize("provenance", tuple(ProvenanceLabel))
def test_catalog_attribute_accepts_every_provenance_as_a_data_label(
    provenance: ProvenanceLabel,
) -> None:
    attribute = _attribute(provenance=provenance)

    assert attribute.provenance is provenance


def test_catalog_attribute_rejects_invalid_attribute_key() -> None:
    with pytest.raises(ValidationError):
        _attribute("Brand")


def test_catalog_attribute_rejects_invalid_nested_attribute_value() -> None:
    with pytest.raises(ValidationError):
        CatalogAttributeV2(
            attribute_key="brand",
            value={"value_type": "integer", "value": True},
            provenance=ProvenanceLabel.CLAIMED,
            evidence_reference_id=_evidence_id(1),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("schema_version", "1"), ("catalog_attribute_version", "catalog-attribute-v3")],
)
def test_catalog_attribute_rejects_version_mismatch(field: str, value: object) -> None:
    values: dict[str, object] = {
        "attribute_key": "brand",
        "value": AttributeValue(value_type=AttributeValueType.STRING, value="Clear"),
        "provenance": ProvenanceLabel.CLAIMED,
        "evidence_reference_id": _evidence_id(1),
        field: value,
    }
    with pytest.raises(ValidationError):
        CatalogAttributeV2(**values)


def test_catalog_product_has_exact_fields_and_preserves_unicode_text() -> None:
    product = _product(display_name="Café Laptop", description="Édition légère")

    assert product.schema_version == "2"
    assert product.catalog_product_version == "catalog-product-v2"
    assert product.display_name == "Café Laptop"
    assert product.description == "Édition légère"
    assert tuple(CatalogProductV2.model_fields) == (
        "schema_version",
        "catalog_product_version",
        "product_id",
        "display_name",
        "description",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("display_name", ""),
        ("display_name", "x" * (MAX_PRODUCT_NAME_CHARS + 1)),
        ("description", "x" * (MAX_PRODUCT_DESCRIPTION_CHARS + 1)),
        ("display_name", "name\x00suffix"),
        ("description", "description\x00suffix"),
        ("display_name", 1),
        ("description", None),
    ],
)
def test_catalog_product_rejects_invalid_text(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _product(**{field: value})


def test_catalog_product_accepts_text_boundaries_without_normalization() -> None:
    name = " " + "n" * (MAX_PRODUCT_NAME_CHARS - 2) + " "
    description = "d" * MAX_PRODUCT_DESCRIPTION_CHARS
    product = _product(display_name=name, description=description)

    assert product.display_name == name
    assert product.description == description
    assert _product(description="").description == ""


def test_catalog_product_accepts_minimum_display_name() -> None:
    assert _product(display_name="x").display_name == "x"


@pytest.mark.parametrize(
    "merchant_sku",
    ["A", "sku-1", "SKU_1.2", "0", "a" + "0" * (MAX_MERCHANT_SKU_CHARS - 1)],
)
def test_catalog_sku_accepts_canonical_merchant_sku(merchant_sku: str) -> None:
    assert _sku(merchant_sku=merchant_sku).merchant_sku == merchant_sku


@pytest.mark.parametrize(
    "merchant_sku",
    [
        "",
        "-sku",
        ".sku",
        "_sku",
        "sku/value",
        "sku value",
        "skú",
        "a" * (MAX_MERCHANT_SKU_CHARS + 1),
        1,
        None,
    ],
)
def test_catalog_sku_rejects_noncanonical_merchant_sku(merchant_sku: object) -> None:
    with pytest.raises(ValidationError):
        _sku(merchant_sku=merchant_sku)


def test_catalog_sku_requires_explicit_tuple_attributes_and_allows_empty() -> None:
    assert _sku(attributes=()).attributes == ()

    with pytest.raises(ValidationError):
        _sku(attributes=[_attribute()])  # type: ignore[arg-type]


def test_catalog_sku_requires_attributes_field() -> None:
    with pytest.raises(ValidationError):
        CatalogSkuV2(
            sku_id=_sku_id(1),
            product_id=_product_id(1),
            merchant_sku="SKU-1",
            display_name="SKU 1",
        )


def test_catalog_sku_has_exact_fields_and_versions() -> None:
    sku = _sku()

    assert sku.schema_version == "2"
    assert sku.catalog_sku_version == "catalog-sku-v2"
    assert tuple(CatalogSkuV2.model_fields) == (
        "schema_version",
        "catalog_sku_version",
        "sku_id",
        "product_id",
        "merchant_sku",
        "display_name",
        "attributes",
    )


def test_catalog_sku_sorts_attributes_and_rejects_duplicate_keys() -> None:
    brand = _attribute(
        "brand",
        value=AttributeValue(value_type=AttributeValueType.STRING, value="Clear"),
        evidence_index=2,
    )
    ram = _attribute("ram_gb", evidence_index=1)
    sku = _sku(attributes=(ram, brand))

    assert tuple(attribute.attribute_key for attribute in sku.attributes) == ("brand", "ram_gb")
    with pytest.raises(ValidationError):
        _sku(attributes=(ram, _attribute("ram_gb", evidence_index=3)))


def test_catalog_sku_accepts_distinct_attribute_provenance_labels() -> None:
    sku = _sku(
        attributes=(
            _attribute("ram_gb", provenance=ProvenanceLabel.VERIFIED, evidence_index=1),
            _attribute("stock_state", provenance=ProvenanceLabel.CLAIMED, evidence_index=2),
        )
    )

    assert {attribute.provenance for attribute in sku.attributes} == {
        ProvenanceLabel.CLAIMED,
        ProvenanceLabel.VERIFIED,
    }


def test_catalog_sku_attribute_bound_is_exact() -> None:
    attributes = tuple(
        _attribute(f"attribute_{index:02d}", evidence_index=index + 1) for index in range(64)
    )

    assert len(_sku(attributes=attributes).attributes) == MAX_ATTRIBUTES_PER_SKU
    with pytest.raises(ValidationError):
        _sku(attributes=(*attributes, _attribute("overflow", evidence_index=100)))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("display_name", ""),
        ("display_name", "x" * (MAX_SKU_NAME_CHARS + 1)),
        ("display_name", "sku\x00name"),
    ],
)
def test_catalog_sku_rejects_invalid_display_name(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _sku(**{field: value})


def test_merchant_catalog_has_exact_fields_and_normalizes_utc() -> None:
    generated_at = datetime(
        2027,
        2,
        3,
        9,
        35,
        6,
        123_456,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )
    catalog = _catalog(generated_at=generated_at)

    assert catalog.schema_version == "2"
    assert catalog.merchant_catalog_version == "merchant-catalog-v2"
    assert catalog.generated_at == _GENERATED_AT
    assert tuple(MerchantCatalogV2.model_fields) == (
        "schema_version",
        "merchant_catalog_version",
        "catalog_id",
        "merchant_id",
        "generated_at",
        "products",
        "skus",
    )


def test_merchant_catalog_requires_nonempty_tuple_collections() -> None:
    for field, value in (
        ("products", ()),
        ("skus", ()),
        ("products", [_product()]),
        ("skus", [_sku()]),
    ):
        with pytest.raises(ValidationError):
            _catalog(**{field: value})


@pytest.mark.parametrize("missing", ["products", "skus"])
def test_merchant_catalog_requires_product_and_sku_fields(missing: str) -> None:
    values: dict[str, object] = {
        "catalog_id": _CATALOG_ID,
        "merchant_id": _MERCHANT_ID,
        "generated_at": _GENERATED_AT,
        "products": (_product(),),
        "skus": (_sku(),),
    }
    del values[missing]

    with pytest.raises(ValidationError):
        MerchantCatalogV2(**values)


def test_merchant_catalog_rejects_naive_generated_at() -> None:
    with pytest.raises(ValidationError):
        _catalog(generated_at=datetime(2027, 2, 3, 4, 5, 6))


def test_merchant_catalog_sorts_products_and_skus() -> None:
    catalog = _catalog(
        products=(_product(2), _product(1)),
        skus=(_sku(2, product_id=_product_id(2)), _sku(1, product_id=_product_id(1))),
    )

    assert tuple(product.product_id for product in catalog.products) == (
        _product_id(1),
        _product_id(2),
    )
    assert tuple(sku.sku_id for sku in catalog.skus) == (_sku_id(1), _sku_id(2))


@pytest.mark.parametrize(
    "products",
    [
        (_product(), _product()),
    ],
)
def test_merchant_catalog_rejects_duplicate_product_ids(
    products: tuple[CatalogProductV2, ...],
) -> None:
    with pytest.raises(ValidationError):
        _catalog(products=products)


def test_merchant_catalog_rejects_duplicate_sku_ids() -> None:
    with pytest.raises(ValidationError):
        _catalog(skus=(_sku(1), _sku(1, merchant_sku="OTHER")))


def test_merchant_catalog_rejects_duplicate_merchant_skus() -> None:
    with pytest.raises(ValidationError):
        _catalog(skus=(_sku(1), _sku(2, merchant_sku="SKU-1")))


def test_merchant_catalog_rejects_unknown_product_reference() -> None:
    with pytest.raises(ValidationError):
        _catalog(skus=(_sku(product_id=_product_id(2)),))


def test_merchant_catalog_rejects_unreferenced_product() -> None:
    with pytest.raises(ValidationError):
        _catalog(products=(_product(1), _product(2)), skus=(_sku(product_id=_product_id(1)),))


def test_merchant_catalog_accepts_product_and_sku_bounds() -> None:
    products = tuple(_product(index + 1) for index in range(MAX_CATALOG_PRODUCTS))
    skus = tuple(
        _sku(index + 1, product_id=_product_id((index % MAX_CATALOG_PRODUCTS) + 1))
        for index in range(MAX_CATALOG_SKUS)
    )

    catalog = _catalog(products=products, skus=skus)

    assert len(catalog.products) == MAX_CATALOG_PRODUCTS
    assert len(catalog.skus) == MAX_CATALOG_SKUS


def test_merchant_catalog_rejects_collection_overflow() -> None:
    too_many_products = tuple(_product(index + 1) for index in range(MAX_CATALOG_PRODUCTS + 1))
    too_many_skus = tuple(_sku(index + 1) for index in range(MAX_CATALOG_SKUS + 1))

    with pytest.raises(ValidationError):
        _catalog(products=too_many_products)
    with pytest.raises(ValidationError):
        _catalog(skus=too_many_skus)


def test_inventory_line_has_exact_fields_and_accepts_quantity_bounds() -> None:
    zero = _line(quantity=0)
    maximum = _line(quantity=MAX_QUANTITY)

    assert zero.schema_version == "2"
    assert zero.inventory_line_version == "inventory-line-v2"
    assert zero.quantity_available == 0
    assert maximum.quantity_available == MAX_QUANTITY
    assert tuple(InventoryLineV2.model_fields) == (
        "schema_version",
        "inventory_line_version",
        "sku_id",
        "quantity_available",
        "provenance",
        "evidence_reference_id",
    )


@pytest.mark.parametrize("quantity", [-1, MAX_QUANTITY + 1, True, False, 1.0, "1"])
def test_inventory_line_rejects_invalid_quantity(quantity: object) -> None:
    with pytest.raises(ValidationError):
        InventoryLineV2(
            sku_id=_sku_id(1),
            quantity_available=quantity,
            provenance=ProvenanceLabel.VERIFIED,
            evidence_reference_id=_evidence_id(101),
        )


@pytest.mark.parametrize("missing", ["provenance", "evidence_reference_id"])
def test_inventory_line_requires_provenance_and_evidence(missing: str) -> None:
    values: dict[str, object] = {
        "sku_id": _sku_id(1),
        "quantity_available": 1,
        "provenance": ProvenanceLabel.CLAIMED,
        "evidence_reference_id": _evidence_id(101),
    }
    del values[missing]

    with pytest.raises(ValidationError):
        InventoryLineV2(**values)


def test_inventory_snapshot_has_exact_fields_and_normalizes_lines() -> None:
    snapshot = _snapshot(lines=(_line(2, quantity=0), _line(1, quantity=7)))

    assert snapshot.schema_version == "2"
    assert snapshot.inventory_snapshot_version == "inventory-snapshot-v2"
    assert tuple(line.sku_id for line in snapshot.lines) == (_sku_id(1), _sku_id(2))
    assert tuple(InventorySnapshotV2.model_fields) == (
        "schema_version",
        "inventory_snapshot_version",
        "snapshot_id",
        "catalog_id",
        "merchant_id",
        "captured_at",
        "lines",
    )


def test_inventory_snapshot_requires_nonempty_tuple_lines() -> None:
    with pytest.raises(ValidationError):
        _snapshot(lines=())
    with pytest.raises(ValidationError):
        _snapshot(lines=[_line()])


def test_inventory_snapshot_rejects_duplicate_sku_lines() -> None:
    with pytest.raises(ValidationError):
        _snapshot(lines=(_line(1), _line(1, evidence_index=202)))


def test_inventory_snapshot_normalizes_aware_time_and_rejects_naive_time() -> None:
    captured_at = datetime(
        2027,
        2,
        3,
        10,
        36,
        7,
        654_321,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    assert _snapshot(captured_at=captured_at).captured_at == _CAPTURED_AT
    with pytest.raises(ValidationError):
        _snapshot(captured_at=datetime(2027, 2, 3, 5, 6, 7))


def test_inventory_snapshot_accepts_maximum_line_count_and_rejects_overflow() -> None:
    lines = tuple(_line(index + 1) for index in range(MAX_CATALOG_SKUS))

    assert len(_snapshot(lines=lines).lines) == MAX_CATALOG_SKUS
    with pytest.raises(ValidationError):
        _snapshot(lines=(*lines, _line(MAX_CATALOG_SKUS + 1)))


def test_inventory_snapshot_does_not_resolve_catalog_references() -> None:
    unrelated = _snapshot(catalog_id=_OTHER_CATALOG_ID, merchant_id=_OTHER_MERCHANT_ID)

    assert unrelated.catalog_id == _OTHER_CATALOG_ID
    assert unrelated.merchant_id == _OTHER_MERCHANT_ID


@pytest.mark.parametrize(
    "model",
    [_attribute(), _product(), _sku(), _catalog(), _line(), _snapshot()],
)
def test_catalog_models_are_frozen(model: object) -> None:
    with pytest.raises(ValidationError):
        model.schema_version = "changed"  # type: ignore[attr-defined]


def test_catalog_models_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CatalogAttributeV2(
            attribute_key="brand",
            value=AttributeValue(value_type=AttributeValueType.STRING, value="Clear"),
            provenance=ProvenanceLabel.CLAIMED,
            evidence_reference_id=_evidence_id(1),
            extra_field=True,
        )
    with pytest.raises(ValidationError):
        _product(extra_field=True)
    with pytest.raises(ValidationError):
        _sku(extra_field=True)
    with pytest.raises(ValidationError):
        _catalog(extra_field=True)
    with pytest.raises(ValidationError):
        InventoryLineV2(
            sku_id=_sku_id(1),
            quantity_available=1,
            provenance=ProvenanceLabel.CLAIMED,
            evidence_reference_id=_evidence_id(101),
            extra_field=True,
        )
    with pytest.raises(ValidationError):
        _snapshot(extra_field=True)


@pytest.mark.parametrize(
    "model_factory",
    [
        lambda: _product(catalog_product_version="catalog-product-v3"),
        lambda: _sku(catalog_sku_version="catalog-sku-v3"),
        lambda: _catalog(merchant_catalog_version="merchant-catalog-v3"),
        lambda: InventoryLineV2(
            inventory_line_version="inventory-line-v3",
            sku_id=_sku_id(1),
            quantity_available=1,
            provenance=ProvenanceLabel.CLAIMED,
            evidence_reference_id=_evidence_id(101),
        ),
        lambda: _snapshot(inventory_snapshot_version="inventory-snapshot-v3"),
    ],
)
def test_catalog_models_reject_version_mismatches(
    model_factory: Callable[[], object],
) -> None:
    with pytest.raises(ValidationError):
        model_factory()
