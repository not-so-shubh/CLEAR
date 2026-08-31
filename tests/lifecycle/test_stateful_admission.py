from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

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
    AdmissionDecision,
    AdmissionRejectionCode,
    AdmissionState,
    admit_signed_bid,
)

# TEST ONLY — NEVER PRODUCTION KEY MATERIAL.
_MERCHANT_A_PRIVATE_SEED_HEX = "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
_MERCHANT_A_PUBLIC_KEY_HEX = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
_MERCHANT_B_PRIVATE_SEED_HEX = "00" * 32
_OUTSIDER_PRIVATE_SEED_HEX = "01" * 32

_MARKET_ID = "10000000-0000-4000-8000-000000000001"
_OTHER_MARKET_ID = "10000000-0000-4000-8000-000000000002"
_BUYER_ID = "20000000-0000-4000-8000-000000000001"
_MERCHANT_A_ID = "30000000-0000-4000-8000-000000000001"
_MERCHANT_B_ID = "30000000-0000-4000-8000-000000000002"
_OUTSIDER_MERCHANT_ID = "30000000-0000-4000-8000-000000000003"
_MERCHANT_A_BID_ID = "40000000-0000-4000-8000-000000000001"
_MERCHANT_B_BID_ID = "40000000-0000-4000-8000-000000000002"
_NEW_MERCHANT_A_BID_ID = "40000000-0000-4000-8000-000000000003"
_DEADLINE = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_SUBMITTED_AT = datetime(2026, 9, 1, 11, 59, 58, tzinfo=UTC)
_RECEIVED_AT = datetime(2026, 9, 1, 11, 59, 59, tzinfo=UTC)


def _private_key(seed_hex: str) -> Ed25519PrivateKey:
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


def _merchant_a_private_key() -> Ed25519PrivateKey:
    return _private_key(_MERCHANT_A_PRIVATE_SEED_HEX)


def _merchant_b_private_key() -> Ed25519PrivateKey:
    return _private_key(_MERCHANT_B_PRIVATE_SEED_HEX)


def _policy(*, reserve_unit_price_paise: int = 125) -> BuyerPolicy:
    return BuyerPolicy(
        market_spec=MarketSpec(
            market_id=_MARKET_ID,
            buyer_id=_BUYER_ID,
            requested_quantity=4,
        ),
        max_total_payment=Money(amount_paise=500),
        reserve_unit_price=Money(amount_paise=reserve_unit_price_paise),
        eligible_merchants=(
            MerchantIdentity(
                merchant_id=_MERCHANT_A_ID,
                ed25519_public_key_hex=_MERCHANT_A_PUBLIC_KEY_HEX,
            ),
            MerchantIdentity(
                merchant_id=_MERCHANT_B_ID,
                ed25519_public_key_hex=_raw_public_key_hex(_merchant_b_private_key()),
            ),
        ),
        bid_deadline=_DEADLINE,
    )


def _signed_bid(
    policy: BuyerPolicy,
    *,
    merchant_id: str = _MERCHANT_A_ID,
    private_key: Ed25519PrivateKey | None = None,
    bid_id: str = _MERCHANT_A_BID_ID,
    market_id: str | None = None,
    committed_policy: BuyerPolicy | None = None,
    policy_commitment: str | None = None,
    quantity_available: int = 4,
    unit_price_paise: int = 100,
    submitted_at: datetime = _SUBMITTED_AT,
) -> SignedMerchantBid:
    commitment_source = policy if committed_policy is None else committed_policy
    commitment = (
        buyer_policy_commitment(commitment_source)
        if policy_commitment is None
        else policy_commitment
    )
    signing_key = _merchant_a_private_key() if private_key is None else private_key
    bid = MerchantBid(
        bid_id=bid_id,
        market_id=policy.market_spec.market_id if market_id is None else market_id,
        merchant_id=merchant_id,
        buyer_policy_commitment=commitment,
        quantity_available=quantity_available,
        unit_price_paise=unit_price_paise,
        submitted_at=submitted_at,
    )
    return sign_merchant_bid(bid, signing_key)


def _merchant_b_signed_bid(
    policy: BuyerPolicy,
    *,
    bid_id: str = _MERCHANT_B_BID_ID,
) -> SignedMerchantBid:
    return _signed_bid(
        policy,
        merchant_id=_MERCHANT_B_ID,
        private_key=_merchant_b_private_key(),
        bid_id=bid_id,
    )


def _context(received_at: datetime = _RECEIVED_AT) -> AdmissionContext:
    return AdmissionContext(received_at=received_at)


def _with_invalid_signature(signed_bid: SignedMerchantBid) -> SignedMerchantBid:
    return SignedMerchantBid(bid=signed_bid.bid, signature_hex="0" * 128)


def test_deterministic_keys_match_policy_identities() -> None:
    policy = _policy()

    assert _raw_public_key_hex(_merchant_a_private_key()) == _MERCHANT_A_PUBLIC_KEY_HEX
    assert policy.eligible_merchants[1].ed25519_public_key_hex == _raw_public_key_hex(
        _merchant_b_private_key()
    )


def test_admission_decision_accepts_an_accepted_attempt() -> None:
    policy = _policy()
    signed_bid = _signed_bid(policy)
    context = _context()

    decision = AdmissionDecision(
        signed_bid=signed_bid,
        context=context,
        rejection_code=None,
    )

    assert decision.rejection_code is None


def test_admission_decision_accepts_a_rejected_attempt() -> None:
    policy = _policy()

    decision = AdmissionDecision(
        signed_bid=_signed_bid(policy),
        context=_context(),
        rejection_code=AdmissionRejectionCode.INVALID_SIGNATURE,
    )

    assert decision.rejection_code is AdmissionRejectionCode.INVALID_SIGNATURE


def test_admission_decision_has_exact_fields_and_preserves_evidence() -> None:
    policy = _policy()
    signed_bid = _signed_bid(policy)
    context = _context()

    decision = AdmissionDecision(
        signed_bid=signed_bid,
        context=context,
        rejection_code=None,
    )

    assert tuple(AdmissionDecision.model_fields) == (
        "signed_bid",
        "context",
        "rejection_code",
    )
    assert decision.signed_bid is signed_bid
    assert decision.context is context
    assert not hasattr(decision, "accepted")


def test_admission_decision_is_frozen() -> None:
    policy = _policy()
    decision = AdmissionDecision(
        signed_bid=_signed_bid(policy),
        context=_context(),
        rejection_code=None,
    )

    with pytest.raises(ValidationError):
        decision.rejection_code = AdmissionRejectionCode.INVALID_SIGNATURE


def test_admission_decision_rejects_extra_fields() -> None:
    policy = _policy()

    with pytest.raises(ValidationError):
        AdmissionDecision(
            signed_bid=_signed_bid(policy),
            context=_context(),
            rejection_code=None,
            accepted=True,
        )


def test_admission_state_binds_policy_and_starts_empty() -> None:
    policy = _policy()

    state = AdmissionState(policy)

    assert state.policy is policy
    assert state.accepted_decisions == ()
    assert isinstance(state.accepted_decisions, tuple)


@pytest.mark.parametrize("invalid_policy", [None, object(), {}])
def test_admission_state_rejects_non_policy(invalid_policy: object) -> None:
    with pytest.raises(TypeError):
        AdmissionState(invalid_policy)


def test_admission_state_policy_has_no_public_setter() -> None:
    state = AdmissionState(_policy())

    with pytest.raises(AttributeError):
        state.policy = _policy(reserve_unit_price_paise=124)


def test_first_valid_bid_is_inserted_once_and_returned() -> None:
    policy = _policy()
    state = AdmissionState(policy)

    decision = admit_signed_bid(state, _signed_bid(policy), _context())

    assert decision.rejection_code is None
    assert state.accepted_decisions == (decision,)
    assert state.accepted_decisions[0] is decision


def test_exact_replay_is_rejected_before_duplicate_without_mutation() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    signed_bid = _signed_bid(policy)
    admit_signed_bid(state, signed_bid, _context())
    before = state.accepted_decisions

    decision = admit_signed_bid(state, signed_bid, _context())

    assert decision.rejection_code is AdmissionRejectionCode.REPLAYED_BID_ID
    assert state.accepted_decisions == before
    assert decision not in state.accepted_decisions


def test_reused_bid_id_from_another_merchant_is_rejected_without_mutation() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    admit_signed_bid(state, _signed_bid(policy), _context())
    before = state.accepted_decisions

    decision = admit_signed_bid(
        state,
        _merchant_b_signed_bid(policy, bid_id=_MERCHANT_A_BID_ID),
        _context(),
    )

    assert decision.rejection_code is AdmissionRejectionCode.REPLAYED_BID_ID
    assert state.accepted_decisions == before


def test_second_bid_from_same_merchant_is_rejected_without_mutation() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    admit_signed_bid(state, _signed_bid(policy), _context())
    before = state.accepted_decisions

    decision = admit_signed_bid(
        state,
        _signed_bid(policy, bid_id=_NEW_MERCHANT_A_BID_ID),
        _context(),
    )

    assert decision.rejection_code is AdmissionRejectionCode.DUPLICATE_MERCHANT_BID
    assert state.accepted_decisions == before


def test_invalid_signature_precedes_replay_without_mutation() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    signed_bid = _signed_bid(policy)
    admit_signed_bid(state, signed_bid, _context())
    before = state.accepted_decisions

    decision = admit_signed_bid(state, _with_invalid_signature(signed_bid), _context())

    assert decision.rejection_code is AdmissionRejectionCode.INVALID_SIGNATURE
    assert state.accepted_decisions == before


def test_rejected_bid_id_does_not_poison_state() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    signed_bid = _signed_bid(policy)

    rejected = admit_signed_bid(state, _with_invalid_signature(signed_bid), _context())

    assert rejected.rejection_code is AdmissionRejectionCode.INVALID_SIGNATURE
    assert state.accepted_decisions == ()

    accepted = admit_signed_bid(state, signed_bid, _context())

    assert accepted.rejection_code is None
    assert state.accepted_decisions == (accepted,)


def test_two_merchants_are_exposed_in_merchant_id_order() -> None:
    policy = _policy()
    state = AdmissionState(policy)

    merchant_b_decision = admit_signed_bid(state, _merchant_b_signed_bid(policy), _context())
    merchant_a_decision = admit_signed_bid(state, _signed_bid(policy), _context())

    assert merchant_b_decision.rejection_code is None
    assert merchant_a_decision.rejection_code is None
    assert state.accepted_decisions == (merchant_a_decision, merchant_b_decision)
    assert tuple(decision.signed_bid.bid.merchant_id for decision in state.accepted_decisions) == (
        _MERCHANT_A_ID,
        _MERCHANT_B_ID,
    )


def test_policy_drift_is_rejected_against_bound_policy() -> None:
    original_policy = _policy()
    changed_policy = _policy(reserve_unit_price_paise=124)
    state = AdmissionState(original_policy)
    changed_policy_bid = _signed_bid(original_policy, committed_policy=changed_policy)

    decision = admit_signed_bid(state, changed_policy_bid, _context())

    assert decision.rejection_code is AdmissionRejectionCode.POLICY_COMMITMENT_MISMATCH
    assert state.accepted_decisions == ()


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("wrong_market", AdmissionRejectionCode.WRONG_MARKET),
        ("policy_mismatch", AdmissionRejectionCode.POLICY_COMMITMENT_MISMATCH),
        ("merchant_not_eligible", AdmissionRejectionCode.MERCHANT_NOT_ELIGIBLE),
        ("invalid_signature", AdmissionRejectionCode.INVALID_SIGNATURE),
        ("submitted_after_received", AdmissionRejectionCode.SUBMITTED_AFTER_RECEIVED),
        ("submitted_after_deadline", AdmissionRejectionCode.SUBMITTED_AFTER_DEADLINE),
        ("received_after_deadline", AdmissionRejectionCode.RECEIVED_AFTER_DEADLINE),
    ],
)
def test_stateless_rejection_never_mutates_state(
    case: str,
    expected: AdmissionRejectionCode,
) -> None:
    policy = _policy()
    state = AdmissionState(policy)
    context = _context()

    if case == "wrong_market":
        signed_bid = _signed_bid(policy, market_id=_OTHER_MARKET_ID)
    elif case == "policy_mismatch":
        signed_bid = _signed_bid(policy, policy_commitment="a" * 64)
    elif case == "merchant_not_eligible":
        signed_bid = _signed_bid(
            policy,
            merchant_id=_OUTSIDER_MERCHANT_ID,
            private_key=_private_key(_OUTSIDER_PRIVATE_SEED_HEX),
        )
    elif case == "invalid_signature":
        signed_bid = _with_invalid_signature(_signed_bid(policy))
    elif case == "submitted_after_received":
        signed_bid = _signed_bid(policy, submitted_at=_DEADLINE)
    elif case == "submitted_after_deadline":
        submitted_at = _DEADLINE + timedelta(microseconds=1)
        signed_bid = _signed_bid(policy, submitted_at=submitted_at)
        context = _context(submitted_at)
    else:
        signed_bid = _signed_bid(policy)
        context = _context(_DEADLINE + timedelta(microseconds=1))

    before = state.accepted_decisions
    decision = admit_signed_bid(state, signed_bid, context)

    assert decision.rejection_code is expected
    assert state.accepted_decisions == before


def test_mechanism_ineligible_values_can_be_admitted() -> None:
    policy = _policy()
    state = AdmissionState(policy)
    signed_bid = _signed_bid(
        policy,
        quantity_available=0,
        unit_price_paise=126,
    )

    decision = admit_signed_bid(state, signed_bid, _context())

    assert decision.rejection_code is None
    assert state.accepted_decisions == (decision,)


def test_replay_tracking_is_scoped_to_each_state() -> None:
    policy = _policy()
    first_state = AdmissionState(policy)
    second_state = AdmissionState(policy)
    signed_bid = _signed_bid(policy)

    first_decision = admit_signed_bid(first_state, signed_bid, _context())
    second_decision = admit_signed_bid(second_state, signed_bid, _context())

    assert first_decision.rejection_code is None
    assert second_decision.rejection_code is None
    assert first_state.accepted_decisions == (first_decision,)
    assert second_state.accepted_decisions == (second_decision,)
