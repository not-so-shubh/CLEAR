from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from clear_market.crypto import buyer_policy_commitment, verify_merchant_bid_signature
from clear_market.domain import BuyerPolicy, MerchantIdentity, SignedMerchantBid, UTCDateTime


class AdmissionContext(BaseModel):
    """Trusted explicit receipt evidence for one stateless admission evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    received_at: UTCDateTime


class AdmissionRejectionCode(StrEnum):
    WRONG_MARKET = "wrong_market"
    POLICY_COMMITMENT_MISMATCH = "policy_commitment_mismatch"
    MERCHANT_NOT_ELIGIBLE = "merchant_not_eligible"
    INVALID_SIGNATURE = "invalid_signature"
    SUBMITTED_AFTER_RECEIVED = "submitted_after_received"
    SUBMITTED_AFTER_DEADLINE = "submitted_after_deadline"
    RECEIVED_AFTER_DEADLINE = "received_after_deadline"
    REPLAYED_BID_ID = "replayed_bid_id"
    DUPLICATE_MERCHANT_BID = "duplicate_merchant_bid"


def evaluate_stateless_admission(
    signed_bid: SignedMerchantBid,
    policy: BuyerPolicy,
    context: AdmissionContext,
) -> AdmissionRejectionCode | None:
    """Return the first stateless rejection in the frozen protocol order."""
    bid = signed_bid.bid

    if bid.market_id != policy.market_spec.market_id:
        return AdmissionRejectionCode.WRONG_MARKET

    if bid.buyer_policy_commitment != buyer_policy_commitment(policy):
        return AdmissionRejectionCode.POLICY_COMMITMENT_MISMATCH

    merchant_identity: MerchantIdentity | None = None
    for candidate in policy.eligible_merchants:
        if candidate.merchant_id == bid.merchant_id:
            merchant_identity = candidate
            break

    if merchant_identity is None:
        return AdmissionRejectionCode.MERCHANT_NOT_ELIGIBLE

    if not verify_merchant_bid_signature(signed_bid, merchant_identity):
        return AdmissionRejectionCode.INVALID_SIGNATURE

    if bid.submitted_at > context.received_at:
        return AdmissionRejectionCode.SUBMITTED_AFTER_RECEIVED

    if bid.submitted_at > policy.bid_deadline:
        return AdmissionRejectionCode.SUBMITTED_AFTER_DEADLINE

    if context.received_at > policy.bid_deadline:
        return AdmissionRejectionCode.RECEIVED_AFTER_DEADLINE

    return None
