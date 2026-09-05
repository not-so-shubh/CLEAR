import inspect
from hashlib import sha256

import pytest

import clear_market.agentmarketbench.runner as runner_module
from clear_market.agentmarketbench.generator import generate_agent_market_bench_case_v1
from clear_market.agentmarketbench.measurement_models import (
    AgentMarketBenchCaseRunV1,
    AgentMarketBenchMetricNotApplicableReasonV1,
    AgentMarketBenchMetricObservationStatusV1,
    AgentMarketBenchMetricObservationV1,
    AgentMarketBenchMetricUnitV1,
    AgentMarketBenchRationalV1,
)
from clear_market.agentmarketbench.method_models import (
    AgentMarketBenchAdmissionV1,
    AgentMarketBenchMethodResultV1,
)
from clear_market.agentmarketbench.models import (
    AgentMarketBenchAdversarialScenarioV1,
    AgentMarketBenchBaselineV1,
    AgentMarketBenchMetricV1,
)
from clear_market.agentmarketbench.runner import (
    run_agent_market_bench_case_v1,
    run_agent_market_bench_cases_v1,
)
from clear_market.agentmarketbench.statistics import summarize_agent_market_bench_case_runs_v1

_START = 100_000_000


def _case_run(seed: int = _START, ticks=None):
    case = generate_agent_market_bench_case_v1(seed)
    clock_values = iter(range(18)) if ticks is None else iter(ticks)
    return case, run_agent_market_bench_case_v1(case, clock_ns=lambda: next(clock_values))


def _replace_observation(
    case_run: AgentMarketBenchCaseRunV1,
    method: AgentMarketBenchBaselineV1,
    replacement: AgentMarketBenchMetricObservationV1,
) -> AgentMarketBenchCaseRunV1:
    evaluations = []
    for evaluation in case_run.evaluations:
        if evaluation.method is not method:
            evaluations.append(evaluation)
            continue
        metrics = tuple(
            replacement if observation.metric is replacement.metric else observation
            for observation in evaluation.metrics
        )
        evaluations.append(
            type(evaluation).model_validate(evaluation.model_copy(update={"metrics": metrics}))
        )
    return AgentMarketBenchCaseRunV1.model_validate(
        case_run.model_copy(update={"evaluations": tuple(evaluations)})
    )


def _measured_observation(
    metric: AgentMarketBenchMetricV1,
    unit: AgentMarketBenchMetricUnitV1,
    numerator: int,
    denominator: int = 1,
) -> AgentMarketBenchMetricObservationV1:
    return AgentMarketBenchMetricObservationV1(
        metric=metric,
        status=AgentMarketBenchMetricObservationStatusV1.MEASURED,
        unit=unit,
        value=AgentMarketBenchRationalV1(
            numerator=numerator,
            denominator=denominator,
        ),
        not_applicable_reason=None,
    )


def _not_applicable_observation(
    metric: AgentMarketBenchMetricV1,
    unit: AgentMarketBenchMetricUnitV1,
) -> AgentMarketBenchMetricObservationV1:
    return AgentMarketBenchMetricObservationV1(
        metric=metric,
        status=AgentMarketBenchMetricObservationStatusV1.NOT_APPLICABLE,
        unit=unit,
        value=None,
        not_applicable_reason=AgentMarketBenchMetricNotApplicableReasonV1.SCENARIO_NOT_DEFINED,
    )


def test_runner_and_statistics_dependency_firewalls() -> None:
    runner_source = inspect.getsource(
        __import__("clear_market.agentmarketbench.runner", fromlist=["x"])
    )
    for forbidden in (
        "agentmarketbench.generator",
        "agentmarketbench.seeds",
        "clear_market.benchmark",
        "payments",
        "Razorpay",
        "persistence",
        "clear_market.execution",
        "AIProvider",
    ):
        assert forbidden not in runner_source
    statistics_source = inspect.getsource(
        __import__("clear_market.agentmarketbench.statistics", fromlist=["x"])
    )
    for forbidden in (
        "random",
        "secrets",
        "numpy",
        "scipy",
        "pandas",
        "perf_counter",
        "import time",
    ):
        assert forbidden not in statistics_source


def test_execution_order_is_the_frozen_case_digest_hash_order() -> None:
    _, case_run = _case_run()
    expected = tuple(
        method
        for _, _, method in sorted(
            (
                sha256(
                    (
                        "agent-market-bench-runner-v1|method-order|"
                        f"case_digest={case_run.case_digest_sha256}|method={method.value}"
                    ).encode("ascii")
                ).hexdigest(),
                method.value,
                method,
            )
            for method in AgentMarketBenchBaselineV1
        )
    )
    assert case_run.execution_order == expected
    assert tuple(evaluation.method for evaluation in case_run.evaluations) == tuple(
        AgentMarketBenchBaselineV1
    )


def test_fake_clock_records_exact_observational_elapsed_ns_and_semantic_repeat_is_equal() -> None:
    _, first = _case_run(ticks=(10, 17) * 9)
    _, second = _case_run(ticks=(10, 17) * 9)
    assert first == second
    assert {evaluation.elapsed_ns for evaluation in first.evaluations} == {7}
    assert all(
        observation.status is AgentMarketBenchMetricObservationStatusV1.MEASURED
        for evaluation in first.evaluations
        for observation in evaluation.metrics
        if observation.metric is AgentMarketBenchMetricV1.LATENCY
    )


def test_clock_rejects_bool_nonint_and_backwards_end() -> None:
    case = generate_agent_market_bench_case_v1(_START)
    with pytest.raises(TypeError):
        run_agent_market_bench_case_v1(case, clock_ns=lambda: True)
    values = iter((1, "not-an-int"))
    with pytest.raises(TypeError):
        run_agent_market_bench_case_v1(case, clock_ns=lambda: next(values))
    values = iter((2, 1))
    with pytest.raises(ValueError, match="precede"):
        run_agent_market_bench_case_v1(case, clock_ns=lambda: next(values))


def test_runner_rejects_wrong_case_type() -> None:
    with pytest.raises(TypeError, match="case must be exactly"):
        run_agent_market_bench_case_v1(None)


def test_default_perf_counter_latency_is_exact_nonnegative_and_matches_observation() -> None:
    case = generate_agent_market_bench_case_v1(_START)
    case_run = run_agent_market_bench_case_v1(case)
    for evaluation in case_run.evaluations:
        assert type(evaluation.elapsed_ns) is int
        assert evaluation.elapsed_ns >= 0
        latency = next(
            observation
            for observation in evaluation.metrics
            if observation.metric is AgentMarketBenchMetricV1.LATENCY
        )
        assert latency.status is AgentMarketBenchMetricObservationStatusV1.MEASURED
        assert latency.value is not None
        assert latency.value.denominator == 1
        assert latency.value.numerator == evaluation.elapsed_ns


def test_case_collection_requires_nonempty_exact_tuple_and_unique_identity() -> None:
    case = generate_agent_market_bench_case_v1(_START)
    with pytest.raises(TypeError):
        run_agent_market_bench_cases_v1([case])
    with pytest.raises(ValueError):
        run_agent_market_bench_cases_v1(())
    with pytest.raises(ValueError, match="IDs"):
        run_agent_market_bench_cases_v1((case, case), clock_ns=lambda: 0)


def test_case_collection_rejects_duplicate_digests_independently() -> None:
    first = generate_agent_market_bench_case_v1(_START)
    second = generate_agent_market_bench_case_v1(_START + 1)
    original_digest = runner_module.agent_market_bench_case_v1_digest
    try:
        runner_module.agent_market_bench_case_v1_digest = lambda _case: "0" * 64
        with pytest.raises(ValueError, match="digests"):
            run_agent_market_bench_cases_v1((first, second), clock_ns=lambda: 0)
    finally:
        runner_module.agent_market_bench_case_v1_digest = original_digest


def test_runner_rejects_one_structurally_valid_result_with_different_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = generate_agent_market_bench_case_v1(_START)
    original = runner_module.run_agent_market_bench_method_v1
    changed_method = AgentMarketBenchBaselineV1.CHEAPEST_QUALIFYING

    def run_method(*, method, market_input):
        result = original(method=method, market_input=market_input)
        if method is not changed_method:
            return result
        assert result.admission.admitted_submission_indices
        different = AgentMarketBenchAdmissionV1(
            admitted_submission_indices=(),
            rejections=(),
        )
        changed = result.model_copy(update={"admission": different})
        return AgentMarketBenchMethodResultV1.model_validate(changed)

    monkeypatch.setattr(runner_module, "run_agent_market_bench_method_v1", run_method)
    with pytest.raises(ValueError, match="share exactly equal admission evidence"):
        run_agent_market_bench_case_v1(case, clock_ns=lambda: 0)


def test_runner_timing_projects_once_before_clock_and_brackets_each_public_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = generate_agent_market_bench_case_v1(_START)
    events: list[tuple[str, object]] = []
    projection = runner_module.agent_market_bench_market_input_v1
    original_method = runner_module.run_agent_market_bench_method_v1
    original_oracle = runner_module.run_agent_market_bench_full_information_oracle_v1

    def project(value):
        events.append(("projection", None))
        return projection(value)

    def run_method(*, method, market_input):
        events.append(("method", method))
        return original_method(method=method, market_input=market_input)

    def run_oracle(value):
        events.append(("oracle", None))
        return original_oracle(value)

    monkeypatch.setattr(runner_module, "agent_market_bench_market_input_v1", project)
    monkeypatch.setattr(runner_module, "run_agent_market_bench_method_v1", run_method)
    monkeypatch.setattr(
        runner_module,
        "run_agent_market_bench_full_information_oracle_v1",
        run_oracle,
    )
    tick = 0

    def clock() -> int:
        nonlocal tick
        events.append(("clock", tick))
        tick += 1
        return tick

    run_agent_market_bench_case_v1(case, clock_ns=clock)
    assert [name for name, _ in events].count("projection") == 1
    first_clock = next(index for index, (name, _) in enumerate(events) if name == "clock")
    assert events.index(("projection", None)) < first_clock
    calls = [index for index, (name, _) in enumerate(events) if name in {"method", "oracle"}]
    assert len(calls) == 9
    for call_index in calls:
        assert events[call_index - 1][0] == "clock"
        assert events[call_index + 1][0] == "clock"
    assert [name for name, _ in events].count("clock") == 18
    ordinary_calls = tuple(value for name, value in events if name == "method")
    expected_ordinary = tuple(
        method
        for method in AgentMarketBenchBaselineV1
        if method is not AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE
    )
    assert len(ordinary_calls) == len(set(ordinary_calls)) == 8
    assert set(ordinary_calls) == set(expected_ordinary)
    assert [name for name, _ in events].count("oracle") == 1


def test_runner_assessments_follow_the_fresh_case_scenario_tuple() -> None:
    base = generate_agent_market_bench_case_v1(_START)
    case = base.model_copy(
        update={
            "adversarial_scenarios": (
                AgentMarketBenchAdversarialScenarioV1.RECOVERY,
                AgentMarketBenchAdversarialScenarioV1.ALTERED_OFFER,
                AgentMarketBenchAdversarialScenarioV1.PROMPT_INJECTION,
            )
        }
    )
    fresh = type(base).model_validate(case)
    assert fresh.adversarial_scenarios == (
        AgentMarketBenchAdversarialScenarioV1.ALTERED_OFFER,
        AgentMarketBenchAdversarialScenarioV1.PROMPT_INJECTION,
        AgentMarketBenchAdversarialScenarioV1.RECOVERY,
    )
    case_run = run_agent_market_bench_case_v1(fresh, clock_ns=lambda: 0)
    scenarios = tuple(item.scenario for item in case_run.scenario_assessments)
    assert scenarios == fresh.adversarial_scenarios
    assert len(scenarios) == len(set(scenarios)) == 3


def test_first_42_development_cases_run_all_nine_methods_with_complete_metrics() -> None:
    for seed in range(_START, _START + 42):
        case = generate_agent_market_bench_case_v1(seed)
        ticks = iter(range(18))

        def clock(ticks=ticks) -> int:
            return next(ticks)

        case_run = run_agent_market_bench_case_v1(case, clock_ns=clock)
        assert len(case_run.evaluations) == 9
        assert all(len(evaluation.metrics) == 11 for evaluation in case_run.evaluations)
        assert len(case_run.scenario_assessments) == len(case.adversarial_scenarios)


def test_summary_has_exact_coverage_and_excludes_na_from_means() -> None:
    _, first = _case_run()
    _, second = _case_run(_START + 2)
    summary = summarize_agent_market_bench_case_runs_v1((first, second))
    assert summary.case_count == 2
    assert len(summary.metric_summaries) == 99
    assert len(summary.paired_summaries) == 88
    random_manipulation = next(
        item
        for item in summary.metric_summaries
        if item.method is AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER
        and item.metric is AgentMarketBenchMetricV1.MANIPULATION_SUCCESS
    )
    assert random_manipulation.not_applicable_count == 2
    assert random_manipulation.measured_count == 0
    assert random_manipulation.mean_value is None


def test_method_metric_mean_uses_exact_rationals() -> None:
    transformed = []
    for seed, (numerator, denominator) in zip(
        (_START, _START + 1, _START + 2),
        ((1, 3), (2, 3), (4, 3)),
        strict=True,
    ):
        case_run = _case_run(seed, ticks=(0,) * 18)[1]
        transformed.append(
            _replace_observation(
                case_run,
                AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER,
                _measured_observation(
                    AgentMarketBenchMetricV1.ALLOCATIVE_EFFICIENCY,
                    AgentMarketBenchMetricUnitV1.RATIO,
                    numerator,
                    denominator,
                ),
            )
        )
    summary = summarize_agent_market_bench_case_runs_v1(tuple(transformed))
    metric_summary = next(
        item
        for item in summary.metric_summaries
        if item.method is AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER
        and item.metric is AgentMarketBenchMetricV1.ALLOCATIVE_EFFICIENCY
    )
    assert metric_summary.measured_count == 3
    assert metric_summary.not_applicable_count == 0
    assert metric_summary.mean_value == AgentMarketBenchRationalV1(
        numerator=7,
        denominator=9,
    )


def test_paired_summary_excludes_each_one_sided_na_instead_of_imputing_zero() -> None:
    metric = AgentMarketBenchMetricV1.MANIPULATION_SUCCESS
    unit = AgentMarketBenchMetricUnitV1.BINARY
    comparator = AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER

    both_measured = _case_run(_START, ticks=(0,) * 18)[1]
    both_measured = _replace_observation(
        both_measured,
        comparator,
        _measured_observation(metric, unit, 1),
    )
    both_measured = _replace_observation(
        both_measured,
        AgentMarketBenchBaselineV1.CLEAR,
        _measured_observation(metric, unit, 0),
    )

    comparator_na = _case_run(_START + 1, ticks=(0,) * 18)[1]
    comparator_na = _replace_observation(
        comparator_na,
        comparator,
        _not_applicable_observation(metric, unit),
    )
    comparator_na = _replace_observation(
        comparator_na,
        AgentMarketBenchBaselineV1.CLEAR,
        _measured_observation(metric, unit, 0),
    )

    clear_na = _case_run(_START + 2, ticks=(0,) * 18)[1]
    clear_na = _replace_observation(
        clear_na,
        comparator,
        _measured_observation(metric, unit, 1),
    )
    clear_na = _replace_observation(
        clear_na,
        AgentMarketBenchBaselineV1.CLEAR,
        _not_applicable_observation(metric, unit),
    )

    summary = summarize_agent_market_bench_case_runs_v1((both_measured, comparator_na, clear_na))
    pair = next(
        item
        for item in summary.paired_summaries
        if item.comparator is comparator and item.metric is metric
    )
    assert pair.paired_count == 1
    assert pair.mean_difference == AgentMarketBenchRationalV1(
        numerator=1,
        denominator=1,
    )
    assert pair.ci95_lower_decimal is None
    assert pair.ci95_upper_decimal is None


def test_paired_summary_is_comparator_minus_clear() -> None:
    _, case_run = _case_run()
    summary = summarize_agent_market_bench_case_runs_v1((case_run,))
    pair = next(
        item
        for item in summary.paired_summaries
        if item.comparator is AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER
        and item.metric is AgentMarketBenchMetricV1.LATENCY
    )
    comparator = next(
        evaluation
        for evaluation in case_run.evaluations
        if evaluation.method is AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER
    )
    clear = next(
        evaluation
        for evaluation in case_run.evaluations
        if evaluation.method is AgentMarketBenchBaselineV1.CLEAR
    )
    assert pair.mean_difference is not None
    assert pair.mean_difference.numerator == (
        next(
            o for o in comparator.metrics if o.metric is AgentMarketBenchMetricV1.LATENCY
        ).value.numerator
        - next(
            o for o in clear.metrics if o.metric is AgentMarketBenchMetricV1.LATENCY
        ).value.numerator
    )


def test_public_paired_summary_has_hard_coded_ci_golden() -> None:
    transformed = []
    for index, seed in enumerate((_START, _START + 1, _START + 2), start=1):
        case_run = _case_run(seed, ticks=(0,) * 18)[1]
        evaluations = []
        for evaluation in case_run.evaluations:
            if evaluation.method is AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER:
                value = AgentMarketBenchRationalV1(numerator=index + 10, denominator=1)
            elif evaluation.method is AgentMarketBenchBaselineV1.CLEAR:
                value = AgentMarketBenchRationalV1(numerator=10, denominator=1)
            else:
                value = None
            if value is None:
                evaluations.append(evaluation)
                continue
            metrics = tuple(
                observation.model_copy(update={"value": value})
                if observation.metric is AgentMarketBenchMetricV1.LATENCY
                else observation
                for observation in evaluation.metrics
            )
            evaluations.append(evaluation.model_copy(update={"metrics": metrics}))
        transformed.append(
            AgentMarketBenchCaseRunV1.model_validate(
                case_run.model_copy(update={"evaluations": tuple(evaluations)})
            )
        )
    summary = summarize_agent_market_bench_case_runs_v1(tuple(transformed))
    pair = next(
        item
        for item in summary.paired_summaries
        if item.comparator is AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER
        and item.metric is AgentMarketBenchMetricV1.LATENCY
    )
    assert pair.paired_count == 3
    assert pair.mean_difference == AgentMarketBenchRationalV1(numerator=2, denominator=1)
    assert pair.ci95_lower_decimal == "0.868414265924"
    assert pair.ci95_upper_decimal == "3.131585734076"


def test_paired_summary_excludes_na_and_handles_zero_or_one_pair() -> None:
    _, empty_case_run = _case_run(_START, ticks=(0,) * 18)
    empty = summarize_agent_market_bench_case_runs_v1((empty_case_run,))
    empty_pair = next(
        item
        for item in empty.paired_summaries
        if item.comparator is AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER
        and item.metric is AgentMarketBenchMetricV1.MANIPULATION_SUCCESS
    )
    assert empty_pair.paired_count == 0
    assert empty_pair.mean_difference is None
    assert empty_pair.ci95_lower_decimal is None
    assert empty_pair.ci95_upper_decimal is None

    one = summarize_agent_market_bench_case_runs_v1((empty_case_run,))
    latency_pair = next(
        item
        for item in one.paired_summaries
        if item.comparator is AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER
        and item.metric is AgentMarketBenchMetricV1.LATENCY
    )
    assert latency_pair.paired_count == 1
    assert latency_pair.mean_difference == AgentMarketBenchRationalV1(numerator=0, denominator=1)
    assert latency_pair.ci95_lower_decimal is None
    assert latency_pair.ci95_upper_decimal is None
