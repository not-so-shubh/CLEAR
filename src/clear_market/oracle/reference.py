from clear_market.crypto import buyer_policy_commitment
from clear_market.domain import MerchantBid, Money
from clear_market.lifecycle import AdmissionState
from clear_market.oracle.models import OracleAllocation, OracleAllocationStatus


def _economic_rank(bid: MerchantBid) -> tuple[int, str]:
    return bid.unit_price_paise, bid.merchant_id


def compute_oracle_allocation(state: AdmissionState) -> OracleAllocation:
    """Independently scan, select, and price accepted bids under the frozen rule."""
    if not isinstance(state, AdmissionState):
        raise TypeError("state must be an AdmissionState")

    policy = state.policy
    requested_quantity = policy.market_spec.requested_quantity
    reserve_amount = policy.reserve_unit_price.amount_paise
    eligible_bids: list[MerchantBid] = []

    for decision in state.accepted_decisions:
        bid = decision.signed_bid.bid
        enough_quantity = bid.quantity_available >= requested_quantity
        within_reserve = bid.unit_price_paise <= reserve_amount
        if enough_quantity and within_reserve:
            eligible_bids.append(bid)

    commitment = buyer_policy_commitment(policy)
    if not eligible_bids:
        return OracleAllocation(
            market_id=policy.market_spec.market_id,
            buyer_policy_commitment=commitment,
            mechanism_version=policy.mechanism_version,
            status=OracleAllocationStatus.INFEASIBLE,
        )

    winner = min(eligible_bids, key=_economic_rank)
    if len(eligible_bids) == 1:
        payment_unit_price = policy.reserve_unit_price
    else:
        second_ranked = min(
            (bid for bid in eligible_bids if bid.merchant_id != winner.merchant_id),
            key=_economic_rank,
        )
        payment_unit_price = Money(amount_paise=second_ranked.unit_price_paise)

    winning_unit_price = Money(amount_paise=winner.unit_price_paise)
    total_payment = payment_unit_price.checked_multiply(requested_quantity)

    return OracleAllocation(
        market_id=policy.market_spec.market_id,
        buyer_policy_commitment=commitment,
        mechanism_version=policy.mechanism_version,
        status=OracleAllocationStatus.FEASIBLE,
        winner_merchant_id=winner.merchant_id,
        winning_bid_id=winner.bid_id,
        allocated_quantity=requested_quantity,
        winning_unit_price=winning_unit_price,
        payment_unit_price=payment_unit_price,
        total_payment=total_payment,
    )
