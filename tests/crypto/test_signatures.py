import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from clear_market.canonical import canonical_merchant_bid_bytes
from clear_market.crypto import (
    MERCHANT_BID_SIGNATURE_VERSION,
    buyer_policy_commitment,
    sign_merchant_bid,
    verify_merchant_bid_signature,
)
from clear_market.domain import (
    BuyerPolicy,
    MarketSpec,
    MerchantBid,
    MerchantIdentity,
    Money,
    SignedMerchantBid,
)

# TEST ONLY — NEVER PRODUCTION KEY MATERIAL.
_PRIVATE_SEED_HEX = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
_PUBLIC_KEY_HEX = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
_WRONG_PRIVATE_SEED_HEX = "00" * 32
_MARKET_ID = "10000000-0000-4000-8000-000000000001"
_BUYER_ID = "20000000-0000-4000-8000-000000000001"
_MERCHANT_ID = "30000000-0000-4000-8000-000000000001"
_OTHER_MERCHANT_ID = "30000000-0000-4000-8000-000000000002"
_BID_ID = "40000000-0000-4000-8000-000000000001"
_DEADLINE = datetime(2026, 9, 1, 12, 0, 0, 123_456, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 9, 1, 11, 59, 59, 123_456, tzinfo=UTC)
_COHERENT_POLICY_COMMITMENT = "1b8119d375dcc864049f093d0d69df031a64bda96af438e46c53c939b7a41495"
_COHERENT_BID_SHA256 = "68f552b15126ad7926af280c49cbb25ee168ec7a0ead0e2280739b82c035ca7e"
_GOLDEN_SIGNATURE_HEX = (
    "0defa5e6b39e347508bfd6f4eb2d1099654698bf9cf04c863e61527b9b6505e8"
    "f1379fd0b69ba0387d16424801cc0820be2eef3648c63e67081b02a369f90508"
)


def _private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(_PRIVATE_SEED_HEX))


def _raw_public_key_hex(private_key: Ed25519PrivateKey) -> str:
    return (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )


def _merchant_identity(
    *,
    merchant_id: str = _MERCHANT_ID,
    public_key_hex: str = _PUBLIC_KEY_HEX,
) -> MerchantIdentity:
    return MerchantIdentity(
        merchant_id=merchant_id,
        ed25519_public_key_hex=public_key_hex,
    )


def _coherent_policy() -> BuyerPolicy:
    return BuyerPolicy(
        market_spec=MarketSpec(
            market_id=_MARKET_ID,
            buyer_id=_BUYER_ID,
            requested_quantity=4,
        ),
        max_total_payment=Money(amount_paise=500),
        reserve_unit_price=Money(amount_paise=125),
        eligible_merchants=(
            _merchant_identity(),
            _merchant_identity(
                merchant_id=_OTHER_MERCHANT_ID,
                public_key_hex="1" * 64,
            ),
        ),
        bid_deadline=_DEADLINE,
    )


def _coherent_bid(
    *,
    market_id: str = _MARKET_ID,
    buyer_policy_commitment: str = _COHERENT_POLICY_COMMITMENT,
    quantity_available: int = 4,
    unit_price_paise: int = 100,
    submitted_at: datetime = _SUBMITTED_AT,
) -> MerchantBid:
    return MerchantBid(
        bid_id=_BID_ID,
        market_id=market_id,
        merchant_id=_MERCHANT_ID,
        buyer_policy_commitment=buyer_policy_commitment,
        quantity_available=quantity_available,
        unit_price_paise=unit_price_paise,
        submitted_at=submitted_at,
    )


def test_signature_version_is_frozen() -> None:
    assert MERCHANT_BID_SIGNATURE_VERSION == "ed25519-raw-clear-json-v1"


def test_test_private_key_derives_frozen_public_key() -> None:
    assert _raw_public_key_hex(_private_key()) == _PUBLIC_KEY_HEX


def test_coherent_policy_commitment_is_frozen() -> None:
    assert buyer_policy_commitment(_coherent_policy()) == _COHERENT_POLICY_COMMITMENT


def test_coherent_bid_diagnostic_is_frozen() -> None:
    message = canonical_merchant_bid_bytes(_coherent_bid())

    assert hashlib.sha256(message).hexdigest() == _COHERENT_BID_SHA256


def test_sign_merchant_bid_returns_frozen_signed_evidence() -> None:
    bid = _coherent_bid()
    signed_bid = sign_merchant_bid(bid, _private_key())

    assert isinstance(signed_bid, SignedMerchantBid)
    assert signed_bid.bid == bid
    assert signed_bid.signature_hex == _GOLDEN_SIGNATURE_HEX
    assert len(signed_bid.signature_hex) == 128
    assert signed_bid.signature_hex == signed_bid.signature_hex.lower()
    assert set(signed_bid.signature_hex) <= set("0123456789abcdef")


def test_sign_merchant_bid_is_deterministic() -> None:
    bid = _coherent_bid()
    private_key = _private_key()

    assert sign_merchant_bid(bid, private_key) == sign_merchant_bid(bid, private_key)


def test_different_valid_bid_content_produces_different_signature() -> None:
    private_key = _private_key()

    original = sign_merchant_bid(_coherent_bid(), private_key)
    changed = sign_merchant_bid(_coherent_bid(unit_price_paise=101), private_key)

    assert changed.signature_hex != original.signature_hex


def test_signature_verifies_raw_canonical_bytes_without_prehashing() -> None:
    private_key = _private_key()
    bid = _coherent_bid()
    message = canonical_merchant_bid_bytes(bid)
    signature = bytes.fromhex(sign_merchant_bid(bid, private_key).signature_hex)

    private_key.public_key().verify(signature, message)
    with pytest.raises(InvalidSignature):
        private_key.public_key().verify(signature, hashlib.sha256(message).digest())


@pytest.mark.parametrize(
    "private_key",
    [bytes.fromhex(_PRIVATE_SEED_HEX), _PRIVATE_SEED_HEX, object()],
)
def test_sign_merchant_bid_rejects_non_ed25519_private_keys(private_key: object) -> None:
    with pytest.raises(TypeError):
        sign_merchant_bid(_coherent_bid(), private_key)


def test_verify_merchant_bid_signature_accepts_valid_evidence() -> None:
    signed_bid = sign_merchant_bid(_coherent_bid(), _private_key())

    assert verify_merchant_bid_signature(signed_bid, _merchant_identity()) is True


def test_verify_merchant_bid_signature_rejects_wrong_public_key() -> None:
    wrong_private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(_WRONG_PRIVATE_SEED_HEX))
    wrong_identity = _merchant_identity(public_key_hex=_raw_public_key_hex(wrong_private_key))
    signed_bid = sign_merchant_bid(_coherent_bid(), _private_key())

    assert verify_merchant_bid_signature(signed_bid, wrong_identity) is False


def test_verify_merchant_bid_signature_rejects_wrong_merchant_id() -> None:
    wrong_identity = _merchant_identity(merchant_id=_OTHER_MERCHANT_ID)
    signed_bid = sign_merchant_bid(_coherent_bid(), _private_key())

    assert verify_merchant_bid_signature(signed_bid, wrong_identity) is False


@pytest.mark.parametrize(
    "changes",
    [
        {"market_id": "10000000-0000-4000-8000-000000000002"},
        {"buyer_policy_commitment": "a" * 64},
        {"quantity_available": 5},
        {"unit_price_paise": 101},
        {"submitted_at": _SUBMITTED_AT + timedelta(seconds=1)},
    ],
    ids=(
        "market-id",
        "buyer-policy-commitment",
        "quantity-available",
        "unit-price-paise",
        "submitted-at",
    ),
)
def test_verify_merchant_bid_signature_rejects_tampered_bid(changes: dict[str, object]) -> None:
    original = sign_merchant_bid(_coherent_bid(), _private_key())
    tampered = SignedMerchantBid(
        bid=_coherent_bid(**changes),
        signature_hex=original.signature_hex,
    )

    assert verify_merchant_bid_signature(tampered, _merchant_identity()) is False


def test_verify_merchant_bid_signature_rejects_tampered_signature() -> None:
    original = sign_merchant_bid(_coherent_bid(), _private_key())
    replacement = "0" if original.signature_hex[0] != "0" else "1"
    tampered = SignedMerchantBid(
        bid=original.bid,
        signature_hex=f"{replacement}{original.signature_hex[1:]}",
    )

    assert verify_merchant_bid_signature(tampered, _merchant_identity()) is False
