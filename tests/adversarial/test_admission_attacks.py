from collections.abc import Callable
from datetime import datetime

import pytest

from clear_market.domain import MerchantBid, SignedMerchantBid
from clear_market.lifecycle import (
    AdmissionDecision,
    AdmissionRejectionCode,
    AdmissionState,
    admit_signed_bid,
)
from tests.adversarial.admission_helpers import (
    AFTER_DEADLINE,
    AFTER_DEADLINE_SUBMITTED,
    AFTER_RECEIVED_SUBMITTED,
    ALTERNATE_BID_ID,
    DEADLINE,
    TAMPERED_VALID_SUBMITTED,
    UNREGISTERED_MERCHANT_ID,
    VALID_RECEIVED,
    VALID_SUBMITTED,
    WRONG_MARKET_ID,
    AdversarialMarketFixture,
    build_adversarial_market,
    build_bid,
    context,
    sign_with_a,
    sign_with_b,
    sign_with_outsider,
)


def _assert_rejected(
    fixture: AdversarialMarketFixture,
    signed_bid: SignedMerchantBid,
    expected_code: AdmissionRejectionCode,
    *,
    received_at: datetime = VALID_RECEIVED,
) -> AdmissionDecision:
    state = AdmissionState(fixture.policy)
    before = state.accepted_decisions

    decision = admit_signed_bid(state, signed_bid, context(received_at))

    assert decision.rejection_code is expected_code
    assert state.accepted_decisions == before
    return decision


def _invalid_signature(bid: MerchantBid) -> SignedMerchantBid:
    return SignedMerchantBid(bid=bid, signature_hex="0" * 128)


def _wrong_commitment(fixture: AdversarialMarketFixture) -> str:
    real_commitment = build_bid(fixture).buyer_policy_commitment
    return "1" * 64 if real_commitment == "0" * 64 else "0" * 64


def test_valid_signed_bid_is_admitted() -> None:
    fixture = build_adversarial_market()
    state = AdmissionState(fixture.policy)

    decision = admit_signed_bid(state, sign_with_a(fixture, build_bid(fixture)), context())

    assert decision.rejection_code is None
    assert state.accepted_decisions == (decision,)


def test_submitted_and_received_exactly_at_deadline_are_accepted() -> None:
    fixture = build_adversarial_market()
    state = AdmissionState(fixture.policy)
    signed_bid = sign_with_a(fixture, build_bid(fixture, submitted_at=DEADLINE))

    decision = admit_signed_bid(state, signed_bid, context(DEADLINE))

    assert decision.rejection_code is None
    assert state.accepted_decisions == (decision,)


def test_received_exactly_at_deadline_after_earlier_submission_is_accepted() -> None:
    fixture = build_adversarial_market()
    state = AdmissionState(fixture.policy)
    signed_bid = sign_with_a(fixture, build_bid(fixture, submitted_at=VALID_SUBMITTED))

    decision = admit_signed_bid(state, signed_bid, context(DEADLINE))

    assert decision.rejection_code is None
    assert state.accepted_decisions == (decision,)


def test_correctly_signed_wrong_market_is_rejected() -> None:
    fixture = build_adversarial_market()
    signed_bid = sign_with_a(fixture, build_bid(fixture, market_id=WRONG_MARKET_ID))

    _assert_rejected(fixture, signed_bid, AdmissionRejectionCode.WRONG_MARKET)


def test_correctly_signed_wrong_policy_commitment_is_rejected() -> None:
    fixture = build_adversarial_market()
    bid = build_bid(fixture, buyer_policy_commitment_value=_wrong_commitment(fixture))

    _assert_rejected(
        fixture,
        sign_with_a(fixture, bid),
        AdmissionRejectionCode.POLICY_COMMITMENT_MISMATCH,
    )


def test_correctly_signed_unregistered_merchant_is_rejected() -> None:
    fixture = build_adversarial_market()
    bid = build_bid(fixture, merchant_id=UNREGISTERED_MERCHANT_ID)

    _assert_rejected(
        fixture,
        sign_with_outsider(fixture, bid),
        AdmissionRejectionCode.MERCHANT_NOT_ELIGIBLE,
    )


@pytest.mark.parametrize("signer", [sign_with_b, sign_with_outsider])
def test_merchant_a_claim_signed_by_wrong_key_is_rejected(
    signer: Callable[[AdversarialMarketFixture, MerchantBid], SignedMerchantBid],
) -> None:
    fixture = build_adversarial_market()
    signed_bid = signer(fixture, build_bid(fixture))

    _assert_rejected(fixture, signed_bid, AdmissionRejectionCode.INVALID_SIGNATURE)


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("quantity_available", 11),
        ("unit_price_paise", 401),
        ("bid_id", ALTERNATE_BID_ID),
        ("submitted_at", TAMPERED_VALID_SUBMITTED),
    ],
)
def test_tampering_signed_bid_field_is_rejected(
    field_name: str,
    replacement: int | str | datetime,
) -> None:
    fixture = build_adversarial_market()
    original = sign_with_a(fixture, build_bid(fixture))
    tampered_bid = original.bid.model_copy(update={field_name: replacement})
    tampered = SignedMerchantBid(
        bid=tampered_bid,
        signature_hex=original.signature_hex,
    )

    _assert_rejected(fixture, tampered, AdmissionRejectionCode.INVALID_SIGNATURE)


def test_submitted_after_received_is_rejected() -> None:
    fixture = build_adversarial_market()
    bid = build_bid(fixture, submitted_at=AFTER_RECEIVED_SUBMITTED)

    _assert_rejected(
        fixture,
        sign_with_a(fixture, bid),
        AdmissionRejectionCode.SUBMITTED_AFTER_RECEIVED,
        received_at=VALID_RECEIVED,
    )


def test_submitted_after_deadline_precedes_received_after_deadline() -> None:
    fixture = build_adversarial_market()
    bid = build_bid(fixture, submitted_at=AFTER_DEADLINE)

    _assert_rejected(
        fixture,
        sign_with_a(fixture, bid),
        AdmissionRejectionCode.SUBMITTED_AFTER_DEADLINE,
        received_at=AFTER_DEADLINE,
    )


def test_received_after_deadline_is_rejected() -> None:
    fixture = build_adversarial_market()
    bid = build_bid(fixture, submitted_at=DEADLINE)

    _assert_rejected(
        fixture,
        sign_with_a(fixture, bid),
        AdmissionRejectionCode.RECEIVED_AFTER_DEADLINE,
        received_at=AFTER_DEADLINE,
    )


def test_precedence_case_1_wrong_market_outranks_all_later_faults() -> None:
    fixture = build_adversarial_market()
    bid = build_bid(
        fixture,
        market_id=WRONG_MARKET_ID,
        merchant_id=UNREGISTERED_MERCHANT_ID,
        buyer_policy_commitment_value=_wrong_commitment(fixture),
        submitted_at=AFTER_DEADLINE_SUBMITTED,
    )

    _assert_rejected(
        fixture,
        _invalid_signature(bid),
        AdmissionRejectionCode.WRONG_MARKET,
        received_at=AFTER_DEADLINE,
    )


def test_precedence_case_2_policy_commitment_outranks_all_later_faults() -> None:
    fixture = build_adversarial_market()
    bid = build_bid(
        fixture,
        merchant_id=UNREGISTERED_MERCHANT_ID,
        buyer_policy_commitment_value=_wrong_commitment(fixture),
        submitted_at=AFTER_DEADLINE_SUBMITTED,
    )

    _assert_rejected(
        fixture,
        _invalid_signature(bid),
        AdmissionRejectionCode.POLICY_COMMITMENT_MISMATCH,
        received_at=AFTER_DEADLINE,
    )


def test_precedence_case_3_merchant_eligibility_outranks_all_later_faults() -> None:
    fixture = build_adversarial_market()
    bid = build_bid(
        fixture,
        merchant_id=UNREGISTERED_MERCHANT_ID,
        submitted_at=AFTER_DEADLINE_SUBMITTED,
    )

    _assert_rejected(
        fixture,
        _invalid_signature(bid),
        AdmissionRejectionCode.MERCHANT_NOT_ELIGIBLE,
        received_at=AFTER_DEADLINE,
    )


def test_precedence_case_4_signature_outranks_all_timing_faults() -> None:
    fixture = build_adversarial_market()
    bid = build_bid(fixture, submitted_at=AFTER_DEADLINE_SUBMITTED)

    _assert_rejected(
        fixture,
        _invalid_signature(bid),
        AdmissionRejectionCode.INVALID_SIGNATURE,
        received_at=AFTER_DEADLINE,
    )


def test_precedence_case_5_submitted_after_received_outranks_deadline_faults() -> None:
    fixture = build_adversarial_market()
    bid = build_bid(fixture, submitted_at=AFTER_DEADLINE_SUBMITTED)

    _assert_rejected(
        fixture,
        sign_with_a(fixture, bid),
        AdmissionRejectionCode.SUBMITTED_AFTER_RECEIVED,
        received_at=AFTER_DEADLINE,
    )


def test_precedence_case_6_submitted_deadline_outranks_received_deadline() -> None:
    fixture = build_adversarial_market()
    bid = build_bid(fixture, submitted_at=AFTER_DEADLINE)

    _assert_rejected(
        fixture,
        sign_with_a(fixture, bid),
        AdmissionRejectionCode.SUBMITTED_AFTER_DEADLINE,
        received_at=AFTER_DEADLINE,
    )


def test_precedence_case_7_received_after_deadline_is_last() -> None:
    fixture = build_adversarial_market()
    bid = build_bid(fixture, submitted_at=DEADLINE)

    _assert_rejected(
        fixture,
        sign_with_a(fixture, bid),
        AdmissionRejectionCode.RECEIVED_AFTER_DEADLINE,
        received_at=AFTER_DEADLINE,
    )
