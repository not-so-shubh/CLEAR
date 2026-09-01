from clear_market.certificate import AllocationCertificate
from clear_market.crypto import buyer_policy_commitment
from clear_market.lifecycle import AdmissionState, admit_signed_bid
from clear_market.oracle import OracleAllocation, compute_oracle_allocation
from clear_market.verification.models import (
    CertificateVerificationFailureCode,
    CertificateVerificationResult,
)


def _claimed_allocation_matches_oracle(
    certificate: AllocationCertificate,
    expected: OracleAllocation,
) -> bool:
    claimed = certificate.allocation
    return (
        claimed.schema_version == expected.schema_version
        and claimed.market_id == expected.market_id
        and claimed.buyer_policy_commitment_version == expected.buyer_policy_commitment_version
        and claimed.buyer_policy_commitment == expected.buyer_policy_commitment
        and claimed.mechanism_version == expected.mechanism_version
        and claimed.status.value == expected.status.value
        and claimed.winner_merchant_id == expected.winner_merchant_id
        and claimed.winning_bid_id == expected.winning_bid_id
        and claimed.allocated_quantity == expected.allocated_quantity
        and claimed.winning_unit_price == expected.winning_unit_price
        and claimed.payment_unit_price == expected.payment_unit_price
        and claimed.total_payment == expected.total_payment
    )


def verify_allocation_certificate(
    certificate: AllocationCertificate,
) -> CertificateVerificationResult:
    """Replay typed certificate evidence and check its claim against the independent oracle."""
    if type(certificate) is not AllocationCertificate:
        raise TypeError("certificate must be exactly an AllocationCertificate")

    expected_commitment = buyer_policy_commitment(certificate.buyer_policy)
    if expected_commitment != certificate.buyer_policy_commitment:
        return CertificateVerificationResult(
            verified=False,
            failure_code=CertificateVerificationFailureCode.POLICY_COMMITMENT_MISMATCH,
        )

    replay_state = AdmissionState(certificate.buyer_policy)
    for index, declared_decision in enumerate(certificate.admission_decisions):
        replayed_decision = admit_signed_bid(
            replay_state,
            declared_decision.signed_bid,
            declared_decision.context,
        )
        if replayed_decision != declared_decision:
            return CertificateVerificationResult(
                verified=False,
                failure_code=CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH,
                failed_admission_index=index,
            )

    expected_allocation = compute_oracle_allocation(replay_state)
    if not _claimed_allocation_matches_oracle(certificate, expected_allocation):
        return CertificateVerificationResult(
            verified=False,
            failure_code=CertificateVerificationFailureCode.ALLOCATION_MISMATCH,
        )

    return CertificateVerificationResult(verified=True)
