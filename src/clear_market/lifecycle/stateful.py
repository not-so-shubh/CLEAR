from pydantic import BaseModel, ConfigDict

from clear_market.domain import BuyerPolicy, SignedMerchantBid
from clear_market.lifecycle.admission import (
    AdmissionContext,
    AdmissionRejectionCode,
    evaluate_stateless_admission,
)


class AdmissionDecision(BaseModel):
    """Immutable evidence for one accepted or rejected admission attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signed_bid: SignedMerchantBid
    context: AdmissionContext
    rejection_code: AdmissionRejectionCode | None


class AdmissionState:
    """In-memory accepted-bid state permanently scoped to one immutable policy."""

    __slots__ = ("_accepted_by_merchant", "_policy")

    _accepted_by_merchant: dict[str, AdmissionDecision]
    _policy: BuyerPolicy

    def __init__(self, policy: BuyerPolicy) -> None:
        if not isinstance(policy, BuyerPolicy):
            raise TypeError("policy must be a BuyerPolicy")

        self._policy = policy
        self._accepted_by_merchant = {}

    @property
    def policy(self) -> BuyerPolicy:
        return self._policy

    @property
    def accepted_decisions(self) -> tuple[AdmissionDecision, ...]:
        """Return a deterministic immutable snapshot, independent of insertion order."""
        return tuple(
            sorted(
                self._accepted_by_merchant.values(),
                key=lambda decision: decision.signed_bid.bid.merchant_id,
            )
        )


def admit_signed_bid(
    state: AdmissionState,
    signed_bid: SignedMerchantBid,
    context: AdmissionContext,
) -> AdmissionDecision:
    """Admit once or return the first rejection without changing accepted state."""
    rejection_code = evaluate_stateless_admission(signed_bid, state.policy, context)
    if rejection_code is not None:
        return AdmissionDecision(
            signed_bid=signed_bid,
            context=context,
            rejection_code=rejection_code,
        )

    bid = signed_bid.bid
    if any(
        decision.signed_bid.bid.bid_id == bid.bid_id
        for decision in state._accepted_by_merchant.values()
    ):
        return AdmissionDecision(
            signed_bid=signed_bid,
            context=context,
            rejection_code=AdmissionRejectionCode.REPLAYED_BID_ID,
        )

    if bid.merchant_id in state._accepted_by_merchant:
        return AdmissionDecision(
            signed_bid=signed_bid,
            context=context,
            rejection_code=AdmissionRejectionCode.DUPLICATE_MERCHANT_BID,
        )

    decision = AdmissionDecision(
        signed_bid=signed_bid,
        context=context,
        rejection_code=None,
    )
    state._accepted_by_merchant[bid.merchant_id] = decision
    return decision
