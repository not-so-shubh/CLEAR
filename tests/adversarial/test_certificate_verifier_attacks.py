from datetime import UTC, datetime

from clear_market.domain import SignedMerchantBid
from clear_market.lifecycle import (
    AdmissionRejectionCode,
    AdmissionState,
    admit_signed_bid,
)
from clear_market.verification import (
    CertificateVerificationFailureCode,
    verify_allocation_certificate,
)
from tests.adversarial.admission_helpers import (
    BASE_BID_ID,
    MERCHANT_A_ID,
    MERCHANT_B_ID,
    build_adversarial_market,
    build_bid,
    context,
    sign_with_a,
    sign_with_b,
)
from tests.adversarial.verifier_helpers import (
    THIRD_BID_ID,
    build_stateful_certificate_fixture,
    increment_allocation_total,
    replace_admission_decision,
    replace_policy_commitment,
)


def test_baseline_and_extended_certificates_verify_with_exact_transcript() -> None:
    fixture = build_stateful_certificate_fixture()

    baseline_result = verify_allocation_certificate(fixture.baseline_certificate)
    extended_result = verify_allocation_certificate(fixture.extended_certificate)

    assert baseline_result.verified is True
    assert baseline_result.failure_code is None
    assert baseline_result.failed_admission_index is None
    assert extended_result.verified is True
    assert extended_result.failure_code is None
    assert extended_result.failed_admission_index is None
    assert tuple(
        decision.rejection_code for decision in fixture.extended_certificate.admission_decisions
    ) == (
        None,
        None,
        AdmissionRejectionCode.REPLAYED_BID_ID,
        AdmissionRejectionCode.DUPLICATE_MERCHANT_BID,
    )
    assert fixture.baseline_certificate.allocation == fixture.extended_certificate.allocation
    assert (
        fixture.aggressive_duplicate_signed_bid.bid.quantity_available
        >= fixture.policy.market_spec.requested_quantity
    )
    assert (
        fixture.aggressive_duplicate_signed_bid.bid.unit_price_paise
        <= fixture.policy.reserve_unit_price.amount_paise
    )


def test_exact_replay_precedes_duplicate_merchant_without_state_mutation() -> None:
    market = build_adversarial_market()
    state = AdmissionState(market.policy)
    signed_bid = sign_with_a(
        market,
        build_bid(market, bid_id=BASE_BID_ID, merchant_id=MERCHANT_A_ID),
    )
    accepted = admit_signed_bid(state, signed_bid, context())
    assert accepted.rejection_code is None
    before = state.accepted_decisions

    replayed = admit_signed_bid(state, signed_bid, context())

    assert replayed.rejection_code is AdmissionRejectionCode.REPLAYED_BID_ID
    assert replayed.rejection_code is not AdmissionRejectionCode.DUPLICATE_MERCHANT_BID
    assert state.accepted_decisions == before


def test_cross_merchant_reused_bid_id_is_replay_without_state_mutation() -> None:
    market = build_adversarial_market()
    state = AdmissionState(market.policy)
    accepted_a = admit_signed_bid(
        state,
        sign_with_a(
            market,
            build_bid(market, bid_id=BASE_BID_ID, merchant_id=MERCHANT_A_ID),
        ),
        context(),
    )
    assert accepted_a.rejection_code is None
    before = state.accepted_decisions
    merchant_b_reused_id = sign_with_b(
        market,
        build_bid(market, bid_id=BASE_BID_ID, merchant_id=MERCHANT_B_ID),
    )

    replayed = admit_signed_bid(state, merchant_b_reused_id, context())

    assert replayed.rejection_code is AdmissionRejectionCode.REPLAYED_BID_ID
    assert state.accepted_decisions == before


def test_same_merchant_new_bid_id_is_duplicate_without_state_mutation() -> None:
    market = build_adversarial_market()
    state = AdmissionState(market.policy)
    accepted_a = admit_signed_bid(
        state,
        sign_with_a(
            market,
            build_bid(market, bid_id=BASE_BID_ID, merchant_id=MERCHANT_A_ID),
        ),
        context(),
    )
    assert accepted_a.rejection_code is None
    before = state.accepted_decisions
    merchant_a_new_bid = sign_with_a(
        market,
        build_bid(market, bid_id=THIRD_BID_ID, merchant_id=MERCHANT_A_ID),
    )

    duplicate = admit_signed_bid(state, merchant_a_new_bid, context())

    assert duplicate.rejection_code is AdmissionRejectionCode.DUPLICATE_MERCHANT_BID
    assert state.accepted_decisions == before


def test_rejected_replay_and_duplicate_evidence_do_not_change_allocation() -> None:
    fixture = build_stateful_certificate_fixture()

    assert len(fixture.baseline_certificate.admission_decisions) == 2
    assert len(fixture.extended_certificate.admission_decisions) == 4
    assert fixture.extended_certificate.admission_decisions[2].rejection_code is (
        AdmissionRejectionCode.REPLAYED_BID_ID
    )
    assert fixture.extended_certificate.admission_decisions[3].rejection_code is (
        AdmissionRejectionCode.DUPLICATE_MERCHANT_BID
    )
    assert fixture.baseline_certificate.allocation == fixture.extended_certificate.allocation


def test_accepted_decision_relabelled_rejected_is_detected_at_zero() -> None:
    fixture = build_stateful_certificate_fixture()
    accepted = fixture.extended_certificate.admission_decisions[0]
    relabelled = accepted.model_copy(
        update={"rejection_code": AdmissionRejectionCode.DUPLICATE_MERCHANT_BID}
    )
    adversarial = replace_admission_decision(
        fixture.extended_certificate,
        0,
        relabelled,
    )

    result = verify_allocation_certificate(adversarial)

    assert result.verified is False
    assert result.failure_code is CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH
    assert result.failed_admission_index == 0


def test_replay_rejection_relabelled_accepted_is_detected_at_two() -> None:
    fixture = build_stateful_certificate_fixture()
    replayed = fixture.extended_certificate.admission_decisions[2]
    relabelled = replayed.model_copy(update={"rejection_code": None})
    adversarial = replace_admission_decision(
        fixture.extended_certificate,
        2,
        relabelled,
    )

    result = verify_allocation_certificate(adversarial)

    assert result.verified is False
    assert result.failure_code is CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH
    assert result.failed_admission_index == 2


def test_rejected_duplicate_signature_tamper_is_detected_at_three() -> None:
    fixture = build_stateful_certificate_fixture()
    duplicate = fixture.extended_certificate.admission_decisions[3]
    old_signature = duplicate.signed_bid.signature_hex
    replacement = "1" * 128 if old_signature == "0" * 128 else "0" * 128
    tampered_signed_bid = SignedMerchantBid(
        bid=duplicate.signed_bid.bid,
        signature_hex=replacement,
    )
    tampered = duplicate.model_copy(update={"signed_bid": tampered_signed_bid})
    adversarial = replace_admission_decision(
        fixture.extended_certificate,
        3,
        tampered,
    )

    result = verify_allocation_certificate(adversarial)

    assert result.verified is False
    assert result.failure_code is CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH
    assert result.failed_admission_index == 3


def test_rejected_duplicate_context_tamper_is_detected_at_three() -> None:
    fixture = build_stateful_certificate_fixture()
    duplicate = fixture.extended_certificate.admission_decisions[3]
    received_after_deadline = datetime(2026, 9, 1, 12, 0, 0, 1, tzinfo=UTC)
    tampered_context = duplicate.context.model_copy(update={"received_at": received_after_deadline})
    tampered = duplicate.model_copy(update={"context": tampered_context})
    adversarial = replace_admission_decision(
        fixture.extended_certificate,
        3,
        tampered,
    )

    result = verify_allocation_certificate(adversarial)

    assert result.verified is False
    assert result.failure_code is CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH
    assert result.failed_admission_index == 3


def test_semantically_meaningful_transcript_reordering_is_detected_at_zero() -> None:
    fixture = build_stateful_certificate_fixture()
    original = fixture.extended_certificate.admission_decisions
    adversarial = fixture.extended_certificate.model_copy(
        update={"admission_decisions": (original[3], original[1], original[2], original[0])}
    )

    result = verify_allocation_certificate(adversarial)

    assert result.verified is False
    assert result.failure_code is CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH
    assert result.failed_admission_index == 0


def test_allocation_total_tamper_is_detected() -> None:
    fixture = build_stateful_certificate_fixture()
    assert fixture.baseline_certificate.allocation.total_payment is not None
    adversarial = increment_allocation_total(fixture.baseline_certificate)

    result = verify_allocation_certificate(adversarial)

    assert result.verified is False
    assert result.failure_code is CertificateVerificationFailureCode.ALLOCATION_MISMATCH
    assert result.failed_admission_index is None


def test_policy_commitment_tamper_is_detected() -> None:
    fixture = build_stateful_certificate_fixture()
    adversarial = replace_policy_commitment(fixture.baseline_certificate)

    result = verify_allocation_certificate(adversarial)

    assert result.verified is False
    assert result.failure_code is CertificateVerificationFailureCode.POLICY_COMMITMENT_MISMATCH
    assert result.failed_admission_index is None


def test_precedence_case_1_policy_outranks_transcript_and_allocation() -> None:
    fixture = build_stateful_certificate_fixture()
    accepted = fixture.extended_certificate.admission_decisions[0]
    relabelled = accepted.model_copy(
        update={"rejection_code": AdmissionRejectionCode.DUPLICATE_MERCHANT_BID}
    )
    transcript_fault = replace_admission_decision(
        fixture.extended_certificate,
        0,
        relabelled,
    )
    allocation_fault = increment_allocation_total(transcript_fault)
    adversarial = replace_policy_commitment(allocation_fault)

    result = verify_allocation_certificate(adversarial)

    assert result.verified is False
    assert result.failure_code is CertificateVerificationFailureCode.POLICY_COMMITMENT_MISMATCH
    assert result.failed_admission_index is None


def test_precedence_case_2_transcript_outranks_allocation() -> None:
    fixture = build_stateful_certificate_fixture()
    accepted = fixture.extended_certificate.admission_decisions[0]
    relabelled = accepted.model_copy(
        update={"rejection_code": AdmissionRejectionCode.DUPLICATE_MERCHANT_BID}
    )
    transcript_fault = replace_admission_decision(
        fixture.extended_certificate,
        0,
        relabelled,
    )
    adversarial = increment_allocation_total(transcript_fault)

    result = verify_allocation_certificate(adversarial)

    assert result.verified is False
    assert result.failure_code is CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH
    assert result.failed_admission_index == 0


def test_precedence_case_3_allocation_failure_is_last() -> None:
    fixture = build_stateful_certificate_fixture()
    adversarial = increment_allocation_total(fixture.baseline_certificate)

    result = verify_allocation_certificate(adversarial)

    assert result.verified is False
    assert result.failure_code is CertificateVerificationFailureCode.ALLOCATION_MISMATCH
    assert result.failed_admission_index is None
