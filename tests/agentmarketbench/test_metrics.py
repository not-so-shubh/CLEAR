from fractions import Fraction

import pytest

from clear_market.agentmarketbench.admission import admit_agent_market_bench_market_input_v1
from clear_market.agentmarketbench.full_information import (
    run_agent_market_bench_full_information_oracle_v1,
)
from clear_market.agentmarketbench.generator import generate_agent_market_bench_case_v1
from clear_market.agentmarketbench.measurement_models import (
    AgentMarketBenchMetricNotApplicableReasonV1,
    AgentMarketBenchMetricObservationStatusV1,
    AgentMarketBenchMetricUnitV1,
)
from clear_market.agentmarketbench.method_models import (
    AgentMarketBenchDecisionLineV1,
    AgentMarketBenchMethodResultV1,
    AgentMarketBenchMethodStatusV1,
)
from clear_market.agentmarketbench.methods import run_agent_market_bench_method_v1
from clear_market.agentmarketbench.metrics import (
    measure_agent_market_bench_method_v1,
    realize_agent_market_bench_method_v1,
)
from clear_market.agentmarketbench.models import (
    AgentMarketBenchAdversarialScenarioV1,
    AgentMarketBenchBaselineV1,
    AgentMarketBenchMetricV1,
)
from clear_market.agentmarketbench.protocol import agent_market_bench_market_input_v1
from clear_market.agentmarketbench.runner import run_agent_market_bench_case_v1
from clear_market.commerce import ComparisonOperator
from clear_market.domain import Money

from .test_full_information import _oracle_case_fixture
from .test_methods import _attribute, _hard_rule, _MerchantSpec, _SkuSpec


def _case_run(seed: int = 100_000_000):
    assert seed < 2_000_000_000
    case = generate_agent_market_bench_case_v1(seed)
    ticks = iter(range(18))
    return case, run_agent_market_bench_case_v1(case, clock_ns=lambda: next(ticks))


def _evaluation(case_run, method):
    return next(evaluation for evaluation in case_run.evaluations if evaluation.method is method)


def _observation(evaluation, metric):
    return next(observation for observation in evaluation.metrics if observation.metric is metric)


def _scenario_case(scenario: AgentMarketBenchAdversarialScenarioV1):
    return next(
        case
        for seed in range(100_000_000, 100_000_042)
        if (case := generate_agent_market_bench_case_v1(seed)).adversarial_scenarios == (scenario,)
    )


def _payment_case(label: str):
    return _oracle_case_fixture(
        label,
        (
            _MerchantSpec("low", (_SkuSpec("sku", 10, 1, ()),)),
            _MerchantSpec("high", (_SkuSpec("sku", 20, 1, ()),)),
        ),
        requested_quantity=1,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
        true_costs={(0, 0): 5, (1, 0): 8},
        true_values={(0, 0): 30, (1, 0): 30},
    )


def _metric_observation(case, result, oracle_result, metric):
    measured = measure_agent_market_bench_method_v1(
        case=case,
        result=result,
        oracle_result=oracle_result,
        elapsed_ns=1,
    )
    return next(
        observation for observation in measured.observations if observation.metric is metric
    )


def _assert_measured_binary(observation, expected: int) -> None:
    assert observation.status is AgentMarketBenchMetricObservationStatusV1.MEASURED
    assert observation.unit is AgentMarketBenchMetricUnitV1.BINARY
    assert observation.not_applicable_reason is None
    assert observation.value is not None
    assert observation.value.numerator == expected
    assert observation.value.denominator == 1


def _assert_measured_rational(observation, numerator: int, denominator: int = 1) -> None:
    assert observation.status is AgentMarketBenchMetricObservationStatusV1.MEASURED
    assert observation.not_applicable_reason is None
    assert observation.value is not None
    assert observation.value.numerator == numerator
    assert observation.value.denominator == denominator


def _assert_scenario_not_defined(observation) -> None:
    assert observation.status is AgentMarketBenchMetricObservationStatusV1.NOT_APPLICABLE
    assert observation.unit is AgentMarketBenchMetricUnitV1.BINARY
    assert observation.value is None
    assert (
        observation.not_applicable_reason
        is AgentMarketBenchMetricNotApplicableReasonV1.SCENARIO_NOT_DEFINED
    )


def _with_first_unit_payment_delta(result, delta: int):
    first = result.lines[0]
    changed_unit = Money(amount_paise=first.unit_payment.amount_paise + delta)
    changed_line = AgentMarketBenchDecisionLineV1(
        source_offer_id=first.source_offer_id,
        merchant_id=first.merchant_id,
        sku_id=first.sku_id,
        allocated_quantity=first.allocated_quantity,
        unit_payment=changed_unit,
        line_payment=changed_unit.checked_multiply(first.allocated_quantity),
    )
    changed_lines = (changed_line, *result.lines[1:])
    return AgentMarketBenchMethodResultV1(
        method=result.method,
        market_id=result.market_id,
        status=result.status,
        admission=result.admission,
        fulfilled_quantity=result.fulfilled_quantity,
        total_payment=Money(
            amount_paise=result.total_payment.amount_paise + delta * first.allocated_quantity
        ),
        winner_count=result.winner_count,
        lines=changed_lines,
    )


def _zero_result(case, method, admission):
    return AgentMarketBenchMethodResultV1(
        method=method,
        market_id=case.buyer_policy.market_spec.market_id,
        status=AgentMarketBenchMethodStatusV1.INFEASIBLE,
        admission=admission,
        fulfilled_quantity=0,
        total_payment=Money(amount_paise=0),
        winner_count=0,
        lines=(),
    )


def test_latent_realization_caps_capacity_and_preserves_surplus_identity() -> None:
    case, case_run = _case_run()
    evaluation = _evaluation(case_run, AgentMarketBenchBaselineV1.CLEAR)
    realization = realize_agent_market_bench_method_v1(case=case, result=evaluation.result)
    assert realization.realized_quantity == evaluation.realized_quantity
    assert realization.latent_capacity_excess_units == evaluation.latent_capacity_excess_units
    buyer = _observation(evaluation, AgentMarketBenchMetricV1.BUYER_SURPLUS).value
    merchant = _observation(evaluation, AgentMarketBenchMetricV1.MERCHANT_SURPLUS).value
    welfare = _observation(evaluation, AgentMarketBenchMetricV1.WELFARE).value
    assert buyer is not None and merchant is not None and welfare is not None
    assert Fraction(buyer.numerator, buyer.denominator) + Fraction(
        merchant.numerator, merchant.denominator
    ) == Fraction(welfare.numerator, welfare.denominator)


def test_all_economic_metrics_are_exact_and_latency_is_integer() -> None:
    _, case_run = _case_run()
    for evaluation in case_run.evaluations:
        assert len(evaluation.metrics) == len(tuple(AgentMarketBenchMetricV1))
        latency = _observation(evaluation, AgentMarketBenchMetricV1.LATENCY)
        assert latency.value is not None
        assert latency.value.denominator == 1
        duplicate = _observation(
            evaluation, AgentMarketBenchMetricV1.DUPLICATE_FINANCIAL_SIDE_EFFECTS
        )
        assert duplicate.status is AgentMarketBenchMetricObservationStatusV1.NOT_APPLICABLE
        assert (
            duplicate.not_applicable_reason
            is AgentMarketBenchMetricNotApplicableReasonV1.NO_FINANCIAL_EXECUTION_IN_24D
        )


def test_no_scenario_manipulation_is_explicit_na() -> None:
    case, case_run = _case_run()
    assert case.adversarial_scenarios == ()
    for evaluation in case_run.evaluations:
        observation = _observation(evaluation, AgentMarketBenchMetricV1.MANIPULATION_SUCCESS)
        assert observation.status is AgentMarketBenchMetricObservationStatusV1.NOT_APPLICABLE
        expected = (
            AgentMarketBenchMetricNotApplicableReasonV1.METHOD_NOT_APPLICABLE
            if evaluation.result.status.value == "NOT_APPLICABLE"
            else AgentMarketBenchMetricNotApplicableReasonV1.SCENARIO_NOT_DEFINED
        )
        assert observation.not_applicable_reason is expected


@pytest.mark.parametrize(
    ("seed", "scenario"),
    (
        (100_000_011, AgentMarketBenchAdversarialScenarioV1.DUPLICATE_EVENT),
        (100_000_013, AgentMarketBenchAdversarialScenarioV1.EVENT_REORDERING),
        (100_000_015, AgentMarketBenchAdversarialScenarioV1.PROVIDER_TIMEOUT),
        (100_000_017, AgentMarketBenchAdversarialScenarioV1.PAYMENT_FAILURE),
        (100_000_019, AgentMarketBenchAdversarialScenarioV1.TRANSFER_FAILURE),
        (100_000_021, AgentMarketBenchAdversarialScenarioV1.RETRY),
        (100_000_023, AgentMarketBenchAdversarialScenarioV1.RECONCILIATION),
        (100_000_025, AgentMarketBenchAdversarialScenarioV1.RECOVERY),
    ),
)
def test_runtime_markers_are_explicitly_out_of_scope_for_manipulation(
    seed: int, scenario: AgentMarketBenchAdversarialScenarioV1
) -> None:
    case, case_run = _case_run(seed)
    assert case.adversarial_scenarios == (scenario,)
    for evaluation in case_run.evaluations:
        observation = _observation(evaluation, AgentMarketBenchMetricV1.MANIPULATION_SUCCESS)
        assert observation.status is AgentMarketBenchMetricObservationStatusV1.NOT_APPLICABLE
        assert (
            observation.not_applicable_reason
            is AgentMarketBenchMetricNotApplicableReasonV1.NO_FINANCIAL_EXECUTION_IN_24D
        )
    clear = _evaluation(case_run, AgentMarketBenchBaselineV1.CLEAR)
    assert clear.result.status is not AgentMarketBenchMethodStatusV1.NOT_APPLICABLE
    reverse = _evaluation(case_run, AgentMarketBenchBaselineV1.REVERSE_VICKREY)
    assert reverse.result.status.value == "NOT_APPLICABLE"


def test_fake_inventory_manipulation_measures_allocation_beyond_inflated_latent_capacity() -> None:
    case = _scenario_case(AgentMarketBenchAdversarialScenarioV1.FAKE_INVENTORY)
    latent_by_key = {(line.merchant_id, line.sku_id): line for line in case.latent_lines}
    inflated = [
        latent_by_key[(merchant.merchant_id, inventory_line.sku_id)]
        for merchant in case.observed_merchants
        for inventory_line in merchant.inventory_snapshot.lines
        if inventory_line.quantity_available
        > latent_by_key[(merchant.merchant_id, inventory_line.sku_id)].true_available_quantity
    ]
    assert len(inflated) == 1
    target = inflated[0]
    public_quantity = next(
        inventory_line.quantity_available
        for merchant in case.observed_merchants
        if merchant.merchant_id == target.merchant_id
        for inventory_line in merchant.inventory_snapshot.lines
        if inventory_line.sku_id == target.sku_id
    )
    assert public_quantity == target.true_available_quantity + 3

    case_run = run_agent_market_bench_case_v1(case, clock_ns=lambda: 0)
    oracle_result = _evaluation(case_run, AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE).result
    excess_result = _manual_result_for_case_line(
        case,
        target,
        target.true_available_quantity + 1,
        method=AgentMarketBenchBaselineV1.CHEAPEST_QUALIFYING,
    )
    excess = _metric_observation(
        case,
        excess_result,
        oracle_result,
        AgentMarketBenchMetricV1.MANIPULATION_SUCCESS,
    )
    _assert_measured_binary(excess, 1)

    no_excess_result = _zero_result(
        case,
        AgentMarketBenchBaselineV1.CHEAPEST_QUALIFYING,
        excess_result.admission,
    )
    no_excess = _metric_observation(
        case,
        no_excess_result,
        oracle_result,
        AgentMarketBenchMetricV1.MANIPULATION_SUCCESS,
    )
    _assert_measured_binary(no_excess, 0)


def test_sla_overpromise_manipulation_requires_allocation_of_latent_failure() -> None:
    sla_rule = _hard_rule("sla_days", 3, ComparisonOperator.LTE)
    base = _oracle_case_fixture(
        "sla-overpromise-measured",
        (
            _MerchantSpec("target", (_SkuSpec("sku", 10, 1, (_attribute("sla_days", 1),)),)),
            _MerchantSpec("other", (_SkuSpec("sku", 20, 1, (_attribute("sla_days", 2),)),)),
        ),
        requested_quantity=1,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
        hard_constraints=(sla_rule,),
        true_costs={(0, 0): 5, (1, 0): 8},
        true_values={(0, 0): 30, (1, 0): 30},
        latent_attribute_values={(0, 0, "sla_days"): 7},
    )
    case = type(base).model_validate(
        base.model_copy(
            update={
                "adversarial_scenarios": (AgentMarketBenchAdversarialScenarioV1.SLA_OVERPROMISE,)
            }
        )
    )
    assert sla_rule.operator is ComparisonOperator.LTE
    latent_by_key = {(line.merchant_id, line.sku_id): line for line in case.latent_lines}
    target = next(
        latent_by_key[(report.signed_offer.offer.merchant_id, line.sku_id)]
        for report in case.reported_offers
        for line in report.signed_offer.offer.lines
        if (
            reported_sla := next(
                attribute for attribute in line.attributes if attribute.attribute_key == "sla_days"
            )
        ).provenance
        in sla_rule.allowed_provenance
        and reported_sla.value.value_type is sla_rule.operand.value_type
        and reported_sla.value.value <= sla_rule.operand.value
        and next(
            attribute.value.value
            for attribute in latent_by_key[
                (report.signed_offer.offer.merchant_id, line.sku_id)
            ].true_attributes
            if attribute.attribute_key == "sla_days"
        )
        > sla_rule.operand.value
    )
    result = _manual_result_for_case_line(
        case,
        target,
        1,
        method=AgentMarketBenchBaselineV1.CHEAPEST_QUALIFYING,
    )
    case_run = run_agent_market_bench_case_v1(case, clock_ns=lambda: 0)
    observation = _metric_observation(
        case,
        result,
        _evaluation(case_run, AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE).result,
        AgentMarketBenchMetricV1.MANIPULATION_SUCCESS,
    )
    _assert_measured_binary(observation, 1)


def test_sla_overpromise_without_relevant_hard_rule_is_explicitly_not_applicable() -> None:
    base = _payment_case("sla-overpromise-without-hard-rule")
    case = type(base).model_validate(
        base.model_copy(
            update={
                "adversarial_scenarios": (AgentMarketBenchAdversarialScenarioV1.SLA_OVERPROMISE,)
            }
        )
    )
    assert all(
        rule.attribute_key != "sla_days" for rule in case.buyer_policy.market_spec.hard_constraints
    )
    case_run = run_agent_market_bench_case_v1(case, clock_ns=lambda: 0)
    clear = _evaluation(case_run, AgentMarketBenchBaselineV1.CLEAR)
    _assert_scenario_not_defined(_observation(clear, AgentMarketBenchMetricV1.MANIPULATION_SUCCESS))


@pytest.mark.parametrize(
    "scenario",
    (
        AgentMarketBenchAdversarialScenarioV1.PROMPT_INJECTION,
        AgentMarketBenchAdversarialScenarioV1.MALICIOUS_CATALOG_TEXT,
        AgentMarketBenchAdversarialScenarioV1.SCHEMA_MANIPULATION,
        AgentMarketBenchAdversarialScenarioV1.STRATEGIC_SHADING,
        AgentMarketBenchAdversarialScenarioV1.SELLER_DROPOUT,
        AgentMarketBenchAdversarialScenarioV1.SYBIL_SENSITIVITY,
        AgentMarketBenchAdversarialScenarioV1.COLLUSION_SENSITIVITY,
    ),
)
def test_ai_and_economic_sensitivity_have_no_causal_manipulation_metric(
    scenario: AgentMarketBenchAdversarialScenarioV1,
) -> None:
    case = _scenario_case(scenario)
    case_run = run_agent_market_bench_case_v1(case, clock_ns=lambda: 0)
    clear = _evaluation(case_run, AgentMarketBenchBaselineV1.CLEAR)
    assert clear.result.status is not AgentMarketBenchMethodStatusV1.NOT_APPLICABLE
    _assert_scenario_not_defined(_observation(clear, AgentMarketBenchMetricV1.MANIPULATION_SUCCESS))


@pytest.mark.parametrize(
    ("scenario", "expected_reason"),
    (
        (
            AgentMarketBenchAdversarialScenarioV1.ALTERED_OFFER,
            "AUTHENTICATION_FAILED",
        ),
        (AgentMarketBenchAdversarialScenarioV1.LATE_OFFER, "LATE_OFFER"),
        (
            AgentMarketBenchAdversarialScenarioV1.REPLAYED_OFFER,
            "DUPLICATE_OFFER_ID",
        ),
        (
            AgentMarketBenchAdversarialScenarioV1.FORGED_MERCHANT,
            "AUTHENTICATION_FAILED",
        ),
    ),
)
def test_protocol_scenarios_measure_expected_shared_admission_rejection_as_zero(
    scenario: AgentMarketBenchAdversarialScenarioV1,
    expected_reason: str,
) -> None:
    case = _scenario_case(scenario)
    case_run = run_agent_market_bench_case_v1(case, clock_ns=lambda: 0)
    clear = _evaluation(case_run, AgentMarketBenchBaselineV1.CLEAR)
    assert expected_reason in {
        rejection.reason.value for rejection in clear.result.admission.rejections
    }
    _assert_measured_binary(
        _observation(clear, AgentMarketBenchMetricV1.MANIPULATION_SUCCESS),
        0,
    )


def test_protocol_scenario_without_expected_rejection_measures_failure_as_one() -> None:
    base = _payment_case("late-label-without-late-offer")
    case = type(base).model_validate(
        base.model_copy(
            update={"adversarial_scenarios": (AgentMarketBenchAdversarialScenarioV1.LATE_OFFER,)}
        )
    )
    case_run = run_agent_market_bench_case_v1(case, clock_ns=lambda: 0)
    clear = _evaluation(case_run, AgentMarketBenchBaselineV1.CLEAR)
    assert not clear.result.admission.rejections
    _assert_measured_binary(
        _observation(clear, AgentMarketBenchMetricV1.MANIPULATION_SUCCESS),
        1,
    )


def test_malformed_positive_result_against_zero_oracle_raises_instead_of_clamping() -> None:
    case, case_run = _case_run()
    clear = _evaluation(case_run, AgentMarketBenchBaselineV1.CLEAR).result
    realization = realize_agent_market_bench_method_v1(case, clear)
    assert (
        realization.realized_quantity >= case.buyer_policy.market_spec.minimum_acceptable_quantity
    )
    assert realization.realized_welfare_paise > 0
    oracle = AgentMarketBenchMethodResultV1(
        method=AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE,
        market_id=clear.market_id,
        status=AgentMarketBenchMethodStatusV1.INFEASIBLE,
        admission=clear.admission,
        fulfilled_quantity=0,
        total_payment=Money(amount_paise=0),
        winner_count=0,
        lines=(),
    )
    assert realize_agent_market_bench_method_v1(case, oracle).realized_welfare_paise == 0
    with pytest.raises(
        ValueError, match=r"^method welfare exceeds full-information oracle welfare$"
    ):
        measure_agent_market_bench_method_v1(
            case=case,
            result=clear,
            oracle_result=oracle,
            elapsed_ns=1,
        )


def test_quarantined_below_minimum_welfare_preserves_raw_realization() -> None:
    seed = 500_002_459
    assert seed < 2_000_000_000
    case = generate_agent_market_bench_case_v1(seed)
    assert case.adversarial_scenarios == (AgentMarketBenchAdversarialScenarioV1.FAKE_INVENTORY,)
    result = run_agent_market_bench_method_v1(
        method=AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER,
        market_input=agent_market_bench_market_input_v1(case),
    )
    oracle = run_agent_market_bench_full_information_oracle_v1(case)
    raw = realize_agent_market_bench_method_v1(case, result)
    assert case.buyer_policy.market_spec.requested_quantity == 5
    assert result.fulfilled_quantity == 5
    assert raw.realized_quantity == 2
    assert case.buyer_policy.market_spec.minimum_acceptable_quantity == 3
    assert raw.realized_welfare_paise == 4224
    assert raw.latent_capacity_excess_units == 3
    assert oracle.status is AgentMarketBenchMethodStatusV1.INFEASIBLE
    assert realize_agent_market_bench_method_v1(case, oracle).realized_welfare_paise == 0

    measured = measure_agent_market_bench_method_v1(case, result, oracle, elapsed_ns=1)
    observations = {item.metric: item for item in measured.observations}
    _assert_measured_rational(observations[AgentMarketBenchMetricV1.WELFARE], 0)
    _assert_measured_rational(observations[AgentMarketBenchMetricV1.REGRET], 0)
    _assert_measured_rational(observations[AgentMarketBenchMetricV1.COMPLETION], 2, 5)
    efficiency = observations[AgentMarketBenchMetricV1.ALLOCATIVE_EFFICIENCY]
    assert efficiency.status is AgentMarketBenchMetricObservationStatusV1.NOT_APPLICABLE
    assert efficiency.value is None
    assert (
        efficiency.not_applicable_reason
        is AgentMarketBenchMetricNotApplicableReasonV1.ORACLE_WELFARE_ZERO
    )
    assert measured.realization == raw
    assert measured.realization.realized_welfare_paise == 4224
    assert measured.realization.latent_capacity_excess_units == 3
    assert realize_agent_market_bench_method_v1(case, result) == raw


@pytest.mark.parametrize(
    ("seed", "method", "raw_welfare", "realized_quantity", "minimum"),
    (
        (100_000_549, AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER, 4792, 4, 6),
        (100_000_549, AgentMarketBenchBaselineV1.CHEAPEST_QUALIFYING, 4792, 4, 6),
        (100_000_803, AgentMarketBenchBaselineV1.STATIC_WEIGHTED_SCORE, 9911, 5, 8),
        (100_000_803, AgentMarketBenchBaselineV1.SEQUENTIAL_NEGOTIATION, 7886, 5, 8),
    ),
)
def test_disclosed_development_welfare_changes_are_exact(
    seed: int,
    method: AgentMarketBenchBaselineV1,
    raw_welfare: int,
    realized_quantity: int,
    minimum: int,
) -> None:
    assert seed < 2_000_000_000
    case, case_run = _case_run(seed)
    evaluation = _evaluation(case_run, method)
    raw = realize_agent_market_bench_method_v1(case, evaluation.result)
    assert raw.realized_welfare_paise == raw_welfare > 0
    assert raw.realized_quantity == realized_quantity
    assert case.buyer_policy.market_spec.minimum_acceptable_quantity == minimum
    assert realized_quantity < minimum
    _assert_measured_rational(_observation(evaluation, AgentMarketBenchMetricV1.WELFARE), 0)


def test_below_minimum_welfare_with_positive_oracle_keeps_raw_surpluses() -> None:
    case = _oracle_case_fixture(
        "below-minimum-positive-oracle",
        (
            _MerchantSpec("partial", (_SkuSpec("sku", 12, 4, ()),)),
            _MerchantSpec("feasible", (_SkuSpec("sku", 20, 4, ()),)),
        ),
        requested_quantity=4,
        minimum_acceptable_quantity=3,
        max_winners=1,
        budget=100,
        true_quantities={(0, 0): 1},
        true_costs={(0, 0): 10, (1, 0): 15},
        true_values={(0, 0): 35, (1, 0): 35},
    )
    result = run_agent_market_bench_method_v1(
        method=AgentMarketBenchBaselineV1.CHEAPEST_QUALIFYING,
        market_input=agent_market_bench_market_input_v1(case),
    )
    oracle = run_agent_market_bench_full_information_oracle_v1(case)
    raw = realize_agent_market_bench_method_v1(case, result)
    oracle_raw = realize_agent_market_bench_method_v1(case, oracle)
    assert result.fulfilled_quantity == 4
    assert result.total_payment.amount_paise == 48
    assert raw.realized_quantity == 1 < case.buyer_policy.market_spec.minimum_acceptable_quantity
    assert raw.realized_buyer_value_paise == 35
    assert raw.realized_true_cost_paise == 10
    assert raw.realized_welfare_paise == 25
    assert oracle.status is AgentMarketBenchMethodStatusV1.FEASIBLE
    assert oracle_raw.realized_quantity == 4
    assert oracle_raw.realized_welfare_paise == 80

    measured = measure_agent_market_bench_method_v1(case, result, oracle, elapsed_ns=1)
    observations = {item.metric: item for item in measured.observations}
    _assert_measured_rational(observations[AgentMarketBenchMetricV1.WELFARE], 0)
    _assert_measured_rational(observations[AgentMarketBenchMetricV1.ALLOCATIVE_EFFICIENCY], 0)
    _assert_measured_rational(observations[AgentMarketBenchMetricV1.REGRET], 80)
    _assert_measured_rational(observations[AgentMarketBenchMetricV1.BUYER_SURPLUS], -13)
    _assert_measured_rational(observations[AgentMarketBenchMetricV1.MERCHANT_SURPLUS], 38)
    _assert_measured_rational(observations[AgentMarketBenchMetricV1.COMPLETION], 1, 4)
    buyer = observations[AgentMarketBenchMetricV1.BUYER_SURPLUS].value
    merchant = observations[AgentMarketBenchMetricV1.MERCHANT_SURPLUS].value
    assert buyer is not None and merchant is not None
    assert buyer.numerator + merchant.numerator == raw.realized_welfare_paise == 25
    assert measured.realization == raw
    _assert_measured_rational(
        _metric_observation(case, oracle, oracle, AgentMarketBenchMetricV1.ALLOCATIVE_EFFICIENCY),
        1,
    )


def test_minimum_qualified_partial_allocation_keeps_welfare_despite_latent_diagnostics() -> None:
    case = _oracle_case_fixture(
        "qualified-with-capacity-and-hard-violations",
        (
            _MerchantSpec("valid", (_SkuSpec("sku", 12, 4, (_attribute("sla_days", 2),)),)),
            _MerchantSpec("invalid", (_SkuSpec("sku", 5, 1, (_attribute("sla_days", 2),)),)),
        ),
        requested_quantity=5,
        minimum_acceptable_quantity=3,
        max_winners=2,
        budget=100,
        hard_constraints=(_hard_rule("sla_days", 3, ComparisonOperator.LTE),),
        true_quantities={(0, 0): 3},
        true_costs={(0, 0): 10, (1, 0): 3},
        true_values={(0, 0): 30, (1, 0): 30},
        latent_attribute_values={(1, 0, "sla_days"): 7},
    )
    valid_line = next(line for line in case.latent_lines if line.true_unit_cost.amount_paise == 10)
    invalid_line = next(line for line in case.latent_lines if line.true_unit_cost.amount_paise == 3)
    valid = _manual_result_for_case_line(
        case, valid_line, 4, method=AgentMarketBenchBaselineV1.CHEAPEST_QUALIFYING
    )
    invalid = _manual_result_for_case_line(
        case, invalid_line, 1, method=AgentMarketBenchBaselineV1.CHEAPEST_QUALIFYING
    )
    result = AgentMarketBenchMethodResultV1(
        method=valid.method,
        market_id=valid.market_id,
        status=AgentMarketBenchMethodStatusV1.FEASIBLE,
        admission=valid.admission,
        fulfilled_quantity=5,
        total_payment=Money(amount_paise=53),
        winner_count=2,
        lines=tuple(sorted((*valid.lines, *invalid.lines), key=lambda line: line.merchant_id)),
    )
    oracle = run_agent_market_bench_full_information_oracle_v1(case)
    measured = measure_agent_market_bench_method_v1(case, result, oracle, elapsed_ns=1)
    raw = measured.realization
    assert raw.realized_quantity == case.buyer_policy.market_spec.minimum_acceptable_quantity == 3
    assert raw.realized_quantity < case.buyer_policy.market_spec.requested_quantity
    assert raw.latent_capacity_excess_units == 1
    assert raw.latent_hard_violation_units == 1
    assert raw.realized_welfare_paise == 60
    observations = {item.metric: item for item in measured.observations}
    _assert_measured_rational(observations[AgentMarketBenchMetricV1.WELFARE], 60)
    _assert_measured_rational(observations[AgentMarketBenchMetricV1.ALLOCATIVE_EFFICIENCY], 1)
    _assert_measured_rational(observations[AgentMarketBenchMetricV1.REGRET], 0)
    _assert_measured_rational(observations[AgentMarketBenchMetricV1.COMPLETION], 3, 5)
    _assert_measured_rational(observations[AgentMarketBenchMetricV1.HARD_CONSTRAINT_VIOLATIONS], 1)
    _assert_measured_rational(observations[AgentMarketBenchMetricV1.BUYER_SURPLUS], 37)
    _assert_measured_rational(observations[AgentMarketBenchMetricV1.MERCHANT_SURPLUS], 23)


def test_ordinary_pay_as_bid_payment_correctness_positive_and_mutated_negative() -> None:
    case = _payment_case("ordinary-payment-correctness")
    case_run = run_agent_market_bench_case_v1(case, clock_ns=lambda: 0)
    oracle = _evaluation(case_run, AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE).result
    result = _evaluation(case_run, AgentMarketBenchBaselineV1.CHEAPEST_QUALIFYING).result
    assert result.status is AgentMarketBenchMethodStatusV1.FEASIBLE
    _assert_measured_binary(
        _metric_observation(
            case,
            result,
            oracle,
            AgentMarketBenchMetricV1.PAYMENT_CORRECTNESS,
        ),
        1,
    )
    _assert_measured_binary(
        _metric_observation(
            case,
            _with_first_unit_payment_delta(result, 1),
            oracle,
            AgentMarketBenchMetricV1.PAYMENT_CORRECTNESS,
        ),
        0,
    )


def test_clear_payment_correctness_positive_and_mutated_negative() -> None:
    case = _payment_case("clear-payment-correctness")
    case_run = run_agent_market_bench_case_v1(case, clock_ns=lambda: 0)
    oracle = _evaluation(case_run, AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE).result
    result = _evaluation(case_run, AgentMarketBenchBaselineV1.CLEAR).result
    assert result.status is AgentMarketBenchMethodStatusV1.FEASIBLE
    _assert_measured_binary(
        _metric_observation(
            case,
            result,
            oracle,
            AgentMarketBenchMetricV1.PAYMENT_CORRECTNESS,
        ),
        1,
    )
    _assert_measured_binary(
        _metric_observation(
            case,
            _with_first_unit_payment_delta(result, 1),
            oracle,
            AgentMarketBenchMetricV1.PAYMENT_CORRECTNESS,
        ),
        0,
    )


def test_first_price_payment_correctness_positive_and_mutated_negative() -> None:
    case = _payment_case("first-price-payment-correctness")
    case_run = run_agent_market_bench_case_v1(case, clock_ns=lambda: 0)
    oracle = _evaluation(case_run, AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE).result
    result = _evaluation(case_run, AgentMarketBenchBaselineV1.FIRST_PRICE_REVERSE_AUCTION).result
    assert result.status is AgentMarketBenchMethodStatusV1.FEASIBLE
    _assert_measured_binary(
        _metric_observation(
            case,
            result,
            oracle,
            AgentMarketBenchMetricV1.PAYMENT_CORRECTNESS,
        ),
        1,
    )
    _assert_measured_binary(
        _metric_observation(
            case,
            _with_first_unit_payment_delta(result, 1),
            oracle,
            AgentMarketBenchMetricV1.PAYMENT_CORRECTNESS,
        ),
        0,
    )


def test_reverse_vickrey_payment_correctness_positive_and_mutated_negative() -> None:
    case = _payment_case("reverse-vickrey-payment-correctness")
    case_run = run_agent_market_bench_case_v1(case, clock_ns=lambda: 0)
    oracle = _evaluation(case_run, AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE).result
    result = _evaluation(case_run, AgentMarketBenchBaselineV1.REVERSE_VICKREY).result
    assert result.status is AgentMarketBenchMethodStatusV1.FEASIBLE
    assert result.lines[0].unit_payment.amount_paise == 20
    _assert_measured_binary(
        _metric_observation(
            case,
            result,
            oracle,
            AgentMarketBenchMetricV1.PAYMENT_CORRECTNESS,
        ),
        1,
    )
    _assert_measured_binary(
        _metric_observation(
            case,
            _with_first_unit_payment_delta(result, 1),
            oracle,
            AgentMarketBenchMetricV1.PAYMENT_CORRECTNESS,
        ),
        0,
    )


def test_oracle_payment_correctness_positive_and_mutated_negative() -> None:
    case = _payment_case("oracle-payment-correctness")
    case_run = run_agent_market_bench_case_v1(case, clock_ns=lambda: 0)
    result = _evaluation(case_run, AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE).result
    assert result.status is AgentMarketBenchMethodStatusV1.FEASIBLE
    latent_by_key = {(line.merchant_id, line.sku_id): line for line in case.latent_lines}
    assert all(
        line.unit_payment == latent_by_key[(line.merchant_id, line.sku_id)].true_unit_cost
        for line in result.lines
    )
    _assert_measured_binary(
        _metric_observation(
            case,
            result,
            result,
            AgentMarketBenchMetricV1.PAYMENT_CORRECTNESS,
        ),
        1,
    )
    _assert_measured_binary(
        _metric_observation(
            case,
            _with_first_unit_payment_delta(result, 1),
            result,
            AgentMarketBenchMetricV1.PAYMENT_CORRECTNESS,
        ),
        0,
    )


def test_infeasible_zero_result_payment_correctness_is_measured_one() -> None:
    case = _payment_case("infeasible-payment-correctness")
    case_run = run_agent_market_bench_case_v1(case, clock_ns=lambda: 0)
    oracle = _evaluation(case_run, AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE).result
    result = _zero_result(
        case,
        AgentMarketBenchBaselineV1.CHEAPEST_QUALIFYING,
        oracle.admission,
    )
    _assert_measured_binary(
        _metric_observation(
            case,
            result,
            oracle,
            AgentMarketBenchMetricV1.PAYMENT_CORRECTNESS,
        ),
        1,
    )


def _manual_result_for_case_line(case, source_line, quantity: int, *, method):
    market_input = agent_market_bench_market_input_v1(case)
    report = next(
        report
        for report in market_input.reported_offers
        if report.signed_offer.offer.merchant_id == source_line.merchant_id
    )
    offer_line = next(
        line for line in report.signed_offer.offer.lines if line.sku_id == source_line.sku_id
    )
    unit_payment = offer_line.unit_price
    decision = AgentMarketBenchDecisionLineV1(
        source_offer_id=report.signed_offer.offer.offer_id,
        merchant_id=source_line.merchant_id,
        sku_id=source_line.sku_id,
        allocated_quantity=quantity,
        unit_payment=unit_payment,
        line_payment=unit_payment.checked_multiply(quantity),
    )
    return AgentMarketBenchMethodResultV1(
        method=method,
        market_id=case.buyer_policy.market_spec.market_id,
        status=AgentMarketBenchMethodStatusV1.FEASIBLE,
        admission=admit_agent_market_bench_market_input_v1(market_input),
        fulfilled_quantity=quantity,
        total_payment=decision.line_payment,
        winner_count=1,
        lines=(decision,),
    )


def test_capacity_excess_and_contractual_payment_penalty_are_exact() -> None:
    case, case_run = _case_run()
    clear = _evaluation(case_run, AgentMarketBenchBaselineV1.CLEAR).result
    source = clear.lines[0]
    latent = next(
        line
        for line in case.latent_lines
        if (line.merchant_id, line.sku_id) == (source.merchant_id, source.sku_id)
    )
    result = _manual_result_for_case_line(
        case,
        latent,
        latent.true_available_quantity + 1,
        method=AgentMarketBenchBaselineV1.CLEAR,
    )
    realization = realize_agent_market_bench_method_v1(case, result)
    assert realization.realized_quantity == latent.true_available_quantity
    assert realization.latent_capacity_excess_units == 1
    oracle = _evaluation(case_run, AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE).result
    measured = measure_agent_market_bench_method_v1(case, result, oracle, elapsed_ns=9)
    values = {
        observation.metric: observation.value
        for observation in measured.observations
        if observation.value is not None
    }
    assert values[AgentMarketBenchMetricV1.BUYER_SURPLUS] is not None
    assert values[AgentMarketBenchMetricV1.WELFARE] is not None
    assert values[AgentMarketBenchMetricV1.BUYER_SURPLUS].numerator == (
        realization.realized_buyer_value_paise - result.total_payment.amount_paise
    )
    assert realization.realized_quantity < case.buyer_policy.market_spec.minimum_acceptable_quantity
    assert values[AgentMarketBenchMetricV1.WELFARE].numerator == 0
    assert values[AgentMarketBenchMetricV1.WELFARE].denominator == 1
    assert (
        values[AgentMarketBenchMetricV1.MERCHANT_SURPLUS].numerator
        + values[AgentMarketBenchMetricV1.BUYER_SURPLUS].numerator
        == realization.realized_welfare_paise
    )


def test_latent_hard_violation_counts_full_contractual_quantity() -> None:
    case, _ = _case_run()
    quality_rule = next(
        rule
        for rule in case.buyer_policy.market_spec.hard_constraints
        if rule.attribute_key == "quality_score"
    )
    bad = next(
        line
        for line in case.latent_lines
        if next(
            attribute.value.value
            for attribute in line.true_attributes
            if attribute.attribute_key == "quality_score"
        )
        < quality_rule.operand.value
    )
    result = _manual_result_for_case_line(
        case, bad, 2, method=AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER
    )
    realization = realize_agent_market_bench_method_v1(case, result)
    assert realization.realized_quantity == 0
    assert realization.latent_hard_violation_units == 2


def test_known_welfare_completion_efficiency_and_regret_use_exact_rationals() -> None:
    case = _oracle_case_fixture(
        "metrics-known-rationals",
        (
            _MerchantSpec("one", (_SkuSpec("sku", 10, 4, ()),)),
            _MerchantSpec("two", (_SkuSpec("sku", 11, 4, ()),)),
        ),
        requested_quantity=4,
        minimum_acceptable_quantity=1,
        max_winners=1,
        budget=100,
        true_costs={(0, 0): 10, (1, 0): 11},
        true_values={(0, 0): 20, (1, 0): 20},
    )
    case_run = run_agent_market_bench_case_v1(case, clock_ns=lambda: 0)
    oracle_result = _evaluation(case_run, AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE).result
    latent = next(line for line in case.latent_lines if line.true_unit_cost.amount_paise == 10)
    half_result = _manual_result_for_case_line(
        case, latent, 2, method=AgentMarketBenchBaselineV1.CHEAPEST_QUALIFYING
    )
    half = measure_agent_market_bench_method_v1(case, half_result, oracle_result, elapsed_ns=4)
    half_values = {observation.metric: observation.value for observation in half.observations}
    assert half_values[AgentMarketBenchMetricV1.WELFARE] is not None
    assert half_values[AgentMarketBenchMetricV1.WELFARE].numerator == 20
    assert half_values[AgentMarketBenchMetricV1.COMPLETION] is not None
    assert half_values[AgentMarketBenchMetricV1.COMPLETION].numerator == 1
    assert half_values[AgentMarketBenchMetricV1.COMPLETION].denominator == 2

    three_result = _manual_result_for_case_line(
        case, latent, 3, method=AgentMarketBenchBaselineV1.CHEAPEST_QUALIFYING
    )
    three = measure_agent_market_bench_method_v1(case, three_result, oracle_result, elapsed_ns=4)
    three_values = {observation.metric: observation.value for observation in three.observations}
    assert three_values[AgentMarketBenchMetricV1.WELFARE] is not None
    assert three_values[AgentMarketBenchMetricV1.WELFARE].numerator == 30
    assert three_values[AgentMarketBenchMetricV1.ALLOCATIVE_EFFICIENCY] is not None
    assert three_values[AgentMarketBenchMetricV1.ALLOCATIVE_EFFICIENCY].numerator == 3
    assert three_values[AgentMarketBenchMetricV1.ALLOCATIVE_EFFICIENCY].denominator == 4
    assert three_values[AgentMarketBenchMetricV1.REGRET] is not None
    assert three_values[AgentMarketBenchMetricV1.REGRET].numerator == 10
