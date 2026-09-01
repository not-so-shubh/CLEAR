import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from clear_market.crypto import buyer_policy_commitment, sign_merchant_bid
from clear_market.domain import (
    BuyerPolicy,
    MarketSpec,
    MerchantBid,
    MerchantIdentity,
    Money,
    SignedMerchantBid,
)
from clear_market.lifecycle import AdmissionContext

MARKET_ID = "81000000-0000-4000-8000-000000000001"
WRONG_MARKET_ID = "81000001-0000-4000-8000-000000000001"
BUYER_ID = "82000000-0000-4000-8000-000000000001"
MERCHANT_A_ID = "83000000-0001-4000-8000-000000000001"
MERCHANT_B_ID = "83000000-0002-4000-8000-000000000001"
UNREGISTERED_MERCHANT_ID = "83000000-0003-4000-8000-000000000001"
BASE_BID_ID = "84000000-0001-4000-8000-000000000001"
ALTERNATE_BID_ID = "84000000-0002-4000-8000-000000000001"

DEADLINE = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
VALID_SUBMITTED = datetime(2026, 9, 1, 11, 59, 58, tzinfo=UTC)
TAMPERED_VALID_SUBMITTED = datetime(2026, 9, 1, 11, 59, 58, 1, tzinfo=UTC)
VALID_RECEIVED = datetime(2026, 9, 1, 11, 59, 59, tzinfo=UTC)
AFTER_RECEIVED_SUBMITTED = datetime(2026, 9, 1, 11, 59, 59, 1, tzinfo=UTC)
AFTER_DEADLINE = datetime(2026, 9, 1, 12, 0, 0, 1, tzinfo=UTC)
AFTER_DEADLINE_SUBMITTED = datetime(2026, 9, 1, 12, 0, 0, 2, tzinfo=UTC)


@dataclass(frozen=True)
class AdversarialMarketFixture:
    policy: BuyerPolicy
    merchant_a_private_key: Ed25519PrivateKey
    merchant_b_private_key: Ed25519PrivateKey
    outsider_private_key: Ed25519PrivateKey


def _private_key(index: int) -> Ed25519PrivateKey:
    # TEST-ONLY deterministic adversarial signing material; never production keys.
    seed = hashlib.sha256(f"clear-adversarial-suite-v1|merchant|{index}".encode("ascii")).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def _public_key_hex(private_key: Ed25519PrivateKey) -> str:
    return (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )


def build_adversarial_market() -> AdversarialMarketFixture:
    merchant_a_private_key = _private_key(0)
    merchant_b_private_key = _private_key(1)
    outsider_private_key = _private_key(2)
    policy = BuyerPolicy(
        market_spec=MarketSpec(
            market_id=MARKET_ID,
            buyer_id=BUYER_ID,
            requested_quantity=10,
        ),
        max_total_payment=Money(amount_paise=5_000),
        reserve_unit_price=Money(amount_paise=500),
        eligible_merchants=(
            MerchantIdentity(
                merchant_id=MERCHANT_A_ID,
                ed25519_public_key_hex=_public_key_hex(merchant_a_private_key),
            ),
            MerchantIdentity(
                merchant_id=MERCHANT_B_ID,
                ed25519_public_key_hex=_public_key_hex(merchant_b_private_key),
            ),
        ),
        bid_deadline=DEADLINE,
    )
    return AdversarialMarketFixture(
        policy=policy,
        merchant_a_private_key=merchant_a_private_key,
        merchant_b_private_key=merchant_b_private_key,
        outsider_private_key=outsider_private_key,
    )


def build_bid(
    fixture: AdversarialMarketFixture,
    *,
    bid_id: str = BASE_BID_ID,
    market_id: str | None = None,
    merchant_id: str = MERCHANT_A_ID,
    buyer_policy_commitment_value: str | None = None,
    quantity_available: int = 10,
    unit_price_paise: int = 400,
    submitted_at: datetime = VALID_SUBMITTED,
) -> MerchantBid:
    return MerchantBid(
        bid_id=bid_id,
        market_id=fixture.policy.market_spec.market_id if market_id is None else market_id,
        merchant_id=merchant_id,
        buyer_policy_commitment=(
            buyer_policy_commitment(fixture.policy)
            if buyer_policy_commitment_value is None
            else buyer_policy_commitment_value
        ),
        quantity_available=quantity_available,
        unit_price_paise=unit_price_paise,
        submitted_at=submitted_at,
    )


def sign_with_a(
    fixture: AdversarialMarketFixture,
    bid: MerchantBid,
) -> SignedMerchantBid:
    return sign_merchant_bid(bid, fixture.merchant_a_private_key)


def sign_with_b(
    fixture: AdversarialMarketFixture,
    bid: MerchantBid,
) -> SignedMerchantBid:
    return sign_merchant_bid(bid, fixture.merchant_b_private_key)


def sign_with_outsider(
    fixture: AdversarialMarketFixture,
    bid: MerchantBid,
) -> SignedMerchantBid:
    return sign_merchant_bid(bid, fixture.outsider_private_key)


def context(received_at: datetime = VALID_RECEIVED) -> AdmissionContext:
    return AdmissionContext(received_at=received_at)
