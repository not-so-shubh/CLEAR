"""Latent-grounded, deterministic AgentMarketBench V1 measurements."""

from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from clear_market.agentmarketbench.admission import admit_agent_market_bench_market_input_v1
from clear_market.agentmarketbench.measurement_models import (
    AgentMarketBenchMetricNotApplicableReasonV1,
    AgentMarketBenchMetricObservationStatusV1,
    AgentMarketBenchMetricObservationV1,
    AgentMarketBenchMetricUnitV1,
    AgentMarketBenchRationalV1,
)
from clear_market.agentmarketbench.method_models import (
    AgentMarketBenchAdmissionV1,
    AgentMarketBenchMethodResultV1,
    AgentMarketBenchMethodStatusV1,
)
from clear_market.agentmarketbench.models import (
    AgentMarketBenchAdversarialScenarioV1,
    AgentMarketBenchBaselineV1,
    AgentMarketBenchCaseV1,
    AgentMarketBenchLatentLineV1,
    AgentMarketBenchMetricV1,
    AgentMarketBenchReportedOfferV1,
)
from clear_market.agentmarketbench.protocol import agent_market_bench_market_input_v1
from clear_market.commerce import (
    CatalogAttributeV2,
    ComparisonOperator,
    HardConstraint,
    SoftPreference,
)

_UNITS: dict[AgentMarketBenchMetricV1, AgentMarketBenchMetricUnitV1] = {
    AgentMarketBenchMetricV1.ALLOCATIVE_EFFICIENCY: AgentMarketBenchMetricUnitV1.RATIO,
    AgentMarketBenchMetricV1.REGRET: AgentMarketBenchMetricUnitV1.PAISE,
    AgentMarketBenchMetricV1.BUYER_SURPLUS: AgentMarketBenchMetricUnitV1.PAISE,
    AgentMarketBenchMetricV1.MERCHANT_SURPLUS: AgentMarketBenchMetricUnitV1.PAISE,
    AgentMarketBenchMetricV1.WELFARE: AgentMarketBenchMetricUnitV1.PAISE,
    AgentMarketBenchMetricV1.COMPLETION: AgentMarketBenchMetricUnitV1.RATIO,
    AgentMarketBenchMetricV1.HARD_CONSTRAINT_VIOLATIONS: AgentMarketBenchMetricUnitV1.COUNT,
    AgentMarketBenchMetricV1.MANIPULATION_SUCCESS: AgentMarketBenchMetricUnitV1.BINARY,
    AgentMarketBenchMetricV1.PAYMENT_CORRECTNESS: AgentMarketBenchMetricUnitV1.BINARY,
    AgentMarketBenchMetricV1.DUPLICATE_FINANCIAL_SIDE_EFFECTS: AgentMarketBenchMetricUnitV1.COUNT,
    AgentMarketBenchMetricV1.LATENCY: AgentMarketBenchMetricUnitV1.NANOSECONDS,
}

_RUNTIME_SCENARIOS = {
    AgentMarketBenchAdversarialScenarioV1.DUPLICATE_EVENT,
    AgentMarketBenchAdversarialScenarioV1.EVENT_REORDERING,
    AgentMarketBenchAdversarialScenarioV1.PROVIDER_TIMEOUT,
    AgentMarketBenchAdversarialScenarioV1.PAYMENT_FAILURE,
    AgentMarketBenchAdversarialScenarioV1.TRANSFER_FAILURE,
    AgentMarketBenchAdversarialScenarioV1.RETRY,
    AgentMarketBenchAdversarialScenarioV1.RECONCILIATION,
    AgentMarketBenchAdversarialScenarioV1.RECOVERY,
}


@dataclass(frozen=True, slots=True)
class AgentMarketBenchLatentRealizationV1:
    """Internal measurement result for a contractual method allocation."""

    realized_quantity: int
    realized_buyer_value_paise: int
    realized_true_cost_paise: int
    realized_welfare_paise: int
    latent_capacity_excess_units: int
    latent_hard_violation_units: int


@dataclass(frozen=True, slots=True)
class AgentMarketBenchMetricEvaluationV1:
    """Metric observations plus diagnostics used to build a method evaluation."""

    observations: tuple[AgentMarketBenchMetricObservationV1, ...]
    realization: AgentMarketBenchLatentRealizationV1


def _rational(value: Fraction | int) -> AgentMarketBenchRationalV1:
    fraction = value if isinstance(value, Fraction) else Fraction(value, 1)
    return AgentMarketBenchRationalV1(
        numerator=fraction.numerator,
        denominator=fraction.denominator,
    )


def _measured(
    metric: AgentMarketBenchMetricV1,
    value: Fraction | int,
) -> AgentMarketBenchMetricObservationV1:
    return AgentMarketBenchMetricObservationV1(
        metric=metric,
        status=AgentMarketBenchMetricObservationStatusV1.MEASURED,
        unit=_UNITS[metric],
        value=_rational(value),
        not_applicable_reason=None,
    )


def _not_applicable(
    metric: AgentMarketBenchMetricV1,
    reason: AgentMarketBenchMetricNotApplicableReasonV1,
) -> AgentMarketBenchMetricObservationV1:
    return AgentMarketBenchMetricObservationV1(
        metric=metric,
        status=AgentMarketBenchMetricObservationStatusV1.NOT_APPLICABLE,
        unit=_UNITS[metric],
        value=None,
        not_applicable_reason=reason,
    )


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


def _matches_reported(
    attributes: Iterable[CatalogAttributeV2], rule: HardConstraint | SoftPreference
) -> bool:
    attribute = next(
        (candidate for candidate in attributes if candidate.attribute_key == rule.attribute_key),
        None,
    )
    if attribute is None or attribute.provenance not in rule.allowed_provenance:
        return False
    if attribute.value.value_type is not rule.operand.value_type:
        return False
    return _compare(attribute.value.value, rule.operand.value, rule.operator)


def _matches_latent(
    latent_line: AgentMarketBenchLatentLineV1, rule: HardConstraint | SoftPreference
) -> bool:
    attribute = next(
        (
            candidate
            for candidate in latent_line.true_attributes
            if candidate.attribute_key == rule.attribute_key
        ),
        None,
    )
    if attribute is None or attribute.value.value_type is not rule.operand.value_type:
        return False
    return _compare(attribute.value.value, rule.operand.value, rule.operator)


def realize_agent_market_bench_method_v1(
    case: AgentMarketBenchCaseV1, result: AgentMarketBenchMethodResultV1
) -> AgentMarketBenchLatentRealizationV1:
    """Measure one result against latent capacities and typed latent attributes."""

    if type(case) is not AgentMarketBenchCaseV1:
        raise TypeError("case must be exactly an AgentMarketBenchCaseV1")
    if type(result) is not AgentMarketBenchMethodResultV1:
        raise TypeError("result must be exactly an AgentMarketBenchMethodResultV1")
    try:
        case = AgentMarketBenchCaseV1.model_validate(case)
        result = AgentMarketBenchMethodResultV1.model_validate(result)
    except Exception as error:
        raise ValueError("case or result failed fresh validation") from error
    latent_by_key = {(line.merchant_id, line.sku_id): line for line in case.latent_lines}
    realized_quantity = 0
    buyer_value = 0
    true_cost = 0
    capacity_excess = 0
    hard_violation = 0
    constraints = case.buyer_policy.market_spec.hard_constraints
    for decision in result.lines:
        latent = latent_by_key.get((decision.merchant_id, decision.sku_id))
        if latent is None:
            raise ValueError("method result line has no exact latent line")
        quantity = decision.allocated_quantity
        capacity_excess += max(0, quantity - latent.true_available_quantity)
        if not all(_matches_latent(latent, rule) for rule in constraints):
            hard_violation += quantity
            continue
        realized = min(quantity, latent.true_available_quantity)
        realized_quantity += realized
        buyer_value += realized * latent.true_unit_buyer_value.amount_paise
        true_cost += realized * latent.true_unit_cost.amount_paise
    return AgentMarketBenchLatentRealizationV1(
        realized_quantity=realized_quantity,
        realized_buyer_value_paise=buyer_value,
        realized_true_cost_paise=true_cost,
        realized_welfare_paise=buyer_value - true_cost,
        latent_capacity_excess_units=capacity_excess,
        latent_hard_violation_units=hard_violation,
    )


def _minimum_qualified_welfare_paise(
    case: AgentMarketBenchCaseV1,
    realization: AgentMarketBenchLatentRealizationV1,
) -> int:
    if realization.realized_quantity < case.buyer_policy.market_spec.minimum_acceptable_quantity:
        return 0
    return realization.realized_welfare_paise


def _admitted_reports(
    case: AgentMarketBenchCaseV1,
) -> tuple[tuple[AgentMarketBenchReportedOfferV1, ...], AgentMarketBenchAdmissionV1]:
    market_input = agent_market_bench_market_input_v1(case)
    admission = admit_agent_market_bench_market_input_v1(market_input)
    return tuple(
        market_input.reported_offers[index] for index in admission.admitted_submission_indices
    ), admission


def _ordinary_payment_correct(
    case: AgentMarketBenchCaseV1,
    result: AgentMarketBenchMethodResultV1,
) -> bool:
    reports, _ = _admitted_reports(case)
    offers = [report.signed_offer for report in reports]
    for line in result.lines:
        matching = [offer for offer in offers if offer.offer.offer_id == line.source_offer_id]
        if len(matching) != 1:
            return False
        offer = matching[0].offer
        if offer.merchant_id != line.merchant_id:
            return False
        source_lines = [candidate for candidate in offer.lines if candidate.sku_id == line.sku_id]
        if len(source_lines) != 1 or source_lines[0].unit_price != line.unit_payment:
            return False
    return True


def _reverse_vickrey_expected(case: AgentMarketBenchCaseV1) -> tuple[str, str, int] | None:
    reports, _ = _admitted_reports(case)
    policy = case.buyer_policy
    if (
        policy.market_spec.requested_quantity != 1
        or policy.market_spec.minimum_acceptable_quantity != 1
        or policy.market_spec.max_winners != 1
    ):
        return None
    candidates = []
    relevant = {rule.attribute_key for rule in policy.market_spec.hard_constraints}
    relevant.update(rule.attribute_key for rule in policy.market_spec.soft_preferences)
    for report in reports:
        offer = report.signed_offer.offer
        qualified = [
            line
            for line in offer.lines
            if all(
                _matches_reported(line.attributes, rule)
                for rule in policy.market_spec.hard_constraints
            )
        ]
        if len(qualified) == 0:
            continue
        if len(qualified) != 1 or qualified[0].max_offer_quantity < 1:
            return None
        candidate = qualified[0]
        candidates.append((offer.merchant_id, offer.offer_id, candidate))
    if len(candidates) < 2:
        return None
    for key in relevant:
        typed = [(line.attributes, merchant_id) for merchant_id, _, line in candidates]
        key_values = []
        for attributes, _ in typed:
            matching_attribute = next(
                (item for item in attributes if item.attribute_key == key), None
            )
            if matching_attribute is None:
                return None
            key_values.append((matching_attribute.value.value_type, matching_attribute.value.value))
        if any(item != key_values[0] for item in key_values[1:]):
            return None
    ranked = sorted(
        candidates, key=lambda item: (item[2].unit_price.amount_paise, item[0], item[1])
    )
    if ranked[1][2].unit_price.amount_paise > policy.max_total_payment.amount_paise:
        return None
    return ranked[0][0], ranked[0][1], ranked[1][2].unit_price.amount_paise


def _payment_correct(case: AgentMarketBenchCaseV1, result: AgentMarketBenchMethodResultV1) -> int:
    if result.status is AgentMarketBenchMethodStatusV1.INFEASIBLE:
        return 1
    if result.method is AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE:
        latent = {(line.merchant_id, line.sku_id): line for line in case.latent_lines}
        return int(
            all(
                line.unit_payment.amount_paise
                == latent[(line.merchant_id, line.sku_id)].true_unit_cost.amount_paise
                for line in result.lines
            )
        )
    if result.method is AgentMarketBenchBaselineV1.REVERSE_VICKREY:
        expected = _reverse_vickrey_expected(case)
        if expected is None or len(result.lines) != 1:
            return 0
        merchant_id, offer_id, payment = expected
        line = result.lines[0]
        return int(
            line.merchant_id == merchant_id
            and line.source_offer_id == offer_id
            and line.unit_payment.amount_paise == payment
            and line.allocated_quantity == 1
        )
    return int(_ordinary_payment_correct(case, result))


def _scenario_manipulation(
    case: AgentMarketBenchCaseV1,
    result: AgentMarketBenchMethodResultV1,
    admission: AgentMarketBenchAdmissionV1,
) -> int | None:
    scenarios = set(case.adversarial_scenarios)
    if not scenarios:
        return None
    protocol_expected = {
        AgentMarketBenchAdversarialScenarioV1.ALTERED_OFFER: "AUTHENTICATION_FAILED",
        AgentMarketBenchAdversarialScenarioV1.FORGED_MERCHANT: "AUTHENTICATION_FAILED",
        AgentMarketBenchAdversarialScenarioV1.LATE_OFFER: "LATE_OFFER",
        AgentMarketBenchAdversarialScenarioV1.REPLAYED_OFFER: "DUPLICATE_OFFER_ID",
    }
    for scenario, reason in protocol_expected.items():
        if scenario in scenarios:
            return int(
                not any(rejection.reason.value == reason for rejection in admission.rejections)
            )
    if AgentMarketBenchAdversarialScenarioV1.FAKE_INVENTORY in scenarios:
        latent = {(line.merchant_id, line.sku_id): line for line in case.latent_lines}
        reported = {
            (merchant.merchant_id, item.sku_id): item.quantity_available
            for merchant in case.observed_merchants
            for item in merchant.inventory_snapshot.lines
        }
        return int(
            any(
                line.allocated_quantity
                > latent[(line.merchant_id, line.sku_id)].true_available_quantity
                and reported[(line.merchant_id, line.sku_id)]
                > latent[(line.merchant_id, line.sku_id)].true_available_quantity
                for line in result.lines
            )
        )
    if AgentMarketBenchAdversarialScenarioV1.SLA_OVERPROMISE in scenarios:
        hard_sla = [
            rule
            for rule in case.buyer_policy.market_spec.hard_constraints
            if rule.attribute_key == "sla_days"
        ]
        if not hard_sla:
            return None
        latent = {(line.merchant_id, line.sku_id): line for line in case.latent_lines}
        reports, _ = _admitted_reports(case)
        reported_by_key = {
            (report.signed_offer.offer.merchant_id, line.sku_id): line
            for report in reports
            for line in report.signed_offer.offer.lines
        }
        overpromised = set()
        for key, reported_line in reported_by_key.items():
            latent_line = latent[key]
            reported_ok = all(
                _matches_reported(reported_line.attributes, rule) for rule in hard_sla
            )
            latent_ok = all(_matches_latent(latent_line, rule) for rule in hard_sla)
            if reported_ok and not latent_ok:
                overpromised.add(key)
        return int(any((line.merchant_id, line.sku_id) in overpromised for line in result.lines))
    return None


def measure_agent_market_bench_method_v1(
    case: AgentMarketBenchCaseV1,
    result: AgentMarketBenchMethodResultV1,
    oracle_result: AgentMarketBenchMethodResultV1,
    elapsed_ns: int,
) -> AgentMarketBenchMetricEvaluationV1:
    """Produce all eleven exact observations for one already-run method result."""

    if type(case) is not AgentMarketBenchCaseV1:
        raise TypeError("case must be exactly an AgentMarketBenchCaseV1")
    if (
        type(result) is not AgentMarketBenchMethodResultV1
        or type(oracle_result) is not AgentMarketBenchMethodResultV1
    ):
        raise TypeError("result and oracle_result must be exact method results")
    try:
        case = AgentMarketBenchCaseV1.model_validate(case)
        result = AgentMarketBenchMethodResultV1.model_validate(result)
        oracle_result = AgentMarketBenchMethodResultV1.model_validate(oracle_result)
    except Exception as error:
        raise ValueError("case or method result failed fresh validation") from error
    if type(elapsed_ns) is not int or type(elapsed_ns) is bool or elapsed_ns < 0:
        raise TypeError("elapsed_ns must be a nonnegative exact int")
    realization = realize_agent_market_bench_method_v1(case=case, result=result)
    oracle_realization = realize_agent_market_bench_method_v1(case=case, result=oracle_result)
    method_benchmark_welfare = _minimum_qualified_welfare_paise(case, realization)
    oracle_benchmark_welfare = _minimum_qualified_welfare_paise(case, oracle_realization)
    if oracle_benchmark_welfare < 0:
        raise ValueError("full-information oracle welfare cannot be negative")
    if (
        result.method is not AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE
        and method_benchmark_welfare > oracle_benchmark_welfare
    ):
        raise ValueError("method welfare exceeds full-information oracle welfare")
    if oracle_realization.realized_welfare_paise > 0 and realization.realized_welfare_paise < 0:
        raise ValueError("method welfare cannot be negative when oracle welfare is positive")
    observations: list[AgentMarketBenchMetricObservationV1] = []
    not_applicable = result.status is AgentMarketBenchMethodStatusV1.NOT_APPLICABLE
    runtime_marker = bool(set(case.adversarial_scenarios) & _RUNTIME_SCENARIOS)
    if not_applicable:
        economic_reason = AgentMarketBenchMetricNotApplicableReasonV1.METHOD_NOT_APPLICABLE
        for metric in AgentMarketBenchMetricV1:
            if metric is AgentMarketBenchMetricV1.DUPLICATE_FINANCIAL_SIDE_EFFECTS:
                observations.append(
                    _not_applicable(
                        metric,
                        AgentMarketBenchMetricNotApplicableReasonV1.NO_FINANCIAL_EXECUTION_IN_24D,
                    )
                )
            elif metric is AgentMarketBenchMetricV1.MANIPULATION_SUCCESS and runtime_marker:
                observations.append(
                    _not_applicable(
                        metric,
                        AgentMarketBenchMetricNotApplicableReasonV1.NO_FINANCIAL_EXECUTION_IN_24D,
                    )
                )
            elif metric is AgentMarketBenchMetricV1.LATENCY:
                observations.append(_measured(metric, elapsed_ns))
            else:
                observations.append(_not_applicable(metric, economic_reason))
        return AgentMarketBenchMetricEvaluationV1(tuple(observations), realization)

    admission = _admitted_reports(case)[1]
    observations.append(
        _measured(
            AgentMarketBenchMetricV1.ALLOCATIVE_EFFICIENCY,
            Fraction(1, 1)
            if result.method is AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE
            and oracle_benchmark_welfare > 0
            else (
                Fraction(method_benchmark_welfare, oracle_benchmark_welfare)
                if oracle_benchmark_welfare > 0
                else 0
            ),
        )
        if oracle_benchmark_welfare != 0
        else _not_applicable(
            AgentMarketBenchMetricV1.ALLOCATIVE_EFFICIENCY,
            AgentMarketBenchMetricNotApplicableReasonV1.ORACLE_WELFARE_ZERO,
        )
    )
    regret = oracle_benchmark_welfare - method_benchmark_welfare
    if regret < 0:
        raise ValueError("method regret cannot be negative")
    observations.extend(
        (
            _measured(AgentMarketBenchMetricV1.REGRET, regret),
            _measured(
                AgentMarketBenchMetricV1.BUYER_SURPLUS,
                realization.realized_buyer_value_paise - result.total_payment.amount_paise,
            ),
            _measured(
                AgentMarketBenchMetricV1.MERCHANT_SURPLUS,
                result.total_payment.amount_paise - realization.realized_true_cost_paise,
            ),
            _measured(AgentMarketBenchMetricV1.WELFARE, method_benchmark_welfare),
            _measured(
                AgentMarketBenchMetricV1.COMPLETION,
                Fraction(
                    realization.realized_quantity, case.buyer_policy.market_spec.requested_quantity
                ),
            ),
            _measured(
                AgentMarketBenchMetricV1.HARD_CONSTRAINT_VIOLATIONS,
                realization.latent_hard_violation_units,
            ),
        )
    )
    manipulation = _scenario_manipulation(case, result, admission)
    if runtime_marker:
        manipulation_observation = _not_applicable(
            AgentMarketBenchMetricV1.MANIPULATION_SUCCESS,
            AgentMarketBenchMetricNotApplicableReasonV1.NO_FINANCIAL_EXECUTION_IN_24D,
        )
    elif manipulation is None:
        manipulation_observation = _not_applicable(
            AgentMarketBenchMetricV1.MANIPULATION_SUCCESS,
            AgentMarketBenchMetricNotApplicableReasonV1.SCENARIO_NOT_DEFINED,
        )
    else:
        manipulation_observation = _measured(
            AgentMarketBenchMetricV1.MANIPULATION_SUCCESS, manipulation
        )
    observations.extend(
        (
            manipulation_observation,
            _measured(AgentMarketBenchMetricV1.PAYMENT_CORRECTNESS, _payment_correct(case, result)),
            _not_applicable(
                AgentMarketBenchMetricV1.DUPLICATE_FINANCIAL_SIDE_EFFECTS,
                AgentMarketBenchMetricNotApplicableReasonV1.NO_FINANCIAL_EXECUTION_IN_24D,
            ),
            _measured(AgentMarketBenchMetricV1.LATENCY, elapsed_ns),
        )
    )
    return AgentMarketBenchMetricEvaluationV1(tuple(observations), realization)


evaluate_agent_market_bench_method_v1 = measure_agent_market_bench_method_v1
measure_agent_market_bench_metrics_v1 = measure_agent_market_bench_method_v1
compute_agent_market_bench_metrics_v1 = measure_agent_market_bench_method_v1


__all__ = (
    "AgentMarketBenchLatentRealizationV1",
    "AgentMarketBenchMetricEvaluationV1",
    "compute_agent_market_bench_metrics_v1",
    "evaluate_agent_market_bench_method_v1",
    "measure_agent_market_bench_method_v1",
    "measure_agent_market_bench_metrics_v1",
    "realize_agent_market_bench_method_v1",
)
