from collections.abc import Sequence
from dataclasses import dataclass
from typing import Never

from ortools.sat.python import cp_model
from pydantic import ValidationError

from clear_market.commerce.authentication import SignedMerchantOfferV2
from clear_market.commerce.catalog import CatalogAttributeV2
from clear_market.commerce.constraints import ComparisonOperator, HardConstraint, SoftPreference
from clear_market.commerce.market import BuyerPolicyV2
from clear_market.commerce.merchant import MerchantOfferLineV2, buyer_policy_v2_commitment
from clear_market.commerce.primitives import AttributeValueType
from clear_market.domain import Money
from clear_market.mechanism.v2.contracts import (
    HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION,
    QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION,
    AllocationLineV2,
    AllocationStatusV2,
    AllocationV2,
    MechanismV2Error,
    MechanismV2ErrorCode,
)


@dataclass(frozen=True, slots=True)
class _QualifiedLine:
    offer_id: str
    merchant_id: str
    sku_id: str
    raw_capacity: int
    effective_max: int
    unit_price_paise: int
    soft_match_count: int


@dataclass(frozen=True, slots=True)
class _SolverResult:
    status: cp_model.CpSolverStatus
    solver: cp_model.CpSolver


@dataclass(frozen=True, slots=True)
class _ModelState:
    model: cp_model.CpModel
    quantity_variables: tuple[cp_model.IntVar, ...]
    fulfilled_quantity: cp_model.IntVar
    total_payment_paise: cp_model.IntVar
    soft_preference_unit_score: cp_model.IntVar


def _raise_mechanism_error(code: MechanismV2ErrorCode) -> Never:
    raise MechanismV2Error(code)


def _fresh_buyer_policy(value: object) -> BuyerPolicyV2:
    if type(value) is not BuyerPolicyV2:
        _raise_mechanism_error(MechanismV2ErrorCode.INVALID_BUYER_POLICY)
    try:
        return BuyerPolicyV2.model_validate(value.model_dump(mode="python", warnings=False))
    except ValidationError:
        _raise_mechanism_error(MechanismV2ErrorCode.INVALID_BUYER_POLICY)


def _fresh_signed_offers(value: object) -> tuple[SignedMerchantOfferV2, ...]:
    if type(value) is not tuple:
        _raise_mechanism_error(MechanismV2ErrorCode.INVALID_SIGNED_OFFER)
    if any(type(item) is not SignedMerchantOfferV2 for item in value):
        _raise_mechanism_error(MechanismV2ErrorCode.INVALID_SIGNED_OFFER)

    validated: list[SignedMerchantOfferV2] = []
    for item in value:
        try:
            validated.append(
                SignedMerchantOfferV2.model_validate(item.model_dump(mode="python", warnings=False))
            )
        except ValidationError:
            _raise_mechanism_error(MechanismV2ErrorCode.INVALID_SIGNED_OFFER)
    return tuple(validated)


def _validate_inputs(
    *,
    buyer_policy: object,
    signed_offers: object,
) -> tuple[BuyerPolicyV2, tuple[SignedMerchantOfferV2, ...], str]:
    policy = _fresh_buyer_policy(buyer_policy)
    if policy.mechanism_version != HETEROGENEOUS_PAY_AS_BID_V2_MECHANISM_VERSION:
        _raise_mechanism_error(MechanismV2ErrorCode.UNSUPPORTED_MECHANISM_VERSION)
    if policy.objective_version != QUANTITY_COST_SOFT_OBJECTIVE_V2_VERSION:
        _raise_mechanism_error(MechanismV2ErrorCode.UNSUPPORTED_OBJECTIVE_VERSION)

    offers = tuple(
        sorted(
            _fresh_signed_offers(signed_offers),
            key=lambda signed: (signed.offer.merchant_id, signed.offer.offer_id),
        )
    )
    offer_ids = tuple(signed.offer.offer_id for signed in offers)
    if len(set(offer_ids)) != len(offer_ids):
        _raise_mechanism_error(MechanismV2ErrorCode.DUPLICATE_OFFER_ID)
    merchant_ids = tuple(signed.offer.merchant_id for signed in offers)
    if len(set(merchant_ids)) != len(merchant_ids):
        _raise_mechanism_error(MechanismV2ErrorCode.DUPLICATE_MERCHANT_OFFER)
    if any(merchant_id not in policy.eligible_merchant_ids for merchant_id in merchant_ids):
        _raise_mechanism_error(MechanismV2ErrorCode.MERCHANT_NOT_ELIGIBLE)
    if any(signed.offer.market_id != policy.market_spec.market_id for signed in offers):
        _raise_mechanism_error(MechanismV2ErrorCode.MARKET_ID_MISMATCH)

    expected_commitment = buyer_policy_v2_commitment(policy)
    if any(signed.offer.buyer_policy_commitment_sha256 != expected_commitment for signed in offers):
        _raise_mechanism_error(MechanismV2ErrorCode.BUYER_POLICY_COMMITMENT_MISMATCH)
    return policy, offers, expected_commitment


def _attribute_satisfies_rule(
    attributes: tuple[CatalogAttributeV2, ...],
    rule: HardConstraint | SoftPreference,
) -> bool:
    attribute = next(
        (candidate for candidate in attributes if candidate.attribute_key == rule.attribute_key),
        None,
    )
    if attribute is None or attribute.provenance not in rule.allowed_provenance:
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


def _hard_qualifies(line: MerchantOfferLineV2, constraints: tuple[HardConstraint, ...]) -> bool:
    return all(_attribute_satisfies_rule(line.attributes, rule) for rule in constraints)


def _soft_match_count(
    line: MerchantOfferLineV2,
    preferences: tuple[SoftPreference, ...],
) -> int:
    return sum(_attribute_satisfies_rule(line.attributes, rule) for rule in preferences)


def _qualified_lines(
    policy: BuyerPolicyV2,
    offers: tuple[SignedMerchantOfferV2, ...],
) -> tuple[_QualifiedLine, ...]:
    requested_quantity = policy.market_spec.requested_quantity
    budget = policy.max_total_payment.amount_paise
    qualified: list[_QualifiedLine] = []
    for signed in offers:
        offer = signed.offer
        for line in offer.lines:
            if not _hard_qualifies(line, policy.market_spec.hard_constraints):
                continue
            price = line.unit_price.amount_paise
            effective_max = min(line.max_offer_quantity, requested_quantity)
            if price > 0:
                effective_max = min(effective_max, budget // price)
            qualified.append(
                _QualifiedLine(
                    offer_id=offer.offer_id,
                    merchant_id=offer.merchant_id,
                    sku_id=line.sku_id,
                    raw_capacity=line.max_offer_quantity,
                    effective_max=effective_max,
                    unit_price_paise=price,
                    soft_match_count=_soft_match_count(
                        line,
                        policy.market_spec.soft_preferences,
                    ),
                )
            )
    return tuple(
        sorted(
            qualified,
            key=lambda line: (line.merchant_id, line.sku_id, line.offer_id),
        )
    )


def _build_model(policy: BuyerPolicyV2, lines: tuple[_QualifiedLine, ...]) -> _ModelState:
    model = cp_model.CpModel()
    quantity_variables = tuple(
        model.new_int_var(0, line.effective_max, f"line_quantity_{index}")
        for index, line in enumerate(lines)
    )

    requested_quantity = policy.market_spec.requested_quantity
    fulfilled_quantity = model.new_int_var(0, requested_quantity, "fulfilled_quantity")
    model.add(fulfilled_quantity == sum(quantity_variables))
    model.add(fulfilled_quantity >= policy.market_spec.minimum_acceptable_quantity)

    budget = policy.max_total_payment.amount_paise
    total_payment_paise = model.new_int_var(0, budget, "total_payment_paise")
    model.add(
        total_payment_paise
        == sum(
            line.unit_price_paise * variable
            for line, variable in zip(lines, quantity_variables, strict=True)
        )
    )

    maximum_soft_score = requested_quantity * len(policy.market_spec.soft_preferences)
    soft_preference_unit_score = model.new_int_var(
        0,
        maximum_soft_score,
        "soft_preference_unit_score",
    )
    model.add(
        soft_preference_unit_score
        == sum(
            line.soft_match_count * variable
            for line, variable in zip(lines, quantity_variables, strict=True)
        )
    )

    merchant_indices: dict[str, list[int]] = {}
    for index, line in enumerate(lines):
        merchant_indices.setdefault(line.merchant_id, []).append(index)
    winner_variables: list[cp_model.IntVar] = []
    for merchant_index, merchant_id in enumerate(sorted(merchant_indices)):
        indices = merchant_indices[merchant_id]
        upper_bound = min(
            requested_quantity,
            sum(lines[index].effective_max for index in indices),
        )
        merchant_quantity = model.new_int_var(
            0,
            upper_bound,
            f"merchant_quantity_{merchant_index}",
        )
        model.add(merchant_quantity == sum(quantity_variables[index] for index in indices))
        winner = model.new_bool_var(f"winner_{merchant_index}")
        model.add(merchant_quantity <= upper_bound * winner)
        model.add(merchant_quantity >= winner)
        winner_variables.append(winner)
    model.add(sum(winner_variables) <= policy.market_spec.max_winners)

    return _ModelState(
        model=model,
        quantity_variables=quantity_variables,
        fulfilled_quantity=fulfilled_quantity,
        total_payment_paise=total_payment_paise,
        soft_preference_unit_score=soft_preference_unit_score,
    )


def _new_solver() -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.randomize_search = False
    return solver


def _solve_model(model: cp_model.CpModel) -> _SolverResult:
    solver = _new_solver()
    return _SolverResult(status=solver.solve(model), solver=solver)


def _require_optimal(result: _SolverResult) -> cp_model.CpSolver:
    if result.status != cp_model.OPTIMAL:
        _raise_mechanism_error(MechanismV2ErrorCode.SOLVER_FAILURE)
    return result.solver


def _replace_maximize(model: cp_model.CpModel, expression: cp_model.LinearExprT) -> None:
    model.clear_objective()  # type: ignore[no-untyped-call]
    model.maximize(expression)


def _replace_minimize(model: cp_model.CpModel, expression: cp_model.LinearExprT) -> None:
    model.clear_objective()  # type: ignore[no-untyped-call]
    model.minimize(expression)


def _optimize(state: _ModelState) -> tuple[tuple[int, ...], int, int, int]:
    _replace_maximize(state.model, state.fulfilled_quantity)
    phase_one = _solve_model(state.model)
    if phase_one.status == cp_model.INFEASIBLE:
        return (), 0, 0, 0
    solver = _require_optimal(phase_one)
    optimal_quantity = solver.value(state.fulfilled_quantity)
    state.model.add(state.fulfilled_quantity == optimal_quantity)

    _replace_minimize(state.model, state.total_payment_paise)
    solver = _require_optimal(_solve_model(state.model))
    optimal_payment = solver.value(state.total_payment_paise)
    state.model.add(state.total_payment_paise == optimal_payment)

    _replace_maximize(state.model, state.soft_preference_unit_score)
    solver = _require_optimal(_solve_model(state.model))
    optimal_soft_score = solver.value(state.soft_preference_unit_score)
    state.model.add(state.soft_preference_unit_score == optimal_soft_score)

    quantities: list[int] = []
    for variable in state.quantity_variables:
        _replace_maximize(state.model, variable)
        solver = _require_optimal(_solve_model(state.model))
        quantity = solver.value(variable)
        quantities.append(quantity)
        state.model.add(variable == quantity)
    return tuple(quantities), optimal_quantity, optimal_payment, optimal_soft_score


def _feasible_allocation(
    *,
    policy: BuyerPolicyV2,
    commitment: str,
    lines: Sequence[_QualifiedLine],
    quantities: Sequence[int],
    fulfilled_quantity: int,
    total_payment_paise: int,
    soft_score: int,
) -> AllocationV2:
    allocation_lines: list[AllocationLineV2] = []
    for line, quantity in zip(lines, quantities, strict=True):
        if quantity == 0:
            continue
        unit_payment = Money(amount_paise=line.unit_price_paise)
        allocation_lines.append(
            AllocationLineV2(
                offer_id=line.offer_id,
                merchant_id=line.merchant_id,
                sku_id=line.sku_id,
                allocated_quantity=quantity,
                unit_payment=unit_payment,
                line_payment=unit_payment.checked_multiply(quantity),
            )
        )
    return AllocationV2(
        market_id=policy.market_spec.market_id,
        buyer_policy_commitment_sha256=commitment,
        status=AllocationStatusV2.FEASIBLE,
        fulfilled_quantity=fulfilled_quantity,
        total_payment=Money(amount_paise=total_payment_paise),
        soft_preference_unit_score=soft_score,
        winner_count=len({line.merchant_id for line in allocation_lines}),
        lines=tuple(allocation_lines),
    )


def _infeasible_allocation(*, policy: BuyerPolicyV2, commitment: str) -> AllocationV2:
    return AllocationV2(
        market_id=policy.market_spec.market_id,
        buyer_policy_commitment_sha256=commitment,
        status=AllocationStatusV2.INFEASIBLE,
        fulfilled_quantity=0,
        total_payment=Money(amount_paise=0),
        soft_preference_unit_score=0,
        winner_count=0,
        lines=(),
    )


def allocate_market_v2(
    *,
    buyer_policy: BuyerPolicyV2,
    signed_offers: tuple[SignedMerchantOfferV2, ...],
) -> AllocationV2:
    """Allocate structurally valid offers; this does not verify signatures or authorize money."""
    policy, offers, commitment = _validate_inputs(
        buyer_policy=buyer_policy,
        signed_offers=signed_offers,
    )
    lines = _qualified_lines(policy, offers)
    state = _build_model(policy, lines)
    quantities, fulfilled_quantity, total_payment_paise, soft_score = _optimize(state)
    if not quantities:
        return _infeasible_allocation(policy=policy, commitment=commitment)
    return _feasible_allocation(
        policy=policy,
        commitment=commitment,
        lines=lines,
        quantities=quantities,
        fulfilled_quantity=fulfilled_quantity,
        total_payment_paise=total_payment_paise,
        soft_score=soft_score,
    )
