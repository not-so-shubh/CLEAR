from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ALLOCATION_CERTIFICATE_VERIFIER_V2_VERSION: Final[str] = "allocation-certificate-verifier-v2"


class AllocationCertificateVerificationFailureCodeV2(StrEnum):
    POLICY_COMMITMENT_MISMATCH = "POLICY_COMMITMENT_MISMATCH"
    UNSUPPORTED_MECHANISM_VERSION = "UNSUPPORTED_MECHANISM_VERSION"
    UNSUPPORTED_OBJECTIVE_VERSION = "UNSUPPORTED_OBJECTIVE_VERSION"
    TRANSCRIPT_REPLAY_MISMATCH = "TRANSCRIPT_REPLAY_MISMATCH"
    ALLOCATION_MISMATCH = "ALLOCATION_MISMATCH"
    ORACLE_REPLAY_FAILURE = "ORACLE_REPLAY_FAILURE"


class AllocationCertificateVerificationResultV2(BaseModel):
    """Immutable result identifying the first failed V2 verification boundary."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        revalidate_instances="always",
    )

    schema_version: Literal["2"] = "2"
    verifier_version: Literal["allocation-certificate-verifier-v2"] = (
        "allocation-certificate-verifier-v2"
    )
    verified: bool
    failure_code: AllocationCertificateVerificationFailureCodeV2 | None = None
    failed_evidence_index: Annotated[int, Field(strict=True, ge=0)] | None = None

    @model_validator(mode="after")
    def _validate_consistency(self) -> Self:
        if self.verified:
            if self.failure_code is not None or self.failed_evidence_index is not None:
                raise ValueError("verified results cannot contain failure evidence")
            return self

        if self.failure_code is None:
            raise ValueError("unverified results require a failure code")
        if (
            self.failure_code
            is AllocationCertificateVerificationFailureCodeV2.TRANSCRIPT_REPLAY_MISMATCH
        ):
            if self.failed_evidence_index is None:
                raise ValueError("transcript failures require an evidence index")
        elif self.failed_evidence_index is not None:
            raise ValueError("only transcript failures may contain an evidence index")
        return self
