import json
from collections.abc import Callable
from typing import cast

import pytest

import clear_market.commerce as commerce
from clear_market.commerce import (
    AttributeValue,
    AttributeValueType,
    SignedMerchantOfferParseError,
    SignedMerchantOfferParseFailureCode,
    canonical_signed_merchant_offer_v2_bytes,
    parse_canonical_signed_merchant_offer_v2,
)
from clear_market.commerce.auth_parsing import MAX_CANONICAL_SIGNED_MERCHANT_OFFER_BYTES
from tests.commerce.test_authentication import _directly_signed, _signed, _verification_data


class _BytesSubclass(bytes):
    pass


def _json_bytes(
    value: object,
    *,
    sort_keys: bool = True,
    ensure_ascii: bool = False,
    separators: tuple[str, str] = (",", ":"),
) -> bytes:
    return json.dumps(
        value,
        sort_keys=sort_keys,
        ensure_ascii=ensure_ascii,
        separators=separators,
    ).encode("utf-8")


def _envelope(data: bytes | None = None) -> dict[str, object]:
    parsed = json.loads(_verification_data() if data is None else data)
    assert type(parsed) is dict
    return cast(dict[str, object], parsed)


def _payload(envelope: dict[str, object]) -> dict[str, object]:
    payload = envelope["payload"]
    assert type(payload) is dict
    return cast(dict[str, object], payload)


def _offer(payload: dict[str, object]) -> dict[str, object]:
    offer = payload["offer"]
    assert type(offer) is dict
    return cast(dict[str, object], offer)


def _first_line(offer: dict[str, object]) -> dict[str, object]:
    lines = offer["lines"]
    assert type(lines) is list
    line = cast(list[object], lines)[0]
    assert type(line) is dict
    return cast(dict[str, object], line)


def _assert_parse_failure(
    data: bytes,
    expected: SignedMerchantOfferParseFailureCode,
) -> None:
    with pytest.raises(SignedMerchantOfferParseError) as caught:
        parse_canonical_signed_merchant_offer_v2(data)
    assert caught.value.code is expected
    assert str(caught.value) == expected.value


def test_parse_failure_contract_and_maximum_are_exact() -> None:
    assert tuple(SignedMerchantOfferParseFailureCode) == (
        SignedMerchantOfferParseFailureCode.INPUT_TOO_LARGE,
        SignedMerchantOfferParseFailureCode.INVALID_UTF8,
        SignedMerchantOfferParseFailureCode.INVALID_JSON,
        SignedMerchantOfferParseFailureCode.DUPLICATE_KEY,
        SignedMerchantOfferParseFailureCode.INVALID_ENVELOPE,
        SignedMerchantOfferParseFailureCode.INVALID_SIGNED_OFFER,
        SignedMerchantOfferParseFailureCode.NON_CANONICAL,
    )
    assert tuple(code.value for code in SignedMerchantOfferParseFailureCode) == (
        "input_too_large",
        "invalid_utf8",
        "invalid_json",
        "duplicate_key",
        "invalid_envelope",
        "invalid_signed_offer",
        "non_canonical",
    )
    assert MAX_CANONICAL_SIGNED_MERCHANT_OFFER_BYTES == 1_048_576
    assert "MAX_CANONICAL_SIGNED_MERCHANT_OFFER_BYTES" not in commerce.__all__


def test_parse_error_code_is_read_only() -> None:
    error = SignedMerchantOfferParseError(SignedMerchantOfferParseFailureCode.INVALID_JSON)
    assert error.code is SignedMerchantOfferParseFailureCode.INVALID_JSON
    assert str(error) == "invalid_json"
    with pytest.raises(AttributeError):
        error.code = SignedMerchantOfferParseFailureCode.NON_CANONICAL


def test_valid_canonical_signed_offer_parses_and_roundtrips_exactly() -> None:
    original = _signed()
    data = canonical_signed_merchant_offer_v2_bytes(original)

    parsed = parse_canonical_signed_merchant_offer_v2(data)

    assert parsed == original
    assert canonical_signed_merchant_offer_v2_bytes(parsed) == data
    assert type(parsed.offer.lines) is tuple
    assert all(type(line.attributes) is tuple for line in parsed.offer.lines)


@pytest.mark.parametrize(
    "value",
    [None, {}, "json", bytearray(b"{}"), memoryview(b"{}"), _BytesSubclass(b"{}")],
)
def test_parser_requires_exact_builtin_bytes(value: object) -> None:
    with pytest.raises(TypeError):
        parse_canonical_signed_merchant_offer_v2(value)  # type: ignore[arg-type]


def test_zero_length_input_is_invalid_json() -> None:
    _assert_parse_failure(b"", SignedMerchantOfferParseFailureCode.INVALID_JSON)


def test_exact_size_bound_proceeds_and_one_byte_over_fails_early() -> None:
    _assert_parse_failure(
        b"x" * MAX_CANONICAL_SIGNED_MERCHANT_OFFER_BYTES,
        SignedMerchantOfferParseFailureCode.INVALID_JSON,
    )
    _assert_parse_failure(
        b"x" * (MAX_CANONICAL_SIGNED_MERCHANT_OFFER_BYTES + 1),
        SignedMerchantOfferParseFailureCode.INPUT_TOO_LARGE,
    )


@pytest.mark.parametrize(
    "data",
    [b"\xff", b"\xef\xbb\xbf" + _verification_data()],
    ids=["invalid-byte", "utf8-bom"],
)
def test_invalid_utf8_and_bom_are_rejected(data: bytes) -> None:
    _assert_parse_failure(data, SignedMerchantOfferParseFailureCode.INVALID_UTF8)


@pytest.mark.parametrize(
    "data",
    [
        b"{",
        _verification_data()[:-1],
        _verification_data() + b"{}",
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
    ],
    ids=["truncated", "truncated-valid", "trailing-json", "nan", "infinity", "negative-infinity"],
)
def test_malformed_json_trailing_json_and_constants_are_rejected(data: bytes) -> None:
    _assert_parse_failure(data, SignedMerchantOfferParseFailureCode.INVALID_JSON)


def test_deeply_nested_bounded_json_recursion_is_invalid_json() -> None:
    data = b"[" * 10_000 + b"0" + b"]" * 10_000

    assert len(data) < MAX_CANONICAL_SIGNED_MERCHANT_OFFER_BYTES
    with pytest.raises(RecursionError):
        json.loads(data)
    _assert_parse_failure(data, SignedMerchantOfferParseFailureCode.INVALID_JSON)


@pytest.mark.parametrize(
    "data",
    [
        (
            b'{"canonicalization_version":"clear-json-v1",'
            b'"canonicalization_version":"clear-json-v1","payload":{},'
            b'"payload_type":"signed_merchant_offer_v2"}'
        ),
        (
            b'{"canonicalization_version":"clear-json-v1","payload":{"offer":{},"offer":{}},'
            b'"payload_type":"signed_merchant_offer_v2"}'
        ),
        (
            b'{"canonicalization_version":"clear-json-v1","payload":{"offer":{"lines":['
            b'{"sku_id":"49000000-0000-4000-8000-000000000001",'
            b'"sku_id":"49000000-0000-4000-8000-000000000001"}]}},'
            b'"payload_type":"signed_merchant_offer_v2"}'
        ),
    ],
    ids=["root", "nested-offer", "nested-line"],
)
def test_duplicate_keys_at_all_required_nesting_levels_are_rejected(data: bytes) -> None:
    _assert_parse_failure(data, SignedMerchantOfferParseFailureCode.DUPLICATE_KEY)


@pytest.mark.parametrize("root", [[], None, "signed", 1, True])
def test_non_object_root_is_invalid_envelope(root: object) -> None:
    _assert_parse_failure(_json_bytes(root), SignedMerchantOfferParseFailureCode.INVALID_ENVELOPE)


@pytest.mark.parametrize(
    "envelope",
    [
        {"canonicalization_version": "clear-json-v1", "payload": {}},
        {
            "canonicalization_version": "clear-json-v1",
            "payload": {},
            "payload_type": "signed_merchant_offer_v2",
            "extra": None,
        },
        {
            "canonicalization_version": "clear-json-v2",
            "payload": {},
            "payload_type": "signed_merchant_offer_v2",
        },
        {
            "canonicalization_version": "clear-json-v1",
            "payload": {},
            "payload_type": "merchant_offer_v2",
        },
        {
            "canonicalization_version": "clear-json-v1",
            "payload": [],
            "payload_type": "signed_merchant_offer_v2",
        },
        {
            "canonicalization_version": "clear-json-v1",
            "payload": None,
            "payload_type": "signed_merchant_offer_v2",
        },
    ],
)
def test_exact_envelope_contract_is_enforced(envelope: dict[str, object]) -> None:
    _assert_parse_failure(
        _json_bytes(envelope),
        SignedMerchantOfferParseFailureCode.INVALID_ENVELOPE,
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "invalid_model_version",
        "invalid_signature_hex",
        "invalid_money",
        "float_quantity",
        "bool_quantity",
        "malformed_uuid",
    ],
)
def test_invalid_signed_offer_payload_shapes_are_rejected(mutation: str) -> None:
    envelope = _envelope()
    payload = _payload(envelope)
    offer = _offer(payload)
    line = _first_line(offer)

    if mutation == "invalid_model_version":
        payload["signed_merchant_offer_version"] = "signed-merchant-offer-v3"
    elif mutation == "invalid_signature_hex":
        payload["signature_hex"] = "invalid"
    elif mutation == "invalid_money":
        line["unit_price"] = {"amount_paise": -1, "currency": "INR"}
    elif mutation == "float_quantity":
        line["max_offer_quantity"] = 5.0
    elif mutation == "bool_quantity":
        line["max_offer_quantity"] = True
    elif mutation == "malformed_uuid":
        offer["offer_id"] = "not-a-uuid"
    else:
        raise AssertionError("unknown mutation")

    _assert_parse_failure(
        _json_bytes(envelope),
        SignedMerchantOfferParseFailureCode.INVALID_SIGNED_OFFER,
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda data: data + b"\n",
        lambda data: b" " + data,
        lambda data: data + b" ",
    ],
    ids=["trailing-newline", "leading-space", "trailing-space"],
)
def test_noncanonical_whitespace_is_rejected(mutator: Callable[[bytes], bytes]) -> None:
    changed = mutator(_verification_data())
    _assert_parse_failure(changed, SignedMerchantOfferParseFailureCode.NON_CANONICAL)


def test_noncanonical_key_order_is_rejected() -> None:
    envelope = _envelope()
    reordered = {
        "payload_type": envelope["payload_type"],
        "payload": envelope["payload"],
        "canonicalization_version": envelope["canonicalization_version"],
    }
    _assert_parse_failure(
        _json_bytes(reordered, sort_keys=False),
        SignedMerchantOfferParseFailureCode.NON_CANONICAL,
    )


def test_escaped_unicode_representation_is_rejected_as_noncanonical() -> None:
    signed = _signed()
    line = signed.offer.lines[0]
    attribute = line.attributes[0]
    changed_attribute = attribute.model_copy(
        update={"value": AttributeValue(value_type=AttributeValueType.STRING, value="Café")}
    )
    changed_line = line.model_copy(update={"attributes": (changed_attribute, line.attributes[1])})
    changed_offer = signed.offer.model_copy(update={"lines": (changed_line, signed.offer.lines[1])})
    canonical = canonical_signed_merchant_offer_v2_bytes(_directly_signed(changed_offer))
    escaped = _json_bytes(_envelope(canonical), ensure_ascii=True)

    assert b"Caf\\u00e9" in escaped
    _assert_parse_failure(escaped, SignedMerchantOfferParseFailureCode.NON_CANONICAL)


def test_lone_unicode_surrogate_is_invalid_signed_offer() -> None:
    envelope = _envelope()
    line = _first_line(_offer(_payload(envelope)))
    attributes = line["attributes"]
    assert type(attributes) is list
    attribute = cast(list[object], attributes)[0]
    assert type(attribute) is dict
    value = cast(dict[str, object], attribute)["value"]
    assert type(value) is dict
    cast(dict[str, object], value)["value"] = "\ud800"
    data = _json_bytes(envelope, ensure_ascii=True)

    assert data.isascii()
    assert b"\\ud800" in data
    _assert_parse_failure(data, SignedMerchantOfferParseFailureCode.INVALID_SIGNED_OFFER)
