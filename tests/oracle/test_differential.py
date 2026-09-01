from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hypothesis import given, settings
from hypothesis import strategies as st

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
from clear_market.mechanism import Allocation, AllocationStatus, allocate_market
from clear_market.oracle import OracleAllocation, compute_oracle_allocation

# TEST ONLY — NEVER PRODUCTION KEY MATERIAL.
_PRIVATE_KEY_SEEDS = tuple(bytes([index]) * 32 for index in range(1, 21))
_MARKET_ID = "10000000-0000-4000-8000-000000000001"
_BUYER_ID = "20000000-0000-4000-8000-000000000001"
_MERCHANT_IDS = tuple(f"30000000-0000-4000-8000-{index:012x}" for index in range(1, 21))
_BID_IDS = tuple(f"40000000-0000-4000-8000-{index:012x}" for index in range(1, 21))
_DEADLINE = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 9, 1, 11, 59, 58, tzinfo=UTC)
_RECEIVED_AT = datetime(2026, 9, 1, 11, 59, 59, tzinfo=UTC)

type _BidInput = tuple[int, int, int]
type _GeneratedSeller = tuple[bool, int, int]
type _GeneratedMarket = tuple[int, int, int, tuple[_GeneratedSeller, ...]]


def _private_key(index: int) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_PRIVATE_KEY_SEEDS[index])


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
    seller_count: int = 5,
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
            for index in range(seller_count)
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


def _state_with_bids(policy: BuyerPolicy, bids: tuple[_BidInput, ...]) -> AdmissionState:
    state = AdmissionState(policy)
    for merchant_index, unit_price_paise, quantity_available in bids:
        _admit(
            state,
            merchant_index,
            unit_price_paise=unit_price_paise,
            quantity_available=quantity_available,
        )
    return state


def _assert_allocations_semantically_equal(
    production: Allocation,
    oracle: OracleAllocation,
) -> None:
    assert production.schema_version == oracle.schema_version
    assert production.market_id == oracle.market_id
    assert production.buyer_policy_commitment_version == oracle.buyer_policy_commitment_version
    assert production.buyer_policy_commitment == oracle.buyer_policy_commitment
    assert production.mechanism_version == oracle.mechanism_version
    assert production.status.value == oracle.status.value
    assert production.winner_merchant_id == oracle.winner_merchant_id
    assert production.winning_bid_id == oracle.winning_bid_id
    assert production.allocated_quantity == oracle.allocated_quantity
    assert production.winning_unit_price == oracle.winning_unit_price
    assert production.payment_unit_price == oracle.payment_unit_price
    assert production.total_payment == oracle.total_payment


def _run_differential(state: AdmissionState) -> tuple[Allocation, OracleAllocation]:
    before = state.accepted_decisions

    production = allocate_market(state)
    oracle = compute_oracle_allocation(state)

    _assert_allocations_semantically_equal(production, oracle)
    assert state.accepted_decisions == before
    return production, oracle


def test_result_models_remain_independent_types() -> None:
    state = _state_with_bids(
        _policy(seller_count=2),
        ((0, 100, 4),),
    )

    production, oracle = _run_differential(state)

    assert type(production) is not type(oracle)
    assert type(production.status) is not type(oracle.status)


def test_zero_accepted_bids_agree_as_infeasible() -> None:
    state = AdmissionState(_policy(seller_count=2))

    production, _ = _run_differential(state)

    assert production.status is AllocationStatus.INFEASIBLE
    assert production.winner_merchant_id is None
    assert production.winning_bid_id is None
    assert production.allocated_quantity is None
    assert production.winning_unit_price is None
    assert production.payment_unit_price is None
    assert production.total_payment is None


def test_five_seller_golden_vector_agrees() -> None:
    prices = (100, 110, 110, 120, 125)
    state = _state_with_bids(
        _policy(),
        tuple((index, prices[index], 4) for index in (4, 2, 0, 3, 1)),
    )

    production, _ = _run_differential(state)

    assert production.status is AllocationStatus.FEASIBLE
    assert production.winner_merchant_id == _MERCHANT_IDS[0]
    assert production.winning_bid_id == _BID_IDS[0]
    assert production.allocated_quantity == 4
    assert production.winning_unit_price == Money(amount_paise=100)
    assert production.payment_unit_price == Money(amount_paise=110)
    assert production.total_payment == Money(amount_paise=440)


def test_equal_lowest_agrees_with_reverse_admission_order() -> None:
    state = _state_with_bids(
        _policy(seller_count=3),
        ((2, 110, 4), (1, 100, 4), (0, 100, 4)),
    )

    production, _ = _run_differential(state)

    assert production.winner_merchant_id == _MERCHANT_IDS[0]
    assert production.winning_bid_id == _BID_IDS[0]
    assert production.payment_unit_price == Money(amount_paise=100)
    assert production.total_payment == Money(amount_paise=400)


def test_single_eligible_bid_agrees_on_reserve_payment() -> None:
    policy = _policy(seller_count=3)
    state = _state_with_bids(
        policy,
        ((0, 100, 4), (1, 90, 3), (2, 130, 4)),
    )

    production, _ = _run_differential(state)

    assert production.winner_merchant_id == _MERCHANT_IDS[0]
    assert production.payment_unit_price == policy.reserve_unit_price
    assert production.total_payment == Money(amount_paise=500)


def test_capacity_ineligible_bid_is_isolated_in_both_implementations() -> None:
    state = _state_with_bids(
        _policy(seller_count=3),
        ((0, 100, 4), (1, 105, 3), (2, 120, 4)),
    )

    production, _ = _run_differential(state)

    assert production.winner_merchant_id == _MERCHANT_IDS[0]
    assert production.payment_unit_price == Money(amount_paise=120)
    assert production.total_payment == Money(amount_paise=480)


def test_above_reserve_bid_is_isolated_in_both_implementations() -> None:
    state = _state_with_bids(
        _policy(seller_count=3),
        ((0, 100, 4), (1, 120, 4), (2, 130, 4)),
    )

    production, _ = _run_differential(state)

    assert production.winner_merchant_id == _MERCHANT_IDS[0]
    assert production.payment_unit_price == Money(amount_paise=120)
    assert production.total_payment == Money(amount_paise=480)


def test_no_eligible_accepted_bids_agree_as_infeasible() -> None:
    state = _state_with_bids(
        _policy(seller_count=3),
        ((0, 100, 3), (1, 126, 4), (2, 130, 3)),
    )

    production, _ = _run_differential(state)

    assert production.status is AllocationStatus.INFEASIBLE
    assert production.winner_merchant_id is None
    assert production.winning_bid_id is None
    assert production.allocated_quantity is None
    assert production.winning_unit_price is None
    assert production.payment_unit_price is None
    assert production.total_payment is None


def test_exact_capacity_and_reserve_boundaries_agree() -> None:
    policy = _policy(seller_count=2)
    state = _state_with_bids(policy, ((0, 125, 4),))

    production, _ = _run_differential(state)

    assert production.status is AllocationStatus.FEASIBLE
    assert production.winner_merchant_id == _MERCHANT_IDS[0]
    assert production.winning_unit_price == policy.reserve_unit_price
    assert production.payment_unit_price == policy.reserve_unit_price
    assert production.total_payment == Money(amount_paise=500)


def test_maximum_money_boundary_agrees() -> None:
    reserve = MAX_MONEY_PAISE // MAX_QUANTITY
    policy = _policy(
        seller_count=2,
        requested_quantity=MAX_QUANTITY,
        reserve_unit_price_paise=reserve,
        max_total_payment_paise=MAX_MONEY_PAISE,
    )
    state = _state_with_bids(policy, ((0, reserve, MAX_QUANTITY),))

    production, _ = _run_differential(state)

    assert production.status is AllocationStatus.FEASIBLE
    assert production.payment_unit_price == Money(amount_paise=reserve)
    assert production.total_payment == Money(amount_paise=MAX_MONEY_PAISE)


def test_rejected_cheap_bid_is_isolated_from_both_implementations() -> None:
    policy = _policy(seller_count=2)
    state = AdmissionState(policy)
    signed_cheap_bid = _signed_bid(
        state,
        0,
        unit_price_paise=1,
        quantity_available=4,
    )
    invalid_cheap_bid = SignedMerchantBid(
        bid=signed_cheap_bid.bid,
        signature_hex="0" * 128,
    )

    rejected = admit_signed_bid(
        state,
        invalid_cheap_bid,
        AdmissionContext(received_at=_RECEIVED_AT),
    )
    assert rejected.rejection_code is AdmissionRejectionCode.INVALID_SIGNATURE

    _admit(state, 1, unit_price_paise=110, quantity_available=4)
    production, _ = _run_differential(state)

    assert len(state.accepted_decisions) == 1
    assert production.winner_merchant_id == _MERCHANT_IDS[1]
    assert production.payment_unit_price == policy.reserve_unit_price
    assert production.total_payment == Money(amount_paise=500)


@st.composite
def _market_cases(draw) -> _GeneratedMarket:
    seller_count = draw(st.integers(min_value=2, max_value=20))
    requested_quantity = draw(st.integers(min_value=1, max_value=20))
    reserve_unit_price_paise = draw(st.integers(min_value=0, max_value=25))
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
    sellers = tuple(
        (
            draw(st.booleans()),
            draw(st.sampled_from(quantity_choices)),
            draw(st.sampled_from(price_choices)),
        )
        for _ in range(seller_count)
    )
    return seller_count, requested_quantity, reserve_unit_price_paise, sellers


@given(case=_market_cases())
@settings(max_examples=250, derandomize=True, deadline=None)
def test_generated_admitted_states_match_independent_oracle(case: _GeneratedMarket) -> None:
    seller_count, requested_quantity, reserve_unit_price_paise, sellers = case
    policy = _policy(
        seller_count=seller_count,
        requested_quantity=requested_quantity,
        reserve_unit_price_paise=reserve_unit_price_paise,
        max_total_payment_paise=reserve_unit_price_paise * requested_quantity,
    )
    state = AdmissionState(policy)

    for merchant_index, (participates, quantity_available, unit_price_paise) in enumerate(sellers):
        if participates:
            _admit(
                state,
                merchant_index,
                unit_price_paise=unit_price_paise,
                quantity_available=quantity_available,
            )

    before = state.accepted_decisions
    production = allocate_market(state)
    oracle = compute_oracle_allocation(state)

    _assert_allocations_semantically_equal(production, oracle)
    assert state.accepted_decisions == before

    if production.status is AllocationStatus.FEASIBLE:
        assert production.total_payment is not None
        assert production.total_payment.amount_paise <= state.policy.max_total_payment.amount_paise
        assert production.winner_merchant_id is not None
        assert production.winning_bid_id is not None
    else:
        assert production.winner_merchant_id is None
        assert production.winning_bid_id is None
        assert production.allocated_quantity is None
        assert production.winning_unit_price is None
        assert production.payment_unit_price is None
        assert production.total_payment is None

    repeated_production = allocate_market(state)
    repeated_oracle = compute_oracle_allocation(state)

    _assert_allocations_semantically_equal(repeated_production, repeated_oracle)
    assert repeated_production == production
    assert repeated_oracle == oracle
    assert state.accepted_decisions == before
