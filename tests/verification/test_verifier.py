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
from clear_market.mechanism import Allocation, AllocationStatus
from clear_market.verification import (
    CertificateVerificationFailureCode,
    verify_allocation_certificate,
)

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
    "40000000-0000-4000-8000-000000000003",
)
_CERTIFICATE_ID = "50000000-0000-4000-8000-000000000001"
_DEADLINE = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 9, 1, 11, 59, 58, tzinfo=UTC)
_RECEIVED_AT = datetime(2026, 9, 1, 11, 59, 59, tzinfo=UTC)
_CONTEXT = AdmissionContext(received_at=_RECEIVED_AT)


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


def _policy() -> BuyerPolicy:
    return BuyerPolicy(
        market_spec=MarketSpec(
            market_id=_MARKET_ID,
            buyer_id=_BUYER_ID,
            requested_quantity=4,
        ),
        max_total_payment=Money(amount_paise=500),
        reserve_unit_price=Money(amount_paise=125),
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
    bid_index: int | None = None,
    unit_price_paise: int,
) -> SignedMerchantBid:
    resolved_bid_index = merchant_index if bid_index is None else bid_index
    bid = MerchantBid(
        bid_id=_BID_IDS[resolved_bid_index],
        market_id=policy.market_spec.market_id,
        merchant_id=_MERCHANT_IDS[merchant_index],
        buyer_policy_commitment=buyer_policy_commitment(policy),
        quantity_available=4,
        unit_price_paise=unit_price_paise,
        submitted_at=_SUBMITTED_AT,
    )
    return sign_merchant_bid(bid, _private_key(merchant_index))


def _admit(state: AdmissionState, signed_bid: SignedMerchantBid) -> AdmissionDecision:
    return admit_signed_bid(state, signed_bid, _CONTEXT)


def _build_certificate(decisions: tuple[AdmissionDecision, ...]) -> AllocationCertificate:
    return build_allocation_certificate(_CERTIFICATE_ID, _policy(), decisions)


def _certificate_with(
    source: AllocationCertificate,
    *,
    admission_decisions: tuple[AdmissionDecision, ...] | None = None,
    allocation: Allocation | None = None,
) -> AllocationCertificate:
    return AllocationCertificate(
        certificate_id=source.certificate_id,
        buyer_policy=source.buyer_policy,
        buyer_policy_commitment=source.buyer_policy_commitment,
        admission_decisions=(
            source.admission_decisions if admission_decisions is None else admission_decisions
        ),
        allocation=source.allocation if allocation is None else allocation,
    )


def _empty_certificate() -> AllocationCertificate:
    return _build_certificate(())


def _one_accepted_certificate() -> AllocationCertificate:
    policy = _policy()
    state = AdmissionState(policy)
    accepted = _admit(state, _signed_bid(policy, 0, unit_price_paise=100))
    assert accepted.rejection_code is None
    return build_allocation_certificate(_CERTIFICATE_ID, policy, (accepted,))


def _two_accepted_certificate() -> AllocationCertificate:
    policy = _policy()
    state = AdmissionState(policy)
    accepted_b = _admit(state, _signed_bid(policy, 1, unit_price_paise=110))
    accepted_a = _admit(state, _signed_bid(policy, 0, unit_price_paise=100))
    assert accepted_b.rejection_code is None
    assert accepted_a.rejection_code is None
    return build_allocation_certificate(
        _CERTIFICATE_ID,
        policy,
        (accepted_b, accepted_a),
    )


def _invalid_signature_and_accepted_certificate() -> AllocationCertificate:
    policy = _policy()
    state = AdmissionState(policy)
    signed_a = _signed_bid(policy, 0, unit_price_paise=1)
    invalid_a = SignedMerchantBid(bid=signed_a.bid, signature_hex="0" * 128)
    rejected_a = _admit(state, invalid_a)
    accepted_b = _admit(state, _signed_bid(policy, 1, unit_price_paise=110))
    assert rejected_a.rejection_code is AdmissionRejectionCode.INVALID_SIGNATURE
    assert accepted_b.rejection_code is None
    return build_allocation_certificate(
        _CERTIFICATE_ID,
        policy,
        (rejected_a, accepted_b),
    )


def _replay_rejection_certificate() -> AllocationCertificate:
    policy = _policy()
    state = AdmissionState(policy)
    signed_a = _signed_bid(policy, 0, unit_price_paise=100)
    accepted_a = _admit(state, signed_a)
    replayed_a = _admit(state, signed_a)
    assert accepted_a.rejection_code is None
    assert replayed_a.rejection_code is AdmissionRejectionCode.REPLAYED_BID_ID
    return build_allocation_certificate(
        _CERTIFICATE_ID,
        policy,
        (accepted_a, replayed_a),
    )


def _duplicate_merchant_rejection_certificate() -> AllocationCertificate:
    policy = _policy()
    state = AdmissionState(policy)
    accepted_a = _admit(state, _signed_bid(policy, 0, unit_price_paise=100))
    duplicate_a = _admit(
        state,
        _signed_bid(policy, 0, bid_index=2, unit_price_paise=90),
    )
    assert accepted_a.rejection_code is None
    assert duplicate_a.rejection_code is AdmissionRejectionCode.DUPLICATE_MERCHANT_BID
    return build_allocation_certificate(
        _CERTIFICATE_ID,
        policy,
        (accepted_a, duplicate_a),
    )


def _infeasible_allocation(certificate: AllocationCertificate) -> Allocation:
    return Allocation(
        market_id=certificate.buyer_policy.market_spec.market_id,
        buyer_policy_commitment=certificate.buyer_policy_commitment,
        mechanism_version=certificate.buyer_policy.mechanism_version,
        status=AllocationStatus.INFEASIBLE,
    )


def test_empty_transcript_certificate_verifies() -> None:
    certificate = _empty_certificate()

    result = verify_allocation_certificate(certificate)

    assert result.verified is True
    assert result.failure_code is None
    assert result.failed_admission_index is None
    assert certificate.allocation.status is AllocationStatus.INFEASIBLE


def test_one_accepted_seller_certificate_verifies_reserve_payment() -> None:
    certificate = _one_accepted_certificate()

    result = verify_allocation_certificate(certificate)

    assert result.verified is True
    assert certificate.allocation.payment_unit_price == Money(amount_paise=125)
    assert certificate.allocation.total_payment == Money(amount_paise=500)


def test_two_accepted_seller_certificate_verifies_second_ranked_payment() -> None:
    certificate = _two_accepted_certificate()

    result = verify_allocation_certificate(certificate)

    assert result.verified is True
    assert certificate.allocation.winner_merchant_id == _MERCHANT_IDS[0]
    assert certificate.allocation.payment_unit_price == Money(amount_paise=110)
    assert certificate.allocation.total_payment == Money(amount_paise=440)


def test_valid_invalid_signature_evidence_and_accepted_bid_verifies() -> None:
    certificate = _invalid_signature_and_accepted_certificate()

    result = verify_allocation_certificate(certificate)

    assert result.verified is True
    assert certificate.admission_decisions[0].rejection_code is (
        AdmissionRejectionCode.INVALID_SIGNATURE
    )


def test_valid_replayed_bid_rejection_evidence_verifies() -> None:
    result = verify_allocation_certificate(_replay_rejection_certificate())

    assert result.verified is True


def test_valid_duplicate_merchant_rejection_evidence_verifies() -> None:
    result = verify_allocation_certificate(_duplicate_merchant_rejection_certificate())

    assert result.verified is True


def test_policy_commitment_tamper_is_detected_first() -> None:
    certificate = _one_accepted_certificate()
    adversarial = certificate.model_copy(update={"buyer_policy_commitment": "0" * 64})

    result = verify_allocation_certificate(adversarial)

    assert result.verified is False
    assert result.failure_code is (CertificateVerificationFailureCode.POLICY_COMMITMENT_MISMATCH)
    assert result.failed_admission_index is None


def test_accepted_decision_relabelled_rejected_is_detected() -> None:
    certificate = _one_accepted_certificate()
    accepted = certificate.admission_decisions[0]
    corrupted = AdmissionDecision(
        signed_bid=accepted.signed_bid,
        context=accepted.context,
        rejection_code=AdmissionRejectionCode.INVALID_SIGNATURE,
    )
    adversarial = _certificate_with(certificate, admission_decisions=(corrupted,))

    result = verify_allocation_certificate(adversarial)

    assert result.failure_code is CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH
    assert result.failed_admission_index == 0


def test_rejected_decision_relabelled_accepted_is_detected() -> None:
    certificate = _invalid_signature_and_accepted_certificate()
    rejected = certificate.admission_decisions[0]
    corrupted = AdmissionDecision(
        signed_bid=rejected.signed_bid,
        context=rejected.context,
        rejection_code=None,
    )
    adversarial = _certificate_with(
        certificate,
        admission_decisions=(corrupted, certificate.admission_decisions[1]),
    )

    result = verify_allocation_certificate(adversarial)

    assert result.failure_code is CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH
    assert result.failed_admission_index == 0


def test_signature_tamper_declared_accepted_is_detected() -> None:
    certificate = _one_accepted_certificate()
    accepted = certificate.admission_decisions[0]
    tampered_signed_bid = SignedMerchantBid(
        bid=accepted.signed_bid.bid,
        signature_hex="0" * 128,
    )
    corrupted = AdmissionDecision(
        signed_bid=tampered_signed_bid,
        context=accepted.context,
        rejection_code=None,
    )
    adversarial = _certificate_with(certificate, admission_decisions=(corrupted,))

    result = verify_allocation_certificate(adversarial)

    assert result.failure_code is CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH
    assert result.failed_admission_index == 0


def test_replay_sensitive_transcript_reordering_is_detected_at_zero() -> None:
    certificate = _replay_rejection_certificate()
    accepted, replayed = certificate.admission_decisions
    adversarial = _certificate_with(
        certificate,
        admission_decisions=(replayed, accepted),
    )

    result = verify_allocation_certificate(adversarial)

    assert result.failure_code is CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH
    assert result.failed_admission_index == 0


def test_structurally_valid_wrong_winner_is_detected() -> None:
    certificate = _two_accepted_certificate()
    wrong_allocation = Allocation(
        market_id=certificate.buyer_policy.market_spec.market_id,
        buyer_policy_commitment=certificate.buyer_policy_commitment,
        mechanism_version=certificate.buyer_policy.mechanism_version,
        status=AllocationStatus.FEASIBLE,
        winner_merchant_id=_MERCHANT_IDS[1],
        winning_bid_id=_BID_IDS[1],
        allocated_quantity=4,
        winning_unit_price=Money(amount_paise=110),
        payment_unit_price=Money(amount_paise=110),
        total_payment=Money(amount_paise=440),
    )
    adversarial = _certificate_with(certificate, allocation=wrong_allocation)

    result = verify_allocation_certificate(adversarial)

    assert result.verified is False
    assert result.failure_code is CertificateVerificationFailureCode.ALLOCATION_MISMATCH
    assert result.failed_admission_index is None


def test_structurally_valid_wrong_payment_is_detected() -> None:
    certificate = _two_accepted_certificate()
    wrong_allocation = Allocation(
        market_id=certificate.buyer_policy.market_spec.market_id,
        buyer_policy_commitment=certificate.buyer_policy_commitment,
        mechanism_version=certificate.buyer_policy.mechanism_version,
        status=AllocationStatus.FEASIBLE,
        winner_merchant_id=_MERCHANT_IDS[0],
        winning_bid_id=_BID_IDS[0],
        allocated_quantity=4,
        winning_unit_price=Money(amount_paise=100),
        payment_unit_price=Money(amount_paise=125),
        total_payment=Money(amount_paise=500),
    )
    adversarial = _certificate_with(certificate, allocation=wrong_allocation)

    result = verify_allocation_certificate(adversarial)

    assert result.failure_code is CertificateVerificationFailureCode.ALLOCATION_MISMATCH
    assert result.failed_admission_index is None


def test_false_infeasible_allocation_is_detected() -> None:
    certificate = _one_accepted_certificate()
    adversarial = _certificate_with(
        certificate,
        allocation=_infeasible_allocation(certificate),
    )

    result = verify_allocation_certificate(adversarial)

    assert result.failure_code is CertificateVerificationFailureCode.ALLOCATION_MISMATCH
    assert result.failed_admission_index is None


def test_policy_mismatch_precedes_transcript_and_allocation_mismatches() -> None:
    certificate = _one_accepted_certificate()
    accepted = certificate.admission_decisions[0]
    corrupted = AdmissionDecision(
        signed_bid=accepted.signed_bid,
        context=accepted.context,
        rejection_code=AdmissionRejectionCode.INVALID_SIGNATURE,
    )
    adversarial = certificate.model_copy(
        update={
            "buyer_policy_commitment": "0" * 64,
            "admission_decisions": (corrupted,),
            "allocation": _infeasible_allocation(certificate),
        }
    )

    result = verify_allocation_certificate(adversarial)

    assert result.failure_code is (CertificateVerificationFailureCode.POLICY_COMMITMENT_MISMATCH)
    assert result.failed_admission_index is None


def test_first_of_multiple_transcript_mismatches_is_reported() -> None:
    certificate = _two_accepted_certificate()
    corrupted = tuple(
        AdmissionDecision(
            signed_bid=decision.signed_bid,
            context=decision.context,
            rejection_code=AdmissionRejectionCode.INVALID_SIGNATURE,
        )
        for decision in certificate.admission_decisions
    )
    adversarial = _certificate_with(certificate, admission_decisions=corrupted)

    result = verify_allocation_certificate(adversarial)

    assert result.failure_code is CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH
    assert result.failed_admission_index == 0


def test_verification_is_deterministic_and_does_not_mutate_certificate() -> None:
    certificate = _two_accepted_certificate()
    before_transcript = certificate.admission_decisions
    before_allocation = certificate.allocation

    first = verify_allocation_certificate(certificate)
    second = verify_allocation_certificate(certificate)

    assert first == second
    assert certificate.admission_decisions == before_transcript
    assert certificate.allocation == before_allocation


@pytest.mark.parametrize("value", [None, {}, "certificate", b"certificate", object()])
def test_non_certificate_values_are_rejected(value: object) -> None:
    with pytest.raises(TypeError):
        verify_allocation_certificate(value)


def test_allocation_certificate_subclass_is_rejected() -> None:
    class _AllocationCertificateSubclass(AllocationCertificate):
        pass

    certificate = _empty_certificate()
    subclass = _AllocationCertificateSubclass(
        certificate_id=certificate.certificate_id,
        buyer_policy=certificate.buyer_policy,
        buyer_policy_commitment=certificate.buyer_policy_commitment,
        admission_decisions=certificate.admission_decisions,
        allocation=certificate.allocation,
    )

    with pytest.raises(TypeError):
        verify_allocation_certificate(subclass)
