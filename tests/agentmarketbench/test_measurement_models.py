import re
from typing import get_args

import pytest
from pydantic import ValidationError

from clear_market.agentmarketbench.generator import generate_agent_market_bench_case_v1
from clear_market.agentmarketbench.measurement_models import (
    AGENT_MARKET_BENCH_CASE_RUN_V1_VERSION,
    AGENT_MARKET_BENCH_METHOD_EVALUATION_V1_VERSION,
    AGENT_MARKET_BENCH_METRIC_OBSERVATION_V1_VERSION,
    AGENT_MARKET_BENCH_METRIC_SEMANTICS_V1_1_VERSION,
    AGENT_MARKET_BENCH_METRIC_SUMMARY_V1_VERSION,
    AGENT_MARKET_BENCH_METRICS_V1_VERSION,
    AGENT_MARKET_BENCH_PAIRED_SUMMARY_V1_VERSION,
    AGENT_MARKET_BENCH_RATIONAL_V1_VERSION,
    AGENT_MARKET_BENCH_RUN_SUMMARY_V1_VERSION,
    AGENT_MARKET_BENCH_RUN_V1_VERSION,
    AGENT_MARKET_BENCH_RUNNER_V1_VERSION,
    AGENT_MARKET_BENCH_SCENARIO_ASSESSMENT_V1_VERSION,
    AGENT_MARKET_BENCH_STATISTICS_V1_VERSION,
    AgentMarketBenchCaseRunV1,
    AgentMarketBenchMethodEvaluationV1,
    AgentMarketBenchMetricNotApplicableReasonV1,
    AgentMarketBenchMetricObservationStatusV1,
    AgentMarketBenchMetricObservationV1,
    AgentMarketBenchMetricSummaryV1,
    AgentMarketBenchMetricUnitV1,
    AgentMarketBenchPairedSummaryV1,
    AgentMarketBenchRationalV1,
    AgentMarketBenchRunSummaryV1,
    AgentMarketBenchRunV1,
    AgentMarketBenchScenarioAssessmentV1,
    AgentMarketBenchScenarioEvidenceBasisV1,
)
from clear_market.agentmarketbench.models import (
    AgentMarketBenchBaselineV1,
    AgentMarketBenchMetricV1,
)
from clear_market.agentmarketbench.runner import (
    run_agent_market_bench_case_v1,
    run_agent_market_bench_cases_v1,
)


def test_metric_semantic_revision_preserves_case_run_v1_schema() -> None:
    assert AGENT_MARKET_BENCH_METRICS_V1_VERSION == "agent-market-bench-metrics-v1"
    assert (
        AGENT_MARKET_BENCH_METRIC_SEMANTICS_V1_1_VERSION
        == "agent-market-bench-metric-semantics-v1.1"
    )
    fields = AgentMarketBenchCaseRunV1.model_fields
    assert tuple(fields) == (
        "schema_version",
        "agent_market_bench_case_run_version",
        "runner_version",
        "metrics_version",
        "statistics_version",
        "case_id",
        "seed",
        "case_digest_sha256",
        "execution_order",
        "evaluations",
        "scenario_assessments",
    )
    for name, literal in (
        ("schema_version", "1"),
        ("agent_market_bench_case_run_version", "agent-market-bench-case-run-v1"),
        ("runner_version", "agent-market-bench-runner-v1"),
        ("metrics_version", "agent-market-bench-metrics-v1"),
        ("statistics_version", "agent-market-bench-statistics-v1"),
    ):
        assert fields[name].default == literal
        assert get_args(fields[name].annotation) == (literal,)


def test_exact_versions_and_enums() -> None:
    assert (
        AGENT_MARKET_BENCH_RUNNER_V1_VERSION,
        AGENT_MARKET_BENCH_METRICS_V1_VERSION,
        AGENT_MARKET_BENCH_STATISTICS_V1_VERSION,
        AGENT_MARKET_BENCH_RATIONAL_V1_VERSION,
        AGENT_MARKET_BENCH_METRIC_OBSERVATION_V1_VERSION,
        AGENT_MARKET_BENCH_SCENARIO_ASSESSMENT_V1_VERSION,
        AGENT_MARKET_BENCH_METHOD_EVALUATION_V1_VERSION,
        AGENT_MARKET_BENCH_CASE_RUN_V1_VERSION,
        AGENT_MARKET_BENCH_METRIC_SUMMARY_V1_VERSION,
        AGENT_MARKET_BENCH_PAIRED_SUMMARY_V1_VERSION,
        AGENT_MARKET_BENCH_RUN_SUMMARY_V1_VERSION,
        AGENT_MARKET_BENCH_RUN_V1_VERSION,
    ) == (
        "agent-market-bench-runner-v1",
        "agent-market-bench-metrics-v1",
        "agent-market-bench-statistics-v1",
        "agent-market-bench-rational-v1",
        "agent-market-bench-metric-observation-v1",
        "agent-market-bench-scenario-assessment-v1",
        "agent-market-bench-method-evaluation-v1",
        "agent-market-bench-case-run-v1",
        "agent-market-bench-metric-summary-v1",
        "agent-market-bench-paired-summary-v1",
        "agent-market-bench-run-summary-v1",
        "agent-market-bench-run-v1",
    )
    assert tuple(AgentMarketBenchMetricObservationStatusV1) == (
        AgentMarketBenchMetricObservationStatusV1.MEASURED,
        AgentMarketBenchMetricObservationStatusV1.NOT_APPLICABLE,
    )
    assert tuple(AgentMarketBenchMetricUnitV1) == (
        AgentMarketBenchMetricUnitV1.RATIO,
        AgentMarketBenchMetricUnitV1.PAISE,
        AgentMarketBenchMetricUnitV1.COUNT,
        AgentMarketBenchMetricUnitV1.BINARY,
        AgentMarketBenchMetricUnitV1.NANOSECONDS,
    )
    assert tuple(AgentMarketBenchMetricNotApplicableReasonV1) == (
        AgentMarketBenchMetricNotApplicableReasonV1.METHOD_NOT_APPLICABLE,
        AgentMarketBenchMetricNotApplicableReasonV1.ORACLE_WELFARE_ZERO,
        AgentMarketBenchMetricNotApplicableReasonV1.SCENARIO_NOT_DEFINED,
        AgentMarketBenchMetricNotApplicableReasonV1.NO_FINANCIAL_EXECUTION_IN_24D,
    )
    assert tuple(AgentMarketBenchScenarioEvidenceBasisV1) == (
        AgentMarketBenchScenarioEvidenceBasisV1.SHARED_ADMISSION,
        AgentMarketBenchScenarioEvidenceBasisV1.ECONOMIC_SENSITIVITY,
        AgentMarketBenchScenarioEvidenceBasisV1.AI_NOT_EXERCISED,
        AgentMarketBenchScenarioEvidenceBasisV1.FINANCIAL_RUNTIME_NOT_EXERCISED,
    )


@pytest.mark.parametrize(
    "model_type",
    (
        AgentMarketBenchRationalV1,
        AgentMarketBenchMetricObservationV1,
        AgentMarketBenchScenarioAssessmentV1,
        AgentMarketBenchMethodEvaluationV1,
        AgentMarketBenchCaseRunV1,
        AgentMarketBenchMetricSummaryV1,
        AgentMarketBenchPairedSummaryV1,
        AgentMarketBenchRunSummaryV1,
        AgentMarketBenchRunV1,
    ),
)
def test_measurement_models_are_strict_frozen_and_revalidating(model_type: type[object]) -> None:
    config = model_type.model_config
    assert config["frozen"] is True
    assert config["strict"] is True
    assert config["extra"] == "forbid"
    assert config["revalidate_instances"] == "always"


def test_tuple_fields_reject_lists_during_behavioral_validation() -> None:
    case = generate_agent_market_bench_case_v1(100_000_000)
    case_run = run_agent_market_bench_case_v1(case, clock_ns=lambda: 0)
    run = run_agent_market_bench_cases_v1((case,), clock_ns=lambda: 0)
    samples = (
        (case_run.evaluations[0], "metrics"),
        (case_run, "execution_order"),
        (case_run, "evaluations"),
        (case_run, "scenario_assessments"),
        (run.summary, "metric_summaries"),
        (run.summary, "paired_summaries"),
        (run, "case_runs"),
    )
    for model, field_name in samples:
        payload = {name: getattr(model, name) for name in type(model).model_fields}
        payload[field_name] = list(payload[field_name])
        with pytest.raises(ValidationError):
            type(model).model_validate(payload)


def test_metric_observation_rejects_wrong_unit() -> None:
    with pytest.raises(ValidationError, match="unit does not match"):
        AgentMarketBenchMetricObservationV1(
            metric=AgentMarketBenchMetricV1.WELFARE,
            status=AgentMarketBenchMetricObservationStatusV1.MEASURED,
            unit=AgentMarketBenchMetricUnitV1.RATIO,
            value=AgentMarketBenchRationalV1(numerator=1, denominator=1),
            not_applicable_reason=None,
        )


def test_metric_observation_rejects_na_with_value_using_complete_payload() -> None:
    with pytest.raises(ValidationError, match="N/A observation"):
        AgentMarketBenchMetricObservationV1(
            metric=AgentMarketBenchMetricV1.WELFARE,
            status=AgentMarketBenchMetricObservationStatusV1.NOT_APPLICABLE,
            unit=AgentMarketBenchMetricUnitV1.PAISE,
            value=AgentMarketBenchRationalV1(numerator=1, denominator=1),
            not_applicable_reason=AgentMarketBenchMetricNotApplicableReasonV1.SCENARIO_NOT_DEFINED,
        )


def test_metric_observation_rejects_measured_with_na_reason() -> None:
    with pytest.raises(ValidationError, match="measured observation"):
        AgentMarketBenchMetricObservationV1(
            metric=AgentMarketBenchMetricV1.WELFARE,
            status=AgentMarketBenchMetricObservationStatusV1.MEASURED,
            unit=AgentMarketBenchMetricUnitV1.PAISE,
            value=AgentMarketBenchRationalV1(numerator=1, denominator=1),
            not_applicable_reason=AgentMarketBenchMetricNotApplicableReasonV1.SCENARIO_NOT_DEFINED,
        )


def test_measurement_models_are_behaviorally_frozen() -> None:
    rational = AgentMarketBenchRationalV1(numerator=1, denominator=1)
    with pytest.raises(ValidationError, match="frozen"):
        rational.numerator = 2


def test_measurement_models_behaviorally_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AgentMarketBenchRationalV1.model_validate(
            {"numerator": 1, "denominator": 1, "unknown_field": 2}
        )


def test_rational_normalization_and_rejects_bool_or_bad_denominator() -> None:
    assert (
        AgentMarketBenchRationalV1(numerator=-12, denominator=18).model_dump(mode="python")[
            "numerator"
        ]
        == -2
    )
    assert AgentMarketBenchRationalV1(numerator=0, denominator=99).denominator == 1
    with pytest.raises(ValidationError):
        AgentMarketBenchRationalV1(numerator=True, denominator=1)
    with pytest.raises(ValidationError):
        AgentMarketBenchRationalV1(numerator=1, denominator=0)


def test_metric_observation_shape_and_decimal_contract() -> None:
    measured = AgentMarketBenchMetricObservationV1(
        metric=AgentMarketBenchMetricV1.WELFARE,
        status=AgentMarketBenchMetricObservationStatusV1.MEASURED,
        unit=AgentMarketBenchMetricUnitV1.PAISE,
        value=AgentMarketBenchRationalV1(numerator=2, denominator=1),
        not_applicable_reason=None,
    )
    assert measured.value is not None
    with pytest.raises(ValidationError):
        AgentMarketBenchMetricObservationV1(
            metric=AgentMarketBenchMetricV1.WELFARE,
            status=AgentMarketBenchMetricObservationStatusV1.MEASURED,
            unit=AgentMarketBenchMetricUnitV1.PAISE,
            value=None,
            not_applicable_reason=None,
        )
    with pytest.raises(ValidationError):
        AgentMarketBenchMetricObservationV1(
            metric=AgentMarketBenchMetricV1.WELFARE,
            status=AgentMarketBenchMetricObservationStatusV1.NOT_APPLICABLE,
            unit=AgentMarketBenchMetricUnitV1.PAISE,
            value=None,
            not_applicable_reason=AgentMarketBenchMetricNotApplicableReasonV1.SCENARIO_NOT_DEFINED,
        ).model_validate({"value": {"numerator": 1, "denominator": 1}})
    assert re.fullmatch(r"-?\d+\.\d{12}", "0.000000000000")
    assert re.fullmatch(r"-?\d+\.\d{12}", "-12.500000000000")


def test_paired_summary_shape_and_canonical_decimal_validation() -> None:
    common = {
        "comparator": AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER,
        "metric": AgentMarketBenchMetricV1.WELFARE,
        "unit": AgentMarketBenchMetricUnitV1.PAISE,
    }
    empty = AgentMarketBenchPairedSummaryV1(
        **common,
        paired_count=0,
        mean_difference=None,
        ci95_lower_decimal=None,
        ci95_upper_decimal=None,
    )
    assert empty.mean_difference is None
    one = AgentMarketBenchPairedSummaryV1(
        **common,
        paired_count=1,
        mean_difference=AgentMarketBenchRationalV1(numerator=2, denominator=1),
        ci95_lower_decimal=None,
        ci95_upper_decimal=None,
    )
    assert one.mean_difference is not None
    with_ci = AgentMarketBenchPairedSummaryV1(
        **common,
        paired_count=2,
        mean_difference=AgentMarketBenchRationalV1(numerator=2, denominator=1),
        ci95_lower_decimal="0.000000000000",
        ci95_upper_decimal="-12.500000000000",
    )
    assert with_ci.ci95_lower_decimal == "0.000000000000"
    for value in ("0", "0.0", "+1.000000000000", "1e-3", "nan", "Infinity"):
        with pytest.raises(ValidationError):
            AgentMarketBenchPairedSummaryV1(
                **common,
                paired_count=2,
                mean_difference=AgentMarketBenchRationalV1(numerator=1, denominator=1),
                ci95_lower_decimal=value,
                ci95_upper_decimal="0.000000000000",
            )


def test_measurement_models_have_no_ranking_or_significance_fields() -> None:
    forbidden = {
        "rank",
        "ranking",
        "winner_method",
        "significance",
        "p_value",
        "statistically_significant",
    }
    for model_type in (
        AgentMarketBenchRationalV1,
        AgentMarketBenchMetricObservationV1,
        AgentMarketBenchScenarioAssessmentV1,
        AgentMarketBenchMethodEvaluationV1,
        AgentMarketBenchCaseRunV1,
        AgentMarketBenchMetricSummaryV1,
        AgentMarketBenchPairedSummaryV1,
        AgentMarketBenchRunSummaryV1,
        AgentMarketBenchRunV1,
    ):
        assert not any(
            any(token in field_name for token in forbidden)
            for field_name in model_type.model_fields
        )


def test_case_run_and_summary_exact_coverage() -> None:
    case = generate_agent_market_bench_case_v1(100_000_000)
    ticks = iter(range(18))
    case_run = run_agent_market_bench_case_v1(case, clock_ns=lambda: next(ticks))
    assert tuple(e.method for e in case_run.evaluations) == tuple(AgentMarketBenchBaselineV1)
    assert all(
        tuple(o.metric for o in e.metrics) == tuple(AgentMarketBenchMetricV1)
        for e in case_run.evaluations
    )
    run = run_agent_market_bench_cases_v1(
        (case, generate_agent_market_bench_case_v1(100_000_001)), clock_ns=lambda: 0
    )
    assert len(run.summary.metric_summaries) == 99
    assert len(run.summary.paired_summaries) == 88
