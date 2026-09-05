"""Mechanical V2 allocation-certificate evidence construction."""

from pydantic import ValidationError

from clear_market.certificate.v2.models import (
    AllocationCertificateV2,
    AllocationClaimLineV2,
    AllocationClaimStatusV2,
    AllocationClaimV2,
    MerchantOfferEvidenceV2,
)
from clear_market.commerce.market import BuyerPolicyV2
from clear_market.commerce.merchant import buyer_policy_v2_commitment
from clear_market.domain import CanonicalUUID4
from clear_market.mechanism.v2.contracts import AllocationStatusV2, AllocationV2


def _fresh_exact_allocation_v2(value: object) -> AllocationV2:
    if type(value) is not AllocationV2:
        raise TypeError("allocation must be exactly an AllocationV2")
    try:
        field_values = {
            field_name: value.__dict__[field_name] for field_name in AllocationV2.model_fields
        }
        return AllocationV2.model_validate(field_values)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError("allocation must be a valid exact AllocationV2") from None


def _fresh_exact_buyer_policy_v2(value: object) -> BuyerPolicyV2:
    if type(value) is not BuyerPolicyV2:
        raise TypeError("buyer_policy must be exactly a BuyerPolicyV2")
    try:
        return BuyerPolicyV2.model_validate(value.model_dump(mode="python", warnings=False))
    except (AttributeError, ValidationError):
        raise ValueError("buyer_policy must be a valid exact BuyerPolicyV2") from None


def _claim_status(status: AllocationStatusV2) -> AllocationClaimStatusV2:
    if status is AllocationStatusV2.FEASIBLE:
        return AllocationClaimStatusV2.FEASIBLE
    if status is AllocationStatusV2.INFEASIBLE:
        return AllocationClaimStatusV2.INFEASIBLE
    raise ValueError("allocation status is unsupported")


def allocation_claim_v2_from_allocation_v2(
    allocation: AllocationV2,
) -> AllocationClaimV2:
    """Project exact allocation evidence without allocating, verifying, or authorizing money."""
    validated = _fresh_exact_allocation_v2(allocation)
    return AllocationClaimV2(
        schema_version=validated.schema_version,
        allocation_version=validated.allocation_version,
        mechanism_version=validated.mechanism_version,
        objective_version=validated.objective_version,
        market_id=validated.market_id,
        buyer_policy_commitment_version=validated.buyer_policy_commitment_version,
        buyer_policy_commitment_sha256=validated.buyer_policy_commitment_sha256,
        status=_claim_status(validated.status),
        fulfilled_quantity=validated.fulfilled_quantity,
        total_payment=validated.total_payment,
        soft_preference_unit_score=validated.soft_preference_unit_score,
        winner_count=validated.winner_count,
        lines=tuple(
            AllocationClaimLineV2(
                schema_version=line.schema_version,
                allocation_line_version=line.allocation_line_version,
                offer_id=line.offer_id,
                merchant_id=line.merchant_id,
                sku_id=line.sku_id,
                allocated_quantity=line.allocated_quantity,
                unit_payment=line.unit_payment,
                line_payment=line.line_payment,
            )
            for line in validated.lines
        ),
    )


def build_allocation_certificate_v2(
    *,
    certificate_id: CanonicalUUID4,
    buyer_policy: BuyerPolicyV2,
    merchant_offer_evidence: tuple[MerchantOfferEvidenceV2, ...],
    allocation: AllocationV2,
) -> AllocationCertificateV2:
    """Construct evidence, not verification, transcript-completeness proof, or money authority."""
    policy = _fresh_exact_buyer_policy_v2(buyer_policy)
    validated_allocation = _fresh_exact_allocation_v2(allocation)
    commitment = buyer_policy_v2_commitment(policy)
    if validated_allocation.market_id != policy.market_spec.market_id:
        raise ValueError("allocation market does not match buyer policy market")
    if validated_allocation.buyer_policy_commitment_sha256 != commitment:
        raise ValueError("allocation commitment does not match buyer policy")

    return AllocationCertificateV2(
        certificate_id=certificate_id,
        buyer_policy=policy,
        buyer_policy_commitment_sha256=commitment,
        merchant_offer_evidence=merchant_offer_evidence,
        allocation=allocation_claim_v2_from_allocation_v2(validated_allocation),
    )


__all__ = (
    "allocation_claim_v2_from_allocation_v2",
    "build_allocation_certificate_v2",
)
