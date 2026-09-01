from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ALLOCATION_CERTIFICATE_VERIFIER_VERSION: Final[str] = "allocation-certificate-verifier-v1"


class CertificateVerificationFailureCode(StrEnum):
    POLICY_COMMITMENT_MISMATCH = "policy_commitment_mismatch"
    TRANSCRIPT_REPLAY_MISMATCH = "transcript_replay_mismatch"
    ALLOCATION_MISMATCH = "allocation_mismatch"


class CertificateVerificationResult(BaseModel):
    """Immutable outcome whose fields identify the first failed verification boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    verifier_version: Literal["allocation-certificate-verifier-v1"] = (
        "allocation-certificate-verifier-v1"
    )
    verified: Annotated[bool, Field(strict=True)]
    failure_code: CertificateVerificationFailureCode | None = None
    failed_admission_index: Annotated[int, Field(strict=True, ge=0)] | None = None

    @model_validator(mode="after")
    def _validate_result_consistency(self) -> Self:
        if self.verified:
            if self.failure_code is not None or self.failed_admission_index is not None:
                raise ValueError("verified results cannot contain failure evidence")
            return self

        if self.failure_code is None:
            raise ValueError("unverified results require a failure code")

        if self.failure_code is CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH:
            if self.failed_admission_index is None:
                raise ValueError("transcript failures require the first mismatching index")
        elif self.failed_admission_index is not None:
            raise ValueError("only transcript failures may contain an admission index")

        return self
