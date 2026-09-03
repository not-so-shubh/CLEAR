from dataclasses import dataclass
from heapq import merge
from itertools import combinations
from typing import Never

from pydantic import ValidationError

from clear_market.commerce.authentication import SignedMerchantOfferV2
from clear_market.commerce.catalog import CatalogAttributeV2
from clear_market.commerce.constraints import ComparisonOperator, HardConstraint, SoftPreference
from clear_market.commerce.market import BuyerPolicyV2
from clear_market.commerce.merchant import MerchantOfferLineV2, buyer_policy_v2_commitment
from clear_market.commerce.primitives import AttributeValueType
from clear_market.domain import Money
from clear_market.oracle.v2.models import (
    OracleAllocationLineV2,
    OracleAllocationStatusV2,
    OracleAllocationV2,
    OracleV2Error,
    OracleV2ErrorCode,
)

_MECHANISM_VERSION = "heterogeneous-pay-as-bid-v2"
_OBJECTIVE_VERSION = "quantity-cost-soft-objective-v2"


@dataclass(frozen=True, slots=True)
class _OracleLine:
    offer_id: str
    merchant_id: str
    sku_id: str
    capacity: int
    unit_price_paise: int
    soft_match_count: int
    canonical_index: int

    @property
    def canonical_key(self) -> tuple[str, str, str]:
        return self.merchant_id, self.sku_id, self.offer_id

    @property
    def selection_key(self) -> tuple[int, int, tuple[str, str, str]]:
        return self.unit_price_paise, -self.soft_match_count, self.canonical_key


@dataclass(frozen=True, slots=True)
class _Candidate:
    quantities: tuple[int, ...]
    fulfilled_quantity: int
    total_payment_paise: int
    soft_preference_unit_score: int
    winner_merchant_ids: frozenset[str]

    @property
    def objective(self) -> tuple[int, int, int, tuple[int, ...]]:
        return (
            self.fulfilled_quantity,
            -self.total_payment_paise,
            self.soft_preference_unit_score,
            self.quantities,
        )


def _raise_oracle_error(code: OracleV2ErrorCode) -> Never:
    raise OracleV2Error(code)


def _fresh_buyer_policy(value: object) -> BuyerPolicyV2:
    if type(value) is not BuyerPolicyV2:
        _raise_oracle_error(OracleV2ErrorCode.INVALID_BUYER_POLICY)
    try:
        return BuyerPolicyV2.model_validate(value.model_dump(mode="python", warnings=False))
    except (AttributeError, ValidationError):
        _raise_oracle_error(OracleV2ErrorCode.INVALID_BUYER_POLICY)


def _fresh_signed_offers(value: object) -> tuple[SignedMerchantOfferV2, ...]:
    if type(value) is not tuple:
        _raise_oracle_error(OracleV2ErrorCode.INVALID_SIGNED_OFFER)
    if any(type(item) is not SignedMerchantOfferV2 for item in value):
        _raise_oracle_error(OracleV2ErrorCode.INVALID_SIGNED_OFFER)

    validated: list[SignedMerchantOfferV2] = []
    for item in value:
        try:
            validated.append(
                SignedMerchantOfferV2.model_validate(item.model_dump(mode="python", warnings=False))
            )
        except (AttributeError, ValidationError):
            _raise_oracle_error(OracleV2ErrorCode.INVALID_SIGNED_OFFER)
    return tuple(validated)


def _validate_inputs(
    *,
    buyer_policy: object,
    signed_offers: object,
) -> tuple[BuyerPolicyV2, tuple[SignedMerchantOfferV2, ...], str]:
    policy = _fresh_buyer_policy(buyer_policy)
    if policy.mechanism_version != _MECHANISM_VERSION:
        _raise_oracle_error(OracleV2ErrorCode.UNSUPPORTED_MECHANISM_VERSION)
    if policy.objective_version != _OBJECTIVE_VERSION:
        _raise_oracle_error(OracleV2ErrorCode.UNSUPPORTED_OBJECTIVE_VERSION)

    offers = tuple(
        sorted(
            _fresh_signed_offers(signed_offers),
            key=lambda signed: (signed.offer.merchant_id, signed.offer.offer_id),
        )
    )
    offer_ids = tuple(signed.offer.offer_id for signed in offers)
    if len(set(offer_ids)) != len(offer_ids):
        _raise_oracle_error(OracleV2ErrorCode.DUPLICATE_OFFER_ID)
    merchant_ids = tuple(signed.offer.merchant_id for signed in offers)
    if len(set(merchant_ids)) != len(merchant_ids):
        _raise_oracle_error(OracleV2ErrorCode.DUPLICATE_MERCHANT_OFFER)
    if any(merchant_id not in policy.eligible_merchant_ids for merchant_id in merchant_ids):
        _raise_oracle_error(OracleV2ErrorCode.MERCHANT_NOT_ELIGIBLE)
    if any(signed.offer.market_id != policy.market_spec.market_id for signed in offers):
        _raise_oracle_error(OracleV2ErrorCode.MARKET_ID_MISMATCH)

    commitment = buyer_policy_v2_commitment(policy)
    if any(signed.offer.buyer_policy_commitment_sha256 != commitment for signed in offers):
        _raise_oracle_error(OracleV2ErrorCode.BUYER_POLICY_COMMITMENT_MISMATCH)
    return policy, offers, commitment


def _attribute_satisfies_rule(
    attributes: tuple[CatalogAttributeV2, ...],
    rule: HardConstraint | SoftPreference,
) -> bool:
    attribute = next(
        (candidate for candidate in attributes if candidate.attribute_key == rule.attribute_key),
        None,
    )
    if attribute is None:
        return False
    if attribute.provenance not in rule.allowed_provenance:
        return False
    if attribute.value.value_type is not rule.operand.value_type:
        return False

    actual = attribute.value.value
    expected = rule.operand.value
    if rule.operator is ComparisonOperator.EQ:
        return actual == expected
    if rule.operator is ComparisonOperator.NE:
        return actual != expected
    if (
        attribute.value.value_type is not AttributeValueType.INTEGER
        or type(actual) is not int
        or type(expected) is not int
    ):
        return False
    if rule.operator is ComparisonOperator.LT:
        return actual < expected
    if rule.operator is ComparisonOperator.LTE:
        return actual <= expected
    if rule.operator is ComparisonOperator.GT:
        return actual > expected
    if rule.operator is ComparisonOperator.GTE:
        return actual >= expected
    return False


def _line_satisfies_hard_constraints(
    line: MerchantOfferLineV2,
    constraints: tuple[HardConstraint, ...],
) -> bool:
    return all(_attribute_satisfies_rule(line.attributes, rule) for rule in constraints)


def _preference_count(
    line: MerchantOfferLineV2,
    preferences: tuple[SoftPreference, ...],
) -> int:
    return sum(_attribute_satisfies_rule(line.attributes, rule) for rule in preferences)


def _oracle_lines(
    policy: BuyerPolicyV2,
    offers: tuple[SignedMerchantOfferV2, ...],
) -> tuple[_OracleLine, ...]:
    qualifying: list[tuple[str, str, str, int, int, int]] = []
    for signed in offers:
        for line in signed.offer.lines:
            if not _line_satisfies_hard_constraints(
                line,
                policy.market_spec.hard_constraints,
            ):
                continue
            qualifying.append(
                (
                    signed.offer.merchant_id,
                    line.sku_id,
                    signed.offer.offer_id,
                    line.max_offer_quantity,
                    line.unit_price.amount_paise,
                    _preference_count(line, policy.market_spec.soft_preferences),
                )
            )

    qualifying.sort(key=lambda record: record[:3])
    return tuple(
        _OracleLine(
            merchant_id=merchant_id,
            sku_id=sku_id,
            offer_id=offer_id,
            capacity=capacity,
            unit_price_paise=unit_price_paise,
            soft_match_count=soft_match_count,
            canonical_index=index,
        )
        for index, (
            merchant_id,
            sku_id,
            offer_id,
            capacity,
            unit_price_paise,
            soft_match_count,
        ) in enumerate(qualifying)
    )


def _candidate_for_allowed_merchants(
    *,
    policy: BuyerPolicyV2,
    lines: tuple[_OracleLine, ...],
    streams_by_merchant: dict[str, tuple[_OracleLine, ...]],
    allowed_merchants: tuple[str, ...],
) -> _Candidate | None:
    """Construct the exact optimum inside one allowed merchant subset.

    Cheaper units first maximize quantity under a fixed budget and then minimize payment. At one
    price, greater unit soft contribution maximizes the quantity-weighted soft score. Remaining
    ties go to the earlier canonical line, which lexicographically maximizes the full vector.
    """
    remaining_quantity = policy.market_spec.requested_quantity
    remaining_budget = policy.max_total_payment.amount_paise
    quantities = [0] * len(lines)
    total_payment_paise = 0
    soft_score = 0
    winners: set[str] = set()

    ordered_lines = merge(
        *(streams_by_merchant[merchant_id] for merchant_id in allowed_merchants),
        key=lambda line: line.selection_key,
    )
    for line in ordered_lines:
        if remaining_quantity == 0:
            break
        if line.unit_price_paise > 0 and line.unit_price_paise > remaining_budget:
            break
        affordable = (
            line.capacity
            if line.unit_price_paise == 0
            else remaining_budget // line.unit_price_paise
        )
        take = min(line.capacity, remaining_quantity, affordable)
        if take == 0:
            continue
        quantities[line.canonical_index] = take
        payment = take * line.unit_price_paise
        remaining_quantity -= take
        remaining_budget -= payment
        total_payment_paise += payment
        soft_score += take * line.soft_match_count
        winners.add(line.merchant_id)

    fulfilled_quantity = policy.market_spec.requested_quantity - remaining_quantity
    if fulfilled_quantity < policy.market_spec.minimum_acceptable_quantity:
        return None
    return _Candidate(
        quantities=tuple(quantities),
        fulfilled_quantity=fulfilled_quantity,
        total_payment_paise=total_payment_paise,
        soft_preference_unit_score=soft_score,
        winner_merchant_ids=frozenset(winners),
    )


def _search(policy: BuyerPolicyV2, lines: tuple[_OracleLine, ...]) -> _Candidate | None:
    """Enumerate exact-size allowed merchant subsets, not required-positive winner sets.

    Every legal allocation uses at most ``max_winners`` merchants. If ``k`` is the smaller of that
    cap and the qualifying merchant population, every allocation using fewer than ``k`` merchants
    is contained in at least one size-``k`` allowed set. Adding allowed merchants never removes a
    feasible allocation. Enumerating every size-``k`` set therefore covers every legal allocation;
    actual winners remain the merchants receiving positive quantity.
    """
    merchant_ids = tuple(sorted({line.merchant_id for line in lines}))
    if not merchant_ids:
        return None
    subset_size = min(policy.market_spec.max_winners, len(merchant_ids))

    streams_by_merchant: dict[str, tuple[_OracleLine, ...]] = {}
    for merchant_id in merchant_ids:
        streams_by_merchant[merchant_id] = tuple(
            sorted(
                (line for line in lines if line.merchant_id == merchant_id),
                key=lambda line: line.selection_key,
            )
        )

    best: _Candidate | None = None
    for allowed_merchants in combinations(merchant_ids, subset_size):
        candidate = _candidate_for_allowed_merchants(
            policy=policy,
            lines=lines,
            streams_by_merchant=streams_by_merchant,
            allowed_merchants=allowed_merchants,
        )
        if candidate is not None and (best is None or candidate.objective > best.objective):
            best = candidate
    return best


def _infeasible_allocation(
    *,
    policy: BuyerPolicyV2,
    commitment: str,
) -> OracleAllocationV2:
    return OracleAllocationV2(
        market_id=policy.market_spec.market_id,
        buyer_policy_commitment_sha256=commitment,
        status=OracleAllocationStatusV2.INFEASIBLE,
        fulfilled_quantity=0,
        total_payment=Money(amount_paise=0),
        soft_preference_unit_score=0,
        winner_count=0,
        lines=(),
    )


def _feasible_allocation(
    *,
    policy: BuyerPolicyV2,
    commitment: str,
    lines: tuple[_OracleLine, ...],
    candidate: _Candidate,
) -> OracleAllocationV2:
    allocation_lines: list[OracleAllocationLineV2] = []
    for line, quantity in zip(lines, candidate.quantities, strict=True):
        if quantity == 0:
            continue
        unit_payment = Money(amount_paise=line.unit_price_paise)
        allocation_lines.append(
            OracleAllocationLineV2(
                offer_id=line.offer_id,
                merchant_id=line.merchant_id,
                sku_id=line.sku_id,
                allocated_quantity=quantity,
                unit_payment=unit_payment,
                line_payment=unit_payment.checked_multiply(quantity),
            )
        )
    return OracleAllocationV2(
        market_id=policy.market_spec.market_id,
        buyer_policy_commitment_sha256=commitment,
        status=OracleAllocationStatusV2.FEASIBLE,
        fulfilled_quantity=candidate.fulfilled_quantity,
        total_payment=Money(amount_paise=candidate.total_payment_paise),
        soft_preference_unit_score=candidate.soft_preference_unit_score,
        winner_count=len(candidate.winner_merchant_ids),
        lines=tuple(allocation_lines),
    )


def compute_oracle_allocation_v2(
    *,
    buyer_policy: BuyerPolicyV2,
    signed_offers: tuple[SignedMerchantOfferV2, ...],
) -> OracleAllocationV2:
    """Compute exact independent economics without authenticating evidence or authorizing money."""
    policy, offers, commitment = _validate_inputs(
        buyer_policy=buyer_policy,
        signed_offers=signed_offers,
    )
    lines = _oracle_lines(policy, offers)
    candidate = _search(policy, lines)
    if candidate is None:
        return _infeasible_allocation(policy=policy, commitment=commitment)
    return _feasible_allocation(
        policy=policy,
        commitment=commitment,
        lines=lines,
        candidate=candidate,
    )
