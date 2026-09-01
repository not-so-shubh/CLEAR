import pytest
from hypothesis import assume, given, settings

from clear_market.certificate import (
    AllocationCertificate,
    AllocationCertificateParseError,
    AllocationCertificateParseFailureCode,
    allocation_certificate_digest,
    canonical_allocation_certificate_bytes,
    parse_canonical_allocation_certificate,
)
from clear_market.domain import Money
from clear_market.lifecycle import admit_signed_bid
from clear_market.verification import (
    CertificateVerificationFailureCode,
    verify_allocation_certificate,
)
from tests.properties.certificate_helpers import (
    build_authenticated_transcript,
    build_certificate_from_decisions,
    build_property_certificate_fixture,
)
from tests.properties.market_strategies import PropertyMarketCase, property_market_cases

_LOWERCASE_HEX_DIGITS = frozenset("0123456789abcdef")


def _assert_verified(certificate: AllocationCertificate) -> None:
    result = verify_allocation_certificate(certificate)
    assert result.verified is True
    assert result.failure_code is None
    assert result.failed_admission_index is None


@pytest.mark.parametrize("value", [True, False, 1.0, "1", None])
def test_certificate_variant_requires_exact_integer(value: object) -> None:
    case = PropertyMarketCase(
        case_tag=0,
        seller_count=2,
        requested_quantity=1,
        reserve_unit_price_paise=0,
        participates=(False, False),
        quantity_available=(0, 0),
        unit_price_paise=(0, 0),
    )

    with pytest.raises(TypeError):
        build_property_certificate_fixture(case, certificate_variant=value)


@pytest.mark.parametrize("value", [0, 3])
def test_certificate_variant_is_limited_to_one_or_two(value: int) -> None:
    case = PropertyMarketCase(
        case_tag=0,
        seller_count=2,
        requested_quantity=1,
        reserve_unit_price_paise=0,
        participates=(False, False),
        quantity_available=(0, 0),
        unit_price_paise=(0, 0),
    )

    with pytest.raises(ValueError):
        build_property_certificate_fixture(case, certificate_variant=value)


@given(property_market_cases())
@settings(max_examples=250, derandomize=True, deadline=None)
def test_valid_certificates_roundtrip_and_verify_deterministically(
    case: PropertyMarketCase,
) -> None:
    fixture = build_property_certificate_fixture(case, certificate_variant=1)
    policy_before = fixture.policy
    attempts_before = fixture.attempts
    decisions_before = fixture.decisions
    certificate = fixture.certificate

    assert all(decision.rejection_code is None for decision in fixture.decisions)
    rebuilt = build_certificate_from_decisions(
        case_tag=case.case_tag,
        certificate_variant=1,
        policy=fixture.policy,
        decisions=fixture.decisions,
    )
    assert rebuilt == certificate
    assert fixture.policy == policy_before
    assert fixture.attempts == attempts_before
    assert fixture.decisions == decisions_before

    canonical_first = canonical_allocation_certificate_bytes(certificate)
    canonical_second = canonical_allocation_certificate_bytes(certificate)
    assert canonical_first == canonical_second

    digest_first = allocation_certificate_digest(certificate)
    digest_second = allocation_certificate_digest(certificate)
    assert digest_first == digest_second
    assert type(digest_first) is str
    assert len(digest_first) == 64
    assert set(digest_first) <= _LOWERCASE_HEX_DIGITS

    parsed = parse_canonical_allocation_certificate(canonical_first)
    assert parsed == certificate
    assert canonical_allocation_certificate_bytes(parsed) == canonical_first
    assert allocation_certificate_digest(parsed) == digest_first

    original_verification_first = verify_allocation_certificate(certificate)
    original_verification_second = verify_allocation_certificate(certificate)
    parsed_verification = verify_allocation_certificate(parsed)
    assert original_verification_first == original_verification_second
    assert original_verification_first.verified is True
    assert original_verification_first.failure_code is None
    assert original_verification_first.failed_admission_index is None
    assert parsed_verification.verified is True
    assert parsed_verification.failure_code is None
    assert parsed_verification.failed_admission_index is None

    certificate_variant_two = build_certificate_from_decisions(
        case_tag=case.case_tag,
        certificate_variant=2,
        policy=fixture.policy,
        decisions=fixture.decisions,
    )
    assert certificate_variant_two != certificate
    assert certificate_variant_two.certificate_id != certificate.certificate_id
    assert certificate_variant_two.allocation == certificate.allocation
    _assert_verified(certificate_variant_two)
    assert canonical_allocation_certificate_bytes(certificate_variant_two) != canonical_first
    assert allocation_certificate_digest(certificate_variant_two) != digest_first

    assert fixture.policy == policy_before
    assert fixture.attempts == attempts_before
    assert fixture.decisions == decisions_before
    assert canonical_allocation_certificate_bytes(certificate) == canonical_first
    assert canonical_allocation_certificate_bytes(parsed) == canonical_first


@given(property_market_cases())
@settings(max_examples=100, derandomize=True, deadline=None)
def test_trailing_newline_is_always_noncanonical(case: PropertyMarketCase) -> None:
    certificate = build_property_certificate_fixture(case).certificate
    canonical = canonical_allocation_certificate_bytes(certificate)

    with pytest.raises(AllocationCertificateParseError) as caught:
        parse_canonical_allocation_certificate(canonical + b"\n")

    assert caught.value.code is AllocationCertificateParseFailureCode.NON_CANONICAL


@given(property_market_cases())
@settings(max_examples=100, derandomize=True, deadline=None)
def test_policy_commitment_tamper_has_frozen_failure_precedence(case: PropertyMarketCase) -> None:
    certificate = build_property_certificate_fixture(case).certificate
    replacement = "0" * 64 if certificate.buyer_policy_commitment != "0" * 64 else "1" * 64
    tampered = certificate.model_copy(update={"buyer_policy_commitment": replacement})

    result = verify_allocation_certificate(tampered)

    assert result.verified is False
    assert result.failure_code is CertificateVerificationFailureCode.POLICY_COMMITMENT_MISMATCH
    assert result.failed_admission_index is None


@given(property_market_cases())
@settings(max_examples=100, derandomize=True, deadline=None)
def test_accepted_signature_tamper_fails_transcript_replay(case: PropertyMarketCase) -> None:
    certificate = build_property_certificate_fixture(case).certificate
    assume(bool(certificate.admission_decisions))
    first = certificate.admission_decisions[0]
    replacement = "0" * 128 if first.signed_bid.signature_hex != "0" * 128 else "1" * 128
    tampered_signed_bid = first.signed_bid.model_copy(update={"signature_hex": replacement})
    tampered_first = first.model_copy(update={"signed_bid": tampered_signed_bid})
    tampered = certificate.model_copy(
        update={
            "admission_decisions": (tampered_first, *certificate.admission_decisions[1:]),
        }
    )

    result = verify_allocation_certificate(tampered)

    assert result.verified is False
    assert result.failure_code is CertificateVerificationFailureCode.TRANSCRIPT_REPLAY_MISMATCH
    assert result.failed_admission_index == 0


@given(property_market_cases())
@settings(max_examples=100, derandomize=True, deadline=None)
def test_allocation_total_tamper_fails_independent_verification(case: PropertyMarketCase) -> None:
    certificate = build_property_certificate_fixture(case).certificate
    assume(certificate.allocation.total_payment is not None)
    original_total = certificate.allocation.total_payment.amount_paise
    tampered_allocation = certificate.allocation.model_copy(
        update={"total_payment": Money(amount_paise=original_total + 1)}
    )
    tampered = certificate.model_copy(update={"allocation": tampered_allocation})

    result = verify_allocation_certificate(tampered)

    assert result.verified is False
    assert result.failure_code is CertificateVerificationFailureCode.ALLOCATION_MISMATCH
    assert result.failed_admission_index is None


@given(property_market_cases())
@settings(max_examples=100, derandomize=True, deadline=None)
def test_genuine_rejected_evidence_roundtrips_and_verifies(case: PropertyMarketCase) -> None:
    policy, attempts, state, decisions = build_authenticated_transcript(case)
    assume(bool(attempts))
    first_attempt = attempts[0]
    replay_decision = admit_signed_bid(
        state,
        first_attempt.signed_bid,
        first_attempt.context,
    )
    assert replay_decision.rejection_code is not None
    extended_decisions = (*decisions, replay_decision)
    certificate = build_certificate_from_decisions(
        case_tag=case.case_tag,
        certificate_variant=2,
        policy=policy,
        decisions=extended_decisions,
    )
    assert certificate.admission_decisions[-1].rejection_code is not None

    canonical = canonical_allocation_certificate_bytes(certificate)
    parsed = parse_canonical_allocation_certificate(canonical)
    result = verify_allocation_certificate(parsed)

    assert parsed == certificate
    assert result.verified is True
    assert result.failure_code is None
    assert result.failed_admission_index is None
