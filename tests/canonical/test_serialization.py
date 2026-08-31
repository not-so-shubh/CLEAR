import hashlib
import json
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from uuid import UUID

import pytest

import clear_market.canonical as canonical
from clear_market.canonical import (
    CANONICALIZATION_VERSION,
    CanonicalizationError,
    canonical_buyer_policy_bytes,
    canonical_json_bytes,
    canonical_merchant_bid_bytes,
    canonical_utc_datetime,
)
from clear_market.domain import (
    BuyerPolicy,
    Currency,
    MarketSpec,
    MerchantBid,
    MerchantIdentity,
    Money,
)

_MARKET_ID = "10000000-0000-4000-8000-000000000001"
_BUYER_ID = "20000000-0000-4000-8000-000000000001"
_MERCHANT_ID_1 = "30000000-0000-4000-8000-000000000001"
_MERCHANT_ID_2 = "30000000-0000-4000-8000-000000000002"
_PUBLIC_KEY_1 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
_PUBLIC_KEY_2 = "1111111111111111111111111111111111111111111111111111111111111111"
_GOLDEN_DEADLINE = datetime(2026, 9, 1, 12, 0, 0, 123_456, tzinfo=UTC)
_BID_ID = "40000000-0000-4000-8000-000000000001"
_BUYER_POLICY_COMMITMENT = "2c11204c2b587606020b0d035719ec2b32f217e0b78ffdb22e038bd7ec1f4ca7"
_BID_SUBMITTED_AT = datetime(2026, 9, 1, 11, 59, 59, 123_456, tzinfo=UTC)
_GOLDEN_JSON = (
    '{"canonicalization_version":"clear-json-v1","payload":{"bid_deadline":'
    '"2026-09-01T12:00:00.123456Z","eligible_merchants":['
    '{"ed25519_public_key_hex":"0123456789abcdef0123456789abcdef0123456789abcdef'
    '0123456789abcdef","merchant_id":"30000000-0000-4000-8000-000000000001",'
    '"schema_version":"1"},{"ed25519_public_key_hex":"11111111111111111111111111111111'
    '11111111111111111111111111111111","merchant_id":'
    '"30000000-0000-4000-8000-000000000002","schema_version":"1"}],'
    '"market_spec":{"buyer_id":"20000000-0000-4000-8000-000000000001",'
    '"market_id":"10000000-0000-4000-8000-000000000001","requested_quantity":4,'
    '"schema_version":"1"},"max_total_payment":{"amount_paise":500,"currency":"INR"},'
    '"mechanism_version":"reverse_second_price_v1","reserve_unit_price":'
    '{"amount_paise":125,"currency":"INR"},"schema_version":"1","tie_break_rule":'
    '"merchant_id_lexicographic_ascending"},"payload_type":"buyer_policy"}'
)
_GOLDEN_BYTES = _GOLDEN_JSON.encode("utf-8")
_GOLDEN_BID_JSON = (
    '{"canonicalization_version":"clear-json-v1","payload":{"bid_id":'
    '"40000000-0000-4000-8000-000000000001","buyer_policy_commitment":'
    '"2c11204c2b587606020b0d035719ec2b32f217e0b78ffdb22e038bd7ec1f4ca7",'
    '"buyer_policy_commitment_version":"sha256-clear-json-v1","currency":"INR",'
    '"market_id":"10000000-0000-4000-8000-000000000001","merchant_id":'
    '"30000000-0000-4000-8000-000000000001","quantity_available":4,'
    '"schema_version":"1","submitted_at":"2026-09-01T11:59:59.123456Z",'
    '"unit_price_paise":100},"payload_type":"merchant_bid"}'
)
_GOLDEN_BID_BYTES = _GOLDEN_BID_JSON.encode()
_GOLDEN_BID_SHA256 = "8fb601e4203a2b2213637505c224652775b8a7baad928e9c2538002aa731f0dc"


class _NoOffsetTimezone(tzinfo):
    def utcoffset(self, _value: datetime | None) -> None:
        return None


def _golden_merchants(*, reverse: bool = False) -> tuple[MerchantIdentity, ...]:
    merchants = (
        MerchantIdentity(
            merchant_id=_MERCHANT_ID_1,
            ed25519_public_key_hex=_PUBLIC_KEY_1,
        ),
        MerchantIdentity(
            merchant_id=_MERCHANT_ID_2,
            ed25519_public_key_hex=_PUBLIC_KEY_2,
        ),
    )
    return tuple(reversed(merchants)) if reverse else merchants


def _golden_policy(
    *,
    reverse_merchants: bool = False,
    deadline: datetime = _GOLDEN_DEADLINE,
) -> BuyerPolicy:
    return BuyerPolicy(
        market_spec=MarketSpec(
            market_id=_MARKET_ID,
            buyer_id=_BUYER_ID,
            requested_quantity=4,
        ),
        max_total_payment=Money(amount_paise=500),
        reserve_unit_price=Money(amount_paise=125),
        eligible_merchants=_golden_merchants(reverse=reverse_merchants),
        bid_deadline=deadline,
    )


def _golden_bid(
    *,
    bid_id: str = _BID_ID,
    market_id: str = _MARKET_ID,
    merchant_id: str = _MERCHANT_ID_1,
    buyer_policy_commitment: str = _BUYER_POLICY_COMMITMENT,
    quantity_available: int = 4,
    unit_price_paise: int = 100,
    submitted_at: datetime = _BID_SUBMITTED_AT,
) -> MerchantBid:
    return MerchantBid(
        bid_id=bid_id,
        market_id=market_id,
        merchant_id=merchant_id,
        buyer_policy_commitment=buyer_policy_commitment,
        quantity_available=quantity_available,
        unit_price_paise=unit_price_paise,
        submitted_at=submitted_at,
    )


def test_canonical_public_api_is_exact() -> None:
    assert canonical.__all__ == (
        "CANONICALIZATION_VERSION",
        "CanonicalizationError",
        "canonical_buyer_policy_bytes",
        "canonical_json_bytes",
        "canonical_merchant_bid_bytes",
        "canonical_utc_datetime",
    )


def test_canonicalization_version_is_frozen() -> None:
    assert CANONICALIZATION_VERSION == "clear-json-v1"


def test_canonical_json_sorts_dictionary_keys() -> None:
    assert canonical_json_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_canonical_json_sorts_nested_dictionary_keys() -> None:
    value = {"z": {"b": 1, "a": 2}, "a": {"d": 3, "c": 4}}

    assert canonical_json_bytes(value) == b'{"a":{"c":4,"d":3},"z":{"a":2,"b":1}}'


def test_canonical_json_has_no_insignificant_whitespace_or_newline() -> None:
    encoded = canonical_json_bytes({"a": [1, 2]})

    assert encoded == b'{"a":[1,2]}'
    assert b" " not in encoded
    assert not encoded.endswith(b"\n")


def test_canonical_json_serializes_tuple_as_ordered_array() -> None:
    assert canonical_json_bytes(("a", "b")) == b'["a","b"]'


def test_canonical_json_preserves_list_order() -> None:
    assert canonical_json_bytes([3, 1, 2]) == b"[3,1,2]"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, b"null"), (True, b"true"), (False, b"false")],
)
def test_canonical_json_serializes_json_scalars(value: object, expected: bytes) -> None:
    assert canonical_json_bytes(value) == expected


def test_canonical_json_preserves_unicode_as_utf8() -> None:
    encoded = canonical_json_bytes({"text": "₹"})
    encoding = "utf-8"

    assert encoded == '{"text":"₹"}'.encode(encoding)
    assert b"\\u20b9" not in encoded


def test_canonical_json_ignores_dictionary_insertion_order() -> None:
    first = {"a": 1, "b": 2}
    second = {"b": 2, "a": 1}

    assert canonical_json_bytes(first) == canonical_json_bytes(second)


@pytest.mark.parametrize(
    "value",
    [
        1.0,
        float("nan"),
        float("inf"),
        float("-inf"),
        Decimal("1"),
        b"bytes",
        bytearray(b"bytes"),
        {1, 2},
        frozenset({1, 2}),
        datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        UUID(_MARKET_ID),
        Currency.INR,
        Money(amount_paise=1),
        object(),
        {1: "value"},
    ],
)
def test_canonical_json_rejects_unsupported_values(value: object) -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json_bytes(value)


def test_canonical_utc_datetime_formats_microseconds_exactly() -> None:
    assert canonical_utc_datetime(_GOLDEN_DEADLINE) == "2026-09-01T12:00:00.123456Z"


def test_canonical_utc_datetime_includes_zero_microseconds() -> None:
    value = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    assert canonical_utc_datetime(value) == "2026-09-01T12:00:00.000000Z"


def test_canonical_utc_datetime_normalizes_positive_offset() -> None:
    value = datetime(
        2026,
        9,
        1,
        17,
        30,
        0,
        123_456,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    assert canonical_utc_datetime(value) == "2026-09-01T12:00:00.123456Z"


def test_canonical_utc_datetime_normalizes_negative_offset() -> None:
    value = datetime(
        2026,
        9,
        1,
        7,
        0,
        0,
        123_456,
        tzinfo=timezone(-timedelta(hours=5)),
    )

    assert canonical_utc_datetime(value) == "2026-09-01T12:00:00.123456Z"


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 9, 1, 12, 0),
        "2026-09-01T12:00:00.000000Z",
        date(2026, 9, 1),
        None,
        datetime(2026, 9, 1, 12, 0, tzinfo=_NoOffsetTimezone()),
    ],
)
def test_canonical_utc_datetime_rejects_invalid_values(value: object) -> None:
    with pytest.raises(CanonicalizationError):
        canonical_utc_datetime(value)


def test_golden_buyer_policy_bytes_are_frozen() -> None:
    encoded = canonical_buyer_policy_bytes(_golden_policy())

    assert encoded == _GOLDEN_BYTES
    assert len(encoded) == 890


def test_buyer_policy_bytes_ignore_merchant_input_order() -> None:
    forward = _golden_policy()
    reverse = _golden_policy(reverse_merchants=True)

    assert canonical_buyer_policy_bytes(forward) == canonical_buyer_policy_bytes(reverse)


def test_buyer_policy_bytes_ignore_equivalent_deadline_timezone() -> None:
    offset_deadline = datetime(
        2026,
        9,
        1,
        17,
        30,
        0,
        123_456,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    assert canonical_buyer_policy_bytes(_golden_policy()) == canonical_buyer_policy_bytes(
        _golden_policy(deadline=offset_deadline)
    )


def test_golden_merchant_bid_bytes_are_frozen() -> None:
    encoded = canonical_merchant_bid_bytes(_golden_bid())

    assert encoded == _GOLDEN_BID_BYTES
    assert len(encoded) == 517


def test_golden_merchant_bid_sha256_diagnostic_is_frozen() -> None:
    encoded = canonical_merchant_bid_bytes(_golden_bid())

    assert hashlib.sha256(encoded).hexdigest() == _GOLDEN_BID_SHA256


def test_merchant_bid_bytes_ignore_equivalent_submitted_at_timezone() -> None:
    offset_submitted_at = datetime(
        2026,
        9,
        1,
        17,
        29,
        59,
        123_456,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    assert canonical_merchant_bid_bytes(_golden_bid()) == canonical_merchant_bid_bytes(
        _golden_bid(submitted_at=offset_submitted_at)
    )


def test_merchant_bid_bytes_bind_protocol_metadata_without_signature() -> None:
    envelope = json.loads(canonical_merchant_bid_bytes(_golden_bid()))
    payload = envelope["payload"]

    assert payload["buyer_policy_commitment_version"] == "sha256-clear-json-v1"
    assert payload["buyer_policy_commitment"] == _BUYER_POLICY_COMMITMENT
    assert payload["currency"] == "INR"
    assert "signature" not in envelope
    assert "signature" not in payload


@pytest.mark.parametrize(
    "changes",
    [
        {"bid_id": "40000000-0000-4000-8000-000000000002"},
        {"market_id": "10000000-0000-4000-8000-000000000002"},
        {"merchant_id": "30000000-0000-4000-8000-000000000002"},
        {"buyer_policy_commitment": "a" * 64},
        {"quantity_available": 5},
        {"unit_price_paise": 101},
        {"submitted_at": datetime(2026, 9, 1, 12, 0, 0, 123_456, tzinfo=UTC)},
    ],
    ids=(
        "bid-id",
        "market-id",
        "merchant-id",
        "buyer-policy-commitment",
        "quantity-available",
        "unit-price-paise",
        "submitted-at",
    ),
)
def test_merchant_bid_bytes_change_with_bound_field(changes: dict[str, object]) -> None:
    original = _golden_bid()
    changed = _golden_bid(**changes)

    assert canonical_merchant_bid_bytes(changed) != canonical_merchant_bid_bytes(original)
