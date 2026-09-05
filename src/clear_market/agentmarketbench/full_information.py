"""Independent full-information economic reference comparator."""

from dataclasses import dataclass

from clear_market.agentmarketbench.admission import _admit_with_reports
from clear_market.agentmarketbench.method_models import (
    AgentMarketBenchAdmissionV1,
    AgentMarketBenchDecisionLineV1,
    AgentMarketBenchMethodResultV1,
    AgentMarketBenchMethodStatusV1,
)
from clear_market.agentmarketbench.models import (
    AgentMarketBenchBaselineV1,
    AgentMarketBenchCaseV1,
    AgentMarketBenchLatentLineV1,
)
from clear_market.agentmarketbench.protocol import agent_market_bench_market_input_v1
from clear_market.commerce import ComparisonOperator, HardConstraint, SoftPreference
from clear_market.domain import Money


@dataclass(frozen=True, slots=True)
class _OracleLine:
    merchant_id: str
    sku_id: str
    capacity: int
    unit_cost_paise: int
    unit_value_paise: int
    soft_match_count: int
    latent_line: AgentMarketBenchLatentLineV1

    @property
    def key(self) -> tuple[str, str]:
        return (self.merchant_id, self.sku_id)


@dataclass(frozen=True, slots=True)
class _State:
    welfare: int
    soft_score: int
    vector: tuple[int, ...]


def _compare(actual: object, expected: object, operator: ComparisonOperator) -> bool:
    if operator is ComparisonOperator.EQ:
        return actual == expected
    if operator is ComparisonOperator.NE:
        return actual != expected
    if type(actual) is not int or type(expected) is not int:
        return False
    if operator is ComparisonOperator.LT:
        return actual < expected
    if operator is ComparisonOperator.LTE:
        return actual <= expected
    if operator is ComparisonOperator.GT:
        return actual > expected
    if operator is ComparisonOperator.GTE:
        return actual >= expected
    return False


def _latent_matches(
    line: _OracleLine,
    rule: HardConstraint | SoftPreference,
) -> bool:
    attribute = next(
        (
            item
            for item in line.latent_line.true_attributes
            if item.attribute_key == rule.attribute_key
        ),
        None,
    )
    if attribute is None or attribute.value.value_type is not rule.operand.value_type:
        return False
    return _compare(attribute.value.value, rule.operand.value, rule.operator)


def _zero_result(
    market_id: str,
    admission: AgentMarketBenchAdmissionV1,
) -> AgentMarketBenchMethodResultV1:
    return AgentMarketBenchMethodResultV1(
        method=AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE,
        market_id=market_id,
        status=AgentMarketBenchMethodStatusV1.INFEASIBLE,
        admission=admission,
        fulfilled_quantity=0,
        total_payment=Money(amount_paise=0),
        winner_count=0,
        lines=(),
    )


def run_agent_market_bench_full_information_oracle_v1(
    case: AgentMarketBenchCaseV1,
) -> AgentMarketBenchMethodResultV1:
    """Run the latent-truth reference comparator for one exactly typed case."""

    if type(case) is not AgentMarketBenchCaseV1:
        raise TypeError("case must be exactly an AgentMarketBenchCaseV1")
    try:
        fresh_case = AgentMarketBenchCaseV1.model_validate(case)
    except Exception as error:
        raise ValueError("case failed fresh validation") from error

    market_input = agent_market_bench_market_input_v1(fresh_case)
    admitted_reports, admission = _admit_with_reports(market_input)
    market_id = fresh_case.buyer_policy.market_spec.market_id
    admitted_merchants = {report.signed_offer.offer.merchant_id for report in admitted_reports}

    latent_by_key = {(line.merchant_id, line.sku_id): line for line in fresh_case.latent_lines}
    candidates: list[_OracleLine] = []
    for latent_key, latent in sorted(latent_by_key.items()):
        if latent_key[0] not in admitted_merchants:
            continue
        candidate = _OracleLine(
            merchant_id=latent.merchant_id,
            sku_id=latent.sku_id,
            capacity=min(
                latent.true_available_quantity,
                fresh_case.buyer_policy.market_spec.requested_quantity,
            ),
            unit_cost_paise=latent.true_unit_cost.amount_paise,
            unit_value_paise=latent.true_unit_buyer_value.amount_paise,
            soft_match_count=0,
            latent_line=latent,
        )
        if not all(
            _latent_matches(candidate, rule)
            for rule in fresh_case.buyer_policy.market_spec.hard_constraints
        ):
            continue
        candidates.append(
            _OracleLine(
                merchant_id=candidate.merchant_id,
                sku_id=candidate.sku_id,
                capacity=candidate.capacity,
                unit_cost_paise=candidate.unit_cost_paise,
                unit_value_paise=candidate.unit_value_paise,
                soft_match_count=sum(
                    _latent_matches(candidate, preference)
                    for preference in fresh_case.buyer_policy.market_spec.soft_preferences
                ),
                latent_line=candidate.latent_line,
            )
        )

    lines = tuple(candidates)
    if not lines:
        return _zero_result(market_id, admission)

    merchant_ids = tuple(sorted({line.merchant_id for line in lines}))
    merchant_bits = {merchant_id: 1 << index for index, merchant_id in enumerate(merchant_ids)}
    requested = fresh_case.buyer_policy.market_spec.requested_quantity
    minimum = fresh_case.buyer_policy.market_spec.minimum_acceptable_quantity
    budget = fresh_case.buyer_policy.max_total_payment.amount_paise

    # Each state is keyed by exact quantity, exact reference cost, and winner set.
    states: dict[tuple[int, int, int], _State] = {(0, 0, 0): _State(0, 0, ())}
    for line in lines:
        next_states: dict[tuple[int, int, int], _State] = {}
        bit = merchant_bits[line.merchant_id]
        unit_welfare = line.unit_value_paise - line.unit_cost_paise
        for (quantity, cost, winner_mask), state in states.items():
            for allocation in range(line.capacity + 1):
                new_quantity = quantity + allocation
                if new_quantity > requested:
                    break
                new_cost = cost + allocation * line.unit_cost_paise
                if new_cost > budget:
                    continue
                new_mask = winner_mask | (bit if allocation else 0)
                if new_mask.bit_count() > fresh_case.buyer_policy.market_spec.max_winners:
                    continue
                state_key = (new_quantity, new_cost, new_mask)
                candidate_state = _State(
                    welfare=state.welfare + allocation * unit_welfare,
                    soft_score=state.soft_score + allocation * line.soft_match_count,
                    vector=(*state.vector, allocation),
                )
                previous = next_states.get(state_key)
                if previous is None or (
                    candidate_state.welfare,
                    candidate_state.soft_score,
                    candidate_state.vector,
                ) > (previous.welfare, previous.soft_score, previous.vector):
                    next_states[state_key] = candidate_state
        states = next_states

    best: tuple[tuple[int, int, int, int, tuple[int, ...]], _State, int, int] | None = None
    for (quantity, cost, _winner_mask), state in states.items():
        if quantity < minimum or quantity == 0:
            continue
        objective = (
            state.welfare,
            quantity,
            state.soft_score,
            -cost,
            state.vector,
        )
        if best is None or objective > best[0]:
            best = (objective, state, quantity, cost)
    if best is None:
        return _zero_result(market_id, admission)

    _, state, quantity, cost = best
    decisions = []
    for line, allocation in zip(lines, state.vector, strict=True):
        if allocation <= 0:
            continue
        unit_payment = Money(amount_paise=line.unit_cost_paise)
        decisions.append(
            AgentMarketBenchDecisionLineV1(
                source_offer_id=None,
                merchant_id=line.merchant_id,
                sku_id=line.sku_id,
                allocated_quantity=allocation,
                unit_payment=unit_payment,
                line_payment=unit_payment.checked_multiply(allocation),
            )
        )
    return AgentMarketBenchMethodResultV1(
        method=AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE,
        market_id=market_id,
        status=AgentMarketBenchMethodStatusV1.FEASIBLE,
        admission=admission,
        fulfilled_quantity=quantity,
        total_payment=Money(amount_paise=cost),
        winner_count=len({line.merchant_id for line in decisions}),
        lines=tuple(decisions),
    )


__all__ = ("run_agent_market_bench_full_information_oracle_v1",)
