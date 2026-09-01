import hashlib
import random
from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from clear_market.benchmark.models import GeneratedAdmissionAttempt, GeneratedMarketCase
from clear_market.benchmark.seeds import MARKET_GENERATOR_VERSION, MAX_GENERATOR_SEED
from clear_market.crypto import buyer_policy_commitment, sign_merchant_bid
from clear_market.domain import (
    MAX_SELLERS,
    MIN_SELLERS,
    BuyerPolicy,
    MarketSpec,
    MerchantBid,
    MerchantIdentity,
    Money,
)
from clear_market.lifecycle import AdmissionContext

_BID_DEADLINE = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 9, 1, 11, 59, 58, tzinfo=UTC)
_RECEIVED_AT = datetime(2026, 9, 1, 11, 59, 59, tzinfo=UTC)


def _market_id(seed: int) -> str:
    return f"10000000-0000-4000-8000-{seed:012x}"


def _buyer_id(seed: int) -> str:
    return f"20000000-0000-4000-8000-{seed:012x}"


def _merchant_id(seed: int, seller_index: int) -> str:
    return f"30000000-{seller_index + 1:04x}-4000-8000-{seed:012x}"


def _bid_id(seed: int, seller_index: int) -> str:
    return f"40000000-{seller_index + 1:04x}-4000-8000-{seed:012x}"


def _benchmark_private_key(seed: int, seller_index: int) -> Ed25519PrivateKey:
    # Deterministic synthetic keys make benchmark evidence reproducible.
    # They are not production identities or production key generation.
    key_material = (f"{MARKET_GENERATOR_VERSION}|merchant-key|{seed}|{seller_index}").encode(
        "ascii"
    )
    private_key_seed = hashlib.sha256(key_material).digest()
    return Ed25519PrivateKey.from_private_bytes(private_key_seed)


def _public_key_hex(private_key: Ed25519PrivateKey) -> str:
    return (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )


def generate_market_case(
    seed: int,
    seller_count: int = 5,
) -> GeneratedMarketCase:
    """Generate reproducible authenticated market input evidence from explicit integers."""
    if type(seed) is not int:
        raise TypeError("seed must be an exact integer")
    if not 0 <= seed <= MAX_GENERATOR_SEED:
        raise ValueError("seed is outside the generator domain")
    if type(seller_count) is not int:
        raise TypeError("seller_count must be an exact integer")
    if not MIN_SELLERS <= seller_count <= MAX_SELLERS:
        raise ValueError("seller_count is outside the market domain")

    rng = random.Random(seed)
    requested_quantity = rng.randint(1, 20)
    reserve_unit_price_paise = rng.randint(0, 25)
    quantity_choices = (
        0,
        max(0, requested_quantity - 1),
        requested_quantity,
        requested_quantity + 1,
        requested_quantity + 2,
    )
    price_choices = (
        0,
        max(0, reserve_unit_price_paise - 1),
        reserve_unit_price_paise,
        reserve_unit_price_paise + 1,
        reserve_unit_price_paise + 2,
    )
    seller_draws = tuple(
        (
            bool(rng.getrandbits(1)),
            rng.choice(quantity_choices),
            rng.choice(price_choices),
        )
        for _ in range(seller_count)
    )

    private_keys = tuple(_benchmark_private_key(seed, index) for index in range(seller_count))
    merchant_identities = tuple(
        MerchantIdentity(
            merchant_id=_merchant_id(seed, index),
            ed25519_public_key_hex=_public_key_hex(private_keys[index]),
        )
        for index in range(seller_count)
    )
    policy = BuyerPolicy(
        market_spec=MarketSpec(
            market_id=_market_id(seed),
            buyer_id=_buyer_id(seed),
            requested_quantity=requested_quantity,
        ),
        max_total_payment=Money(
            amount_paise=reserve_unit_price_paise * requested_quantity,
        ),
        reserve_unit_price=Money(amount_paise=reserve_unit_price_paise),
        eligible_merchants=merchant_identities,
        bid_deadline=_BID_DEADLINE,
    )
    policy_commitment = buyer_policy_commitment(policy)

    attempts: list[GeneratedAdmissionAttempt] = []
    for index, (participates, quantity_available, unit_price_paise) in enumerate(seller_draws):
        if participates:
            bid = MerchantBid(
                bid_id=_bid_id(seed, index),
                market_id=policy.market_spec.market_id,
                merchant_id=merchant_identities[index].merchant_id,
                buyer_policy_commitment=policy_commitment,
                quantity_available=quantity_available,
                unit_price_paise=unit_price_paise,
                submitted_at=_SUBMITTED_AT,
            )
            attempts.append(
                GeneratedAdmissionAttempt(
                    signed_bid=sign_merchant_bid(bid, private_keys[index]),
                    context=AdmissionContext(received_at=_RECEIVED_AT),
                )
            )

    rng.shuffle(attempts)
    return GeneratedMarketCase(
        seed=seed,
        buyer_policy=policy,
        admission_attempts=tuple(attempts),
    )
