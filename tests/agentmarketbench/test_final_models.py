from typing import Literal, get_origin

import pytest
from pydantic import BaseModel, ValidationError

from clear_market.agentmarketbench import final_models, generator
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
    AGENT_MARKET_BENCH_REPLACEMENT_FINAL_EVIDENCE_V1_VERSION,
    AGENT_MARKET_BENCH_REPLACEMENT_FINAL_MANIFEST_V1_VERSION,
    AGENT_MARKET_BENCH_REPLACEMENT_FINAL_RUN_METADATA_V1_VERSION,
    AGENT_MARKET_BENCH_REPLACEMENT_FINAL_SUMMARY_V1_VERSION,
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
    AgentMarketBenchReplacementFinalManifestV1,
    AgentMarketBenchReplacementFinalRunMetadataV1,
    AgentMarketBenchReplacementFinalSummaryV1,
)
from clear_market.agentmarketbench.generator import generate_agent_market_bench_case_v1
from clear_market.agentmarketbench.models import AgentMarketBenchMetricV1
from clear_market.agentmarketbench.runner import run_agent_market_bench_case_v1
from clear_market.agentmarketbench.seeds import (
    AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1,
    AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEED_SEQUENCE_SHA256_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1,
)

_COMMIT = "e3c0d06f5c07fe10b4ad62dc5575108f51be337c"
_SHA = "a" * 64


@pytest.fixture(autouse=True)
def _guard_final_holdout_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    original = generate_agent_market_bench_case_v1

    def guarded(seed: int):
        if seed in AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1:
            raise AssertionError("R2 tests must not generate a replacement-holdout case")
        if seed in AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1:
            raise AssertionError("R2 tests must not generate an original-final case")
        if seed not in AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1:
            raise AssertionError("R2 model tests may generate only frozen development cases")
        return original(seed)

    monkeypatch.setitem(globals(), "generate_agent_market_bench_case_v1", guarded)
    monkeypatch.setattr(generator, "generate_agent_market_bench_case_v1", guarded)


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


def _replacement_summary() -> AgentMarketBenchReplacementFinalSummaryV1:
    semantic, timing = _records(AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1[1])
    accumulator = AgentMarketBenchFinalStreamingAccumulatorV1()
    accumulator.add(semantic, timing)
    historical = accumulator.build_final_summary_v1(
        evaluated_source_commit=_COMMIT,
        seed_sequence_sha256=_SHA,
    )
    values = _payload(historical)
    del values["agent_market_bench_final_summary_version"]
    return AgentMarketBenchReplacementFinalSummaryV1.model_validate(
        {
            **values,
            "selection_anchor_commit": (
                AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1
            ),
            "selection_sha256": AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1,
        }
    )


def _replacement_metadata() -> AgentMarketBenchReplacementFinalRunMetadataV1:
    return AgentMarketBenchReplacementFinalRunMetadataV1(
        evaluated_source_commit=_COMMIT,
        selection_anchor_commit=AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1,
        selection_sha256=AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1,
        started_at_utc="2026-09-05T00:00:00.000000Z",
        completed_at_utc="2026-09-05T00:00:01.000000Z",
        python_version="3.12.0",
        platform_system="TestOS",
        platform_machine="test-machine-class",
        pydantic_version="2.0.0",
        ortools_version="9.15.6755",
        cryptography_version="43.0.0",
    )


def _replacement_manifest() -> AgentMarketBenchReplacementFinalManifestV1:
    """Synthetic manifest entries only: no case, outcome, record, or evidence file is made."""
    seeds = AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1
    entries = []
    for directory, kind in (
        ("semantic", AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD),
        ("timing", AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD),
    ):
        for index in range(20):
            entries.append(
                AgentMarketBenchFinalEvidenceFileV1(
                    relative_path=f"{directory}/part-{index:05d}.jsonl.gz",
                    kind=kind,
                    sha256=_SHA,
                    byte_count=100,
                    line_count=500,
                    uncompressed_sha256="b" * 64,
                    first_seed=seeds[index * 500],
                    last_seed=seeds[(index + 1) * 500 - 1],
                )
            )
    for relative_path, kind in (
        ("summary.json", AgentMarketBenchFinalEvidenceFileKindV1.SUMMARY),
        ("report.md", AgentMarketBenchFinalEvidenceFileKindV1.REPORT),
        ("run_metadata.json", AgentMarketBenchFinalEvidenceFileKindV1.RUN_METADATA),
    ):
        entries.append(
            AgentMarketBenchFinalEvidenceFileV1(
                relative_path=relative_path,
                kind=kind,
                sha256=_SHA,
                byte_count=100,
                line_count=1,
                uncompressed_sha256=None,
                first_seed=None,
                last_seed=None,
            )
        )
    return AgentMarketBenchReplacementFinalManifestV1(
        evaluated_source_commit=_COMMIT,
        selection_anchor_commit=AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1,
        selection_sha256=AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1,
        case_count=10_000,
        first_seed=seeds[0],
        last_seed=seeds[-1],
        seed_sequence_sha256=AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEED_SEQUENCE_SHA256_V1,
        semantic_root_sha256=_SHA,
        timing_root_sha256=_SHA,
        evidence_root_sha256=_SHA,
        files=tuple(sorted(entries, key=lambda item: item.relative_path)),
    )


def _replacement_models() -> tuple[BaseModel, ...]:
    return (_replacement_summary(), _replacement_metadata(), _replacement_manifest())


def test_replacement_versions_and_exports_are_exact() -> None:
    assert (
        AGENT_MARKET_BENCH_REPLACEMENT_FINAL_EVIDENCE_V1_VERSION,
        AGENT_MARKET_BENCH_REPLACEMENT_FINAL_SUMMARY_V1_VERSION,
        AGENT_MARKET_BENCH_REPLACEMENT_FINAL_MANIFEST_V1_VERSION,
        AGENT_MARKET_BENCH_REPLACEMENT_FINAL_RUN_METADATA_V1_VERSION,
    ) == (
        "agent-market-bench-replacement-final-evidence-v1",
        "agent-market-bench-replacement-final-summary-v1",
        "agent-market-bench-replacement-final-manifest-v1",
        "agent-market-bench-replacement-final-run-metadata-v1",
    )
    names = (
        "AGENT_MARKET_BENCH_REPLACEMENT_FINAL_EVIDENCE_V1_VERSION",
        "AGENT_MARKET_BENCH_REPLACEMENT_FINAL_SUMMARY_V1_VERSION",
        "AGENT_MARKET_BENCH_REPLACEMENT_FINAL_MANIFEST_V1_VERSION",
        "AGENT_MARKET_BENCH_REPLACEMENT_FINAL_RUN_METADATA_V1_VERSION",
        "AgentMarketBenchReplacementFinalSummaryV1",
        "AgentMarketBenchReplacementFinalRunMetadataV1",
        "AgentMarketBenchReplacementFinalManifestV1",
    )
    assert all(name in final_models.__all__ for name in names)


@pytest.mark.parametrize(
    "model_type",
    (
        AgentMarketBenchReplacementFinalSummaryV1,
        AgentMarketBenchReplacementFinalRunMetadataV1,
        AgentMarketBenchReplacementFinalManifestV1,
    ),
)
def test_replacement_models_are_standalone_strict_frozen_and_revalidating(
    model_type: type[BaseModel],
) -> None:
    assert model_type.__bases__ == (BaseModel,)
    assert model_type.model_config["strict"] is True
    assert model_type.model_config["frozen"] is True
    assert model_type.model_config["extra"] == "forbid"
    assert model_type.model_config["revalidate_instances"] == "always"
    assert not any(name.startswith("agent_market_bench_final_") for name in model_type.model_fields)
    forbidden = ("rank", "winner_method", "significance", "p_value", "recommendation")
    assert not any(token in name for name in model_type.model_fields for token in forbidden)


def test_replacement_round_trips_bind_semantics_and_selection_explicitly() -> None:
    for model in _replacement_models():
        round_trip = type(model).model_validate(_payload(model))
        assert round_trip == model
        assert round_trip is not model
        assert type(model).model_validate(model) == model
        payload = model.model_dump(mode="json")
        assert payload["schema_version"] == "1"
        assert payload["metric_semantics_version"] == "agent-market-bench-metric-semantics-v1.1"
        assert payload["selection_version"] == "agent-market-bench-replacement-holdout-selection-v1"
        assert payload["selection_anchor_commit"] == (
            AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1
        )
        assert payload["selection_sha256"] == (
            AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1
        )
    metadata = _replacement_metadata()
    assert (
        AgentMarketBenchReplacementFinalRunMetadataV1.model_validate_json(
            metadata.model_dump_json()
        )
        == metadata
    )


def test_every_replacement_literal_rejects_other_values() -> None:
    for model in _replacement_models():
        for field_name, field in type(model).model_fields.items():
            if get_origin(field.annotation) is Literal:
                with pytest.raises(ValidationError, match="Input should be"):
                    type(model).model_validate(_payload(model, **{field_name: "wrong-version"}))


def test_replacement_models_enforce_frozen_selection_and_exact_commit_and_digest_types() -> None:
    for model in _replacement_models():
        for field_name in ("evaluated_source_commit", "selection_anchor_commit"):
            for invalid in ("A" * 40, "a" * 39, "g" * 40, b"a" * 40, True):
                with pytest.raises(ValidationError, match="lowercase 40-hex"):
                    type(model).model_validate(_payload(model, **{field_name: invalid}))
        for invalid in ("A" * 64, "a" * 63, "g" * 64, b"a" * 64, True):
            with pytest.raises(ValidationError, match="lowercase SHA-256"):
                type(model).model_validate(_payload(model, selection_sha256=invalid))
        with pytest.raises(ValidationError, match="frozen R1 commit"):
            type(model).model_validate(_payload(model, selection_anchor_commit=_COMMIT))
        with pytest.raises(ValidationError, match="frozen selection digest"):
            type(model).model_validate(_payload(model, selection_sha256=_SHA))
        for required in ("evaluated_source_commit", "selection_anchor_commit", "selection_sha256"):
            payload = _payload(model)
            del payload[required]
            with pytest.raises(ValidationError, match="Field required"):
                type(model).model_validate(payload)


def test_replacement_models_are_behaviorally_frozen_and_forbid_extras() -> None:
    for model in _replacement_models():
        with pytest.raises(ValidationError, match="frozen"):
            model.evaluated_source_commit = "a" * 40
        with pytest.raises(ValidationError, match="Extra inputs"):
            type(model).model_validate(_payload(model, unknown=True))
        historical_version = next(
            name.replace("replacement_final_", "final_")
            for name in type(model).model_fields
            if name.startswith("agent_market_bench_replacement_final_")
        )
        with pytest.raises(ValidationError, match="Extra inputs"):
            type(model).model_validate(_payload(model, **{historical_version: "historical"}))
        corrupted = model.model_copy(update={"metric_semantics_version": "wrong-version"})
        with pytest.raises(ValidationError):
            type(model).model_validate(corrupted)


def test_replacement_summary_requires_exact_historical_count_coverage() -> None:
    summary = _replacement_summary()
    assert summary.case_count == 1
    assert summary.run_summary.case_count == 1
    assert summary.scenario_assessment_counts
    statuses = summary.method_status_counts
    scenarios = summary.scenario_counts
    assessments = summary.scenario_assessment_counts
    changed_status = statuses[0].model_copy(update={"count": statuses[0].count + 1})
    invalid_payloads = (
        ({"method_status_counts": statuses[:-1]}, "exact 9x3"),
        ({"method_status_counts": tuple(reversed(statuses))}, "exact 9x3"),
        ({"method_status_counts": (statuses[0], *statuses[:-1])}, "exact 9x3"),
        ({"method_status_counts": (changed_status, *statuses[1:])}, "sum to case_count"),
        ({"scenario_counts": scenarios[:-1]}, "every scenario"),
        ({"scenario_counts": tuple(reversed(scenarios))}, "every scenario"),
        ({"standard_case_count": summary.standard_case_count + 1}, "standard and scenario"),
        ({"scenario_assessment_counts": (*assessments, assessments[0])}, "unique and normalized"),
        (
            {"scenario_assessment_counts": (assessments[0].model_copy(update={"count": 0}),)},
            "only observed combinations",
        ),
        (
            {"run_summary": summary.run_summary.model_copy(update={"case_count": 2})},
            "run summary case_count must equal",
        ),
    )
    for updates, message in invalid_payloads:
        with pytest.raises(ValidationError, match=message):
            AgentMarketBenchReplacementFinalSummaryV1.model_validate(_payload(summary, **updates))


def test_replacement_summary_and_manifest_reject_coercion_and_fresh_validate_nested_models() -> (
    None
):
    summary = _replacement_summary()
    manifest = _replacement_manifest()
    for model, fields in (
        (summary, ("case_count", "standard_case_count")),
        (
            manifest,
            (
                "case_count",
                "first_seed",
                "last_seed",
                "shard_size",
                "semantic_shard_count",
                "timing_shard_count",
            ),
        ),
    ):
        for field_name in fields:
            for invalid in (
                True,
                str(getattr(model, field_name)),
                float(getattr(model, field_name)),
            ):
                with pytest.raises(ValidationError, match="valid integer"):
                    type(model).model_validate(_payload(model, **{field_name: invalid}))
    for field_name in ("method_status_counts", "scenario_counts", "scenario_assessment_counts"):
        values = getattr(summary, field_name)
        for invalid in (list(values), [item.model_dump() for item in values]):
            with pytest.raises(ValidationError, match="supplied as a tuple"):
                AgentMarketBenchReplacementFinalSummaryV1.model_validate(
                    _payload(summary, **{field_name: invalid})
                )
        corrupted = values[0].model_copy(update={"count": True})
        with pytest.raises(ValidationError, match="failed fresh validation"):
            AgentMarketBenchReplacementFinalSummaryV1.model_validate(
                _payload(summary, **{field_name: (corrupted, *values[1:])})
            )
        with pytest.raises(ValidationError, match="value must be exactly"):
            AgentMarketBenchReplacementFinalSummaryV1.model_validate(
                _payload(summary, **{field_name: (values[0].model_dump(), *values[1:])})
            )
    with pytest.raises(ValidationError, match="failed fresh validation"):
        AgentMarketBenchReplacementFinalSummaryV1.model_validate(
            _payload(
                summary, run_summary=summary.run_summary.model_copy(update={"case_count": True})
            )
        )
    with pytest.raises(ValidationError, match="supplied as a tuple"):
        AgentMarketBenchReplacementFinalManifestV1.model_validate(
            _payload(manifest, files=list(manifest.files))
        )
    corrupt_entry = manifest.files[0].model_copy(update={"byte_count": True})
    with pytest.raises(ValidationError, match="failed fresh validation"):
        AgentMarketBenchReplacementFinalManifestV1.model_validate(
            _payload(manifest, files=(corrupt_entry, *manifest.files[1:]))
        )


def test_replacement_metadata_preserves_timestamp_text_and_privacy_validation() -> None:
    metadata = _replacement_metadata()
    text_fields = (
        "python_version",
        "platform_system",
        "platform_machine",
        "pydantic_version",
        "ortools_version",
        "cryptography_version",
    )
    for field_name in text_fields:
        for invalid in ("", "two\nlines", "null\x00byte", 1, True):
            with pytest.raises(ValidationError):
                AgentMarketBenchReplacementFinalRunMetadataV1.model_validate(
                    _payload(metadata, **{field_name: invalid})
                )
    for field_name in ("started_at_utc", "completed_at_utc"):
        for invalid in (
            "2026-09-05T00:00:00Z",
            "2026-09-05T00:00:00.000000+00:00",
            "2026-02-30T00:00:00.000000Z",
            "2026-09-05T24:00:00.000000Z",
            0,
        ):
            with pytest.raises(ValidationError, match="timestamp"):
                AgentMarketBenchReplacementFinalRunMetadataV1.model_validate(
                    _payload(metadata, **{field_name: invalid})
                )
    with pytest.raises(ValidationError, match="must not precede"):
        AgentMarketBenchReplacementFinalRunMetadataV1.model_validate(
            _payload(metadata, completed_at_utc="2026-09-04T00:00:00.000000Z")
        )
    with pytest.raises(ValidationError, match=r"time\.perf_counter_ns"):
        AgentMarketBenchReplacementFinalRunMetadataV1.model_validate(
            _payload(metadata, clock_name="time.time")
        )
    for forbidden in (
        "hostname",
        "username",
        "repository_path",
        "ip_address",
        "network_identifier",
        "device_serial",
        "environment_variables",
    ):
        assert forbidden not in type(metadata).model_fields
        with pytest.raises(ValidationError, match="Extra inputs"):
            AgentMarketBenchReplacementFinalRunMetadataV1.model_validate(
                _payload(metadata, **{forbidden: "private"})
            )


def test_replacement_manifest_requires_complete_frozen_inventory_with_no_small_run_bypass() -> None:
    manifest = _replacement_manifest()
    assert manifest.case_count == 10_000
    assert manifest.shard_size == 500
    assert manifest.semantic_shard_count == manifest.timing_shard_count == 20
    assert len(manifest.files) == 43
    assert all(type(item) is AgentMarketBenchFinalEvidenceFileV1 for item in manifest.files)
    assert "manifest.json" not in {item.relative_path for item in manifest.files}
    for field_name, invalid in (
        ("case_count", 1),
        ("case_count", 9_999),
        ("case_count", 10_001),
        ("shard_size", 499),
        ("shard_size", 501),
        ("semantic_shard_count", 19),
        ("semantic_shard_count", 21),
        ("timing_shard_count", 19),
        ("timing_shard_count", 21),
    ):
        with pytest.raises(ValidationError):
            AgentMarketBenchReplacementFinalManifestV1.model_validate(
                _payload(manifest, **{field_name: invalid})
            )
    for field_name, invalid in (
        ("first_seed", manifest.first_seed + 1),
        ("last_seed", manifest.last_seed - 1),
        ("first_seed", AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1[0]),
        ("last_seed", AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1[-1]),
        ("seed_sequence_sha256", _SHA),
    ):
        with pytest.raises(ValidationError, match="frozen"):
            AgentMarketBenchReplacementFinalManifestV1.model_validate(
                _payload(manifest, **{field_name: invalid})
            )


def test_replacement_manifest_rejects_missing_extra_duplicate_reordered_or_gapped_paths() -> None:
    manifest = _replacement_manifest()
    renamed = manifest.files[0].model_copy(update={"relative_path": "manifest.json"})
    semantic_index = next(
        index
        for index, item in enumerate(manifest.files)
        if item.kind is AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD
    )
    gapped = list(manifest.files)
    gapped[semantic_index] = gapped[semantic_index].model_copy(
        update={"relative_path": "semantic/part-00020.jsonl.gz"}
    )
    for files in (
        manifest.files[:-1],
        tuple(sorted((*manifest.files, renamed), key=lambda item: item.relative_path)),
        (manifest.files[0], *manifest.files[:-1]),
        tuple(reversed(manifest.files)),
        tuple(sorted(gapped, key=lambda item: item.relative_path)),
        (renamed, *manifest.files[1:]),
    ):
        with pytest.raises(ValidationError, match="exactly 43 frozen paths"):
            AgentMarketBenchReplacementFinalManifestV1.model_validate(
                _payload(manifest, files=files)
            )


def test_replacement_manifest_rejects_wrong_path_kinds_and_every_incomplete_shard() -> None:
    manifest = _replacement_manifest()
    for index, item in enumerate(manifest.files):
        if item.kind in (
            AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD,
            AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD,
        ):
            wrong_kind = (
                AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD
                if item.kind is AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD
                else AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD
            )
            invalid_fields = (
                ("kind", wrong_kind, "file kind must match"),
                ("line_count", 499, "line_count must equal 500"),
                ("line_count", 501, "line_count must equal 500"),
                ("first_seed", item.first_seed + 1, "exact consecutive seed bounds"),
                ("last_seed", item.last_seed - 1, "exact consecutive seed bounds"),
            )
        else:
            wrong_kind = (
                AgentMarketBenchFinalEvidenceFileKindV1.REPORT
                if item.kind is AgentMarketBenchFinalEvidenceFileKindV1.SUMMARY
                else AgentMarketBenchFinalEvidenceFileKindV1.SUMMARY
            )
            invalid_fields = (("kind", wrong_kind, "file kind must match"),)
        for field_name, invalid, message in invalid_fields:
            corrupted = item.model_copy(update={field_name: invalid})
            files = (*manifest.files[:index], corrupted, *manifest.files[index + 1 :])
            with pytest.raises(ValidationError, match=message):
                AgentMarketBenchReplacementFinalManifestV1.model_validate(
                    _payload(manifest, files=files)
                )
