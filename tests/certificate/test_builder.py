from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from clear_market.certificate import AllocationCertificate, build_allocation_certificate
from clear_market.crypto import buyer_policy_commitment, sign_merchant_bid
from clear_market.domain import (
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
    AdmissionRejectionCode,
    AdmissionState,
    admit_signed_bid,
)
from clear_market.mechanism import AllocationStatus

# TEST ONLY — NEVER PRODUCTION KEY MATERIAL.
_PRIVATE_KEY_SEEDS = (bytes([1]) * 32, bytes([2]) * 32)
_MARKET_ID = "10000000-0000-4000-8000-000000000001"
_BUYER_ID = "20000000-0000-4000-8000-000000000001"
_MERCHANT_IDS = (
    "30000000-0000-4000-8000-000000000001",
    "30000000-0000-4000-8000-000000000002",
)
_BID_IDS = (
    "40000000-0000-4000-8000-000000000001",
    "40000000-0000-4000-8000-000000000002",
)
_NEW_MERCHANT_A_BID_ID = "40000000-0000-4000-8000-000000000003"
_CERTIFICATE_ID = "50000000-0000-4000-8000-000000000001"
_DEADLINE = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 9, 1, 11, 59, 58, tzinfo=UTC)
_RECEIVED_AT = datetime(2026, 9, 1, 11, 59, 59, tzinfo=UTC)


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


def _policy(*, reserve_unit_price_paise: int = 125) -> BuyerPolicy:
    return BuyerPolicy(
        market_spec=MarketSpec(
            market_id=_MARKET_ID,
            buyer_id=_BUYER_ID,
            requested_quantity=4,
        ),
        max_total_payment=Money(amount_paise=500),
        reserve_unit_price=Money(amount_paise=reserve_unit_price_paise),
        eligible_merchants=tuple(
            MerchantIdentity(
                merchant_id=_MERCHANT_IDS[index],
                ed25519_public_key_hex=_public_key_hex(index),
            )
            for index in range(2)
        ),
        bid_deadline=_DEADLINE,
    )


def _signed_bid(
    policy: BuyerPolicy,
    merchant_index: int,
    *,
    bid_id: str | None = None,
    unit_price_paise: int = 100,
) -> SignedMerchantBid:
    bid = MerchantBid(
        bid_id=_BID_IDS[merchant_index] if bid_id is None else bid_id,
        market_id=policy.market_spec.market_id,
        merchant_id=_MERCHANT_IDS[merchant_index],
        buyer_policy_commitment=buyer_policy_commitment(policy),
        quantity_available=4,
        unit_price_paise=unit_price_paise,
        submitted_at=_SUBMITTED_AT,
    )
    return sign_merchant_bid(bid, _private_key(merchant_index))


def _context() -> AdmissionContext:
    return AdmissionContext(received_at=_RECEIVED_AT)


def _attempt(state: AdmissionState, signed_bid: SignedMerchantBid) -> AdmissionDecision:
    return admit_signed_bid(state, signed_bid, _context())


def _assert_certificate_bindings(
    allocation_certificate: AllocationCertificate,
    policy: BuyerPolicy,
    decisions: tuple[AdmissionDecision, ...],
) -> None:
    assert allocation_certificate.buyer_policy is policy
    assert allocation_certificate.buyer_policy_commitment == buyer_policy_commitment(policy)
    assert allocation_certificate.admission_decisions == decisions
    assert allocation_certificate.allocation.market_id == policy.market_spec.market_id
    assert (
        allocation_certificate.allocation.buyer_policy_commitment_version
        == allocation_certificate.buyer_policy_commitment_version
    )
    assert (
        allocation_certificate.allocation.buyer_policy_commitment
        == allocation_certificate.buyer_policy_commitment
    )
    assert allocation_certificate.allocation.mechanism_version == policy.mechanism_version


def test_builder_accepts_empty_transcript_and_records_infeasible_allocation() -> None:
    policy = _policy()
    decisions: tuple[AdmissionDecision, ...] = ()

    allocation_certificate = build_allocation_certificate(
        _CERTIFICATE_ID,
        policy,
        decisions,
    )

    _assert_certificate_bindings(allocation_certificate, policy, decisions)
    assert allocation_certificate.allocation.status is AllocationStatus.INFEASIBLE
    assert allocation_certificate.allocation.winner_merchant_id is None
    assert allocation_certificate.allocation.total_payment is None


def test_builder_replays_one_accepted_seller_and_uses_reserve_payment() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    accepted = _attempt(state, _signed_bid(policy, 0, unit_price_paise=100))
    decisions = (accepted,)

    allocation_certificate = build_allocation_certificate(
        _CERTIFICATE_ID,
        policy,
        decisions,
    )

    _assert_certificate_bindings(allocation_certificate, policy, decisions)
    assert accepted.rejection_code is None
    assert allocation_certificate.allocation.status is AllocationStatus.FEASIBLE
    assert allocation_certificate.allocation.winner_merchant_id == _MERCHANT_IDS[0]
    assert allocation_certificate.allocation.payment_unit_price == Money(amount_paise=125)
    assert allocation_certificate.allocation.total_payment == Money(amount_paise=500)


def test_builder_replays_two_sellers_and_records_second_ranked_payment() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    merchant_b = _attempt(state, _signed_bid(policy, 1, unit_price_paise=110))
    merchant_a = _attempt(state, _signed_bid(policy, 0, unit_price_paise=100))
    decisions = (merchant_b, merchant_a)

    allocation_certificate = build_allocation_certificate(
        _CERTIFICATE_ID,
        policy,
        decisions,
    )

    _assert_certificate_bindings(allocation_certificate, policy, decisions)
    assert merchant_b.rejection_code is None
    assert merchant_a.rejection_code is None
    assert allocation_certificate.admission_decisions == (merchant_b, merchant_a)
    assert allocation_certificate.allocation.winner_merchant_id == _MERCHANT_IDS[0]
    assert allocation_certificate.allocation.payment_unit_price == Money(amount_paise=110)
    assert allocation_certificate.allocation.total_payment == Money(amount_paise=440)


def test_builder_retains_rejected_cheap_bid_without_affecting_allocation() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    signed_cheap_bid = _signed_bid(policy, 0, unit_price_paise=1)
    invalid_cheap_bid = SignedMerchantBid(
        bid=signed_cheap_bid.bid,
        signature_hex="0" * 128,
    )
    rejected = _attempt(state, invalid_cheap_bid)
    accepted = _attempt(state, _signed_bid(policy, 1, unit_price_paise=110))
    decisions = (rejected, accepted)

    allocation_certificate = build_allocation_certificate(
        _CERTIFICATE_ID,
        policy,
        decisions,
    )

    _assert_certificate_bindings(allocation_certificate, policy, decisions)
    assert rejected.rejection_code is AdmissionRejectionCode.INVALID_SIGNATURE
    assert accepted.rejection_code is None
    assert len(allocation_certificate.admission_decisions) == 2
    assert allocation_certificate.allocation.winner_merchant_id == _MERCHANT_IDS[1]
    assert allocation_certificate.allocation.payment_unit_price == Money(amount_paise=125)


def test_builder_replays_exact_bid_rejection_and_retains_both_attempts() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    signed_bid = _signed_bid(policy, 0)
    accepted = _attempt(state, signed_bid)
    replayed = _attempt(state, signed_bid)
    decisions = (accepted, replayed)

    allocation_certificate = build_allocation_certificate(
        _CERTIFICATE_ID,
        policy,
        decisions,
    )

    _assert_certificate_bindings(allocation_certificate, policy, decisions)
    assert accepted.rejection_code is None
    assert replayed.rejection_code is AdmissionRejectionCode.REPLAYED_BID_ID
    assert len(allocation_certificate.admission_decisions) == 2
    assert allocation_certificate.allocation.winner_merchant_id == _MERCHANT_IDS[0]


def test_builder_replays_duplicate_merchant_rejection_and_retains_attempt() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    accepted = _attempt(state, _signed_bid(policy, 0))
    duplicate = _attempt(
        state,
        _signed_bid(
            policy,
            0,
            bid_id=_NEW_MERCHANT_A_BID_ID,
            unit_price_paise=90,
        ),
    )
    decisions = (accepted, duplicate)

    allocation_certificate = build_allocation_certificate(
        _CERTIFICATE_ID,
        policy,
        decisions,
    )

    _assert_certificate_bindings(allocation_certificate, policy, decisions)
    assert accepted.rejection_code is None
    assert duplicate.rejection_code is AdmissionRejectionCode.DUPLICATE_MERCHANT_BID
    assert len(allocation_certificate.admission_decisions) == 2
    assert allocation_certificate.allocation.winning_unit_price == Money(amount_paise=100)


@pytest.mark.parametrize("buyer_policy", [None, object(), {}])
def test_builder_rejects_non_buyer_policy(buyer_policy: object) -> None:
    with pytest.raises(TypeError):
        build_allocation_certificate(_CERTIFICATE_ID, buyer_policy, ())


def test_builder_rejects_list_transcript() -> None:
    with pytest.raises(TypeError):
        build_allocation_certificate(_CERTIFICATE_ID, _policy(), [])


def test_builder_rejects_non_decision_tuple_element() -> None:
    with pytest.raises(TypeError):
        build_allocation_certificate(_CERTIFICATE_ID, _policy(), (object(),))


def test_builder_rejects_false_declared_rejection_code() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    signed_bid = _signed_bid(policy, 0)
    invalid_signed_bid = SignedMerchantBid(bid=signed_bid.bid, signature_hex="0" * 128)
    actual = _attempt(state, invalid_signed_bid)
    declared = AdmissionDecision(
        signed_bid=actual.signed_bid,
        context=actual.context,
        rejection_code=AdmissionRejectionCode.RECEIVED_AFTER_DEADLINE,
    )

    with pytest.raises(ValueError):
        build_allocation_certificate(_CERTIFICATE_ID, policy, (declared,))


def test_builder_rejects_rejected_bid_relabelled_as_accepted() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    signed_bid = _signed_bid(policy, 0)
    invalid_signed_bid = SignedMerchantBid(bid=signed_bid.bid, signature_hex="0" * 128)
    actual = _attempt(state, invalid_signed_bid)
    declared = AdmissionDecision(
        signed_bid=actual.signed_bid,
        context=actual.context,
        rejection_code=None,
    )

    with pytest.raises(ValueError):
        build_allocation_certificate(_CERTIFICATE_ID, policy, (declared,))


def test_builder_rejects_accepted_bid_relabelled_as_rejected() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    actual = _attempt(state, _signed_bid(policy, 0))
    declared = AdmissionDecision(
        signed_bid=actual.signed_bid,
        context=actual.context,
        rejection_code=AdmissionRejectionCode.INVALID_SIGNATURE,
    )

    with pytest.raises(ValueError):
        build_allocation_certificate(_CERTIFICATE_ID, policy, (declared,))


def test_builder_rejects_reordered_replay_sensitive_transcript() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    signed_bid = _signed_bid(policy, 0)
    accepted = _attempt(state, signed_bid)
    replayed = _attempt(state, signed_bid)

    with pytest.raises(ValueError):
        build_allocation_certificate(_CERTIFICATE_ID, policy, (replayed, accepted))


def test_builder_rejects_decisions_bound_to_different_policy() -> None:
    original_policy = _policy()
    changed_policy = _policy(reserve_unit_price_paise=124)
    state = AdmissionState(original_policy)
    accepted = _attempt(state, _signed_bid(original_policy, 0))

    with pytest.raises(ValueError):
        build_allocation_certificate(_CERTIFICATE_ID, changed_policy, (accepted,))
