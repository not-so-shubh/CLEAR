"""Pure exact-arithmetic summaries for AgentMarketBench V1."""

from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from fractions import Fraction

from clear_market.agentmarketbench.measurement_models import (
    AGENT_MARKET_BENCH_METRICS_V1_VERSION,
    AGENT_MARKET_BENCH_STATISTICS_V1_VERSION,
    AgentMarketBenchCaseRunV1,
    AgentMarketBenchMetricObservationStatusV1,
    AgentMarketBenchMetricSummaryV1,
    AgentMarketBenchPairedSummaryV1,
    AgentMarketBenchRationalV1,
    AgentMarketBenchRunSummaryV1,
)
from clear_market.agentmarketbench.models import (
    AgentMarketBenchBaselineV1,
    AgentMarketBenchMetricV1,
)

_Z95 = Decimal("1.95996398454005423552")
_QUANTUM = Decimal("0.000000000001")


def _fraction(value: AgentMarketBenchRationalV1 | None) -> Fraction:
    if value is None:
        raise ValueError("measured observation must have a value")
    return Fraction(value.numerator, value.denominator)


def _rational(value: Fraction) -> AgentMarketBenchRationalV1:
    return AgentMarketBenchRationalV1(
        numerator=value.numerator,
        denominator=value.denominator,
    )


def _decimal(value: Fraction) -> Decimal:
    with localcontext() as context:
        context.prec = 80
        return Decimal(value.numerator) / Decimal(value.denominator)


def _decimal_string(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_HALF_EVEN
        quantized = value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)
    if quantized == 0:
        quantized = Decimal(0).quantize(_QUANTUM)
    return format(quantized, ".12f")


def _ci95(values: tuple[Fraction, ...]) -> tuple[str | None, str | None]:
    count = len(values)
    if count < 2:
        return None, None
    mean = sum(values, Fraction(0)) / count
    variance_numerator = sum(((value - mean) ** 2 for value in values), Fraction(0))
    variance = Fraction(
        variance_numerator.numerator,
        variance_numerator.denominator * (count - 1),
    )
    with localcontext() as context:
        context.prec = 80
        standard_error = (
            Decimal(variance.numerator) / Decimal(variance.denominator) / count
        ).sqrt()
        half_width = _Z95 * standard_error
        lower = _decimal(mean) - half_width
        upper = _decimal(mean) + half_width
    return _decimal_string(lower), _decimal_string(upper)


def summarize_agent_market_bench_case_runs_v1(
    case_runs: tuple[AgentMarketBenchCaseRunV1, ...],
) -> AgentMarketBenchRunSummaryV1:
    """Summarize measured observations without imputing N/A values."""

    if type(case_runs) is not tuple:
        raise TypeError("case_runs must be supplied as a tuple")
    if not case_runs or any(
        type(case_run) is not AgentMarketBenchCaseRunV1 for case_run in case_runs
    ):
        raise ValueError("case_runs must be a non-empty tuple of exact case runs")
    metric_summaries = []
    evaluation_by_method = {
        method: tuple(
            next(evaluation for evaluation in case_run.evaluations if evaluation.method is method)
            for case_run in case_runs
        )
        for method in AgentMarketBenchBaselineV1
    }
    for method in AgentMarketBenchBaselineV1:
        evaluations = evaluation_by_method[method]
        for metric in AgentMarketBenchMetricV1:
            observations = tuple(
                next(
                    observation
                    for observation in evaluation.metrics
                    if observation.metric is metric
                )
                for evaluation in evaluations
            )
            measured = tuple(
                _fraction(observation.value)
                for observation in observations
                if observation.status is AgentMarketBenchMetricObservationStatusV1.MEASURED
            )
            unit = observations[0].unit
            mean = sum(measured, Fraction(0)) / len(measured) if measured else None
            metric_summaries.append(
                AgentMarketBenchMetricSummaryV1(
                    method=method,
                    metric=metric,
                    unit=unit,
                    measured_count=len(measured),
                    not_applicable_count=sum(
                        observation.status
                        is AgentMarketBenchMetricObservationStatusV1.NOT_APPLICABLE
                        for observation in observations
                    ),
                    mean_value=None if mean is None else _rational(mean),
                )
            )

    paired_summaries = []
    comparators = tuple(
        method
        for method in AgentMarketBenchBaselineV1
        if method is not AgentMarketBenchBaselineV1.CLEAR
    )
    for comparator in comparators:
        for metric in AgentMarketBenchMetricV1:
            differences = []
            units = []
            for case_run in case_runs:
                comparator_evaluation = next(
                    evaluation
                    for evaluation in case_run.evaluations
                    if evaluation.method is comparator
                )
                clear_evaluation = next(
                    evaluation
                    for evaluation in case_run.evaluations
                    if evaluation.method is AgentMarketBenchBaselineV1.CLEAR
                )
                comparator_observation = next(
                    observation
                    for observation in comparator_evaluation.metrics
                    if observation.metric is metric
                )
                clear_observation = next(
                    observation
                    for observation in clear_evaluation.metrics
                    if observation.metric is metric
                )
                if (
                    comparator_observation.status
                    is AgentMarketBenchMetricObservationStatusV1.MEASURED
                    and clear_observation.status
                    is AgentMarketBenchMetricObservationStatusV1.MEASURED
                ):
                    differences.append(
                        _fraction(comparator_observation.value) - _fraction(clear_observation.value)
                    )
                    units.append(comparator_observation.unit)
            unit = (
                units[0]
                if units
                else next(
                    observation.unit
                    for evaluation in case_runs[0].evaluations
                    if evaluation.method is comparator
                    for observation in evaluation.metrics
                    if observation.metric is metric
                )
            )
            paired_count = len(differences)
            mean_difference = (
                None
                if paired_count == 0
                else _rational(sum(differences, Fraction(0)) / paired_count)
            )
            lower, upper = _ci95(tuple(differences))
            paired_summaries.append(
                AgentMarketBenchPairedSummaryV1(
                    comparator=comparator,
                    metric=metric,
                    unit=unit,
                    paired_count=paired_count,
                    mean_difference=mean_difference,
                    ci95_lower_decimal=lower,
                    ci95_upper_decimal=upper,
                )
            )
    return AgentMarketBenchRunSummaryV1(
        case_count=len(case_runs),
        metric_summaries=tuple(metric_summaries),
        paired_summaries=tuple(paired_summaries),
    )


build_agent_market_bench_run_summary_v1 = summarize_agent_market_bench_case_runs_v1
summarize_agent_market_bench_run_v1 = summarize_agent_market_bench_case_runs_v1
build_agent_market_bench_statistics_v1 = summarize_agent_market_bench_case_runs_v1


__all__ = (
    "AGENT_MARKET_BENCH_METRICS_V1_VERSION",
    "AGENT_MARKET_BENCH_STATISTICS_V1_VERSION",
    "build_agent_market_bench_run_summary_v1",
    "build_agent_market_bench_statistics_v1",
    "summarize_agent_market_bench_case_runs_v1",
    "summarize_agent_market_bench_run_v1",
)
