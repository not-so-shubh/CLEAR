import hashlib
import json
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from clear_market.certificate import (
    AllocationCertificate,
    allocation_certificate_digest,
    build_allocation_certificate,
    canonical_allocation_certificate_bytes,
)
from clear_market.crypto import buyer_policy_commitment, sign_merchant_bid
from clear_market.domain import (
    BuyerPolicy,
    MarketSpec,
    MerchantBid,
    MerchantIdentity,
    Money,
    SignedMerchantBid,
)
from clear_market.lifecycle import (
    AdmissionContext,
    AdmissionRejectionCode,
    AdmissionState,
    admit_signed_bid,
)

# TEST ONLY — NEVER PRODUCTION KEY MATERIAL.
_PRIVATE_KEY_SEEDS = (bytes([1]) * 32, bytes([2]) * 32)
_PUBLIC_KEY_HEX = (
    "8a88e3dd7409f195fd52db2d3cba5d72ca6709bf1d94121bf3748801b40f6f5c",
    "8139770ea87d175f56a35466c34c7ecccb8d8a91b4ee37a25df60f5b8fc9b394",
)
_MARKET_ID = "10000000-0000-4000-8000-000000000001"
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
_POLICY_COMMITMENT = "dcb9511bf596d70544da40d436fd1abe009392987cdfcd87d448388ad07147cf"
_MERCHANT_B_SIGNATURE = (
    "137ad69177ccde4cd461fb6faa2d6aab3266870d5254a67575bdcc160c900cae"
    "1430dac52e2dbc211ed3fe0ddac917d219b88428b5674f1cd298a2a71f344904"
)
_GOLDEN_CERTIFICATE_SHA256 = "53a6342dd1d719bea7b15dd4c5ae66a392cf2a862febc49a16f233ca632d1796"
_GOLDEN_CERTIFICATE_JSON = (
    '{"canonicalization_version":"clear-json-v1","payload":{"admission_decisions":['
    '{"context":{"received_at":"2026-09-01T11:59:59.000000Z"},'
    '"rejection_code":"invalid_signature","signed_bid":{"bid":{'
    '"bid_id":"40000000-0000-4000-8000-000000000001",'
    '"buyer_policy_commitment":"dcb9511bf596d70544da40d436fd1abe009392987cdfcd87d448388ad07147cf",'
    '"buyer_policy_commitment_version":"sha256-clear-json-v1","currency":"INR",'
    '"market_id":"10000000-0000-4000-8000-000000000001",'
    '"merchant_id":"30000000-0000-4000-8000-000000000001",'
    '"quantity_available":4,"schema_version":"1",'
    '"submitted_at":"2026-09-01T11:59:58.000000Z","unit_price_paise":1},'
    '"signature_hex":"0000000000000000000000000000000000000000000000000000000000000000'
    '0000000000000000000000000000000000000000000000000000000000000000"}},'
    '{"context":{"received_at":"2026-09-01T11:59:59.000000Z"},'
    '"rejection_code":null,"signed_bid":{"bid":{'
    '"bid_id":"40000000-0000-4000-8000-000000000002",'
    '"buyer_policy_commitment":"dcb9511bf596d70544da40d436fd1abe009392987cdfcd87d448388ad07147cf",'
    '"buyer_policy_commitment_version":"sha256-clear-json-v1","currency":"INR",'
    '"market_id":"10000000-0000-4000-8000-000000000001",'
    '"merchant_id":"30000000-0000-4000-8000-000000000002",'
    '"quantity_available":4,"schema_version":"1",'
    '"submitted_at":"2026-09-01T11:59:58.000000Z","unit_price_paise":110},'
    '"signature_hex":"137ad69177ccde4cd461fb6faa2d6aab3266870d5254a67575bdcc160c900cae'
    '1430dac52e2dbc211ed3fe0ddac917d219b88428b5674f1cd298a2a71f344904"}}],'
    '"allocation":{"allocated_quantity":4,'
    '"buyer_policy_commitment":"dcb9511bf596d70544da40d436fd1abe009392987cdfcd87d448388ad07147cf",'
    '"buyer_policy_commitment_version":"sha256-clear-json-v1",'
    '"market_id":"10000000-0000-4000-8000-000000000001",'
    '"mechanism_version":"reverse_second_price_v1",'
    '"payment_unit_price":{"amount_paise":125,"currency":"INR"},'
    '"schema_version":"1","status":"feasible",'
    '"total_payment":{"amount_paise":500,"currency":"INR"},'
    '"winner_merchant_id":"30000000-0000-4000-8000-000000000002",'
    '"winning_bid_id":"40000000-0000-4000-8000-000000000002",'
    '"winning_unit_price":{"amount_paise":110,"currency":"INR"}},'
    '"buyer_policy":{"bid_deadline":"2026-09-01T12:00:00.000000Z",'
    '"eligible_merchants":[{"ed25519_public_key_hex":'
    '"8a88e3dd7409f195fd52db2d3cba5d72ca6709bf1d94121bf3748801b40f6f5c",'
    '"merchant_id":"30000000-0000-4000-8000-000000000001","schema_version":"1"},'
    '{"ed25519_public_key_hex":'
    '"8139770ea87d175f56a35466c34c7ecccb8d8a91b4ee37a25df60f5b8fc9b394",'
    '"merchant_id":"30000000-0000-4000-8000-000000000002","schema_version":"1"}],'
    '"market_spec":{"buyer_id":"20000000-0000-4000-8000-000000000001",'
    '"market_id":"10000000-0000-4000-8000-000000000001",'
    '"requested_quantity":4,"schema_version":"1"},'
    '"max_total_payment":{"amount_paise":500,"currency":"INR"},'
    '"mechanism_version":"reverse_second_price_v1",'
    '"reserve_unit_price":{"amount_paise":125,"currency":"INR"},'
    '"schema_version":"1","tie_break_rule":"merchant_id_lexicographic_ascending"},'
    '"buyer_policy_commitment":'
    '"dcb9511bf596d70544da40d436fd1abe009392987cdfcd87d448388ad07147cf",'
    '"buyer_policy_commitment_version":"sha256-clear-json-v1",'
    '"canonicalization_version":"clear-json-v1",'
    '"certificate_id":"50000000-0000-4000-8000-000000000001",'
    '"certificate_version":"allocation-certificate-v1",'
    '"merchant_bid_signature_version":"ed25519-raw-clear-json-v1",'
    '"schema_version":"1"},"payload_type":"allocation_certificate"}'
)


def _private_key(index: int) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_PRIVATE_KEY_SEEDS[index])


def _public_key_hex(index: int) -> str:
    return (
        _private_key(index)
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        .hex()
    )


def _policy() -> BuyerPolicy:
    return BuyerPolicy(
        market_spec=MarketSpec(
            market_id=_MARKET_ID,
            buyer_id=_BUYER_ID,
            requested_quantity=4,
        ),
        max_total_payment=Money(amount_paise=500),
        reserve_unit_price=Money(amount_paise=125),
        eligible_merchants=tuple(
            MerchantIdentity(
                merchant_id=_MERCHANT_IDS[index],
                ed25519_public_key_hex=_public_key_hex(index),
            )
            for index in range(2)
        ),
        bid_deadline=_DEADLINE,
    )


def _signed_bid(
    policy: BuyerPolicy,
    merchant_index: int,
    *,
    unit_price_paise: int,
) -> SignedMerchantBid:
    bid = MerchantBid(
        bid_id=_BID_IDS[merchant_index],
        market_id=policy.market_spec.market_id,
        merchant_id=_MERCHANT_IDS[merchant_index],
        buyer_policy_commitment=buyer_policy_commitment(policy),
        quantity_available=4,
        unit_price_paise=unit_price_paise,
        submitted_at=_SUBMITTED_AT,
    )
    return sign_merchant_bid(bid, _private_key(merchant_index))


def _golden_certificate(
    certificate_id: str = _CERTIFICATE_ID,
) -> AllocationCertificate:
    policy = _policy()
    state = AdmissionState(policy)
    signed_a = _signed_bid(policy, 0, unit_price_paise=1)
    invalid_a = SignedMerchantBid(bid=signed_a.bid, signature_hex="0" * 128)
    invalid_a_decision = admit_signed_bid(
        state,
        invalid_a,
        AdmissionContext(received_at=_RECEIVED_AT),
    )
    accepted_b_decision = admit_signed_bid(
        state,
        _signed_bid(policy, 1, unit_price_paise=110),
        AdmissionContext(received_at=_RECEIVED_AT),
    )
    assert invalid_a_decision.rejection_code is AdmissionRejectionCode.INVALID_SIGNATURE
    assert accepted_b_decision.rejection_code is None
    return build_allocation_certificate(
        certificate_id,
        policy,
        (invalid_a_decision, accepted_b_decision),
    )


def _accepted_order_certificate(order: tuple[int, int]) -> AllocationCertificate:
    policy = _policy()
    state = AdmissionState(policy)
    prices = (100, 110)
    decisions = tuple(
        admit_signed_bid(
            state,
            _signed_bid(policy, index, unit_price_paise=prices[index]),
            AdmissionContext(received_at=_RECEIVED_AT),
        )
        for index in order
    )
    assert all(decision.rejection_code is None for decision in decisions)
    return build_allocation_certificate(_CERTIFICATE_ID, policy, decisions)


def _empty_certificate() -> AllocationCertificate:
    return build_allocation_certificate(_CERTIFICATE_ID, _policy(), ())


@pytest.mark.parametrize("value", [None, {}, "certificate", b"certificate", object()])
def test_canonical_certificate_bytes_rejects_non_certificate(value: object) -> None:
    with pytest.raises(TypeError):
        canonical_allocation_certificate_bytes(value)


def test_golden_public_keys_are_exact() -> None:
    assert tuple(_public_key_hex(index) for index in range(2)) == _PUBLIC_KEY_HEX


def test_golden_buyer_policy_commitment_is_exact() -> None:
    assert buyer_policy_commitment(_policy()) == _POLICY_COMMITMENT


def test_golden_merchant_b_signature_is_exact() -> None:
    assert _signed_bid(_policy(), 1, unit_price_paise=110).signature_hex == _MERCHANT_B_SIGNATURE


def test_golden_certificate_construction_succeeds() -> None:
    allocation_certificate = _golden_certificate()

    assert allocation_certificate.buyer_policy_commitment == _POLICY_COMMITMENT
    assert len(allocation_certificate.admission_decisions) == 2
    assert allocation_certificate.allocation.winner_merchant_id == _MERCHANT_IDS[1]
    assert allocation_certificate.allocation.payment_unit_price == Money(amount_paise=125)
    assert allocation_certificate.allocation.total_payment == Money(amount_paise=500)


def test_golden_certificate_bytes_are_exact() -> None:
    encoded = canonical_allocation_certificate_bytes(_golden_certificate())

    assert encoded == _GOLDEN_CERTIFICATE_JSON.encode("utf-8")
    assert len(encoded) == 3311
    assert hashlib.sha256(encoded).hexdigest() == _GOLDEN_CERTIFICATE_SHA256
    assert not encoded.endswith(b"\n")
    assert encoded.decode("utf-8") == _GOLDEN_CERTIFICATE_JSON


def test_golden_certificate_payload_contains_complete_evidence() -> None:
    envelope = json.loads(canonical_allocation_certificate_bytes(_golden_certificate()))
    payload = envelope["payload"]
    policy = payload["buyer_policy"]
    decisions = payload["admission_decisions"]
    allocation = payload["allocation"]

    assert set(envelope) == {"canonicalization_version", "payload_type", "payload"}
    assert envelope["canonicalization_version"] == "clear-json-v1"
    assert envelope["payload_type"] == "allocation_certificate"
    assert payload["schema_version"] == "1"
    assert payload["certificate_version"] == "allocation-certificate-v1"
    assert payload["canonicalization_version"] == "clear-json-v1"
    assert payload["buyer_policy_commitment_version"] == "sha256-clear-json-v1"
    assert payload["merchant_bid_signature_version"] == "ed25519-raw-clear-json-v1"
    assert set(policy) == {
        "schema_version",
        "market_spec",
        "max_total_payment",
        "reserve_unit_price",
        "eligible_merchants",
        "bid_deadline",
        "mechanism_version",
        "tie_break_rule",
    }
    assert policy["market_spec"]["requested_quantity"] == 4
    assert policy["max_total_payment"] == {"amount_paise": 500, "currency": "INR"}
    assert policy["reserve_unit_price"] == {"amount_paise": 125, "currency": "INR"}
    assert policy["bid_deadline"] == "2026-09-01T12:00:00.000000Z"
    assert len(policy["eligible_merchants"]) == 2
    assert len(decisions) == 2
    assert decisions[0]["rejection_code"] == "invalid_signature"
    assert decisions[1]["rejection_code"] is None
    assert decisions[0]["signed_bid"]["signature_hex"] == "0" * 128
    assert decisions[1]["signed_bid"]["signature_hex"] == _MERCHANT_B_SIGNATURE
    assert decisions[0]["signed_bid"]["bid"]["submitted_at"] == ("2026-09-01T11:59:58.000000Z")
    assert decisions[1]["signed_bid"]["bid"]["submitted_at"] == ("2026-09-01T11:59:58.000000Z")
    assert decisions[0]["context"]["received_at"] == "2026-09-01T11:59:59.000000Z"
    assert decisions[1]["context"]["received_at"] == "2026-09-01T11:59:59.000000Z"
    assert allocation["status"] == "feasible"
    assert allocation["winner_merchant_id"] == _MERCHANT_IDS[1]
    assert allocation["payment_unit_price"] == {"amount_paise": 125, "currency": "INR"}
    assert allocation["total_payment"] == {"amount_paise": 500, "currency": "INR"}


def test_transcript_order_is_byte_and_digest_visible_without_changing_allocation() -> None:
    certificate_ab = _accepted_order_certificate((0, 1))
    certificate_ba = _accepted_order_certificate((1, 0))

    assert certificate_ab.allocation == certificate_ba.allocation
    assert canonical_allocation_certificate_bytes(certificate_ab) != (
        canonical_allocation_certificate_bytes(certificate_ba)
    )
    assert allocation_certificate_digest(certificate_ab) != allocation_certificate_digest(
        certificate_ba
    )


def test_infeasible_allocation_serializes_all_optional_fields_as_null() -> None:
    envelope = json.loads(canonical_allocation_certificate_bytes(_empty_certificate()))
    allocation = envelope["payload"]["allocation"]
    optional_fields = (
        "winner_merchant_id",
        "winning_bid_id",
        "allocated_quantity",
        "winning_unit_price",
        "payment_unit_price",
        "total_payment",
    )

    assert all(field in allocation for field in optional_fields)
    assert all(allocation[field] is None for field in optional_fields)


def test_empty_feasible_and_rejected_transcript_certificates_canonicalize() -> None:
    empty = canonical_allocation_certificate_bytes(_empty_certificate())
    feasible = canonical_allocation_certificate_bytes(_accepted_order_certificate((0, 1)))
    rejected_and_accepted = canonical_allocation_certificate_bytes(_golden_certificate())

    assert empty
    assert feasible
    assert rejected_and_accepted
