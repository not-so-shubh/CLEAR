import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hypothesis import given, settings

from clear_market.crypto import buyer_policy_commitment, sign_merchant_bid
from clear_market.domain import (
    MAX_SELLERS,
    BuyerPolicy,
    MarketSpec,
    MerchantBid,
    MerchantIdentity,
    Money,
    SignedMerchantBid,
)
from clear_market.lifecycle import (
    AdmissionContext,
    AdmissionDecision,
    AdmissionState,
    admit_signed_bid,
)
from clear_market.mechanism import Allocation, AllocationStatus, allocate_market
from clear_market.oracle import OracleAllocation, compute_oracle_allocation
from tests.properties.market_strategies import PropertyMarketCase, property_market_cases

_DEADLINE = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 9, 1, 11, 59, 58, tzinfo=UTC)
_RECEIVED_AT = datetime(2026, 9, 1, 11, 59, 59, tzinfo=UTC)

# TEST-ONLY deterministic signing material for reproducible Hypothesis evidence;
# never production keys.
_PRIVATE_KEYS = tuple(
    Ed25519PrivateKey.from_private_bytes(
        hashlib.sha256(f"clear-property-suite-v1|merchant|{index}".encode("ascii")).digest()
    )
    for index in range(MAX_SELLERS)
)
_PUBLIC_KEY_HEXES = tuple(
    private_key.public_key()
    .public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    .hex()
    for private_key in _PRIVATE_KEYS
)


@dataclass(frozen=True)
class GeneratedTestAttempt:
    signed_bid: SignedMerchantBid
    context: AdmissionContext


def _market_id(case_tag: int) -> str:
    return f"61000000-0000-4000-8000-{case_tag:012x}"


def _buyer_id(case_tag: int) -> str:
    return f"62000000-0000-4000-8000-{case_tag:012x}"


def _merchant_id(case_tag: int, seller_index: int) -> str:
    return f"63000000-{seller_index + 1:04x}-4000-8000-{case_tag:012x}"


def _bid_id(case_tag: int, seller_index: int) -> str:
    return f"64000000-{seller_index + 1:04x}-4000-8000-{case_tag:012x}"


def build_property_market(
    case: PropertyMarketCase,
) -> tuple[BuyerPolicy, tuple[GeneratedTestAttempt, ...]]:
    identities = tuple(
        MerchantIdentity(
            merchant_id=_merchant_id(case.case_tag, seller_index),
            ed25519_public_key_hex=_PUBLIC_KEY_HEXES[seller_index],
        )
        for seller_index in range(case.seller_count)
    )
    policy = BuyerPolicy(
        market_spec=MarketSpec(
            market_id=_market_id(case.case_tag),
            buyer_id=_buyer_id(case.case_tag),
            requested_quantity=case.requested_quantity,
        ),
        max_total_payment=Money(
            amount_paise=case.reserve_unit_price_paise * case.requested_quantity
        ),
        reserve_unit_price=Money(amount_paise=case.reserve_unit_price_paise),
        eligible_merchants=identities,
        bid_deadline=_DEADLINE,
    )
    commitment = buyer_policy_commitment(policy)
    attempts = tuple(
        GeneratedTestAttempt(
            signed_bid=sign_merchant_bid(
                MerchantBid(
                    bid_id=_bid_id(case.case_tag, seller_index),
                    market_id=policy.market_spec.market_id,
                    merchant_id=_merchant_id(case.case_tag, seller_index),
                    buyer_policy_commitment=commitment,
                    quantity_available=case.quantity_available[seller_index],
                    unit_price_paise=case.unit_price_paise[seller_index],
                    submitted_at=_SUBMITTED_AT,
                ),
                _PRIVATE_KEYS[seller_index],
            ),
            context=AdmissionContext(received_at=_RECEIVED_AT),
        )
        for seller_index, participates in enumerate(case.participates)
        if participates
    )
    return policy, attempts


def admit_attempts(
    policy: BuyerPolicy,
    attempts: tuple[GeneratedTestAttempt, ...],
) -> tuple[AdmissionState, tuple[AdmissionDecision, ...]]:
    state = AdmissionState(policy)
    decisions = tuple(
        admit_signed_bid(state, attempt.signed_bid, attempt.context) for attempt in attempts
    )
    return state, decisions


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


def _assert_policy_and_bid_bindings(
    policy: BuyerPolicy,
    attempts: tuple[GeneratedTestAttempt, ...],
) -> None:
    merchant_ids = tuple(identity.merchant_id for identity in policy.eligible_merchants)
    participating_merchant_ids = tuple(attempt.signed_bid.bid.merchant_id for attempt in attempts)
    bid_ids = tuple(attempt.signed_bid.bid.bid_id for attempt in attempts)
    commitment = buyer_policy_commitment(policy)

    assert policy.bid_deadline == _DEADLINE
    assert len(set(participating_merchant_ids)) == len(participating_merchant_ids)
    assert len(set(bid_ids)) == len(bid_ids)

    for attempt in attempts:
        bid = attempt.signed_bid.bid
        assert bid.market_id == policy.market_spec.market_id
        assert bid.merchant_id in merchant_ids
        assert bid.buyer_policy_commitment == commitment
        assert bid.submitted_at == _SUBMITTED_AT
        assert attempt.context.received_at == _RECEIVED_AT


def _assert_feasible_invariants(production: Allocation, state: AdmissionState) -> None:
    policy = state.policy
    requested_quantity = policy.market_spec.requested_quantity

    assert production.winner_merchant_id is not None
    assert production.winning_bid_id is not None
    assert production.allocated_quantity is not None
    assert production.winning_unit_price is not None
    assert production.payment_unit_price is not None
    assert production.total_payment is not None
    assert production.allocated_quantity == requested_quantity

    winner_decisions = tuple(
        decision
        for decision in state.accepted_decisions
        if decision.signed_bid.bid.merchant_id == production.winner_merchant_id
        and decision.signed_bid.bid.bid_id == production.winning_bid_id
    )
    assert len(winner_decisions) == 1
    winner_bid = winner_decisions[0].signed_bid.bid

    assert winner_bid.quantity_available >= requested_quantity
    assert winner_bid.unit_price_paise <= policy.reserve_unit_price.amount_paise
    assert winner_bid.unit_price_paise == production.winning_unit_price.amount_paise
    assert production.winning_unit_price.amount_paise <= production.payment_unit_price.amount_paise
    assert production.payment_unit_price.amount_paise <= policy.reserve_unit_price.amount_paise
    assert (
        production.total_payment.amount_paise
        == production.payment_unit_price.amount_paise * requested_quantity
    )
    assert production.total_payment.amount_paise <= policy.max_total_payment.amount_paise


def _assert_infeasible_invariants(production: Allocation, state: AdmissionState) -> None:
    policy = state.policy
    requested_quantity = policy.market_spec.requested_quantity
    reserve = policy.reserve_unit_price.amount_paise

    assert production.winner_merchant_id is None
    assert production.winning_bid_id is None
    assert production.allocated_quantity is None
    assert production.winning_unit_price is None
    assert production.payment_unit_price is None
    assert production.total_payment is None
    assert not any(
        decision.signed_bid.bid.quantity_available >= requested_quantity
        and decision.signed_bid.bid.unit_price_paise <= reserve
        for decision in state.accepted_decisions
    )


@given(property_market_cases())
@settings(max_examples=500, derandomize=True, deadline=None)
def test_authenticated_markets_match_oracle_and_hold_invariants(case: PropertyMarketCase) -> None:
    policy, attempts = build_property_market(case)
    _assert_policy_and_bid_bindings(policy, attempts)
    state, decisions = admit_attempts(policy, attempts)

    assert all(decision.rejection_code is None for decision in decisions)
    assert len(state.accepted_decisions) == len(attempts)
    before = state.accepted_decisions

    production_first = allocate_market(state)
    assert state.accepted_decisions == before
    oracle_first = compute_oracle_allocation(state)
    assert state.accepted_decisions == before
    _assert_allocations_semantically_equal(production_first, oracle_first)

    production_second = allocate_market(state)
    assert state.accepted_decisions == before
    oracle_second = compute_oracle_allocation(state)
    assert state.accepted_decisions == before
    assert production_second == production_first
    assert oracle_second == oracle_first
    _assert_allocations_semantically_equal(production_second, oracle_second)

    if production_first.status is AllocationStatus.FEASIBLE:
        _assert_feasible_invariants(production_first, state)
    else:
        _assert_infeasible_invariants(production_first, state)


@given(property_market_cases())
@settings(max_examples=300, derandomize=True, deadline=None)
def test_allocation_is_invariant_to_admission_order(case: PropertyMarketCase) -> None:
    policy, attempts = build_property_market(case)
    forward_state, forward_decisions = admit_attempts(policy, attempts)
    reverse_state, reverse_decisions = admit_attempts(policy, tuple(reversed(attempts)))

    assert all(decision.rejection_code is None for decision in forward_decisions)
    assert all(decision.rejection_code is None for decision in reverse_decisions)
    assert len(forward_state.accepted_decisions) == len(attempts)
    assert len(reverse_state.accepted_decisions) == len(attempts)

    forward_production = allocate_market(forward_state)
    reverse_production = allocate_market(reverse_state)
    forward_oracle = compute_oracle_allocation(forward_state)
    reverse_oracle = compute_oracle_allocation(reverse_state)

    assert forward_production == reverse_production
    assert forward_oracle == reverse_oracle
    _assert_allocations_semantically_equal(forward_production, forward_oracle)
    _assert_allocations_semantically_equal(reverse_production, reverse_oracle)
