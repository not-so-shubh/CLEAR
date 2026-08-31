from clear_market.crypto import buyer_policy_commitment
from clear_market.domain import Money
from clear_market.lifecycle import AdmissionState
from clear_market.mechanism.allocation import Allocation, AllocationStatus


def allocate_market(state: AdmissionState) -> Allocation:
    """Apply the frozen economic eligibility, ranking, and payment rules."""
    if not isinstance(state, AdmissionState):
        raise TypeError("state must be an AdmissionState")

    policy = state.policy
    eligible_bids = sorted(
        (
            decision.signed_bid.bid
            for decision in state.accepted_decisions
            if decision.signed_bid.bid.quantity_available >= policy.market_spec.requested_quantity
            and decision.signed_bid.bid.unit_price_paise <= policy.reserve_unit_price.amount_paise
        ),
        key=lambda bid: (bid.unit_price_paise, bid.merchant_id),
    )
    policy_commitment = buyer_policy_commitment(policy)

    if not eligible_bids:
        return Allocation(
            market_id=policy.market_spec.market_id,
            buyer_policy_commitment=policy_commitment,
            mechanism_version=policy.mechanism_version,
            status=AllocationStatus.INFEASIBLE,
        )

    winner = eligible_bids[0]
    winning_unit_price = Money(amount_paise=winner.unit_price_paise)
    payment_unit_price = (
        Money(amount_paise=eligible_bids[1].unit_price_paise)
        if len(eligible_bids) >= 2
        else policy.reserve_unit_price
    )
    total_payment = payment_unit_price.checked_multiply(policy.market_spec.requested_quantity)

    return Allocation(
        market_id=policy.market_spec.market_id,
        buyer_policy_commitment=policy_commitment,
        mechanism_version=policy.mechanism_version,
        status=AllocationStatus.FEASIBLE,
        winner_merchant_id=winner.merchant_id,
        winning_bid_id=winner.bid_id,
        allocated_quantity=policy.market_spec.requested_quantity,
        winning_unit_price=winning_unit_price,
        payment_unit_price=payment_unit_price,
        total_payment=total_payment,
    )
