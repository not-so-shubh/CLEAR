import pytest
from pydantic import ValidationError

import clear_market.verification as verification
from clear_market.verification import (
    ALLOCATION_CERTIFICATE_VERIFIER_VERSION,
    CertificateVerificationFailureCode,
    CertificateVerificationResult,
)


def test_public_api_is_exact() -> None:
    assert verification.__all__ == (
        "ALLOCATION_CERTIFICATE_VERIFIER_VERSION",
        "CertificateVerificationFailureCode",
        "CertificateVerificationResult",
        "verify_allocation_certificate",
    )


def test_verifier_version_is_exact() -> None:
    assert ALLOCATION_CERTIFICATE_VERIFIER_VERSION == "allocation-certificate-verifier-v1"


def test_failure_enum_is_exact() -> None:
    assert tuple(CertificateVerificationFailureCode) == (
        CertificateVerificationFailureCode.POLICY_COMMITMENT_MISMATCH,
        CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH,
        CertificateVerificationFailureCode.ALLOCATION_MISMATCH,
    )
    assert tuple(member.value for member in CertificateVerificationFailureCode) == (
        "policy_commitment_mismatch",
        "transcript_replay_mismatch",
        "allocation_mismatch",
    )


def test_result_fields_and_default_verifier_version_are_exact() -> None:
    result = CertificateVerificationResult(verified=True)

    assert tuple(CertificateVerificationResult.model_fields) == (
        "schema_version",
        "verifier_version",
        "verified",
        "failure_code",
        "failed_admission_index",
    )
    assert result.schema_version == "1"
    assert result.verifier_version == ALLOCATION_CERTIFICATE_VERIFIER_VERSION


def test_verified_result_is_valid() -> None:
    result = CertificateVerificationResult(verified=True)

    assert result.verified is True
    assert result.failure_code is None
    assert result.failed_admission_index is None


def test_policy_mismatch_result_is_valid() -> None:
    result = CertificateVerificationResult(
        verified=False,
        failure_code=CertificateVerificationFailureCode.POLICY_COMMITMENT_MISMATCH,
    )

    assert result.failed_admission_index is None


def test_transcript_mismatch_with_zero_index_is_valid() -> None:
    result = CertificateVerificationResult(
        verified=False,
        failure_code=CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH,
        failed_admission_index=0,
    )

    assert result.failed_admission_index == 0


def test_allocation_mismatch_result_is_valid() -> None:
    result = CertificateVerificationResult(
        verified=False,
        failure_code=CertificateVerificationFailureCode.ALLOCATION_MISMATCH,
    )

    assert result.failed_admission_index is None


def test_result_is_frozen() -> None:
    result = CertificateVerificationResult(verified=True)

    with pytest.raises(ValidationError):
        result.verified = False


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        CertificateVerificationResult(verified=True, message="unexpected")


@pytest.mark.parametrize("value", [0, 1, "true"])
def test_verified_is_strict_bool(value: object) -> None:
    with pytest.raises(ValidationError):
        CertificateVerificationResult(verified=value)


def test_negative_failed_admission_index_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CertificateVerificationResult(
            verified=False,
            failure_code=CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH,
            failed_admission_index=-1,
        )


def test_verified_with_failure_code_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CertificateVerificationResult(
            verified=True,
            failure_code=CertificateVerificationFailureCode.ALLOCATION_MISMATCH,
        )


def test_verified_with_failed_index_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CertificateVerificationResult(verified=True, failed_admission_index=0)


def test_unverified_without_failure_code_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CertificateVerificationResult(verified=False)


def test_transcript_failure_without_index_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CertificateVerificationResult(
            verified=False,
            failure_code=CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH,
        )


def test_policy_failure_with_index_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CertificateVerificationResult(
            verified=False,
            failure_code=CertificateVerificationFailureCode.POLICY_COMMITMENT_MISMATCH,
            failed_admission_index=0,
        )


def test_allocation_failure_with_index_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CertificateVerificationResult(
            verified=False,
            failure_code=CertificateVerificationFailureCode.ALLOCATION_MISMATCH,
            failed_admission_index=0,
        )
