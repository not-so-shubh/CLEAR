from typing import Any, cast

import pytest
from pydantic import ValidationError

import clear_market.verification.v2 as verification_v2
from clear_market.verification.v2 import (
    ALLOCATION_CERTIFICATE_VERIFIER_V2_VERSION,
    AllocationCertificateVerificationFailureCodeV2,
    AllocationCertificateVerificationResultV2,
)


def test_version_failure_codes_and_public_api_are_exact() -> None:
    assert ALLOCATION_CERTIFICATE_VERIFIER_V2_VERSION == ("allocation-certificate-verifier-v2")
    assert tuple(AllocationCertificateVerificationFailureCodeV2) == (
        AllocationCertificateVerificationFailureCodeV2.POLICY_COMMITMENT_MISMATCH,
        AllocationCertificateVerificationFailureCodeV2.UNSUPPORTED_MECHANISM_VERSION,
        AllocationCertificateVerificationFailureCodeV2.UNSUPPORTED_OBJECTIVE_VERSION,
        AllocationCertificateVerificationFailureCodeV2.TRANSCRIPT_REPLAY_MISMATCH,
        AllocationCertificateVerificationFailureCodeV2.ALLOCATION_MISMATCH,
        AllocationCertificateVerificationFailureCodeV2.ORACLE_REPLAY_FAILURE,
    )
    assert tuple(member.value for member in AllocationCertificateVerificationFailureCodeV2) == (
        "POLICY_COMMITMENT_MISMATCH",
        "UNSUPPORTED_MECHANISM_VERSION",
        "UNSUPPORTED_OBJECTIVE_VERSION",
        "TRANSCRIPT_REPLAY_MISMATCH",
        "ALLOCATION_MISMATCH",
        "ORACLE_REPLAY_FAILURE",
    )
    assert verification_v2.__all__ == (
        "ALLOCATION_CERTIFICATE_VERIFIER_V2_VERSION",
        "AllocationCertificateVerificationFailureCodeV2",
        "AllocationCertificateVerificationResultV2",
        "verify_allocation_certificate_v2",
    )


def test_result_has_exact_fields_versions_and_model_config() -> None:
    result = AllocationCertificateVerificationResultV2(verified=True)
    assert tuple(type(result).model_fields) == (
        "schema_version",
        "verifier_version",
        "verified",
        "failure_code",
        "failed_evidence_index",
    )
    assert result.schema_version == "2"
    assert result.verifier_version == "allocation-certificate-verifier-v2"
    assert result.verified is True
    assert result.failure_code is None
    assert result.failed_evidence_index is None
    assert type(result).model_config["frozen"] is True
    assert type(result).model_config["extra"] == "forbid"
    assert type(result).model_config["strict"] is True
    assert type(result).model_config["revalidate_instances"] == "always"


@pytest.mark.parametrize("verified", [0, 1, "true", None])
def test_verified_requires_strict_bool(verified: object) -> None:
    with pytest.raises(ValidationError):
        AllocationCertificateVerificationResultV2(verified=cast(Any, verified))


@pytest.mark.parametrize("index", [True, 0.0, "0", -1])
def test_failed_evidence_index_requires_nonnegative_strict_int(index: object) -> None:
    with pytest.raises(ValidationError):
        AllocationCertificateVerificationResultV2(
            verified=False,
            failure_code=(
                AllocationCertificateVerificationFailureCodeV2.TRANSCRIPT_REPLAY_MISMATCH
            ),
            failed_evidence_index=cast(Any, index),
        )


def test_verified_success_forbids_failure_evidence() -> None:
    with pytest.raises(ValidationError):
        AllocationCertificateVerificationResultV2(
            verified=True,
            failure_code=AllocationCertificateVerificationFailureCodeV2.ALLOCATION_MISMATCH,
        )
    with pytest.raises(ValidationError):
        AllocationCertificateVerificationResultV2(
            verified=True,
            failed_evidence_index=0,
        )


def test_unverified_result_requires_failure_code() -> None:
    with pytest.raises(ValidationError):
        AllocationCertificateVerificationResultV2(verified=False)


def test_transcript_failure_requires_evidence_index() -> None:
    with pytest.raises(ValidationError):
        AllocationCertificateVerificationResultV2(
            verified=False,
            failure_code=(
                AllocationCertificateVerificationFailureCodeV2.TRANSCRIPT_REPLAY_MISMATCH
            ),
        )
    result = AllocationCertificateVerificationResultV2(
        verified=False,
        failure_code=(AllocationCertificateVerificationFailureCodeV2.TRANSCRIPT_REPLAY_MISMATCH),
        failed_evidence_index=3,
    )
    assert result.failed_evidence_index == 3


@pytest.mark.parametrize(
    "code",
    [
        AllocationCertificateVerificationFailureCodeV2.POLICY_COMMITMENT_MISMATCH,
        AllocationCertificateVerificationFailureCodeV2.UNSUPPORTED_MECHANISM_VERSION,
        AllocationCertificateVerificationFailureCodeV2.UNSUPPORTED_OBJECTIVE_VERSION,
        AllocationCertificateVerificationFailureCodeV2.ALLOCATION_MISMATCH,
        AllocationCertificateVerificationFailureCodeV2.ORACLE_REPLAY_FAILURE,
    ],
)
def test_non_transcript_failures_forbid_evidence_index(
    code: AllocationCertificateVerificationFailureCodeV2,
) -> None:
    with pytest.raises(ValidationError):
        AllocationCertificateVerificationResultV2(
            verified=False,
            failure_code=code,
            failed_evidence_index=0,
        )


def test_result_is_frozen_and_forbids_extra_fields() -> None:
    result = AllocationCertificateVerificationResultV2(verified=True)
    with pytest.raises(ValidationError):
        result.verified = False
    with pytest.raises(ValidationError):
        AllocationCertificateVerificationResultV2(verified=True, extra=True)
