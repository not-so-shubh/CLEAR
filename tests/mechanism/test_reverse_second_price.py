from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from clear_market.crypto import buyer_policy_commitment, sign_merchant_bid
from clear_market.domain import (
    MAX_MONEY_PAISE,
    MAX_QUANTITY,
    BuyerPolicy,
    MarketSpec,
    MerchantBid,
    MerchantIdentity,
    Money,
    SignedMerchantBid,
)
from clear_market.lifecycle import (
    AdmissionContext,
    AdmissionRejectionCode,
    AdmissionState,
    admit_signed_bid,
)
from clear_market.mechanism import AllocationStatus, allocate_market

# TEST ONLY — NEVER PRODUCTION KEY MATERIAL.
_PRIVATE_SEEDS_HEX = tuple(f"{index:02x}" * 32 for index in range(1, 6))
_MARKET_ID = "10000000-0000-4000-8000-000000000001"
_BUYER_ID = "20000000-0000-4000-8000-000000000001"
_MERCHANT_IDS = tuple(f"30000000-0000-4000-8000-{index:012x}" for index in range(1, 6))
_BID_IDS = tuple(f"40000000-0000-4000-8000-{index:012x}" for index in range(1, 6))
_DEADLINE = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 9, 1, 11, 59, 58, tzinfo=UTC)
_RECEIVED_AT = datetime(2026, 9, 1, 11, 59, 59, tzinfo=UTC)


def _private_key(index: int) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(_PRIVATE_SEEDS_HEX[index]))


def _public_key_hex(index: int) -> str:
    return (
        _private_key(index)
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )


def _policy(
    *,
    requested_quantity: int = 4,
    reserve_unit_price_paise: int = 125,
    max_total_payment_paise: int = 500,
) -> BuyerPolicy:
    return BuyerPolicy(
        market_spec=MarketSpec(
            market_id=_MARKET_ID,
            buyer_id=_BUYER_ID,
            requested_quantity=requested_quantity,
        ),
        max_total_payment=Money(amount_paise=max_total_payment_paise),
        reserve_unit_price=Money(amount_paise=reserve_unit_price_paise),
        eligible_merchants=tuple(
            MerchantIdentity(
                merchant_id=_MERCHANT_IDS[index],
                ed25519_public_key_hex=_public_key_hex(index),
            )
            for index in range(5)
        ),
        bid_deadline=_DEADLINE,
    )


def _signed_bid(
    state: AdmissionState,
    merchant_index: int,
    *,
    unit_price_paise: int,
    quantity_available: int,
) -> SignedMerchantBid:
    policy = state.policy
    bid = MerchantBid(
        bid_id=_BID_IDS[merchant_index],
        market_id=policy.market_spec.market_id,
        merchant_id=_MERCHANT_IDS[merchant_index],
        buyer_policy_commitment=buyer_policy_commitment(policy),
        quantity_available=quantity_available,
        unit_price_paise=unit_price_paise,
        submitted_at=_SUBMITTED_AT,
    )
    return sign_merchant_bid(bid, _private_key(merchant_index))


def _admit(
    state: AdmissionState,
    merchant_index: int,
    *,
    unit_price_paise: int,
    quantity_available: int,
) -> None:
    decision = admit_signed_bid(
        state,
        _signed_bid(
            state,
            merchant_index,
            unit_price_paise=unit_price_paise,
            quantity_available=quantity_available,
        ),
        AdmissionContext(received_at=_RECEIVED_AT),
    )
    assert decision.rejection_code is None


def test_allocate_market_rejects_non_admission_state() -> None:
    with pytest.raises(TypeError):
        allocate_market(object())


def test_zero_accepted_bids_is_explicitly_infeasible() -> None:
    policy = _policy()
    state = AdmissionState(policy)

    allocation = allocate_market(state)

    assert allocation.status is AllocationStatus.INFEASIBLE
    assert allocation.market_id == policy.market_spec.market_id
    assert allocation.buyer_policy_commitment == buyer_policy_commitment(policy)
    assert allocation.buyer_policy_commitment_version == "sha256-clear-json-v1"
    assert allocation.mechanism_version == policy.mechanism_version
    assert allocation.winner_merchant_id is None
    assert allocation.winning_bid_id is None
    assert allocation.allocated_quantity is None
    assert allocation.winning_unit_price is None
    assert allocation.payment_unit_price is None
    assert allocation.total_payment is None


def test_five_seller_golden_economic_vector() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    prices = (100, 110, 110, 120, 125)

    for index in (4, 2, 0, 3, 1):
        _admit(
            state,
            index,
            unit_price_paise=prices[index],
            quantity_available=4,
        )

    allocation = allocate_market(state)

    assert allocation.status is AllocationStatus.FEASIBLE
    assert allocation.winner_merchant_id == _MERCHANT_IDS[0]
    assert allocation.winning_bid_id == _BID_IDS[0]
    assert allocation.allocated_quantity == 4
    assert allocation.winning_unit_price == Money(amount_paise=100)
    assert allocation.payment_unit_price == Money(amount_paise=110)
    assert allocation.total_payment == Money(amount_paise=440)
    assert allocation.buyer_policy_commitment == buyer_policy_commitment(policy)
    assert allocation.total_payment.amount_paise <= policy.max_total_payment.amount_paise


def test_equal_lowest_payment_uses_second_ranked_bid_not_second_distinct_price() -> None:
    state = AdmissionState(_policy())

    _admit(state, 1, unit_price_paise=100, quantity_available=4)
    _admit(state, 0, unit_price_paise=100, quantity_available=4)
    _admit(state, 2, unit_price_paise=110, quantity_available=4)

    allocation = allocate_market(state)

    assert allocation.winner_merchant_id == _MERCHANT_IDS[0]
    assert allocation.payment_unit_price == Money(amount_paise=100)
    assert allocation.total_payment == Money(amount_paise=400)


def test_insufficient_capacity_bid_does_not_affect_second_price() -> None:
    state = AdmissionState(_policy())

    _admit(state, 0, unit_price_paise=100, quantity_available=4)
    _admit(state, 1, unit_price_paise=105, quantity_available=3)
    _admit(state, 2, unit_price_paise=120, quantity_available=4)

    allocation = allocate_market(state)

    assert allocation.winner_merchant_id == _MERCHANT_IDS[0]
    assert allocation.payment_unit_price == Money(amount_paise=120)
    assert allocation.total_payment == Money(amount_paise=480)


def test_above_reserve_bid_does_not_affect_second_price() -> None:
    state = AdmissionState(_policy())

    _admit(state, 0, unit_price_paise=100, quantity_available=4)
    _admit(state, 1, unit_price_paise=120, quantity_available=4)
    _admit(state, 2, unit_price_paise=130, quantity_available=4)

    allocation = allocate_market(state)

    assert allocation.winner_merchant_id == _MERCHANT_IDS[0]
    assert allocation.payment_unit_price == Money(amount_paise=120)
    assert allocation.total_payment == Money(amount_paise=480)


def test_single_eligible_bid_uses_reserve_payment() -> None:
    policy = _policy()
    state = AdmissionState(policy)

    _admit(state, 0, unit_price_paise=100, quantity_available=4)
    _admit(state, 1, unit_price_paise=90, quantity_available=3)
    _admit(state, 2, unit_price_paise=130, quantity_available=4)

    allocation = allocate_market(state)

    assert allocation.status is AllocationStatus.FEASIBLE
    assert allocation.winner_merchant_id == _MERCHANT_IDS[0]
    assert allocation.payment_unit_price == policy.reserve_unit_price
    assert allocation.total_payment == Money(amount_paise=500)
    assert allocation.total_payment.amount_paise <= policy.max_total_payment.amount_paise


def test_accepted_bids_with_no_economically_eligible_bid_are_infeasible() -> None:
    state = AdmissionState(_policy())

    _admit(state, 0, unit_price_paise=100, quantity_available=3)
    _admit(state, 1, unit_price_paise=126, quantity_available=4)
    _admit(state, 2, unit_price_paise=130, quantity_available=3)

    allocation = allocate_market(state)

    assert allocation.status is AllocationStatus.INFEASIBLE
    assert allocation.winner_merchant_id is None
    assert allocation.winning_bid_id is None
    assert allocation.allocated_quantity is None
    assert allocation.winning_unit_price is None
    assert allocation.payment_unit_price is None
    assert allocation.total_payment is None


def test_capacity_and_reserve_boundaries_are_inclusive() -> None:
    policy = _policy()
    state = AdmissionState(policy)

    _admit(state, 0, unit_price_paise=125, quantity_available=4)

    allocation = allocate_market(state)

    assert allocation.status is AllocationStatus.FEASIBLE
    assert allocation.winner_merchant_id == _MERCHANT_IDS[0]
    assert allocation.winning_unit_price == policy.reserve_unit_price
    assert allocation.payment_unit_price == policy.reserve_unit_price
    assert allocation.total_payment == Money(amount_paise=500)


def test_rejected_cheap_bid_never_reaches_allocation_or_payment() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    cheap_bid = _signed_bid(
        state,
        0,
        unit_price_paise=1,
        quantity_available=4,
    )
    invalid_cheap_bid = SignedMerchantBid(bid=cheap_bid.bid, signature_hex="0" * 128)

    rejected = admit_signed_bid(
        state,
        invalid_cheap_bid,
        AdmissionContext(received_at=_RECEIVED_AT),
    )
    _admit(state, 1, unit_price_paise=110, quantity_available=4)
    allocation = allocate_market(state)

    assert rejected.rejection_code is AdmissionRejectionCode.INVALID_SIGNATURE
    assert len(state.accepted_decisions) == 1
    assert allocation.winner_merchant_id == _MERCHANT_IDS[1]
    assert allocation.payment_unit_price == policy.reserve_unit_price
    assert allocation.total_payment == Money(amount_paise=500)


def test_maximum_money_boundary_succeeds_exactly() -> None:
    reserve = MAX_MONEY_PAISE // MAX_QUANTITY
    policy = _policy(
        requested_quantity=MAX_QUANTITY,
        reserve_unit_price_paise=reserve,
        max_total_payment_paise=MAX_MONEY_PAISE,
    )
    state = AdmissionState(policy)

    _admit(
        state,
        0,
        unit_price_paise=reserve,
        quantity_available=MAX_QUANTITY,
    )

    allocation = allocate_market(state)

    assert allocation.status is AllocationStatus.FEASIBLE
    assert allocation.payment_unit_price == Money(amount_paise=reserve)
    assert allocation.total_payment == Money(amount_paise=MAX_MONEY_PAISE)
    assert allocation.total_payment.amount_paise <= policy.max_total_payment.amount_paise


def test_allocation_is_deterministic_and_does_not_mutate_state() -> None:
    state = AdmissionState(_policy())
    _admit(state, 1, unit_price_paise=110, quantity_available=4)
    _admit(state, 0, unit_price_paise=100, quantity_available=4)
    before = state.accepted_decisions

    first = allocate_market(state)
    second = allocate_market(state)

    assert first == second
    assert state.accepted_decisions == before
