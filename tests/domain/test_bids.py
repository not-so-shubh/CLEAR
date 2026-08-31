from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from clear_market.crypto import BUYER_POLICY_COMMITMENT_VERSION
from clear_market.domain import (
    MAX_MONEY_PAISE,
    MAX_QUANTITY,
    Currency,
    MerchantBid,
)

_BID_ID = "40000000-0000-4000-8000-000000000001"
_MARKET_ID = "10000000-0000-4000-8000-000000000001"
_MERCHANT_ID = "30000000-0000-4000-8000-000000000001"
_UUID_WITH_LETTERS = "550e8400-e29b-41d4-a716-446655440000"
_BUYER_POLICY_COMMITMENT = "2c11204c2b587606020b0d035719ec2b32f217e0b78ffdb22e038bd7ec1f4ca7"
_SUBMITTED_AT = datetime(2026, 9, 1, 11, 59, 59, 123_456, tzinfo=UTC)


def _bid(
    *,
    schema_version: object = "1",
    bid_id: object = _BID_ID,
    market_id: object = _MARKET_ID,
    merchant_id: object = _MERCHANT_ID,
    buyer_policy_commitment_version: object = "sha256-clear-json-v1",
    buyer_policy_commitment: object = _BUYER_POLICY_COMMITMENT,
    quantity_available: object = 4,
    unit_price_paise: object = 100,
    currency: object = Currency.INR,
    submitted_at: object = _SUBMITTED_AT,
) -> MerchantBid:
    return MerchantBid(
        schema_version=schema_version,
        bid_id=bid_id,
        market_id=market_id,
        merchant_id=merchant_id,
        buyer_policy_commitment_version=buyer_policy_commitment_version,
        buyer_policy_commitment=buyer_policy_commitment,
        quantity_available=quantity_available,
        unit_price_paise=unit_price_paise,
        currency=currency,
        submitted_at=submitted_at,
    )


def test_merchant_bid_accepts_valid_input() -> None:
    bid = _bid()

    assert bid.schema_version == "1"
    assert bid.bid_id == _BID_ID
    assert bid.market_id == _MARKET_ID
    assert bid.merchant_id == _MERCHANT_ID
    assert bid.buyer_policy_commitment == _BUYER_POLICY_COMMITMENT
    assert bid.quantity_available == 4
    assert bid.unit_price_paise == 100
    assert bid.submitted_at == _SUBMITTED_AT


def test_merchant_bid_defaults_versions_and_currency() -> None:
    bid = MerchantBid(
        bid_id=_BID_ID,
        market_id=_MARKET_ID,
        merchant_id=_MERCHANT_ID,
        buyer_policy_commitment=_BUYER_POLICY_COMMITMENT,
        quantity_available=4,
        unit_price_paise=100,
        submitted_at=_SUBMITTED_AT,
    )

    assert bid.schema_version == "1"
    assert bid.buyer_policy_commitment_version == "sha256-clear-json-v1"
    assert bid.currency is Currency.INR


def test_merchant_bid_protocol_version_matches_crypto_protocol() -> None:
    assert _bid().buyer_policy_commitment_version == BUYER_POLICY_COMMITMENT_VERSION


def test_merchant_bid_ids_remain_strings() -> None:
    bid = _bid()

    assert type(bid.bid_id) is str
    assert type(bid.market_id) is str
    assert type(bid.merchant_id) is str


def test_merchant_bid_stores_submitted_at_in_utc() -> None:
    bid = _bid()

    assert bid.submitted_at.utcoffset() == timedelta(0)


def test_merchant_bid_is_frozen() -> None:
    bid = _bid()

    with pytest.raises(ValidationError):
        bid.unit_price_paise = 101


def test_merchant_bid_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        MerchantBid(
            bid_id=_BID_ID,
            market_id=_MARKET_ID,
            merchant_id=_MERCHANT_ID,
            buyer_policy_commitment=_BUYER_POLICY_COMMITMENT,
            quantity_available=4,
            unit_price_paise=100,
            submitted_at=_SUBMITTED_AT,
            unexpected=True,
        )


@pytest.mark.parametrize("schema_version", [1, "2", None, "unsupported"])
def test_merchant_bid_rejects_invalid_schema_version(schema_version: object) -> None:
    with pytest.raises(ValidationError):
        _bid(schema_version=schema_version)


@pytest.mark.parametrize(
    "bid_id",
    ["not-a-uuid", _UUID_WITH_LETTERS.upper(), UUID(_BID_ID)],
)
def test_merchant_bid_rejects_invalid_bid_id(bid_id: object) -> None:
    with pytest.raises(ValidationError):
        _bid(bid_id=bid_id)


@pytest.mark.parametrize("market_id", ["not-a-uuid", UUID(_MARKET_ID)])
def test_merchant_bid_rejects_invalid_market_id(market_id: object) -> None:
    with pytest.raises(ValidationError):
        _bid(market_id=market_id)


@pytest.mark.parametrize("merchant_id", ["not-a-uuid", UUID(_MERCHANT_ID)])
def test_merchant_bid_rejects_invalid_merchant_id(merchant_id: object) -> None:
    with pytest.raises(ValidationError):
        _bid(merchant_id=merchant_id)


def test_merchant_bid_accepts_exact_buyer_policy_commitment() -> None:
    assert _bid().buyer_policy_commitment == _BUYER_POLICY_COMMITMENT


@pytest.mark.parametrize(
    "commitment",
    [
        _BUYER_POLICY_COMMITMENT[:-1],
        f"{_BUYER_POLICY_COMMITMENT}0",
        _BUYER_POLICY_COMMITMENT.upper(),
        f" {_BUYER_POLICY_COMMITMENT}",
        f"{_BUYER_POLICY_COMMITMENT} ",
        f"0x{_BUYER_POLICY_COMMITMENT}",
        f"sha256:{_BUYER_POLICY_COMMITMENT}",
        f"g{_BUYER_POLICY_COMMITMENT[1:]}",
        _BUYER_POLICY_COMMITMENT.encode(),
        1,
        None,
    ],
)
def test_merchant_bid_rejects_invalid_buyer_policy_commitment(commitment: object) -> None:
    with pytest.raises(ValidationError):
        _bid(buyer_policy_commitment=commitment)


@pytest.mark.parametrize("version", ["sha256-clear-json-v2", 1, None])
def test_merchant_bid_rejects_invalid_buyer_policy_commitment_version(version: object) -> None:
    with pytest.raises(ValidationError):
        _bid(buyer_policy_commitment_version=version)


@pytest.mark.parametrize("quantity", [0, 1, MAX_QUANTITY])
def test_merchant_bid_accepts_quantity_bounds(quantity: int) -> None:
    assert _bid(quantity_available=quantity).quantity_available == quantity


@pytest.mark.parametrize(
    "quantity",
    [-1, MAX_QUANTITY + 1, 1.0, True, Decimal("1"), "1"],
)
def test_merchant_bid_rejects_invalid_quantity(quantity: object) -> None:
    with pytest.raises(ValidationError):
        _bid(quantity_available=quantity)


@pytest.mark.parametrize("unit_price_paise", [0, 1, MAX_MONEY_PAISE])
def test_merchant_bid_accepts_unit_price_bounds(unit_price_paise: int) -> None:
    assert _bid(unit_price_paise=unit_price_paise).unit_price_paise == unit_price_paise


@pytest.mark.parametrize(
    "unit_price_paise",
    [-1, MAX_MONEY_PAISE + 1, 1.0, True, Decimal("1"), "1"],
)
def test_merchant_bid_rejects_invalid_unit_price(unit_price_paise: object) -> None:
    with pytest.raises(ValidationError):
        _bid(unit_price_paise=unit_price_paise)


def test_merchant_bid_accepts_explicit_inr() -> None:
    assert _bid(currency="INR").currency is Currency.INR


@pytest.mark.parametrize("currency", ["USD", None])
def test_merchant_bid_rejects_invalid_currency(currency: object) -> None:
    with pytest.raises(ValidationError):
        _bid(currency=currency)


def test_merchant_bid_normalizes_positive_offset_submitted_at() -> None:
    submitted_at = datetime(
        2026,
        9,
        1,
        17,
        29,
        59,
        123_456,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    assert _bid(submitted_at=submitted_at).submitted_at == _SUBMITTED_AT


def test_merchant_bid_normalizes_negative_offset_submitted_at() -> None:
    submitted_at = datetime(
        2026,
        9,
        1,
        6,
        59,
        59,
        123_456,
        tzinfo=timezone(-timedelta(hours=5)),
    )

    assert _bid(submitted_at=submitted_at).submitted_at == _SUBMITTED_AT


def test_merchant_bid_preserves_submitted_at_microseconds() -> None:
    assert _bid().submitted_at.microsecond == 123_456


@pytest.mark.parametrize(
    "submitted_at",
    [datetime(2026, 9, 1, 11, 59, 59), "2026-09-01T11:59:59.123456Z", None],
)
def test_merchant_bid_rejects_invalid_submitted_at(submitted_at: object) -> None:
    with pytest.raises(ValidationError):
        _bid(submitted_at=submitted_at)
