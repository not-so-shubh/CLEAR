from datetime import UTC, datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

import clear_market.lifecycle as lifecycle
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
    evaluate_stateless_admission,
)

# TEST ONLY — NEVER PRODUCTION KEY MATERIAL.
_PRIVATE_SEED_HEX = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
_PUBLIC_KEY_HEX = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
_OTHER_PRIVATE_SEED_HEX = "00" * 32
_MARKET_ID = "10000000-0000-4000-8000-000000000001"
_OTHER_MARKET_ID = "10000000-0000-4000-8000-000000000002"
_BUYER_ID = "20000000-0000-4000-8000-000000000001"
_MERCHANT_ID = "30000000-0000-4000-8000-000000000001"
_SECOND_MERCHANT_ID = "30000000-0000-4000-8000-000000000002"
_OUTSIDER_MERCHANT_ID = "30000000-0000-4000-8000-000000000003"
_BID_ID = "40000000-0000-4000-8000-000000000001"
_DEADLINE = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 9, 1, 11, 59, 58, tzinfo=UTC)
_RECEIVED_AT = datetime(2026, 9, 1, 11, 59, 59, tzinfo=UTC)


def _private_key(seed_hex: str = _PRIVATE_SEED_HEX) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex))


def _raw_public_key_hex(private_key: Ed25519PrivateKey) -> str:
    return (
        private_key.public_key()
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
        eligible_merchants=(
            MerchantIdentity(
                merchant_id=_MERCHANT_ID,
                ed25519_public_key_hex=_PUBLIC_KEY_HEX,
            ),
            MerchantIdentity(
                merchant_id=_SECOND_MERCHANT_ID,
                ed25519_public_key_hex="1" * 64,
            ),
        ),
        bid_deadline=_DEADLINE,
    )


def _bid(
    policy: BuyerPolicy,
    *,
    market_id: str | None = None,
    merchant_id: str = _MERCHANT_ID,
    policy_commitment: str | None = None,
    quantity_available: int = 4,
    unit_price_paise: int = 100,
    submitted_at: datetime = _SUBMITTED_AT,
) -> MerchantBid:
    return MerchantBid(
        bid_id=_BID_ID,
        market_id=policy.market_spec.market_id if market_id is None else market_id,
        merchant_id=merchant_id,
        buyer_policy_commitment=(
            buyer_policy_commitment(policy) if policy_commitment is None else policy_commitment
        ),
        quantity_available=quantity_available,
        unit_price_paise=unit_price_paise,
        submitted_at=submitted_at,
    )


def _signed_bid(
    policy: BuyerPolicy,
    *,
    private_key: Ed25519PrivateKey | None = None,
    market_id: str | None = None,
    merchant_id: str = _MERCHANT_ID,
    policy_commitment: str | None = None,
    quantity_available: int = 4,
    unit_price_paise: int = 100,
    submitted_at: datetime = _SUBMITTED_AT,
) -> SignedMerchantBid:
    signing_key = _private_key() if private_key is None else private_key
    bid = _bid(
        policy,
        market_id=market_id,
        merchant_id=merchant_id,
        policy_commitment=policy_commitment,
        quantity_available=quantity_available,
        unit_price_paise=unit_price_paise,
        submitted_at=submitted_at,
    )
    return sign_merchant_bid(bid, signing_key)


def _context(received_at: datetime = _RECEIVED_AT) -> AdmissionContext:
    return AdmissionContext(received_at=received_at)


def _with_invalid_signature(signed_bid: SignedMerchantBid) -> SignedMerchantBid:
    return SignedMerchantBid(bid=signed_bid.bid, signature_hex="0" * 128)


def test_lifecycle_public_api_is_exact() -> None:
    assert lifecycle.__all__ == (
        "AdmissionContext",
        "AdmissionRejectionCode",
        "evaluate_stateless_admission",
    )


def test_test_private_key_derives_expected_public_key() -> None:
    assert _raw_public_key_hex(_private_key()) == _PUBLIC_KEY_HEX


def test_admission_context_accepts_utc_received_at() -> None:
    context = _context()

    assert context.received_at == _RECEIVED_AT
    assert context.received_at.utcoffset() == timedelta(0)


def test_admission_context_normalizes_positive_offset() -> None:
    received_at = datetime(
        2026,
        9,
        1,
        17,
        29,
        59,
        123_456,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )

    assert _context(received_at).received_at == datetime(
        2026, 9, 1, 11, 59, 59, 123_456, tzinfo=UTC
    )


def test_admission_context_normalizes_negative_offset() -> None:
    received_at = datetime(
        2026,
        9,
        1,
        6,
        59,
        59,
        123_456,
        tzinfo=timezone(-timedelta(hours=5)),
    )

    assert _context(received_at).received_at == datetime(
        2026, 9, 1, 11, 59, 59, 123_456, tzinfo=UTC
    )


def test_admission_context_preserves_microseconds() -> None:
    received_at = datetime(2026, 9, 1, 11, 59, 59, 654_321, tzinfo=UTC)

    assert _context(received_at).received_at.microsecond == 654_321


@pytest.mark.parametrize(
    "received_at",
    [datetime(2026, 9, 1, 11, 59, 59), "2026-09-01T11:59:59.000000Z", None],
)
def test_admission_context_rejects_invalid_received_at(received_at: object) -> None:
    with pytest.raises(ValidationError):
        AdmissionContext(received_at=received_at)


def test_admission_context_requires_received_at() -> None:
    with pytest.raises(ValidationError):
        AdmissionContext()


def test_admission_context_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AdmissionContext(received_at=_RECEIVED_AT, unexpected=True)


def test_admission_context_is_frozen() -> None:
    context = _context()

    with pytest.raises(ValidationError):
        context.received_at = _DEADLINE


def test_admission_rejection_codes_are_exact() -> None:
    assert tuple((code.name, code.value) for code in AdmissionRejectionCode) == (
        ("WRONG_MARKET", "wrong_market"),
        ("POLICY_COMMITMENT_MISMATCH", "policy_commitment_mismatch"),
        ("MERCHANT_NOT_ELIGIBLE", "merchant_not_eligible"),
        ("INVALID_SIGNATURE", "invalid_signature"),
        ("SUBMITTED_AFTER_RECEIVED", "submitted_after_received"),
        ("SUBMITTED_AFTER_DEADLINE", "submitted_after_deadline"),
        ("RECEIVED_AFTER_DEADLINE", "received_after_deadline"),
    )


def test_valid_signed_bid_passes_stateless_admission() -> None:
    policy = _policy()

    assert evaluate_stateless_admission(_signed_bid(policy), policy, _context()) is None


def test_wrong_market_is_rejected() -> None:
    policy = _policy()
    signed_bid = _signed_bid(policy, market_id=_OTHER_MARKET_ID)

    assert (
        evaluate_stateless_admission(signed_bid, policy, _context())
        is AdmissionRejectionCode.WRONG_MARKET
    )


def test_policy_commitment_mismatch_is_rejected() -> None:
    policy = _policy()
    signed_bid = _signed_bid(policy, policy_commitment="a" * 64)

    assert (
        evaluate_stateless_admission(signed_bid, policy, _context())
        is AdmissionRejectionCode.POLICY_COMMITMENT_MISMATCH
    )


def test_merchant_not_eligible_is_rejected() -> None:
    policy = _policy()
    outsider_key = _private_key(_OTHER_PRIVATE_SEED_HEX)
    signed_bid = _signed_bid(
        policy,
        private_key=outsider_key,
        merchant_id=_OUTSIDER_MERCHANT_ID,
    )

    assert (
        evaluate_stateless_admission(signed_bid, policy, _context())
        is AdmissionRejectionCode.MERCHANT_NOT_ELIGIBLE
    )


def test_invalid_signature_is_rejected() -> None:
    policy = _policy()
    signed_bid = _signed_bid(policy, private_key=_private_key(_OTHER_PRIVATE_SEED_HEX))

    assert (
        evaluate_stateless_admission(signed_bid, policy, _context())
        is AdmissionRejectionCode.INVALID_SIGNATURE
    )


def test_submitted_one_microsecond_after_received_is_rejected() -> None:
    policy = _policy()
    received_at = datetime(2026, 9, 1, 11, 59, 59, tzinfo=UTC)
    submitted_at = received_at + timedelta(microseconds=1)

    assert (
        evaluate_stateless_admission(
            _signed_bid(policy, submitted_at=submitted_at),
            policy,
            _context(received_at),
        )
        is AdmissionRejectionCode.SUBMITTED_AFTER_RECEIVED
    )


def test_submission_and_receipt_at_deadline_are_inclusive() -> None:
    policy = _policy()
    signed_bid = _signed_bid(policy, submitted_at=_DEADLINE)

    assert evaluate_stateless_admission(signed_bid, policy, _context(_DEADLINE)) is None


def test_submission_one_microsecond_after_deadline_is_rejected() -> None:
    policy = _policy()
    submitted_at = _DEADLINE + timedelta(microseconds=1)

    assert (
        evaluate_stateless_admission(
            _signed_bid(policy, submitted_at=submitted_at),
            policy,
            _context(submitted_at),
        )
        is AdmissionRejectionCode.SUBMITTED_AFTER_DEADLINE
    )


def test_receipt_at_deadline_is_inclusive() -> None:
    policy = _policy()

    assert evaluate_stateless_admission(_signed_bid(policy), policy, _context(_DEADLINE)) is None


def test_receipt_one_microsecond_after_deadline_is_rejected() -> None:
    policy = _policy()
    received_at = _DEADLINE + timedelta(microseconds=1)

    assert (
        evaluate_stateless_admission(_signed_bid(policy), policy, _context(received_at))
        is AdmissionRejectionCode.RECEIVED_AFTER_DEADLINE
    )


def test_equivalent_timezone_received_at_has_same_result() -> None:
    policy = _policy()
    offset_received_at = datetime(
        2026,
        9,
        1,
        17,
        29,
        59,
        tzinfo=timezone(timedelta(hours=5, minutes=30)),
    )
    signed_bid = _signed_bid(policy)

    assert evaluate_stateless_admission(signed_bid, policy, _context()) == (
        evaluate_stateless_admission(signed_bid, policy, _context(offset_received_at))
    )


def test_wrong_market_precedes_invalid_signature() -> None:
    policy = _policy()
    signed_bid = _with_invalid_signature(_signed_bid(policy, market_id=_OTHER_MARKET_ID))

    assert (
        evaluate_stateless_admission(signed_bid, policy, _context())
        is AdmissionRejectionCode.WRONG_MARKET
    )


def test_policy_commitment_mismatch_precedes_invalid_signature() -> None:
    policy = _policy()
    signed_bid = _with_invalid_signature(_signed_bid(policy, policy_commitment="a" * 64))

    assert (
        evaluate_stateless_admission(signed_bid, policy, _context())
        is AdmissionRejectionCode.POLICY_COMMITMENT_MISMATCH
    )


def test_merchant_not_eligible_precedes_invalid_signature() -> None:
    policy = _policy()
    signed_bid = _with_invalid_signature(_signed_bid(policy, merchant_id=_OUTSIDER_MERCHANT_ID))

    assert (
        evaluate_stateless_admission(signed_bid, policy, _context())
        is AdmissionRejectionCode.MERCHANT_NOT_ELIGIBLE
    )


def test_invalid_signature_precedes_submitted_after_deadline() -> None:
    policy = _policy()
    submitted_at = _DEADLINE + timedelta(microseconds=1)
    signed_bid = _signed_bid(
        policy,
        private_key=_private_key(_OTHER_PRIVATE_SEED_HEX),
        submitted_at=submitted_at,
    )

    assert (
        evaluate_stateless_admission(signed_bid, policy, _context(submitted_at))
        is AdmissionRejectionCode.INVALID_SIGNATURE
    )


def test_submitted_after_received_precedes_submitted_after_deadline() -> None:
    policy = _policy()
    received_at = _DEADLINE
    submitted_at = _DEADLINE + timedelta(microseconds=1)

    assert (
        evaluate_stateless_admission(
            _signed_bid(policy, submitted_at=submitted_at),
            policy,
            _context(received_at),
        )
        is AdmissionRejectionCode.SUBMITTED_AFTER_RECEIVED
    )


def test_submitted_after_deadline_precedes_received_after_deadline() -> None:
    policy = _policy()
    submitted_at = _DEADLINE + timedelta(microseconds=1)
    received_at = _DEADLINE + timedelta(microseconds=2)

    assert (
        evaluate_stateless_admission(
            _signed_bid(policy, submitted_at=submitted_at),
            policy,
            _context(received_at),
        )
        is AdmissionRejectionCode.SUBMITTED_AFTER_DEADLINE
    )


def test_mechanism_ineligible_values_still_pass_stateless_admission() -> None:
    policy = _policy()
    signed_bid = _signed_bid(
        policy,
        quantity_available=0,
        unit_price_paise=126,
    )

    assert evaluate_stateless_admission(signed_bid, policy, _context()) is None


def test_repeated_evaluation_remains_stateless() -> None:
    policy = _policy()
    signed_bid = _signed_bid(policy)
    context = _context()

    assert evaluate_stateless_admission(signed_bid, policy, context) is None
    assert evaluate_stateless_admission(signed_bid, policy, context) is None
