import hashlib
from datetime import timedelta
from typing import Any, cast

import pytest

import clear_market.verification.v2.verifier as verifier_module
from clear_market.certificate.v2 import (
    AllocationCertificateV2,
    AllocationClaimLineV2,
    AllocationClaimStatusV2,
    AllocationClaimV2,
    MerchantOfferAdmissionDecisionV2,
    MerchantOfferEvidenceV2,
    canonical_allocation_certificate_v2_bytes,
    parse_canonical_allocation_certificate_v2,
)
from clear_market.commerce import (
    BuyerPolicyV2,
    MerchantSigningIdentityV2,
    SignedMerchantOfferV2,
    buyer_policy_v2_commitment,
)
from clear_market.commerce.offer_serialization import canonical_merchant_offer_v2_bytes
from clear_market.domain import Money
from clear_market.oracle.v2 import (
    OracleAllocationV2,
    OracleV2Error,
    OracleV2ErrorCode,
    compute_oracle_allocation_v2,
)
from clear_market.verification.v2 import (
    AllocationCertificateVerificationFailureCodeV2,
    AllocationCertificateVerificationResultV2,
    verify_allocation_certificate_v2,
)
from tests.certificate.v2.test_serialization import (
    _OFFER_DEADLINE,
    _RECEIVED_BEFORE_DEADLINE,
    _allocation,
    _catalog,
    _certificate,
    _evidence,
    _identity,
    _inventory,
    _offer,
    _offer_id,
    _policy,
    _private_key,
    _validated_copy,
)

_OTHER_MARKET_ID = "b1000000-0000-4000-8000-000000000002"
_OTHER_SKU_ID = "b6000000-0009-4000-8000-000000000001"
_OTHER_OFFER_ID = "b8000000-0009-4000-8000-000000000001"


class _CertificateSubclass(AllocationCertificateV2):
    pass


class _IdentitySubclass(MerchantSigningIdentityV2):
    pass


class _TupleSubclass(tuple):
    pass


def _trusted() -> tuple[MerchantSigningIdentityV2, ...]:
    return _identity(1), _identity(2)


def _claim_from_oracle(
    policy: BuyerPolicyV2,
    signed_offers: tuple[SignedMerchantOfferV2, ...],
) -> AllocationClaimV2:
    oracle = compute_oracle_allocation_v2(
        buyer_policy=policy,
        signed_offers=signed_offers,
    )
    return _claim_from_result(oracle)


def _claim_from_result(oracle: OracleAllocationV2) -> AllocationClaimV2:
    return AllocationClaimV2(
        market_id=oracle.market_id,
        buyer_policy_commitment_sha256=oracle.buyer_policy_commitment_sha256,
        status=AllocationClaimStatusV2(oracle.status.value),
        fulfilled_quantity=oracle.fulfilled_quantity,
        total_payment=oracle.total_payment,
        soft_preference_unit_score=oracle.soft_preference_unit_score,
        winner_count=oracle.winner_count,
        lines=tuple(
            AllocationClaimLineV2(
                offer_id=line.offer_id,
                merchant_id=line.merchant_id,
                sku_id=line.sku_id,
                allocated_quantity=line.allocated_quantity,
                unit_payment=line.unit_payment,
                line_payment=line.line_payment,
            )
            for line in oracle.lines
        ),
    )


def _zero_claim(policy: BuyerPolicyV2) -> AllocationClaimV2:
    return AllocationClaimV2(
        market_id=policy.market_spec.market_id,
        buyer_policy_commitment_sha256=buyer_policy_v2_commitment(policy),
        status=AllocationClaimStatusV2.INFEASIBLE,
        fulfilled_quantity=0,
        total_payment=Money(amount_paise=0),
        soft_preference_unit_score=0,
        winner_count=0,
        lines=(),
    )


def _certificate_for(
    *,
    policy: BuyerPolicyV2,
    evidence: tuple[MerchantOfferEvidenceV2, ...],
    admitted_offers: tuple[SignedMerchantOfferV2, ...],
) -> AllocationCertificateV2:
    base = _certificate()
    return AllocationCertificateV2(
        certificate_id=base.certificate_id,
        buyer_policy=policy,
        buyer_policy_commitment_sha256=buyer_policy_v2_commitment(policy),
        merchant_offer_evidence=evidence,
        allocation=_claim_from_oracle(policy, admitted_offers),
    )


def _assert_verified(
    certificate: AllocationCertificateV2,
    trusted: tuple[MerchantSigningIdentityV2, ...],
) -> AllocationCertificateVerificationResultV2:
    result = verify_allocation_certificate_v2(
        certificate,
        trusted_signing_identities=trusted,
    )
    assert result == AllocationCertificateVerificationResultV2(verified=True)
    return result


def _assert_failure(
    certificate: AllocationCertificateV2,
    trusted: tuple[MerchantSigningIdentityV2, ...],
    code: AllocationCertificateVerificationFailureCodeV2,
    *,
    index: int | None = None,
) -> None:
    result = verify_allocation_certificate_v2(
        certificate,
        trusted_signing_identities=trusted,
    )
    assert result.verified is False
    assert result.failure_code is code
    assert result.failed_evidence_index == index


def _simple_rejection_case(
    kind: str,
    *,
    stored: MerchantOfferAdmissionDecisionV2,
) -> tuple[
    BuyerPolicyV2,
    MerchantOfferEvidenceV2,
    tuple[MerchantSigningIdentityV2, ...],
]:
    policy = _policy()
    catalog = _catalog(1)
    inventory = _inventory(1)
    offer = _offer(1, policy=policy, catalog=catalog, inventory=inventory)
    trusted = _trusted()

    if kind == "wrong_market":
        offer = _validated_copy(offer, market_id=_OTHER_MARKET_ID)
        evidence = _evidence(1, policy=policy, offer=offer)
    elif kind == "wrong_policy_commitment":
        offer = _validated_copy(offer, buyer_policy_commitment_sha256="f" * 64)
        evidence = _evidence(1, policy=policy, offer=offer)
    elif kind == "ineligible_merchant":
        evidence = _evidence(3, policy=policy)
        trusted = (*trusted, _identity(3))
    elif kind == "missing_trust":
        evidence = _evidence(1, policy=policy)
        trusted = (_identity(2),)
    elif kind == "identity_mismatch":
        altered_identity = _identity(
            1,
            public_key_hex=_identity(2).ed25519_public_key_hex,
        )
        evidence = _evidence(1, policy=policy, identity=altered_identity)
    elif kind == "bad_signature":
        evidence = _evidence(1, policy=policy, signature_hex="0" * 128)
    elif kind == "catalog_commitment_mismatch":
        altered_catalog = _catalog(1, product_name="Altered catalog claim")
        evidence = _evidence(
            1,
            policy=policy,
            catalog=altered_catalog,
            inventory=inventory,
            offer=offer,
        )
    elif kind == "inventory_commitment_mismatch":
        altered_inventory = _inventory(1, quantity=3)
        evidence = _evidence(
            1,
            policy=policy,
            catalog=catalog,
            inventory=altered_inventory,
            offer=offer,
        )
    elif kind == "offer_source_mismatch":
        evidence = _evidence(
            1,
            policy=policy,
            catalog=_catalog(2),
            inventory=_inventory(2),
            offer=offer,
        )
    elif kind == "late":
        evidence = _evidence(
            1,
            policy=policy,
            received_at=_OFFER_DEADLINE + timedelta(microseconds=1),
        )
    else:
        raise AssertionError(kind)

    return policy, _validated_copy(evidence, admission_decision=stored), trusted


_SIMPLE_REJECTIONS = (
    "wrong_market",
    "wrong_policy_commitment",
    "ineligible_merchant",
    "missing_trust",
    "identity_mismatch",
    "bad_signature",
    "catalog_commitment_mismatch",
    "inventory_commitment_mismatch",
    "offer_source_mismatch",
    "late",
)


def test_frozen_golden_raw_bytes_parse_and_verify_end_to_end() -> None:
    data = canonical_allocation_certificate_v2_bytes(_certificate())
    assert len(data) == 14_454
    assert hashlib.sha256(data).hexdigest() == (
        "1676b8a9a0513c28933d2772ff39285d16efd3252422784095aea86714e43353"
    )
    parsed = parse_canonical_allocation_certificate_v2(data)
    _assert_verified(parsed, _trusted())


def test_valid_external_trust_order_is_semantically_irrelevant() -> None:
    certificate = _certificate()
    first = _assert_verified(certificate, _trusted())
    second = _assert_verified(certificate, tuple(reversed(_trusted())))
    assert first == second


def test_verifier_documents_bound_transcript_not_external_receipt_completeness() -> None:
    documentation = verify_allocation_certificate_v2.__doc__ or ""
    assert "certificate-bound evidence" in documentation
    assert "external receipt-log completeness is out of scope" in documentation
    assert "omitted no submissions" in documentation


def test_certificate_input_requires_fresh_exact_model() -> None:
    certificate = _certificate()
    subclass = _CertificateSubclass.model_construct(**certificate.__dict__)
    with pytest.raises(TypeError):
        verify_allocation_certificate_v2(
            subclass,
            trusted_signing_identities=_trusted(),
        )

    malformed = AllocationCertificateV2.model_construct(certificate_id=certificate.certificate_id)
    with pytest.raises(ValueError):
        verify_allocation_certificate_v2(
            malformed,
            trusted_signing_identities=_trusted(),
        )


def test_trusted_identity_input_requires_fresh_exact_unique_tuple() -> None:
    certificate = _certificate()
    with pytest.raises(TypeError):
        verify_allocation_certificate_v2(
            certificate,
            trusted_signing_identities=cast(Any, list(_trusted())),
        )
    with pytest.raises(TypeError):
        verify_allocation_certificate_v2(
            certificate,
            trusted_signing_identities=cast(Any, _TupleSubclass(_trusted())),
        )

    identity = _identity(1)
    subclass = _IdentitySubclass.model_construct(**identity.__dict__)
    with pytest.raises(TypeError):
        verify_allocation_certificate_v2(
            certificate,
            trusted_signing_identities=(subclass,),
        )

    malformed = MerchantSigningIdentityV2.model_construct(merchant_id=identity.merchant_id)
    with pytest.raises(ValueError):
        verify_allocation_certificate_v2(
            certificate,
            trusted_signing_identities=(malformed,),
        )

    with pytest.raises(ValueError):
        verify_allocation_certificate_v2(
            certificate,
            trusted_signing_identities=(identity, identity),
        )


def test_embedded_key_cannot_authenticate_itself() -> None:
    policy = _policy()
    catalog = _catalog(1)
    inventory = _inventory(1)
    offer = _offer(1, policy=policy, catalog=catalog, inventory=inventory)
    attacker_identity = _identity(
        1,
        public_key_hex=_identity(2).ed25519_public_key_hex,
    )
    attacker_signature = _private_key(2).sign(canonical_merchant_offer_v2_bytes(offer)).hex()
    evidence = _evidence(
        1,
        policy=policy,
        identity=attacker_identity,
        catalog=catalog,
        inventory=inventory,
        offer=offer,
        signature_hex=attacker_signature,
    )
    certificate = _certificate_for(
        policy=policy,
        evidence=(evidence,),
        admitted_offers=(),
    )
    _assert_failure(
        certificate,
        (_identity(1),),
        AllocationCertificateVerificationFailureCodeV2.TRANSCRIPT_REPLAY_MISMATCH,
        index=0,
    )


def test_altered_external_trusted_key_causes_transcript_mismatch() -> None:
    altered = _identity(1, public_key_hex=_identity(2).ed25519_public_key_hex)
    _assert_failure(
        _certificate(),
        (altered, _identity(2)),
        AllocationCertificateVerificationFailureCodeV2.TRANSCRIPT_REPLAY_MISMATCH,
        index=0,
    )


@pytest.mark.parametrize("kind", _SIMPLE_REJECTIONS)
def test_stored_admitted_never_overrides_independent_rejection(kind: str) -> None:
    policy, evidence, trusted = _simple_rejection_case(
        kind,
        stored=MerchantOfferAdmissionDecisionV2.ADMITTED,
    )
    certificate = _certificate_for(
        policy=policy,
        evidence=(evidence,),
        admitted_offers=(),
    )
    _assert_failure(
        certificate,
        trusted,
        AllocationCertificateVerificationFailureCodeV2.TRANSCRIPT_REPLAY_MISMATCH,
        index=0,
    )


@pytest.mark.parametrize("kind", _SIMPLE_REJECTIONS)
def test_stored_rejected_matches_each_independent_rejection(kind: str) -> None:
    policy, evidence, trusted = _simple_rejection_case(
        kind,
        stored=MerchantOfferAdmissionDecisionV2.REJECTED,
    )
    certificate = _certificate_for(
        policy=policy,
        evidence=(evidence,),
        admitted_offers=(),
    )
    _assert_verified(certificate, trusted)


@pytest.mark.parametrize(
    "kind",
    [
        "wrong_market",
        "wrong_policy_commitment",
        "ineligible_merchant",
        "missing_trust",
        "identity_mismatch",
    ],
)
def test_earlier_binding_rejections_do_not_reach_authentication(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy, evidence, trusted = _simple_rejection_case(
        kind,
        stored=MerchantOfferAdmissionDecisionV2.REJECTED,
    )

    def unexpected_authentication(**_kwargs: object) -> SignedMerchantOfferV2:
        raise AssertionError("authentication must not run before earlier binding checks pass")

    monkeypatch.setattr(
        verifier_module,
        "verify_canonical_signed_merchant_offer_v2",
        unexpected_authentication,
    )
    certificate = _certificate_for(
        policy=policy,
        evidence=(evidence,),
        admitted_offers=(),
    )
    _assert_verified(certificate, trusted)


def test_rejected_invalid_attempt_does_not_consume_offer_or_merchant_slot() -> None:
    policy = _policy()
    invalid = _evidence(
        1,
        policy=policy,
        signature_hex="0" * 128,
        admission_decision=MerchantOfferAdmissionDecisionV2.REJECTED,
    )
    valid = _evidence(
        1,
        policy=policy,
        received_at=_OFFER_DEADLINE,
    )
    certificate = _certificate_for(
        policy=policy,
        evidence=(invalid, valid),
        admitted_offers=(valid.signed_offer,),
    )
    _assert_verified(certificate, (_identity(1),))


def test_first_admitted_then_same_offer_id_is_independently_rejected() -> None:
    policy = _policy()
    admitted = _evidence(1, policy=policy)
    replay = _validated_copy(
        admitted,
        received_at=_OFFER_DEADLINE,
        admission_decision=MerchantOfferAdmissionDecisionV2.REJECTED,
    )
    certificate = _certificate_for(
        policy=policy,
        evidence=(admitted, replay),
        admitted_offers=(admitted.signed_offer,),
    )
    _assert_verified(certificate, (_identity(1),))

    false_declaration = _validated_copy(
        replay,
        admission_decision=MerchantOfferAdmissionDecisionV2.ADMITTED,
    )
    false_certificate = _validated_copy(
        certificate,
        merchant_offer_evidence=(admitted, false_declaration),
    )
    _assert_failure(
        false_certificate,
        (_identity(1),),
        AllocationCertificateVerificationFailureCodeV2.TRANSCRIPT_REPLAY_MISMATCH,
        index=1,
    )


def test_first_admitted_then_different_offer_same_merchant_is_rejected() -> None:
    policy = _policy()
    admitted = _evidence(1, policy=policy)
    catalog = _catalog(1)
    inventory = _inventory(1)
    new_offer = _offer(
        1,
        policy=policy,
        catalog=catalog,
        inventory=inventory,
        offer_id=_offer_id(3),
    )
    duplicate_merchant = _evidence(
        1,
        policy=policy,
        catalog=catalog,
        inventory=inventory,
        offer=new_offer,
        received_at=_OFFER_DEADLINE,
        admission_decision=MerchantOfferAdmissionDecisionV2.REJECTED,
    )
    certificate = _certificate_for(
        policy=policy,
        evidence=(admitted, duplicate_merchant),
        admitted_offers=(admitted.signed_offer,),
    )
    _assert_verified(certificate, (_identity(1),))

    false_declaration = _validated_copy(
        duplicate_merchant,
        admission_decision=MerchantOfferAdmissionDecisionV2.ADMITTED,
    )
    _assert_failure(
        _validated_copy(
            certificate,
            merchant_offer_evidence=(admitted, false_declaration),
        ),
        (_identity(1),),
        AllocationCertificateVerificationFailureCodeV2.TRANSCRIPT_REPLAY_MISMATCH,
        index=1,
    )


def test_equal_receipt_timestamps_preserve_tuple_replay_order() -> None:
    policy = _policy()
    invalid = _evidence(
        1,
        policy=policy,
        signature_hex="0" * 128,
        received_at=_RECEIVED_BEFORE_DEADLINE,
        admission_decision=MerchantOfferAdmissionDecisionV2.REJECTED,
    )
    valid = _evidence(
        1,
        policy=policy,
        received_at=_RECEIVED_BEFORE_DEADLINE,
    )
    certificate = _certificate_for(
        policy=policy,
        evidence=(invalid, valid),
        admitted_offers=(valid.signed_offer,),
    )
    _assert_verified(certificate, (_identity(1),))


def test_decreasing_receipt_time_fails_at_current_index_before_record_replay() -> None:
    policy = _policy()
    first = _evidence(1, policy=policy, received_at=_OFFER_DEADLINE)
    second = _evidence(
        2,
        policy=policy,
        received_at=_RECEIVED_BEFORE_DEADLINE,
        admission_decision=MerchantOfferAdmissionDecisionV2.REJECTED,
    )
    certificate = _certificate_for(
        policy=policy,
        evidence=(first, second),
        admitted_offers=(first.signed_offer,),
    )
    _assert_failure(
        certificate,
        _trusted(),
        AllocationCertificateVerificationFailureCodeV2.TRANSCRIPT_REPLAY_MISMATCH,
        index=1,
    )


@pytest.mark.parametrize(
    ("offset", "decision"),
    [
        (-1, MerchantOfferAdmissionDecisionV2.ADMITTED),
        (0, MerchantOfferAdmissionDecisionV2.ADMITTED),
        (1, MerchantOfferAdmissionDecisionV2.REJECTED),
    ],
)
def test_inclusive_receipt_deadline_boundary(
    offset: int,
    decision: MerchantOfferAdmissionDecisionV2,
) -> None:
    policy = _policy()
    evidence = _evidence(
        1,
        policy=policy,
        received_at=_OFFER_DEADLINE + timedelta(microseconds=offset),
        admission_decision=decision,
    )
    admitted = (
        (evidence.signed_offer,) if decision is MerchantOfferAdmissionDecisionV2.ADMITTED else ()
    )
    certificate = _certificate_for(
        policy=policy,
        evidence=(evidence,),
        admitted_offers=admitted,
    )
    _assert_verified(certificate, (_identity(1),))


def test_rejected_one_paise_offer_never_reaches_independent_oracle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    certificate = _certificate()
    captured: list[tuple[SignedMerchantOfferV2, ...]] = []
    real_oracle = compute_oracle_allocation_v2

    def recording_oracle(
        *,
        buyer_policy: BuyerPolicyV2,
        signed_offers: tuple[SignedMerchantOfferV2, ...],
    ) -> OracleAllocationV2:
        captured.append(signed_offers)
        return real_oracle(buyer_policy=buyer_policy, signed_offers=signed_offers)

    monkeypatch.setattr(verifier_module, "compute_oracle_allocation_v2", recording_oracle)
    _assert_verified(certificate, _trusted())
    assert len(captured) == 1
    assert captured[0] == tuple(
        evidence.signed_offer for evidence in certificate.merchant_offer_evidence[:2]
    )
    assert _offer_id(3) not in {signed.offer.offer_id for signed in captured[0]}


def test_top_level_failure_precedence_is_policy_then_versions_then_transcript() -> None:
    base = _certificate()
    bad_signature = _validated_copy(
        base.merchant_offer_evidence[0].signed_offer,
        signature_hex="0" * 128,
    )
    bad_evidence = _validated_copy(
        base.merchant_offer_evidence[0],
        signed_offer=bad_signature,
    )
    evidence = (bad_evidence, *base.merchant_offer_evidence[1:])

    wrong_commitment = _validated_copy(
        base,
        buyer_policy_commitment_sha256="f" * 64,
        merchant_offer_evidence=evidence,
    )
    _assert_failure(
        wrong_commitment,
        _trusted(),
        AllocationCertificateVerificationFailureCodeV2.POLICY_COMMITMENT_MISMATCH,
    )

    for field, expected in (
        (
            "mechanism_version",
            AllocationCertificateVerificationFailureCodeV2.UNSUPPORTED_MECHANISM_VERSION,
        ),
        (
            "objective_version",
            AllocationCertificateVerificationFailureCodeV2.UNSUPPORTED_OBJECTIVE_VERSION,
        ),
    ):
        policy = _validated_copy(base.buyer_policy, **{field: "unsupported-v2"})
        certificate = AllocationCertificateV2(
            certificate_id=base.certificate_id,
            buyer_policy=policy,
            buyer_policy_commitment_sha256=buyer_policy_v2_commitment(policy),
            merchant_offer_evidence=evidence,
            allocation=_zero_claim(policy),
        )
        _assert_failure(certificate, _trusted(), expected)


def _tampered_allocation(kind: str) -> AllocationClaimV2:
    claim = _allocation()
    first, second = claim.lines
    if kind == "market":
        return _validated_copy(claim, market_id=_OTHER_MARKET_ID)
    if kind == "commitment":
        return _validated_copy(claim, buyer_policy_commitment_sha256="f" * 64)
    if kind == "fulfilled":
        changed = _validated_copy(
            first,
            allocated_quantity=2,
            line_payment=Money(amount_paise=1_000),
        )
        return _validated_copy(
            claim,
            fulfilled_quantity=4,
            total_payment=Money(amount_paise=2_200),
            lines=(changed, second),
        )
    if kind == "payment":
        changed = _validated_copy(
            first,
            unit_payment=Money(amount_paise=501),
            line_payment=Money(amount_paise=1_503),
        )
        return _validated_copy(
            claim,
            total_payment=Money(amount_paise=2_703),
            lines=(changed, second),
        )
    if kind == "soft_score":
        return _validated_copy(claim, soft_preference_unit_score=1)
    if kind == "winner_allocation":
        return _validated_copy(
            claim,
            fulfilled_quantity=3,
            total_payment=Money(amount_paise=1_500),
            winner_count=1,
            lines=(first,),
        )
    if kind == "offer_id":
        changed = _validated_copy(first, offer_id=_OTHER_OFFER_ID)
        return _validated_copy(claim, lines=(changed, second))
    if kind == "sku_id":
        changed = _validated_copy(first, sku_id=_OTHER_SKU_ID)
        return _validated_copy(claim, lines=(changed, second))
    if kind == "line_quantity":
        changed_first = _validated_copy(
            first,
            allocated_quantity=2,
            line_payment=Money(amount_paise=1_000),
        )
        changed_second = _validated_copy(
            second,
            allocated_quantity=3,
            line_payment=Money(amount_paise=1_800),
        )
        return _validated_copy(
            claim,
            total_payment=Money(amount_paise=2_800),
            lines=(changed_first, changed_second),
        )
    raise AssertionError(kind)


@pytest.mark.parametrize(
    "kind",
    [
        "market",
        "commitment",
        "fulfilled",
        "payment",
        "soft_score",
        "winner_allocation",
        "offer_id",
        "sku_id",
        "line_quantity",
    ],
)
def test_structurally_coherent_allocation_tampering_is_rejected(kind: str) -> None:
    certificate = _validated_copy(_certificate(), allocation=_tampered_allocation(kind))
    _assert_failure(
        certificate,
        _trusted(),
        AllocationCertificateVerificationFailureCodeV2.ALLOCATION_MISMATCH,
    )


def test_oracle_error_fails_closed_without_production_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_oracle(**_kwargs: object) -> OracleAllocationV2:
        raise OracleV2Error(OracleV2ErrorCode.INVALID_SIGNED_OFFER)

    monkeypatch.setattr(verifier_module, "compute_oracle_allocation_v2", failing_oracle)
    _assert_failure(
        _certificate(),
        _trusted(),
        AllocationCertificateVerificationFailureCodeV2.ORACLE_REPLAY_FAILURE,
    )
