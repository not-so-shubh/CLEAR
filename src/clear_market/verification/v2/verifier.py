from pydantic import ValidationError

from clear_market.canonical import CanonicalizationError
from clear_market.certificate.v2 import (
    AllocationCertificateV2,
    AllocationClaimLineV2,
    AllocationClaimV2,
    MerchantOfferAdmissionDecisionV2,
)
from clear_market.commerce import (
    BuyerPolicyV2,
    MerchantSigningIdentityV2,
    SignedMerchantOfferV2,
    buyer_policy_v2_commitment,
    canonical_signed_merchant_offer_v2_bytes,
    verify_canonical_signed_merchant_offer_v2,
)
from clear_market.commerce.authentication import MerchantOfferVerificationError
from clear_market.domain import Money
from clear_market.oracle.v2 import (
    OracleAllocationLineV2,
    OracleAllocationV2,
    OracleV2Error,
    compute_oracle_allocation_v2,
)
from clear_market.verification.v2.models import (
    AllocationCertificateVerificationFailureCodeV2,
    AllocationCertificateVerificationResultV2,
)

_MECHANISM_VERSION = "heterogeneous-pay-as-bid-v2"
_OBJECTIVE_VERSION = "quantity-cost-soft-objective-v2"


def _fresh_certificate(value: object) -> AllocationCertificateV2:
    if type(value) is not AllocationCertificateV2:
        raise TypeError("certificate must be exactly an AllocationCertificateV2")
    try:
        fields = {name: value.__dict__[name] for name in AllocationCertificateV2.model_fields}
        return AllocationCertificateV2.model_validate(fields)
    except (AttributeError, KeyError, ValidationError):
        raise ValueError("certificate must be a valid exact AllocationCertificateV2") from None


def _fresh_trusted_identities(
    value: object,
) -> tuple[MerchantSigningIdentityV2, ...]:
    if type(value) is not tuple:
        raise TypeError("trusted_signing_identities must be exactly a tuple")

    identities: list[MerchantSigningIdentityV2] = []
    for identity in value:
        if type(identity) is not MerchantSigningIdentityV2:
            raise TypeError("trusted identities must be exact MerchantSigningIdentityV2 values")
        try:
            identities.append(
                MerchantSigningIdentityV2.model_validate(
                    identity.model_dump(mode="python", warnings=False)
                )
            )
        except (AttributeError, ValidationError):
            raise ValueError("trusted identities must be valid exact values") from None

    merchant_ids = tuple(identity.merchant_id for identity in identities)
    if len(set(merchant_ids)) != len(merchant_ids):
        raise ValueError("trusted identity merchant IDs must be unique")
    return tuple(identities)


def _failure(
    code: AllocationCertificateVerificationFailureCodeV2,
    *,
    evidence_index: int | None = None,
) -> AllocationCertificateVerificationResultV2:
    return AllocationCertificateVerificationResultV2(
        verified=False,
        failure_code=code,
        failed_evidence_index=evidence_index,
    )


def _independent_admission_decision(
    *,
    certificate: AllocationCertificateV2,
    evidence_index: int,
    trusted_by_merchant: dict[str, MerchantSigningIdentityV2],
    admitted_offer_ids: set[str],
    admitted_merchant_ids: set[str],
) -> MerchantOfferAdmissionDecisionV2:
    evidence = certificate.merchant_offer_evidence[evidence_index]
    offer = evidence.signed_offer.offer
    policy = certificate.buyer_policy
    if offer.market_id != policy.market_spec.market_id:
        return MerchantOfferAdmissionDecisionV2.REJECTED
    if offer.buyer_policy_commitment_sha256 != certificate.buyer_policy_commitment_sha256:
        return MerchantOfferAdmissionDecisionV2.REJECTED
    if offer.merchant_id not in policy.eligible_merchant_ids:
        return MerchantOfferAdmissionDecisionV2.REJECTED

    trusted_identity = trusted_by_merchant.get(offer.merchant_id)
    if trusted_identity is None:
        return MerchantOfferAdmissionDecisionV2.REJECTED
    if evidence.signing_identity != trusted_identity:
        return MerchantOfferAdmissionDecisionV2.REJECTED

    try:
        signed_offer_data = canonical_signed_merchant_offer_v2_bytes(evidence.signed_offer)
        verify_canonical_signed_merchant_offer_v2(
            data=signed_offer_data,
            signing_identity=trusted_identity,
            buyer_policy=policy,
            catalog=evidence.catalog,
            inventory=evidence.inventory,
        )
    except (CanonicalizationError, MerchantOfferVerificationError):
        return MerchantOfferAdmissionDecisionV2.REJECTED

    if evidence.received_at > policy.offer_deadline:
        return MerchantOfferAdmissionDecisionV2.REJECTED
    if offer.offer_id in admitted_offer_ids:
        return MerchantOfferAdmissionDecisionV2.REJECTED
    if offer.merchant_id in admitted_merchant_ids:
        return MerchantOfferAdmissionDecisionV2.REJECTED
    return MerchantOfferAdmissionDecisionV2.ADMITTED


def _money_projection(value: Money) -> tuple[int, object]:
    return value.amount_paise, value.currency


def _claim_line_projection(value: AllocationClaimLineV2) -> tuple[object, ...]:
    return (
        value.offer_id,
        value.merchant_id,
        value.sku_id,
        value.allocated_quantity,
        *_money_projection(value.unit_payment),
        *_money_projection(value.line_payment),
    )


def _oracle_line_projection(value: OracleAllocationLineV2) -> tuple[object, ...]:
    return (
        value.offer_id,
        value.merchant_id,
        value.sku_id,
        value.allocated_quantity,
        *_money_projection(value.unit_payment),
        *_money_projection(value.line_payment),
    )


def _allocation_matches_oracle(
    claimed: AllocationClaimV2,
    expected: OracleAllocationV2,
) -> bool:
    return (
        claimed.status.value == expected.status.value
        and claimed.mechanism_version == expected.mechanism_version
        and claimed.objective_version == expected.objective_version
        and claimed.market_id == expected.market_id
        and claimed.buyer_policy_commitment_version == expected.buyer_policy_commitment_version
        and claimed.buyer_policy_commitment_sha256 == expected.buyer_policy_commitment_sha256
        and claimed.fulfilled_quantity == expected.fulfilled_quantity
        and _money_projection(claimed.total_payment) == _money_projection(expected.total_payment)
        and claimed.soft_preference_unit_score == expected.soft_preference_unit_score
        and claimed.winner_count == expected.winner_count
        and tuple(_claim_line_projection(line) for line in claimed.lines)
        == tuple(_oracle_line_projection(line) for line in expected.lines)
    )


def verify_allocation_certificate_v2(
    certificate: AllocationCertificateV2,
    *,
    trusted_signing_identities: tuple[MerchantSigningIdentityV2, ...],
) -> AllocationCertificateVerificationResultV2:
    """Verify only certificate-bound evidence; external receipt-log completeness is out of scope.

    The transcript is replayed in its bound tuple order. This pure verifier cannot establish that
    external receipt infrastructure omitted no submissions; a future trusted receipt log must bind
    that separate completeness property.
    """
    validated_certificate = _fresh_certificate(certificate)
    trusted_identities = _fresh_trusted_identities(trusted_signing_identities)

    policy: BuyerPolicyV2 = validated_certificate.buyer_policy
    if buyer_policy_v2_commitment(policy) != (validated_certificate.buyer_policy_commitment_sha256):
        return _failure(AllocationCertificateVerificationFailureCodeV2.POLICY_COMMITMENT_MISMATCH)
    if policy.mechanism_version != _MECHANISM_VERSION:
        return _failure(
            AllocationCertificateVerificationFailureCodeV2.UNSUPPORTED_MECHANISM_VERSION
        )
    if policy.objective_version != _OBJECTIVE_VERSION:
        return _failure(
            AllocationCertificateVerificationFailureCodeV2.UNSUPPORTED_OBJECTIVE_VERSION
        )

    trusted_by_merchant = {identity.merchant_id: identity for identity in trusted_identities}
    admitted_offer_ids: set[str] = set()
    admitted_merchant_ids: set[str] = set()
    admitted_offers: list[SignedMerchantOfferV2] = []
    previous_received_at = None

    for index, evidence in enumerate(validated_certificate.merchant_offer_evidence):
        if previous_received_at is not None and evidence.received_at < previous_received_at:
            return _failure(
                AllocationCertificateVerificationFailureCodeV2.TRANSCRIPT_REPLAY_MISMATCH,
                evidence_index=index,
            )
        previous_received_at = evidence.received_at

        decision = _independent_admission_decision(
            certificate=validated_certificate,
            evidence_index=index,
            trusted_by_merchant=trusted_by_merchant,
            admitted_offer_ids=admitted_offer_ids,
            admitted_merchant_ids=admitted_merchant_ids,
        )
        if decision is not evidence.admission_decision:
            return _failure(
                AllocationCertificateVerificationFailureCodeV2.TRANSCRIPT_REPLAY_MISMATCH,
                evidence_index=index,
            )
        if decision is MerchantOfferAdmissionDecisionV2.ADMITTED:
            offer = evidence.signed_offer.offer
            admitted_offer_ids.add(offer.offer_id)
            admitted_merchant_ids.add(offer.merchant_id)
            admitted_offers.append(evidence.signed_offer)

    try:
        expected = compute_oracle_allocation_v2(
            buyer_policy=policy,
            signed_offers=tuple(admitted_offers),
        )
    except OracleV2Error:
        return _failure(AllocationCertificateVerificationFailureCodeV2.ORACLE_REPLAY_FAILURE)

    if not _allocation_matches_oracle(validated_certificate.allocation, expected):
        return _failure(AllocationCertificateVerificationFailureCodeV2.ALLOCATION_MISMATCH)
    return AllocationCertificateVerificationResultV2(verified=True)
