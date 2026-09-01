from dataclasses import dataclass

from clear_market.certificate import AllocationCertificate, build_allocation_certificate
from clear_market.domain import BuyerPolicy, Money, SignedMerchantBid
from clear_market.lifecycle import (
    AdmissionDecision,
    AdmissionRejectionCode,
    AdmissionState,
    admit_signed_bid,
)
from tests.adversarial.admission_helpers import (
    ALTERNATE_BID_ID,
    BASE_BID_ID,
    MERCHANT_A_ID,
    MERCHANT_B_ID,
    build_adversarial_market,
    build_bid,
    context,
    sign_with_a,
    sign_with_b,
)

THIRD_BID_ID = "84000000-0003-4000-8000-000000000001"
BASELINE_CERTIFICATE_ID = "85000000-0001-4000-8000-000000000001"
EXTENDED_CERTIFICATE_ID = "85000000-0002-4000-8000-000000000001"


@dataclass(frozen=True)
class StatefulCertificateFixture:
    policy: BuyerPolicy
    merchant_a_signed_bid: SignedMerchantBid
    merchant_b_signed_bid: SignedMerchantBid
    aggressive_duplicate_signed_bid: SignedMerchantBid
    accepted_decisions: tuple[AdmissionDecision, AdmissionDecision]
    replay_decision: AdmissionDecision
    duplicate_decision: AdmissionDecision
    baseline_certificate: AllocationCertificate
    extended_certificate: AllocationCertificate


def build_stateful_certificate_fixture() -> StatefulCertificateFixture:
    market = build_adversarial_market()
    policy = market.policy
    state = AdmissionState(policy)

    merchant_a_signed_bid = sign_with_a(
        market,
        build_bid(
            market,
            bid_id=BASE_BID_ID,
            merchant_id=MERCHANT_A_ID,
            quantity_available=10,
            unit_price_paise=400,
        ),
    )
    accepted_a = admit_signed_bid(state, merchant_a_signed_bid, context())
    assert accepted_a.rejection_code is None

    merchant_b_signed_bid = sign_with_b(
        market,
        build_bid(
            market,
            bid_id=ALTERNATE_BID_ID,
            merchant_id=MERCHANT_B_ID,
            quantity_available=10,
            unit_price_paise=450,
        ),
    )
    accepted_b = admit_signed_bid(state, merchant_b_signed_bid, context())
    assert accepted_b.rejection_code is None

    accepted_decisions = (accepted_a, accepted_b)
    assert state.accepted_decisions == accepted_decisions
    baseline_certificate = build_allocation_certificate(
        BASELINE_CERTIFICATE_ID,
        policy,
        accepted_decisions,
    )

    before_replay = state.accepted_decisions
    replay_decision = admit_signed_bid(state, merchant_a_signed_bid, context())
    assert replay_decision.rejection_code is AdmissionRejectionCode.REPLAYED_BID_ID
    assert state.accepted_decisions == before_replay

    aggressive_duplicate_signed_bid = sign_with_a(
        market,
        build_bid(
            market,
            bid_id=THIRD_BID_ID,
            merchant_id=MERCHANT_A_ID,
            quantity_available=1_000,
            unit_price_paise=0,
        ),
    )
    before_duplicate = state.accepted_decisions
    duplicate_decision = admit_signed_bid(state, aggressive_duplicate_signed_bid, context())
    assert duplicate_decision.rejection_code is AdmissionRejectionCode.DUPLICATE_MERCHANT_BID
    assert state.accepted_decisions == before_duplicate

    extended_certificate = build_allocation_certificate(
        EXTENDED_CERTIFICATE_ID,
        policy,
        (
            accepted_decisions[0],
            accepted_decisions[1],
            replay_decision,
            duplicate_decision,
        ),
    )
    return StatefulCertificateFixture(
        policy=policy,
        merchant_a_signed_bid=merchant_a_signed_bid,
        merchant_b_signed_bid=merchant_b_signed_bid,
        aggressive_duplicate_signed_bid=aggressive_duplicate_signed_bid,
        accepted_decisions=accepted_decisions,
        replay_decision=replay_decision,
        duplicate_decision=duplicate_decision,
        baseline_certificate=baseline_certificate,
        extended_certificate=extended_certificate,
    )


def replace_admission_decision(
    certificate: AllocationCertificate,
    index: int,
    decision: AdmissionDecision,
) -> AllocationCertificate:
    decisions = certificate.admission_decisions
    assert 0 <= index < len(decisions)
    replacement = (*decisions[:index], decision, *decisions[index + 1 :])
    return certificate.model_copy(update={"admission_decisions": replacement})


def increment_allocation_total(certificate: AllocationCertificate) -> AllocationCertificate:
    original_total = certificate.allocation.total_payment
    assert original_total is not None
    changed_total = Money(
        amount_paise=original_total.amount_paise + 1,
        currency=original_total.currency,
    )
    changed_allocation = certificate.allocation.model_copy(update={"total_payment": changed_total})
    return certificate.model_copy(update={"allocation": changed_allocation})


def replace_policy_commitment(certificate: AllocationCertificate) -> AllocationCertificate:
    replacement = "1" * 64 if certificate.buyer_policy_commitment == "0" * 64 else "0" * 64
    return certificate.model_copy(update={"buyer_policy_commitment": replacement})
