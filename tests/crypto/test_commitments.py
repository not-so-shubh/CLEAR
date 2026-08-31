import hashlib
from datetime import UTC, datetime, timedelta, timezone

import pytest

import clear_market.crypto as crypto
from clear_market.canonical import canonical_buyer_policy_bytes
from clear_market.crypto import (
    BUYER_POLICY_COMMITMENT_VERSION,
    buyer_policy_commitment,
)
from clear_market.domain import BuyerPolicy, MarketSpec, MerchantIdentity, Money

_MARKET_ID = "10000000-0000-4000-8000-000000000001"
_BUYER_ID = "20000000-0000-4000-8000-000000000001"
_MERCHANT_ID_1 = "30000000-0000-4000-8000-000000000001"
_MERCHANT_ID_2 = "30000000-0000-4000-8000-000000000002"
_ALTERNATE_MARKET_ID = "10000000-0000-4000-8000-000000000002"
_ALTERNATE_BUYER_ID = "20000000-0000-4000-8000-000000000002"
_ALTERNATE_MERCHANT_ID = "30000000-0000-4000-8000-000000000003"
_PUBLIC_KEY_1 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
_PUBLIC_KEY_2 = "1111111111111111111111111111111111111111111111111111111111111111"
_ALTERNATE_PUBLIC_KEY = "2222222222222222222222222222222222222222222222222222222222222222"
_DEADLINE = datetime(2026, 9, 1, 12, 0, 0, 123_456, tzinfo=UTC)
_GOLDEN_COMMITMENT = "2c11204c2b587606020b0d035719ec2b32f217e0b78ffdb22e038bd7ec1f4ca7"


def _policy(
    *,
    market_id: str = _MARKET_ID,
    buyer_id: str = _BUYER_ID,
    requested_quantity: int = 4,
    max_total_payment_paise: int = 500,
    reserve_unit_price_paise: int = 125,
    merchant_id_1: str = _MERCHANT_ID_1,
    public_key_1: str = _PUBLIC_KEY_1,
    deadline: datetime = _DEADLINE,
    reverse_merchants: bool = False,
) -> BuyerPolicy:
    merchants = (
        MerchantIdentity(
            merchant_id=merchant_id_1,
            ed25519_public_key_hex=public_key_1,
        ),
        MerchantIdentity(
            merchant_id=_MERCHANT_ID_2,
            ed25519_public_key_hex=_PUBLIC_KEY_2,
        ),
    )
    if reverse_merchants:
        merchants = tuple(reversed(merchants))

    return BuyerPolicy(
        market_spec=MarketSpec(
            market_id=market_id,
            buyer_id=buyer_id,
            requested_quantity=requested_quantity,
        ),
        max_total_payment=Money(amount_paise=max_total_payment_paise),
        reserve_unit_price=Money(amount_paise=reserve_unit_price_paise),
        eligible_merchants=merchants,
        bid_deadline=deadline,
    )


def test_crypto_public_api_is_exact() -> None:
    assert crypto.__all__ == (
        "BUYER_POLICY_COMMITMENT_VERSION",
        "buyer_policy_commitment",
    )


def test_buyer_policy_commitment_version_is_frozen() -> None:
    assert BUYER_POLICY_COMMITMENT_VERSION == "sha256-clear-json-v1"


def test_golden_buyer_policy_commitment_is_frozen() -> None:
    assert buyer_policy_commitment(_policy()) == _GOLDEN_COMMITMENT


def test_buyer_policy_commitment_is_exact_sha256_of_canonical_bytes() -> None:
    policy = _policy()
    expected = hashlib.sha256(canonical_buyer_policy_bytes(policy)).hexdigest()

    assert buyer_policy_commitment(policy) == expected


def test_buyer_policy_commitment_has_unprefixed_lowercase_hex_representation() -> None:
    commitment = buyer_policy_commitment(_policy())

    assert len(commitment) == 64
    assert commitment == commitment.lower()
    assert set(commitment) <= set("0123456789abcdef")
    assert not commitment.startswith("0x")
    assert not commitment.startswith("sha256:")
    assert commitment == commitment.strip()


def test_commitment_ignores_merchant_input_order() -> None:
    forward = _policy()
    reverse = _policy(reverse_merchants=True)

    assert canonical_buyer_policy_bytes(forward) == canonical_buyer_policy_bytes(reverse)
    assert buyer_policy_commitment(forward) == buyer_policy_commitment(reverse)


def test_commitment_ignores_equivalent_deadline_timezone() -> None:
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
    utc_policy = _policy()
    offset_policy = _policy(deadline=offset_deadline)

    assert canonical_buyer_policy_bytes(utc_policy) == canonical_buyer_policy_bytes(offset_policy)
    assert buyer_policy_commitment(utc_policy) == buyer_policy_commitment(offset_policy)


@pytest.mark.parametrize(
    "changes",
    [
        {"market_id": _ALTERNATE_MARKET_ID},
        {"buyer_id": _ALTERNATE_BUYER_ID},
        {"requested_quantity": 3},
        {"max_total_payment_paise": 501},
        {"reserve_unit_price_paise": 124},
        {"merchant_id_1": _ALTERNATE_MERCHANT_ID},
        {"public_key_1": _ALTERNATE_PUBLIC_KEY},
        {"deadline": datetime(2026, 9, 1, 12, 0, 1, 123_456, tzinfo=UTC)},
    ],
    ids=(
        "market-id",
        "buyer-id",
        "requested-quantity",
        "max-total-payment",
        "reserve-unit-price",
        "merchant-id",
        "merchant-public-key",
        "bid-deadline",
    ),
)
def test_commitment_changes_with_allocation_relevant_value(changes: dict[str, object]) -> None:
    original = _policy()
    changed = _policy(**changes)

    assert buyer_policy_commitment(changed) != buyer_policy_commitment(original)
