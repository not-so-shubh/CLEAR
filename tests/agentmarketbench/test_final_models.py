import pytest
from pydantic import BaseModel, ValidationError

from clear_market.agentmarketbench.final_evidence import (
    AgentMarketBenchFinalStreamingAccumulatorV1,
    compact_agent_market_bench_case_run_v1,
)
from clear_market.agentmarketbench.final_models import (
    AGENT_MARKET_BENCH_FINAL_EVIDENCE_V1_VERSION,
    AGENT_MARKET_BENCH_FINAL_MANIFEST_V1_VERSION,
    AGENT_MARKET_BENCH_FINAL_RUN_METADATA_V1_VERSION,
    AGENT_MARKET_BENCH_FINAL_SEMANTIC_RECORD_V1_VERSION,
    AGENT_MARKET_BENCH_FINAL_SUMMARY_V1_VERSION,
    AGENT_MARKET_BENCH_FINAL_TIMING_RECORD_V1_VERSION,
    AgentMarketBenchFinalEvidenceFileKindV1,
    AgentMarketBenchFinalEvidenceFileV1,
    AgentMarketBenchFinalManifestV1,
    AgentMarketBenchFinalMethodStatusCountV1,
    AgentMarketBenchFinalRunMetadataV1,
    AgentMarketBenchFinalScenarioAssessmentCountV1,
    AgentMarketBenchFinalScenarioCountV1,
    AgentMarketBenchFinalSemanticMethodV1,
    AgentMarketBenchFinalSemanticRecordV1,
    AgentMarketBenchFinalSummaryV1,
    AgentMarketBenchFinalTimingMethodV1,
    AgentMarketBenchFinalTimingRecordV1,
)
from clear_market.agentmarketbench.generator import generate_agent_market_bench_case_v1
from clear_market.agentmarketbench.models import AgentMarketBenchMetricV1
from clear_market.agentmarketbench.runner import run_agent_market_bench_case_v1

_COMMIT = "e3c0d06f5c07fe10b4ad62dc5575108f51be337c"
_SHA = "a" * 64


@pytest.fixture(autouse=True)
def _guard_final_holdout_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    original = generate_agent_market_bench_case_v1

    def guarded(seed: int):
        if seed >= 2_000_000_000:
            raise AssertionError("24E-A tests must not generate a final-holdout case")
        return original(seed)

    monkeypatch.setitem(globals(), "generate_agent_market_bench_case_v1", guarded)


def _records(seed: int = 100_000_000):
    case = generate_agent_market_bench_case_v1(seed)
    case_run = run_agent_market_bench_case_v1(case, clock_ns=lambda: 0)
    return compact_agent_market_bench_case_run_v1(case_run)


def _payload(model: BaseModel, **updates: object) -> dict[str, object]:
    values = {field_name: getattr(model, field_name) for field_name in type(model).model_fields}
    values.update(updates)
    return values


def _summary() -> AgentMarketBenchFinalSummaryV1:
    semantic, timing = _records()
    accumulator = AgentMarketBenchFinalStreamingAccumulatorV1()
    accumulator.add(semantic, timing)
    return accumulator.build_final_summary_v1(
        evaluated_source_commit=_COMMIT,
        seed_sequence_sha256=_SHA,
    )


def test_all_six_final_evidence_versions_are_exact() -> None:
    assert (
        AGENT_MARKET_BENCH_FINAL_EVIDENCE_V1_VERSION,
        AGENT_MARKET_BENCH_FINAL_SEMANTIC_RECORD_V1_VERSION,
        AGENT_MARKET_BENCH_FINAL_TIMING_RECORD_V1_VERSION,
        AGENT_MARKET_BENCH_FINAL_SUMMARY_V1_VERSION,
        AGENT_MARKET_BENCH_FINAL_MANIFEST_V1_VERSION,
        AGENT_MARKET_BENCH_FINAL_RUN_METADATA_V1_VERSION,
    ) == (
        "agent-market-bench-final-evidence-v1",
        "agent-market-bench-final-semantic-record-v1",
        "agent-market-bench-final-timing-record-v1",
        "agent-market-bench-final-summary-v1",
        "agent-market-bench-final-manifest-v1",
        "agent-market-bench-final-run-metadata-v1",
    )


@pytest.mark.parametrize(
    "model_type",
    (
        AgentMarketBenchFinalSemanticMethodV1,
        AgentMarketBenchFinalSemanticRecordV1,
        AgentMarketBenchFinalTimingMethodV1,
        AgentMarketBenchFinalTimingRecordV1,
        AgentMarketBenchFinalMethodStatusCountV1,
        AgentMarketBenchFinalScenarioCountV1,
        AgentMarketBenchFinalScenarioAssessmentCountV1,
        AgentMarketBenchFinalSummaryV1,
        AgentMarketBenchFinalEvidenceFileV1,
        AgentMarketBenchFinalRunMetadataV1,
        AgentMarketBenchFinalManifestV1,
    ),
)
def test_final_models_are_strict_frozen_extra_forbid_and_revalidating(
    model_type: type[BaseModel],
) -> None:
    assert model_type.model_config["strict"] is True
    assert model_type.model_config["frozen"] is True
    assert model_type.model_config["extra"] == "forbid"
    assert model_type.model_config["revalidate_instances"] == "always"


def test_tuple_fields_reject_lists_behaviorally() -> None:
    semantic, timing = _records()
    summary = _summary()
    samples = (
        (semantic.methods[0], "metrics"),
        (semantic, "adversarial_scenarios"),
        (semantic, "scenario_assessments"),
        (semantic, "methods"),
        (timing, "timings"),
        (summary, "method_status_counts"),
        (summary, "scenario_counts"),
        (summary, "scenario_assessment_counts"),
    )
    for model, field_name in samples:
        with pytest.raises(ValidationError):
            type(model).model_validate(
                _payload(model, **{field_name: list(getattr(model, field_name))})
            )


def test_sha256_and_git_commit_patterns_are_strict_lowercase() -> None:
    semantic, _ = _records()
    method = semantic.methods[0]
    for bad_sha in ("A" * 64, "a" * 63, "g" * 64):
        with pytest.raises(ValidationError, match="lowercase SHA-256"):
            AgentMarketBenchFinalSemanticMethodV1.model_validate(
                _payload(method, result_digest_sha256=bad_sha)
            )
    summary = _summary()
    for bad_commit in ("E" * 40, "e" * 39, "z" * 40):
        with pytest.raises(ValidationError, match="lowercase 40-hex"):
            AgentMarketBenchFinalSummaryV1.model_validate(
                _payload(summary, evaluated_source_commit=bad_commit)
            )


def test_semantic_method_requires_exact_ten_non_latency_metrics() -> None:
    semantic, _ = _records()
    method = semantic.methods[0]
    assert tuple(item.metric for item in method.metrics) == tuple(
        metric
        for metric in AgentMarketBenchMetricV1
        if metric is not AgentMarketBenchMetricV1.LATENCY
    )
    case_run = run_agent_market_bench_case_v1(
        generate_agent_market_bench_case_v1(100_000_000), clock_ns=lambda: 0
    )
    latency = next(
        item
        for item in case_run.evaluations[0].metrics
        if item.metric is AgentMarketBenchMetricV1.LATENCY
    )
    with pytest.raises(ValidationError, match="exact ten non-latency"):
        AgentMarketBenchFinalSemanticMethodV1.model_validate(
            _payload(method, metrics=(*method.metrics, latency))
        )


def test_semantic_and_timing_records_require_all_nine_methods_in_enum_order() -> None:
    semantic, timing = _records()
    with pytest.raises(ValidationError, match="all nine baselines"):
        AgentMarketBenchFinalSemanticRecordV1.model_validate(
            _payload(semantic, methods=tuple(reversed(semantic.methods)))
        )
    with pytest.raises(ValidationError, match="all nine baselines"):
        AgentMarketBenchFinalTimingRecordV1.model_validate(
            _payload(timing, timings=tuple(reversed(timing.timings)))
        )


def test_scenario_assessments_must_match_scenario_tuple() -> None:
    semantic, _ = _records(100_000_001)
    assert semantic.adversarial_scenarios
    with pytest.raises(ValidationError, match="must equal adversarial scenarios"):
        AgentMarketBenchFinalSemanticRecordV1.model_validate(
            _payload(semantic, adversarial_scenarios=())
        )


def test_evidence_paths_and_shard_metadata_are_strict() -> None:
    shard = AgentMarketBenchFinalEvidenceFileV1(
        relative_path="semantic/part-00000.jsonl.gz",
        kind=AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD,
        sha256=_SHA,
        byte_count=100,
        line_count=500,
        uncompressed_sha256="b" * 64,
        first_seed=100_000_000,
        last_seed=100_000_499,
    )
    assert shard.line_count == 500
    for path in ("/absolute", "../escape", "semantic/../escape", "semantic\\part.gz"):
        with pytest.raises(ValidationError, match="POSIX relative"):
            AgentMarketBenchFinalEvidenceFileV1.model_validate(_payload(shard, relative_path=path))
    with pytest.raises(ValidationError, match="uncompressed SHA-256"):
        AgentMarketBenchFinalEvidenceFileV1.model_validate(
            _payload(shard, uncompressed_sha256=None)
        )
    with pytest.raises(ValidationError, match="cannot have uncompressed"):
        AgentMarketBenchFinalEvidenceFileV1.model_validate(
            _payload(
                shard,
                relative_path="summary.json",
                kind=AgentMarketBenchFinalEvidenceFileKindV1.SUMMARY,
            )
        )


def test_final_summary_requires_exact_status_coverage_and_count_invariants() -> None:
    summary = _summary()
    assert len(summary.method_status_counts) == 9 * 3
    with pytest.raises(ValidationError, match="exact 9x3"):
        AgentMarketBenchFinalSummaryV1.model_validate(
            _payload(summary, method_status_counts=summary.method_status_counts[:-1])
        )
    changed = summary.method_status_counts[0].model_copy(
        update={"count": summary.method_status_counts[0].count + 1}
    )
    with pytest.raises(ValidationError, match="sum to case_count"):
        AgentMarketBenchFinalSummaryV1.model_validate(
            _payload(summary, method_status_counts=(changed, *summary.method_status_counts[1:]))
        )
    with pytest.raises(ValidationError, match="standard and scenario"):
        AgentMarketBenchFinalSummaryV1.model_validate(
            _payload(summary, standard_case_count=summary.standard_case_count + 1)
        )


def test_final_models_are_frozen_and_forbid_unknown_fields() -> None:
    semantic, _ = _records()
    with pytest.raises(ValidationError, match="frozen"):
        semantic.seed = 100_000_001
    with pytest.raises(ValidationError, match="Extra inputs"):
        AgentMarketBenchFinalSemanticRecordV1.model_validate(
            {**_payload(semantic), "unknown": True}
        )


def test_final_models_have_no_ranking_winner_significance_or_p_value_fields() -> None:
    forbidden = ("rank", "winner_method", "significance", "p_value", "recommendation")
    for model_type in (
        AgentMarketBenchFinalSemanticMethodV1,
        AgentMarketBenchFinalSemanticRecordV1,
        AgentMarketBenchFinalTimingMethodV1,
        AgentMarketBenchFinalTimingRecordV1,
        AgentMarketBenchFinalMethodStatusCountV1,
        AgentMarketBenchFinalScenarioCountV1,
        AgentMarketBenchFinalScenarioAssessmentCountV1,
        AgentMarketBenchFinalSummaryV1,
        AgentMarketBenchFinalEvidenceFileV1,
        AgentMarketBenchFinalRunMetadataV1,
        AgentMarketBenchFinalManifestV1,
    ):
        assert not any(
            token in field_name for field_name in model_type.model_fields for token in forbidden
        )
