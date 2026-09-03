import json
import re
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Final, cast

from pydantic import ValidationError

from clear_market.canonical import CanonicalizationError
from clear_market.certificate.v2.models import (
    AllocationCertificateV2,
    AllocationClaimLineV2,
    AllocationClaimStatusV2,
    AllocationClaimV2,
    MerchantOfferAdmissionDecisionV2,
    MerchantOfferEvidenceV2,
)
from clear_market.certificate.v2.serialization import canonical_allocation_certificate_v2_bytes
from clear_market.commerce.authentication import MerchantSigningIdentityV2, SignedMerchantOfferV2
from clear_market.commerce.catalog import (
    CatalogAttributeV2,
    CatalogProductV2,
    CatalogSkuV2,
    InventoryLineV2,
    InventorySnapshotV2,
    MerchantCatalogV2,
)
from clear_market.commerce.constraints import ComparisonOperator, HardConstraint, SoftPreference
from clear_market.commerce.market import BuyerPolicyV2, MarketSpecV2
from clear_market.commerce.merchant import MerchantOfferLineV2, MerchantOfferV2
from clear_market.commerce.primitives import AttributeValue, AttributeValueType, ProvenanceLabel
from clear_market.domain import Currency, Money

MAX_CANONICAL_ALLOCATION_CERTIFICATE_V2_BYTES: Final[int] = 1_048_576

_UTF8_BOM = b"\xef\xbb\xbf"
_ENVELOPE_KEYS = frozenset(("canonicalization_version", "payload_type", "payload"))
_WIRE_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)


class AllocationCertificateV2ParseFailureCode(StrEnum):
    INPUT_TOO_LARGE = "input_too_large"
    INVALID_UTF8 = "invalid_utf8"
    INVALID_JSON = "invalid_json"
    DUPLICATE_KEY = "duplicate_key"
    INVALID_ENVELOPE = "invalid_envelope"
    INVALID_CERTIFICATE = "invalid_certificate"
    NON_CANONICAL = "non_canonical"


class AllocationCertificateV2ParseError(ValueError):
    """Stable failure category for untrusted canonical V2 certificate bytes."""

    __slots__ = ("_code",)

    def __init__(self, code: AllocationCertificateV2ParseFailureCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> AllocationCertificateV2ParseFailureCode:
        return self._code


class _DuplicateKeyError(ValueError):
    pass


class _NonStandardConstantError(ValueError):
    pass


class _InvalidWireTimestampError(ValueError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_nonstandard_constant(_value: str) -> object:
    raise _NonStandardConstantError


def _as_exact_dict(value: object) -> dict[str, object] | None:
    if type(value) is not dict:
        return None
    return cast(dict[str, object], value)


def _wire_enum(value: object, enum_type: type[StrEnum]) -> object:
    if type(value) is not str:
        return value
    try:
        return enum_type(value)
    except ValueError:
        return value


def _wire_datetime(value: object) -> object:
    if type(value) is not str:
        return value
    if _WIRE_TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise _InvalidWireTimestampError
    construction_text = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(construction_text)
    except ValueError:
        raise _InvalidWireTimestampError from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _InvalidWireTimestampError
    return parsed


def _wire_tuple(value: object, converter: Callable[[object], object]) -> object:
    if type(value) is not list:
        return value
    return tuple(converter(item) for item in cast(list[object], value))


def _wire_enum_tuple(value: object, enum_type: type[StrEnum]) -> object:
    return _wire_tuple(value, lambda item: _wire_enum(item, enum_type))


def _wire_identity(value: object) -> object:
    data = _as_exact_dict(value)
    return value if data is None else MerchantSigningIdentityV2.model_validate(data)


def _wire_money(value: object) -> object:
    data = _as_exact_dict(value)
    if data is None:
        return value
    converted = dict(data)
    if "currency" in converted:
        converted["currency"] = _wire_enum(converted["currency"], Currency)
    return Money.model_validate(converted)


def _wire_attribute_value(value: object) -> object:
    data = _as_exact_dict(value)
    if data is None:
        return value
    converted = dict(data)
    if "value_type" in converted:
        converted["value_type"] = _wire_enum(converted["value_type"], AttributeValueType)
    return AttributeValue.model_validate(converted)


def _wire_rule(value: object, rule_type: type[HardConstraint] | type[SoftPreference]) -> object:
    data = _as_exact_dict(value)
    if data is None:
        return value
    converted = dict(data)
    if "operator" in converted:
        converted["operator"] = _wire_enum(converted["operator"], ComparisonOperator)
    if "operand" in converted:
        converted["operand"] = _wire_attribute_value(converted["operand"])
    if "allowed_provenance" in converted:
        converted["allowed_provenance"] = _wire_enum_tuple(
            converted["allowed_provenance"], ProvenanceLabel
        )
    return rule_type.model_validate(converted)


def _wire_hard_constraint(value: object) -> object:
    return _wire_rule(value, HardConstraint)


def _wire_soft_preference(value: object) -> object:
    return _wire_rule(value, SoftPreference)


def _wire_market_spec(value: object) -> object:
    data = _as_exact_dict(value)
    if data is None:
        return value
    converted = dict(data)
    if "hard_constraints" in converted:
        converted["hard_constraints"] = _wire_tuple(
            converted["hard_constraints"], _wire_hard_constraint
        )
    if "soft_preferences" in converted:
        converted["soft_preferences"] = _wire_tuple(
            converted["soft_preferences"], _wire_soft_preference
        )
    return MarketSpecV2.model_validate(converted)


def _wire_buyer_policy(value: object) -> object:
    data = _as_exact_dict(value)
    if data is None:
        return value
    converted = dict(data)
    if "market_spec" in converted:
        converted["market_spec"] = _wire_market_spec(converted["market_spec"])
    if "max_total_payment" in converted:
        converted["max_total_payment"] = _wire_money(converted["max_total_payment"])
    if "eligible_merchant_ids" in converted:
        converted["eligible_merchant_ids"] = _wire_tuple(
            converted["eligible_merchant_ids"], lambda item: item
        )
    if "offer_deadline" in converted:
        converted["offer_deadline"] = _wire_datetime(converted["offer_deadline"])
    return BuyerPolicyV2.model_validate(converted)


def _wire_catalog_attribute(value: object) -> object:
    data = _as_exact_dict(value)
    if data is None:
        return value
    converted = dict(data)
    if "value" in converted:
        converted["value"] = _wire_attribute_value(converted["value"])
    if "provenance" in converted:
        converted["provenance"] = _wire_enum(converted["provenance"], ProvenanceLabel)
    return CatalogAttributeV2.model_validate(converted)


def _wire_catalog_product(value: object) -> object:
    data = _as_exact_dict(value)
    return value if data is None else CatalogProductV2.model_validate(data)


def _wire_catalog_sku(value: object) -> object:
    data = _as_exact_dict(value)
    if data is None:
        return value
    converted = dict(data)
    if "attributes" in converted:
        converted["attributes"] = _wire_tuple(converted["attributes"], _wire_catalog_attribute)
    return CatalogSkuV2.model_validate(converted)


def _wire_catalog(value: object) -> object:
    data = _as_exact_dict(value)
    if data is None:
        return value
    converted = dict(data)
    if "generated_at" in converted:
        converted["generated_at"] = _wire_datetime(converted["generated_at"])
    if "products" in converted:
        converted["products"] = _wire_tuple(converted["products"], _wire_catalog_product)
    if "skus" in converted:
        converted["skus"] = _wire_tuple(converted["skus"], _wire_catalog_sku)
    return MerchantCatalogV2.model_validate(converted)


def _wire_inventory_line(value: object) -> object:
    data = _as_exact_dict(value)
    if data is None:
        return value
    converted = dict(data)
    if "provenance" in converted:
        converted["provenance"] = _wire_enum(converted["provenance"], ProvenanceLabel)
    return InventoryLineV2.model_validate(converted)


def _wire_inventory(value: object) -> object:
    data = _as_exact_dict(value)
    if data is None:
        return value
    converted = dict(data)
    if "captured_at" in converted:
        converted["captured_at"] = _wire_datetime(converted["captured_at"])
    if "lines" in converted:
        converted["lines"] = _wire_tuple(converted["lines"], _wire_inventory_line)
    return InventorySnapshotV2.model_validate(converted)


def _wire_offer_line(value: object) -> object:
    data = _as_exact_dict(value)
    if data is None:
        return value
    converted = dict(data)
    if "unit_price" in converted:
        converted["unit_price"] = _wire_money(converted["unit_price"])
    if "attributes" in converted:
        converted["attributes"] = _wire_tuple(converted["attributes"], _wire_catalog_attribute)
    if "inventory_provenance" in converted:
        converted["inventory_provenance"] = _wire_enum(
            converted["inventory_provenance"], ProvenanceLabel
        )
    return MerchantOfferLineV2.model_validate(converted)


def _wire_offer(value: object) -> object:
    data = _as_exact_dict(value)
    if data is None:
        return value
    converted = dict(data)
    if "lines" in converted:
        converted["lines"] = _wire_tuple(converted["lines"], _wire_offer_line)
    return MerchantOfferV2.model_validate(converted)


def _wire_signed_offer(value: object) -> object:
    data = _as_exact_dict(value)
    if data is None:
        return value
    converted = dict(data)
    if "offer" in converted:
        converted["offer"] = _wire_offer(converted["offer"])
    return SignedMerchantOfferV2.model_validate(converted)


def _wire_evidence(value: object) -> object:
    data = _as_exact_dict(value)
    if data is None:
        return value
    converted = dict(data)
    if "received_at" in converted:
        converted["received_at"] = _wire_datetime(converted["received_at"])
    if "admission_decision" in converted:
        converted["admission_decision"] = _wire_enum(
            converted["admission_decision"], MerchantOfferAdmissionDecisionV2
        )
    if "signing_identity" in converted:
        converted["signing_identity"] = _wire_identity(converted["signing_identity"])
    if "catalog" in converted:
        converted["catalog"] = _wire_catalog(converted["catalog"])
    if "inventory" in converted:
        converted["inventory"] = _wire_inventory(converted["inventory"])
    if "signed_offer" in converted:
        converted["signed_offer"] = _wire_signed_offer(converted["signed_offer"])
    return MerchantOfferEvidenceV2.model_validate(converted)


def _wire_claim_line(value: object) -> object:
    data = _as_exact_dict(value)
    if data is None:
        return value
    converted = dict(data)
    if "unit_payment" in converted:
        converted["unit_payment"] = _wire_money(converted["unit_payment"])
    if "line_payment" in converted:
        converted["line_payment"] = _wire_money(converted["line_payment"])
    return AllocationClaimLineV2.model_validate(converted)


def _wire_allocation(value: object) -> object:
    data = _as_exact_dict(value)
    if data is None:
        return value
    converted = dict(data)
    if "status" in converted:
        converted["status"] = _wire_enum(converted["status"], AllocationClaimStatusV2)
    if "total_payment" in converted:
        converted["total_payment"] = _wire_money(converted["total_payment"])
    if "lines" in converted:
        converted["lines"] = _wire_tuple(converted["lines"], _wire_claim_line)
    return AllocationClaimV2.model_validate(converted)


def _wire_certificate(payload: dict[str, object]) -> AllocationCertificateV2:
    converted = dict(payload)
    if "buyer_policy" in converted:
        converted["buyer_policy"] = _wire_buyer_policy(converted["buyer_policy"])
    if "merchant_offer_evidence" in converted:
        converted["merchant_offer_evidence"] = _wire_tuple(
            converted["merchant_offer_evidence"], _wire_evidence
        )
    if "allocation" in converted:
        converted["allocation"] = _wire_allocation(converted["allocation"])
    return AllocationCertificateV2.model_validate(converted)


def parse_canonical_allocation_certificate_v2(data: bytes) -> AllocationCertificateV2:
    """Accept only bounded exact canonical bytes for the V2 certificate evidence protocol."""
    if type(data) is not bytes:
        raise TypeError("data must be exactly bytes")
    if len(data) > MAX_CANONICAL_ALLOCATION_CERTIFICATE_V2_BYTES:
        raise AllocationCertificateV2ParseError(
            AllocationCertificateV2ParseFailureCode.INPUT_TOO_LARGE
        )
    if data.startswith(_UTF8_BOM):
        raise AllocationCertificateV2ParseError(
            AllocationCertificateV2ParseFailureCode.INVALID_UTF8
        )

    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise AllocationCertificateV2ParseError(
            AllocationCertificateV2ParseFailureCode.INVALID_UTF8
        ) from None

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_constant,
        )
    except _DuplicateKeyError:
        raise AllocationCertificateV2ParseError(
            AllocationCertificateV2ParseFailureCode.DUPLICATE_KEY
        ) from None
    except (_NonStandardConstantError, json.JSONDecodeError, RecursionError, ValueError):
        raise AllocationCertificateV2ParseError(
            AllocationCertificateV2ParseFailureCode.INVALID_JSON
        ) from None

    root = _as_exact_dict(parsed)
    if root is None or set(root) != _ENVELOPE_KEYS:
        raise AllocationCertificateV2ParseError(
            AllocationCertificateV2ParseFailureCode.INVALID_ENVELOPE
        )
    if root["canonicalization_version"] != "clear-json-v1":
        raise AllocationCertificateV2ParseError(
            AllocationCertificateV2ParseFailureCode.INVALID_ENVELOPE
        )
    if root["payload_type"] != "allocation_certificate_v2":
        raise AllocationCertificateV2ParseError(
            AllocationCertificateV2ParseFailureCode.INVALID_ENVELOPE
        )

    payload = _as_exact_dict(root["payload"])
    if payload is None:
        raise AllocationCertificateV2ParseError(
            AllocationCertificateV2ParseFailureCode.INVALID_ENVELOPE
        )

    try:
        certificate = _wire_certificate(payload)
    except (_InvalidWireTimestampError, RecursionError, ValidationError):
        raise AllocationCertificateV2ParseError(
            AllocationCertificateV2ParseFailureCode.INVALID_CERTIFICATE
        ) from None

    try:
        canonical_data = canonical_allocation_certificate_v2_bytes(certificate)
    except CanonicalizationError:
        raise AllocationCertificateV2ParseError(
            AllocationCertificateV2ParseFailureCode.INVALID_CERTIFICATE
        ) from None
    if canonical_data != data:
        raise AllocationCertificateV2ParseError(
            AllocationCertificateV2ParseFailureCode.NON_CANONICAL
        )
    return certificate
