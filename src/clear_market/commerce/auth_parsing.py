import json
from enum import StrEnum
from typing import Final, cast

from pydantic import ValidationError

from clear_market.canonical import CanonicalizationError
from clear_market.commerce.auth_serialization import canonical_signed_merchant_offer_v2_bytes
from clear_market.commerce.authentication import SignedMerchantOfferV2
from clear_market.commerce.primitives import AttributeValueType, ProvenanceLabel

MAX_CANONICAL_SIGNED_MERCHANT_OFFER_BYTES: Final[int] = 1_048_576

_UTF8_BOM = b"\xef\xbb\xbf"
_ENVELOPE_KEYS = frozenset(("canonicalization_version", "payload_type", "payload"))


class SignedMerchantOfferParseFailureCode(StrEnum):
    INPUT_TOO_LARGE = "input_too_large"
    INVALID_UTF8 = "invalid_utf8"
    INVALID_JSON = "invalid_json"
    DUPLICATE_KEY = "duplicate_key"
    INVALID_ENVELOPE = "invalid_envelope"
    INVALID_SIGNED_OFFER = "invalid_signed_offer"
    NON_CANONICAL = "non_canonical"


class SignedMerchantOfferParseError(ValueError):
    """Stable failure category for untrusted signed-offer bytes."""

    __slots__ = ("_code",)

    def __init__(self, code: SignedMerchantOfferParseFailureCode) -> None:
        self._code = code
        super().__init__(code.value)

    @property
    def code(self) -> SignedMerchantOfferParseFailureCode:
        return self._code


class _DuplicateKeyError(ValueError):
    pass


class _NonStandardConstantError(ValueError):
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


def _convert_targeted_wire_values(payload: dict[str, object]) -> None:
    offer = _as_exact_dict(payload.get("offer"))
    if offer is None:
        return
    lines_value = offer.get("lines")
    if type(lines_value) is not list:
        return

    lines = cast(list[object], lines_value)
    for line_value in lines:
        line = _as_exact_dict(line_value)
        if line is None:
            continue
        if "inventory_provenance" in line:
            line["inventory_provenance"] = _wire_enum(line["inventory_provenance"], ProvenanceLabel)

        attributes_value = line.get("attributes")
        if type(attributes_value) is not list:
            continue
        attributes = cast(list[object], attributes_value)
        for attribute_value in attributes:
            attribute = _as_exact_dict(attribute_value)
            if attribute is None:
                continue
            if "provenance" in attribute:
                attribute["provenance"] = _wire_enum(attribute["provenance"], ProvenanceLabel)
            typed_value = _as_exact_dict(attribute.get("value"))
            if typed_value is not None and "value_type" in typed_value:
                typed_value["value_type"] = _wire_enum(
                    typed_value["value_type"], AttributeValueType
                )
        line["attributes"] = tuple(attributes)
    offer["lines"] = tuple(lines)


def parse_canonical_signed_merchant_offer_v2(data: bytes) -> SignedMerchantOfferV2:
    """Accept only bounded exact canonical bytes for the signed-offer protocol."""
    if type(data) is not bytes:
        raise TypeError("data must be exactly bytes")
    if len(data) > MAX_CANONICAL_SIGNED_MERCHANT_OFFER_BYTES:
        raise SignedMerchantOfferParseError(SignedMerchantOfferParseFailureCode.INPUT_TOO_LARGE)
    if data.startswith(_UTF8_BOM):
        raise SignedMerchantOfferParseError(SignedMerchantOfferParseFailureCode.INVALID_UTF8)

    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise SignedMerchantOfferParseError(
            SignedMerchantOfferParseFailureCode.INVALID_UTF8
        ) from None

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonstandard_constant,
        )
    except _DuplicateKeyError:
        raise SignedMerchantOfferParseError(
            SignedMerchantOfferParseFailureCode.DUPLICATE_KEY
        ) from None
    except (_NonStandardConstantError, json.JSONDecodeError, RecursionError, ValueError):
        raise SignedMerchantOfferParseError(
            SignedMerchantOfferParseFailureCode.INVALID_JSON
        ) from None

    root = _as_exact_dict(parsed)
    if root is None or set(root) != _ENVELOPE_KEYS:
        raise SignedMerchantOfferParseError(SignedMerchantOfferParseFailureCode.INVALID_ENVELOPE)
    if root["canonicalization_version"] != "clear-json-v1":
        raise SignedMerchantOfferParseError(SignedMerchantOfferParseFailureCode.INVALID_ENVELOPE)
    if root["payload_type"] != "signed_merchant_offer_v2":
        raise SignedMerchantOfferParseError(SignedMerchantOfferParseFailureCode.INVALID_ENVELOPE)

    payload = _as_exact_dict(root["payload"])
    if payload is None:
        raise SignedMerchantOfferParseError(SignedMerchantOfferParseFailureCode.INVALID_ENVELOPE)

    try:
        _convert_targeted_wire_values(payload)
        signed_offer = SignedMerchantOfferV2.model_validate(payload)
    except (RecursionError, ValidationError):
        raise SignedMerchantOfferParseError(
            SignedMerchantOfferParseFailureCode.INVALID_SIGNED_OFFER
        ) from None

    try:
        canonical_data = canonical_signed_merchant_offer_v2_bytes(signed_offer)
    except CanonicalizationError:
        raise SignedMerchantOfferParseError(
            SignedMerchantOfferParseFailureCode.INVALID_SIGNED_OFFER
        ) from None

    if canonical_data != data:
        raise SignedMerchantOfferParseError(SignedMerchantOfferParseFailureCode.NON_CANONICAL)
    return signed_offer
