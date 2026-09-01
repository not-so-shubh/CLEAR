from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, model_validator

from clear_market.crypto import buyer_policy_commitment as _compute_buyer_policy_commitment
from clear_market.domain import BuyerPolicy, CanonicalUUID4
from clear_market.lifecycle import AdmissionDecision
from clear_market.mechanism import Allocation

ALLOCATION_CERTIFICATE_VERSION: Final[str] = "allocation-certificate-v1"

_LOWERCASE_HEX_DIGITS = frozenset("0123456789abcdef")


def _validate_buyer_policy_commitment(value: object) -> str:
    """Require the exact SHA-256 hexadecimal representation without normalization."""
    if type(value) is not str:
        raise ValueError("buyer policy commitment must be a string")
    if len(value) != 64 or any(character not in _LOWERCASE_HEX_DIGITS for character in value):
        raise ValueError("buyer policy commitment must be 64 lowercase hexadecimal characters")
    return value


type _BuyerPolicyCommitment = Annotated[
    str,
    BeforeValidator(_validate_buyer_policy_commitment),
]


class AllocationCertificate(BaseModel):
    """Immutable evidence container bound to one policy and claimed allocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    certificate_version: Literal["allocation-certificate-v1"] = "allocation-certificate-v1"
    certificate_id: CanonicalUUID4
    canonicalization_version: Literal["clear-json-v1"] = "clear-json-v1"
    buyer_policy_commitment_version: Literal["sha256-clear-json-v1"] = "sha256-clear-json-v1"
    merchant_bid_signature_version: Literal["ed25519-raw-clear-json-v1"] = (
        "ed25519-raw-clear-json-v1"
    )
    buyer_policy: BuyerPolicy
    buyer_policy_commitment: _BuyerPolicyCommitment
    admission_decisions: tuple[AdmissionDecision, ...]
    allocation: Allocation

    @model_validator(mode="after")
    def _validate_local_bindings(self) -> Self:
        expected_commitment = _compute_buyer_policy_commitment(self.buyer_policy)
        if self.buyer_policy_commitment != expected_commitment:
            raise ValueError("certificate commitment does not bind the supplied buyer policy")

        if self.allocation.market_id != self.buyer_policy.market_spec.market_id:
            raise ValueError("allocation market does not bind the certificate buyer policy")
        if self.allocation.buyer_policy_commitment_version != self.buyer_policy_commitment_version:
            raise ValueError("allocation commitment version does not bind the certificate")
        if self.allocation.buyer_policy_commitment != self.buyer_policy_commitment:
            raise ValueError("allocation commitment does not bind the certificate")
        if self.allocation.mechanism_version != self.buyer_policy.mechanism_version:
            raise ValueError("allocation mechanism does not bind the certificate buyer policy")
        return self
