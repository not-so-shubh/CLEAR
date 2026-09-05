"""Timed paired AgentMarketBench V1 execution over already-built cases."""

from collections.abc import Callable
from hashlib import sha256
from time import perf_counter_ns

from clear_market.agentmarketbench.full_information import (
    run_agent_market_bench_full_information_oracle_v1,
)
from clear_market.agentmarketbench.measurement_models import (
    AGENT_MARKET_BENCH_RUNNER_V1_VERSION,
    AgentMarketBenchCaseRunV1,
    AgentMarketBenchMethodEvaluationV1,
    AgentMarketBenchRunV1,
)
from clear_market.agentmarketbench.methods import run_agent_market_bench_method_v1
from clear_market.agentmarketbench.metrics import measure_agent_market_bench_method_v1
from clear_market.agentmarketbench.models import (
    AgentMarketBenchBaselineV1,
    AgentMarketBenchCaseV1,
)
from clear_market.agentmarketbench.protocol import (
    agent_market_bench_case_v1_digest,
    agent_market_bench_market_input_v1,
)
from clear_market.agentmarketbench.scenario_audit import audit_agent_market_bench_scenarios_v1
from clear_market.agentmarketbench.statistics import summarize_agent_market_bench_case_runs_v1


def _fresh_case(value: object) -> AgentMarketBenchCaseV1:
    if type(value) is not AgentMarketBenchCaseV1:
        raise TypeError("case must be exactly an AgentMarketBenchCaseV1")
    try:
        return AgentMarketBenchCaseV1.model_validate(value)
    except Exception as error:
        raise ValueError("case failed fresh validation") from error


def _clock_value(clock_ns: Callable[[], int]) -> int:
    value = clock_ns()
    if type(value) is not int:
        raise TypeError("clock_ns must return an exact int")
    return value


def _execution_order(case_digest: str) -> tuple[AgentMarketBenchBaselineV1, ...]:
    ranked = []
    for method in AgentMarketBenchBaselineV1:
        rank = sha256(
            (
                f"{AGENT_MARKET_BENCH_RUNNER_V1_VERSION}|method-order|"
                f"case_digest={case_digest}|method={method.value}"
            ).encode("ascii")
        ).hexdigest()
        ranked.append((rank, method.value, method))
    return tuple(item[2] for item in sorted(ranked, key=lambda item: item[:2]))


def run_agent_market_bench_case_v1(
    case: AgentMarketBenchCaseV1,
    *,
    clock_ns: Callable[[], int] = perf_counter_ns,
) -> AgentMarketBenchCaseRunV1:
    """Run all nine frozen methods and evaluate their results against latent truth."""

    fresh_case = _fresh_case(case)
    case_digest = agent_market_bench_case_v1_digest(fresh_case)
    execution_order = _execution_order(case_digest)
    market_input = agent_market_bench_market_input_v1(fresh_case)
    results = {}
    elapsed = {}
    for method in execution_order:
        start = _clock_value(clock_ns)
        if method is AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE:
            result = run_agent_market_bench_full_information_oracle_v1(fresh_case)
        else:
            result = run_agent_market_bench_method_v1(
                method=method,
                market_input=market_input,
            )
        end = _clock_value(clock_ns)
        if end < start:
            raise ValueError("clock_ns end value must not precede start value")
        results[method] = result
        elapsed[method] = end - start

    admissions = {result.admission for result in results.values()}
    if len(admissions) != 1:
        raise ValueError("all method results must share exactly equal admission evidence")
    admission = next(iter(admissions))
    oracle_result = results[AgentMarketBenchBaselineV1.FULL_INFORMATION_ORACLE]
    evaluations = []
    for method in AgentMarketBenchBaselineV1:
        result = results[method]
        measured = measure_agent_market_bench_method_v1(
            case=fresh_case,
            result=result,
            oracle_result=oracle_result,
            elapsed_ns=elapsed[method],
        )
        evaluations.append(
            AgentMarketBenchMethodEvaluationV1(
                method=method,
                result=result,
                elapsed_ns=elapsed[method],
                realized_quantity=measured.realization.realized_quantity,
                latent_capacity_excess_units=measured.realization.latent_capacity_excess_units,
                latent_hard_violation_units=measured.realization.latent_hard_violation_units,
                metrics=measured.observations,
            )
        )
    assessments = audit_agent_market_bench_scenarios_v1(
        case=fresh_case,
        admission=admission,
    )
    if tuple(assessment.scenario for assessment in assessments) != fresh_case.adversarial_scenarios:
        raise ValueError(
            "runner invariant violated: scenario assessments must follow the normalized case tuple"
        )
    return AgentMarketBenchCaseRunV1(
        case_id=fresh_case.case_id,
        seed=fresh_case.seed,
        case_digest_sha256=case_digest,
        execution_order=execution_order,
        evaluations=tuple(evaluations),
        scenario_assessments=assessments,
    )


def run_agent_market_bench_cases_v1(
    cases: tuple[AgentMarketBenchCaseV1, ...],
    *,
    clock_ns: Callable[[], int] = perf_counter_ns,
) -> AgentMarketBenchRunV1:
    """Run a non-empty exact tuple of unique cases and produce exact summaries."""

    if type(cases) is not tuple:
        raise TypeError("cases must be supplied as a tuple")
    if not cases:
        raise ValueError("cases must be non-empty")
    fresh_cases = tuple(_fresh_case(case) for case in cases)
    case_ids = tuple(case.case_id for case in fresh_cases)
    digests = tuple(agent_market_bench_case_v1_digest(case) for case in fresh_cases)
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("case IDs must be unique")
    if len(set(digests)) != len(digests):
        raise ValueError("case digests must be unique")
    case_runs = tuple(
        run_agent_market_bench_case_v1(case, clock_ns=clock_ns) for case in fresh_cases
    )
    summary = summarize_agent_market_bench_case_runs_v1(case_runs)
    return AgentMarketBenchRunV1(case_runs=case_runs, summary=summary)


__all__ = (
    "run_agent_market_bench_case_v1",
    "run_agent_market_bench_cases_v1",
)
