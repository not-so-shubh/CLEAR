import re
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from clear_market.commerce.primitives import AttributeKey, AttributeValue, ProvenanceLabel
from clear_market.domain import MAX_QUANTITY, CanonicalUUID4, UTCDateTime

CATALOG_ATTRIBUTE_V2_VERSION: Final[str] = "catalog-attribute-v2"
CATALOG_PRODUCT_V2_VERSION: Final[str] = "catalog-product-v2"
CATALOG_SKU_V2_VERSION: Final[str] = "catalog-sku-v2"
MERCHANT_CATALOG_V2_VERSION: Final[str] = "merchant-catalog-v2"
INVENTORY_LINE_V2_VERSION: Final[str] = "inventory-line-v2"
INVENTORY_SNAPSHOT_V2_VERSION: Final[str] = "inventory-snapshot-v2"

MAX_CATALOG_PRODUCTS: Final[int] = 256
MAX_CATALOG_SKUS: Final[int] = 1_024
MAX_ATTRIBUTES_PER_SKU: Final[int] = 64
MAX_PRODUCT_NAME_CHARS: Final[int] = 256
MAX_PRODUCT_DESCRIPTION_CHARS: Final[int] = 4_096
MAX_SKU_NAME_CHARS: Final[int] = 256
MAX_MERCHANT_SKU_CHARS: Final[int] = 128

_MERCHANT_SKU_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", flags=re.ASCII)


def _require_tuple(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("collection must be supplied as a tuple")
    return value


def _validate_text(value: object, *, allow_empty: bool, maximum: int) -> str:
    if type(value) is not str:
        raise ValueError("catalog text must be supplied as a string")
    if "\x00" in value:
        raise ValueError("catalog text must not contain NUL")
    minimum = 0 if allow_empty else 1
    if not minimum <= len(value) <= maximum:
        raise ValueError("catalog text length is outside its bound")
    return value


def _validate_product_name(value: object) -> str:
    return _validate_text(value, allow_empty=False, maximum=MAX_PRODUCT_NAME_CHARS)


def _validate_product_description(value: object) -> str:
    return _validate_text(value, allow_empty=True, maximum=MAX_PRODUCT_DESCRIPTION_CHARS)


def _validate_sku_name(value: object) -> str:
    return _validate_text(value, allow_empty=False, maximum=MAX_SKU_NAME_CHARS)


def _validate_merchant_sku(value: object) -> str:
    if type(value) is not str or _MERCHANT_SKU_PATTERN.fullmatch(value) is None:
        raise ValueError("merchant SKU is not canonical")
    return value


type _ProductName = Annotated[
    str,
    BeforeValidator(_validate_product_name),
    Field(min_length=1, max_length=MAX_PRODUCT_NAME_CHARS),
]
type _ProductDescription = Annotated[
    str,
    BeforeValidator(_validate_product_description),
    Field(min_length=0, max_length=MAX_PRODUCT_DESCRIPTION_CHARS),
]
type _SkuName = Annotated[
    str,
    BeforeValidator(_validate_sku_name),
    Field(min_length=1, max_length=MAX_SKU_NAME_CHARS),
]
type _MerchantSku = Annotated[str, BeforeValidator(_validate_merchant_sku)]
type _CatalogAttributes = Annotated[
    tuple["CatalogAttributeV2", ...],
    BeforeValidator(_require_tuple),
    Field(max_length=MAX_ATTRIBUTES_PER_SKU),
]
type _CatalogProducts = Annotated[
    tuple["CatalogProductV2", ...],
    BeforeValidator(_require_tuple),
    Field(min_length=1, max_length=MAX_CATALOG_PRODUCTS),
]
type _CatalogSkus = Annotated[
    tuple["CatalogSkuV2", ...],
    BeforeValidator(_require_tuple),
    Field(min_length=1, max_length=MAX_CATALOG_SKUS),
]
type _InventoryQuantity = Annotated[int, Field(strict=True, ge=0, le=MAX_QUANTITY)]
type _InventoryLines = Annotated[
    tuple["InventoryLineV2", ...],
    BeforeValidator(_require_tuple),
    Field(min_length=1, max_length=MAX_CATALOG_SKUS),
]


class CatalogAttributeV2(BaseModel):
    """A typed catalog fact with an explicit provenance label and evidence reference."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["2"] = "2"
    catalog_attribute_version: Literal["catalog-attribute-v2"] = "catalog-attribute-v2"
    attribute_key: AttributeKey
    value: AttributeValue
    provenance: ProvenanceLabel
    evidence_reference_id: CanonicalUUID4


class CatalogProductV2(BaseModel):
    """Untrusted human-facing product text bound to a canonical product identity."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["2"] = "2"
    catalog_product_version: Literal["catalog-product-v2"] = "catalog-product-v2"
    product_id: CanonicalUUID4
    display_name: _ProductName
    description: _ProductDescription


class CatalogSkuV2(BaseModel):
    """A merchant SKU with deterministic typed attribute ordering."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["2"] = "2"
    catalog_sku_version: Literal["catalog-sku-v2"] = "catalog-sku-v2"
    sku_id: CanonicalUUID4
    product_id: CanonicalUUID4
    merchant_sku: _MerchantSku
    display_name: _SkuName
    attributes: _CatalogAttributes

    @field_validator("attributes")
    @classmethod
    def _validate_and_normalize_attributes(
        cls,
        attributes: tuple[CatalogAttributeV2, ...],
    ) -> tuple[CatalogAttributeV2, ...]:
        attribute_keys = tuple(attribute.attribute_key for attribute in attributes)
        if len(set(attribute_keys)) != len(attribute_keys):
            raise ValueError("catalog attribute keys must be unique within a SKU")
        return tuple(sorted(attributes, key=lambda attribute: attribute.attribute_key))


class MerchantCatalogV2(BaseModel):
    """A bounded, deterministic merchant catalog with closed product references."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["2"] = "2"
    merchant_catalog_version: Literal["merchant-catalog-v2"] = "merchant-catalog-v2"
    catalog_id: CanonicalUUID4
    merchant_id: CanonicalUUID4
    generated_at: UTCDateTime
    products: _CatalogProducts
    skus: _CatalogSkus

    @field_validator("products")
    @classmethod
    def _validate_and_normalize_products(
        cls,
        products: tuple[CatalogProductV2, ...],
    ) -> tuple[CatalogProductV2, ...]:
        product_ids = tuple(product.product_id for product in products)
        if len(set(product_ids)) != len(product_ids):
            raise ValueError("catalog product IDs must be unique")
        return tuple(sorted(products, key=lambda product: product.product_id))

    @field_validator("skus")
    @classmethod
    def _validate_and_normalize_skus(
        cls,
        skus: tuple[CatalogSkuV2, ...],
    ) -> tuple[CatalogSkuV2, ...]:
        sku_ids = tuple(sku.sku_id for sku in skus)
        merchant_skus = tuple(sku.merchant_sku for sku in skus)
        if len(set(sku_ids)) != len(sku_ids):
            raise ValueError("catalog SKU IDs must be unique")
        if len(set(merchant_skus)) != len(merchant_skus):
            raise ValueError("merchant SKU identifiers must be unique")
        return tuple(sorted(skus, key=lambda sku: sku.sku_id))

    @model_validator(mode="after")
    def _validate_product_references(self) -> Self:
        product_ids = {product.product_id for product in self.products}
        referenced_product_ids = {sku.product_id for sku in self.skus}
        if not referenced_product_ids <= product_ids:
            raise ValueError("catalog SKU references an unknown product")
        if product_ids != referenced_product_ids:
            raise ValueError("every catalog product must be referenced by a SKU")
        return self


class InventoryLineV2(BaseModel):
    """A bounded quantity statement with explicit provenance and evidence reference."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["2"] = "2"
    inventory_line_version: Literal["inventory-line-v2"] = "inventory-line-v2"
    sku_id: CanonicalUUID4
    quantity_available: _InventoryQuantity
    provenance: ProvenanceLabel
    evidence_reference_id: CanonicalUUID4


class InventorySnapshotV2(BaseModel):
    """An immutable merchant inventory snapshot independent of catalog resolution."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal["2"] = "2"
    inventory_snapshot_version: Literal["inventory-snapshot-v2"] = "inventory-snapshot-v2"
    snapshot_id: CanonicalUUID4
    catalog_id: CanonicalUUID4
    merchant_id: CanonicalUUID4
    captured_at: UTCDateTime
    lines: _InventoryLines

    @field_validator("lines")
    @classmethod
    def _validate_and_normalize_lines(
        cls,
        lines: tuple[InventoryLineV2, ...],
    ) -> tuple[InventoryLineV2, ...]:
        sku_ids = tuple(line.sku_id for line in lines)
        if len(set(sku_ids)) != len(sku_ids):
            raise ValueError("inventory line SKU IDs must be unique")
        return tuple(sorted(lines, key=lambda line: line.sku_id))
