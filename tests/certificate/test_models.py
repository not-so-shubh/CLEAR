from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

import clear_market.certificate as certificate
from clear_market.certificate import ALLOCATION_CERTIFICATE_VERSION, AllocationCertificate
from clear_market.crypto import buyer_policy_commitment
from clear_market.domain import (
    BuyerPolicy,
    MarketSpec,
    MerchantBid,
    MerchantIdentity,
    Money,
    SignedMerchantBid,
)
from clear_market.lifecycle import AdmissionContext, AdmissionDecision, AdmissionRejectionCode
from clear_market.mechanism import Allocation, AllocationStatus

_MARKET_ID = "10000000-0000-4000-8000-000000000001"
_OTHER_MARKET_ID = "10000000-0000-4000-8000-000000000002"
_BUYER_ID = "20000000-0000-4000-8000-000000000001"
_MERCHANT_IDS = (
    "30000000-0000-4000-8000-000000000001",
    "30000000-0000-4000-8000-000000000002",
)
_BID_IDS = (
    "40000000-0000-4000-8000-000000000001",
    "40000000-0000-4000-8000-000000000002",
)
_CERTIFICATE_ID = "50000000-0000-4000-8000-000000000001"
_DEADLINE = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 9, 1, 11, 59, 58, tzinfo=UTC)
_RECEIVED_AT = datetime(2026, 9, 1, 11, 59, 59, tzinfo=UTC)


def _policy() -> BuyerPolicy:
    return BuyerPolicy(
        market_spec=MarketSpec(
            market_id=_MARKET_ID,
            buyer_id=_BUYER_ID,
            requested_quantity=4,
        ),
        max_total_payment=Money(amount_paise=500),
        reserve_unit_price=Money(amount_paise=125),
        eligible_merchants=(
            MerchantIdentity(
                merchant_id=_MERCHANT_IDS[0],
                ed25519_public_key_hex="0" * 64,
            ),
            MerchantIdentity(
                merchant_id=_MERCHANT_IDS[1],
                ed25519_public_key_hex="1" * 64,
            ),
        ),
        bid_deadline=_DEADLINE,
    )


def _different_commitment(commitment: str) -> str:
    replacement = "0" if commitment[0] != "0" else "1"
    return f"{replacement}{commitment[1:]}"


def _allocation(
    policy: BuyerPolicy,
    *,
    market_id: str | None = None,
    commitment: str | None = None,
) -> Allocation:
    return Allocation(
        market_id=policy.market_spec.market_id if market_id is None else market_id,
        buyer_policy_commitment=(
            buyer_policy_commitment(policy) if commitment is None else commitment
        ),
        mechanism_version=policy.mechanism_version,
        status=AllocationStatus.INFEASIBLE,
    )


def _decision(policy: BuyerPolicy, merchant_index: int) -> AdmissionDecision:
    bid = MerchantBid(
        bid_id=_BID_IDS[merchant_index],
        market_id=policy.market_spec.market_id,
        merchant_id=_MERCHANT_IDS[merchant_index],
        buyer_policy_commitment=buyer_policy_commitment(policy),
        quantity_available=4,
        unit_price_paise=100 + merchant_index,
        submitted_at=_SUBMITTED_AT,
    )
    return AdmissionDecision(
        signed_bid=SignedMerchantBid(bid=bid, signature_hex=str(merchant_index) * 128),
        context=AdmissionContext(received_at=_RECEIVED_AT),
        rejection_code=AdmissionRejectionCode.INVALID_SIGNATURE,
    )


def _certificate(**overrides: object) -> AllocationCertificate:
    policy = _policy()
    fields: dict[str, object] = {
        "certificate_id": _CERTIFICATE_ID,
        "buyer_policy": policy,
        "buyer_policy_commitment": buyer_policy_commitment(policy),
        "admission_decisions": (),
        "allocation": _allocation(policy),
    }
    fields.update(overrides)
    return AllocationCertificate(**fields)


def test_certificate_public_api_is_exact() -> None:
    assert certificate.__all__ == (
        "ALLOCATION_CERTIFICATE_DIGEST_VERSION",
        "ALLOCATION_CERTIFICATE_VERSION",
        "AllocationCertificate",
        "AllocationCertificateParseError",
        "AllocationCertificateParseFailureCode",
        "MAX_CANONICAL_CERTIFICATE_BYTES",
        "allocation_certificate_digest",
        "build_allocation_certificate",
        "canonical_allocation_certificate_bytes",
        "parse_canonical_allocation_certificate",
    )


def test_allocation_certificate_version_is_exact() -> None:
    assert ALLOCATION_CERTIFICATE_VERSION == "allocation-certificate-v1"


def test_allocation_certificate_has_exact_fields_and_protocol_defaults() -> None:
    allocation_certificate = _certificate()

    assert tuple(AllocationCertificate.model_fields) == (
        "schema_version",
        "certificate_version",
        "certificate_id",
        "canonicalization_version",
        "buyer_policy_commitment_version",
        "merchant_bid_signature_version",
        "buyer_policy",
        "buyer_policy_commitment",
        "admission_decisions",
        "allocation",
    )
    assert allocation_certificate.schema_version == "1"
    assert allocation_certificate.certificate_version == "allocation-certificate-v1"
    assert allocation_certificate.canonicalization_version == "clear-json-v1"
    assert allocation_certificate.buyer_policy_commitment_version == "sha256-clear-json-v1"
    assert allocation_certificate.merchant_bid_signature_version == "ed25519-raw-clear-json-v1"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", "2"),
        ("certificate_version", "allocation-certificate-v2"),
        ("canonicalization_version", "clear-json-v2"),
        ("buyer_policy_commitment_version", "sha256-clear-json-v2"),
        ("merchant_bid_signature_version", "ed25519-raw-clear-json-v2"),
    ],
)
def test_allocation_certificate_rejects_unsupported_protocol_values(
    field: str,
    value: str,
) -> None:
    with pytest.raises(ValidationError):
        _certificate(**{field: value})


def test_valid_allocation_certificate_is_accepted() -> None:
    allocation_certificate = _certificate()

    assert allocation_certificate.certificate_id == _CERTIFICATE_ID
    assert allocation_certificate.admission_decisions == ()
    assert allocation_certificate.allocation.status is AllocationStatus.INFEASIBLE


def test_allocation_certificate_is_frozen() -> None:
    allocation_certificate = _certificate()

    with pytest.raises(ValidationError):
        allocation_certificate.certificate_id = "50000000-0000-4000-8000-000000000002"


def test_allocation_certificate_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        _certificate(unexpected=True)


@pytest.mark.parametrize(
    "certificate_id",
    [
        "50000000-0000-4000-8000-00000000000A",
        "50000000000040008000000000000001",
        "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        UUID(_CERTIFICATE_ID),
        _CERTIFICATE_ID.encode(),
        1,
        None,
    ],
)
def test_allocation_certificate_rejects_noncanonical_uuid4_id(certificate_id: object) -> None:
    with pytest.raises(ValidationError):
        _certificate(certificate_id=certificate_id)


@pytest.mark.parametrize(
    "commitment",
    [
        "a" * 63,
        "a" * 65,
        "A" * 64,
        f" {'a' * 64}",
        f"{'a' * 64} ",
        f"0x{'a' * 64}",
        f"sha256:{'a' * 64}",
        f"g{'a' * 63}",
        b"a" * 64,
        1,
        None,
    ],
)
def test_allocation_certificate_rejects_invalid_commitment_representation(
    commitment: object,
) -> None:
    with pytest.raises(ValidationError):
        _certificate(buyer_policy_commitment=commitment)


def test_allocation_certificate_rejects_policy_commitment_mismatch() -> None:
    policy = _policy()
    commitment = buyer_policy_commitment(policy)

    with pytest.raises(ValidationError):
        _certificate(
            buyer_policy=policy,
            buyer_policy_commitment=_different_commitment(commitment),
            allocation=_allocation(policy),
        )


def test_allocation_certificate_rejects_allocation_market_mismatch() -> None:
    policy = _policy()

    with pytest.raises(ValidationError):
        _certificate(
            buyer_policy=policy,
            buyer_policy_commitment=buyer_policy_commitment(policy),
            allocation=_allocation(policy, market_id=_OTHER_MARKET_ID),
        )


def test_allocation_certificate_rejects_allocation_commitment_mismatch() -> None:
    policy = _policy()
    commitment = buyer_policy_commitment(policy)

    with pytest.raises(ValidationError):
        _certificate(
            buyer_policy=policy,
            buyer_policy_commitment=commitment,
            allocation=_allocation(policy, commitment=_different_commitment(commitment)),
        )


def test_allocation_certificate_rejects_allocation_commitment_version_mismatch() -> None:
    policy = _policy()
    allocation = _allocation(policy).model_copy(
        update={"buyer_policy_commitment_version": "sha256-clear-json-v2"}
    )

    with pytest.raises(ValidationError):
        _certificate(
            buyer_policy=policy,
            buyer_policy_commitment=buyer_policy_commitment(policy),
            allocation=allocation,
        )


def test_allocation_certificate_rejects_allocation_mechanism_mismatch() -> None:
    policy = _policy()
    allocation = _allocation(policy).model_copy(
        update={"mechanism_version": "reverse_first_price_v1"}
    )

    with pytest.raises(ValidationError):
        _certificate(
            buyer_policy=policy,
            buyer_policy_commitment=buyer_policy_commitment(policy),
            allocation=allocation,
        )


def test_allocation_certificate_preserves_admission_decision_order() -> None:
    policy = _policy()
    first = _decision(policy, 0)
    second = _decision(policy, 1)
    supplied = (second, first)

    allocation_certificate = _certificate(
        buyer_policy=policy,
        buyer_policy_commitment=buyer_policy_commitment(policy),
        admission_decisions=supplied,
        allocation=_allocation(policy),
    )

    assert allocation_certificate.admission_decisions == supplied
    assert allocation_certificate.admission_decisions[0] is second
    assert allocation_certificate.admission_decisions[1] is first


def test_allocation_certificate_allows_empty_admission_transcript() -> None:
    assert _certificate(admission_decisions=()).admission_decisions == ()
