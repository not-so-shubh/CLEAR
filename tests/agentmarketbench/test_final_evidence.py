import gzip
import json
from fractions import Fraction
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest

import clear_market.agentmarketbench.generator as generator_module
from clear_market.agentmarketbench.final_evidence import (
    AgentMarketBenchFinalStreamingAccumulatorV1,
    _verify_agent_market_bench_evidence_bundle_v1,
    _write_agent_market_bench_development_evidence_v1,
    agent_market_bench_final_admission_digest_v1,
    agent_market_bench_final_evidence_root_digest_v1,
    agent_market_bench_final_method_result_digest_v1,
    agent_market_bench_final_shard_content_root_digest_v1,
    canonical_agent_market_bench_final_json_v1_bytes,
    compact_agent_market_bench_case_run_v1,
)
from clear_market.agentmarketbench.final_models import (
    AgentMarketBenchFinalEvidenceFileKindV1,
    AgentMarketBenchFinalEvidenceFileV1,
    AgentMarketBenchFinalManifestV1,
    AgentMarketBenchFinalSemanticMethodV1,
    AgentMarketBenchFinalSemanticRecordV1,
    AgentMarketBenchFinalTimingMethodV1,
    AgentMarketBenchFinalTimingRecordV1,
)
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
    AgentMarketBenchDecisionLineV1,
    AgentMarketBenchMethodResultV1,
)
from clear_market.agentmarketbench.models import (
    AgentMarketBenchAdversarialScenarioV1,
    AgentMarketBenchBaselineV1,
    AgentMarketBenchMetricV1,
)
from clear_market.agentmarketbench.runner import run_agent_market_bench_case_v1
from clear_market.agentmarketbench.statistics import summarize_agent_market_bench_case_runs_v1
from clear_market.domain import Money

_START = 100_000_000
_COMMIT = "e3c0d06f5c07fe10b4ad62dc5575108f51be337c"


@pytest.fixture(autouse=True)
def _guard_final_holdout_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    original = generator_module.generate_agent_market_bench_case_v1

    def guarded(seed: int):
        if seed >= 2_000_000_000:
            raise AssertionError("24E-A tests must not generate a final-holdout case")
        return original(seed)

    monkeypatch.setitem(globals(), "generate_agent_market_bench_case_v1", guarded)
    monkeypatch.setattr(generator_module, "generate_agent_market_bench_case_v1", guarded)


def _case_run(seed: int, durations: tuple[int, ...] = (0,) * 9) -> AgentMarketBenchCaseRunV1:
    ticks = []
    current = 0
    for duration in durations:
        ticks.extend((current, current + duration))
        current += duration + 1
    values = iter(ticks)
    return run_agent_market_bench_case_v1(
        generate_agent_market_bench_case_v1(seed),
        clock_ns=lambda: next(values),
    )


def _payload(model, **updates: object) -> dict[str, object]:
    values = {field_name: getattr(model, field_name) for field_name in type(model).model_fields}
    values.update(updates)
    return values


def _replace_timing(
    record: AgentMarketBenchFinalTimingRecordV1,
    method: AgentMarketBenchBaselineV1,
    elapsed_ns: int,
) -> AgentMarketBenchFinalTimingRecordV1:
    timings = tuple(
        AgentMarketBenchFinalTimingMethodV1.model_validate(_payload(item, elapsed_ns=elapsed_ns))
        if item.method is method
        else item
        for item in record.timings
    )
    return AgentMarketBenchFinalTimingRecordV1.model_validate(_payload(record, timings=timings))


def _observation(
    metric: AgentMarketBenchMetricV1,
    unit: AgentMarketBenchMetricUnitV1,
    value: Fraction | None,
) -> AgentMarketBenchMetricObservationV1:
    return AgentMarketBenchMetricObservationV1(
        metric=metric,
        status=(
            AgentMarketBenchMetricObservationStatusV1.NOT_APPLICABLE
            if value is None
            else AgentMarketBenchMetricObservationStatusV1.MEASURED
        ),
        unit=unit,
        value=(
            None
            if value is None
            else AgentMarketBenchRationalV1(
                numerator=value.numerator,
                denominator=value.denominator,
            )
        ),
        not_applicable_reason=(
            AgentMarketBenchMetricNotApplicableReasonV1.SCENARIO_NOT_DEFINED
            if value is None
            else None
        ),
    )


def _replace_semantic_observation(
    record: AgentMarketBenchFinalSemanticRecordV1,
    method: AgentMarketBenchBaselineV1,
    replacement: AgentMarketBenchMetricObservationV1,
) -> AgentMarketBenchFinalSemanticRecordV1:
    methods = []
    for item in record.methods:
        if item.method is not method:
            methods.append(item)
            continue
        metrics = tuple(
            replacement if observation.metric is replacement.metric else observation
            for observation in item.metrics
        )
        methods.append(
            AgentMarketBenchFinalSemanticMethodV1.model_validate(_payload(item, metrics=metrics))
        )
    return AgentMarketBenchFinalSemanticRecordV1.model_validate(
        _payload(record, methods=tuple(methods))
    )


def _gzip_mtime_zero(data: bytes, *, compresslevel: int = 9) -> bytes:
    buffer = BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        fileobj=buffer,
        compresslevel=compresslevel,
        mtime=0,
    ) as file:
        file.write(data)
    return buffer.getvalue()


def _development_bundle(output_dir: Path):
    case_runs = tuple(_case_run(seed) for seed in range(_START, _START + 4))
    manifest = _write_agent_market_bench_development_evidence_v1(
        case_runs=case_runs,
        output_dir=output_dir,
        evaluated_source_commit=_COMMIT,
        shard_size=2,
    )
    return case_runs, manifest


def _updated_file_record(
    original: AgentMarketBenchFinalEvidenceFileV1,
    *,
    stored: bytes,
    uncompressed: bytes | None = None,
) -> AgentMarketBenchFinalEvidenceFileV1:
    updates: dict[str, object] = {
        "sha256": sha256(stored).hexdigest(),
        "byte_count": len(stored),
        "line_count": (stored if uncompressed is None else uncompressed).count(b"\n"),
    }
    if uncompressed is not None:
        updates["uncompressed_sha256"] = sha256(uncompressed).hexdigest()
    return AgentMarketBenchFinalEvidenceFileV1.model_validate(_payload(original, **updates))


def _manifest_with_updated_file(
    manifest: AgentMarketBenchFinalManifestV1,
    replacement: AgentMarketBenchFinalEvidenceFileV1,
) -> AgentMarketBenchFinalManifestV1:
    files = tuple(
        replacement if item.relative_path == replacement.relative_path else item
        for item in manifest.files
    )
    semantic_files = tuple(
        item
        for item in files
        if item.kind is AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD
    )
    timing_files = tuple(
        item for item in files if item.kind is AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD
    )
    return AgentMarketBenchFinalManifestV1.model_validate(
        _payload(
            manifest,
            files=files,
            semantic_root_sha256=agent_market_bench_final_shard_content_root_digest_v1(
                semantic_files,
                kind=AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD,
            ),
            timing_root_sha256=agent_market_bench_final_shard_content_root_digest_v1(
                timing_files,
                kind=AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD,
            ),
            evidence_root_sha256=agent_market_bench_final_evidence_root_digest_v1(files),
        )
    )


def _write_expected_manifest(
    output_dir: Path,
    manifest: AgentMarketBenchFinalManifestV1,
) -> None:
    (output_dir / "manifest.json").write_bytes(
        canonical_agent_market_bench_final_json_v1_bytes(manifest)
    )


def test_compaction_isolates_semantic_evidence_from_changed_timing() -> None:
    first = _case_run(_START, (1,) * 9)
    second = _case_run(_START, tuple(range(9)))
    first_semantic, first_timing = compact_agent_market_bench_case_run_v1(first)
    second_semantic, second_timing = compact_agent_market_bench_case_run_v1(second)
    assert first_semantic == second_semantic
    assert first_timing != second_timing


def test_complete_result_digest_is_stable_and_changes_with_valid_payment_mutation() -> None:
    case_run = _case_run(_START)
    result = next(
        evaluation.result for evaluation in case_run.evaluations if evaluation.result.lines
    )
    assert agent_market_bench_final_method_result_digest_v1(result) == (
        agent_market_bench_final_method_result_digest_v1(result)
    )
    first = result.lines[0]
    changed_unit = Money(amount_paise=first.unit_payment.amount_paise + 1)
    changed_line = AgentMarketBenchDecisionLineV1(
        source_offer_id=first.source_offer_id,
        merchant_id=first.merchant_id,
        sku_id=first.sku_id,
        allocated_quantity=first.allocated_quantity,
        unit_payment=changed_unit,
        line_payment=changed_unit.checked_multiply(first.allocated_quantity),
    )
    changed_lines = (changed_line, *result.lines[1:])
    changed = AgentMarketBenchMethodResultV1(
        method=result.method,
        market_id=result.market_id,
        status=result.status,
        admission=result.admission,
        fulfilled_quantity=result.fulfilled_quantity,
        total_payment=Money(
            amount_paise=result.total_payment.amount_paise + first.allocated_quantity
        ),
        winner_count=result.winner_count,
        lines=changed_lines,
    )
    assert agent_market_bench_final_method_result_digest_v1(changed) != (
        agent_market_bench_final_method_result_digest_v1(result)
    )


def test_compaction_has_one_stable_shared_admission_digest() -> None:
    case_run = _case_run(_START)
    semantic, _ = compact_agent_market_bench_case_run_v1(case_run)
    admissions = {evaluation.result.admission for evaluation in case_run.evaluations}
    assert len(admissions) == 1
    admission = next(iter(admissions))
    assert semantic.shared_admission_digest_sha256 == (
        agent_market_bench_final_admission_digest_v1(admission)
    )
    assert agent_market_bench_final_admission_digest_v1(admission) == (
        agent_market_bench_final_admission_digest_v1(admission)
    )


def test_semantic_has_no_latency_and_timing_has_no_economic_values() -> None:
    semantic, timing = compact_agent_market_bench_case_run_v1(_case_run(_START))
    assert all(
        observation.metric is not AgentMarketBenchMetricV1.LATENCY
        for method in semantic.methods
        for observation in method.metrics
    )
    timing_fields = set(AgentMarketBenchFinalTimingRecordV1.model_fields)
    timing_method_fields = set(AgentMarketBenchFinalTimingMethodV1.model_fields)
    assert not timing_fields & {"metrics", "scenario_assessments", "result_digest_sha256"}
    assert timing_method_fields == {"method", "elapsed_ns"}
    assert timing.timings


def test_canonical_json_is_sorted_deterministic_and_has_one_trailing_newline() -> None:
    semantic, _ = compact_agent_market_bench_case_run_v1(_case_run(_START))
    first = canonical_agent_market_bench_final_json_v1_bytes(semantic)
    second = canonical_agent_market_bench_final_json_v1_bytes(semantic)
    assert first == second
    assert first.endswith(b"\n")
    assert not first.endswith(b"\n\n")
    assert first == (
        json.dumps(
            semantic.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def test_shard_content_root_is_compression_independent_but_transport_root_is_not() -> None:
    common = {
        "relative_path": "semantic/part-00000.jsonl.gz",
        "kind": AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD,
        "line_count": 2,
        "uncompressed_sha256": "c" * 64,
        "first_seed": _START,
        "last_seed": _START + 1,
    }
    first = AgentMarketBenchFinalEvidenceFileV1(
        **common,
        sha256="a" * 64,
        byte_count=101,
    )
    second = AgentMarketBenchFinalEvidenceFileV1(
        **common,
        sha256="b" * 64,
        byte_count=202,
    )
    kind = AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD
    assert agent_market_bench_final_shard_content_root_digest_v1(
        (first,), kind=kind
    ) == agent_market_bench_final_shard_content_root_digest_v1((second,), kind=kind)
    assert agent_market_bench_final_evidence_root_digest_v1(
        (first,)
    ) != agent_market_bench_final_evidence_root_digest_v1((second,))


def test_actual_recompression_changes_only_transport_root() -> None:
    semantic, _ = compact_agent_market_bench_case_run_v1(_case_run(_START))
    raw = canonical_agent_market_bench_final_json_v1_bytes(semantic)
    compressed_level_1 = _gzip_mtime_zero(raw, compresslevel=1)
    compressed_level_9 = _gzip_mtime_zero(raw, compresslevel=9)
    assert compressed_level_1 != compressed_level_9
    assert sha256(compressed_level_1).digest() != sha256(compressed_level_9).digest()
    assert gzip.decompress(compressed_level_1) == gzip.decompress(compressed_level_9) == raw

    def record(compressed: bytes) -> AgentMarketBenchFinalEvidenceFileV1:
        return AgentMarketBenchFinalEvidenceFileV1(
            relative_path="semantic/part-00000.jsonl.gz",
            kind=AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD,
            sha256=sha256(compressed).hexdigest(),
            byte_count=len(compressed),
            line_count=1,
            uncompressed_sha256=sha256(raw).hexdigest(),
            first_seed=semantic.seed,
            last_seed=semantic.seed,
        )

    first = record(compressed_level_1)
    second = record(compressed_level_9)
    kind = AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD
    assert agent_market_bench_final_shard_content_root_digest_v1(
        (first,), kind=kind
    ) == agent_market_bench_final_shard_content_root_digest_v1((second,), kind=kind)
    assert agent_market_bench_final_evidence_root_digest_v1(
        (first,)
    ) != agent_market_bench_final_evidence_root_digest_v1((second,))


def test_streaming_first_42_development_cases_exactly_equal_frozen_24d_summary() -> None:
    case_runs = tuple(_case_run(seed) for seed in range(_START, _START + 42))
    reference = summarize_agent_market_bench_case_runs_v1(case_runs)
    accumulator = AgentMarketBenchFinalStreamingAccumulatorV1()
    scenarios = set()
    for case_run in case_runs:
        semantic, timing = compact_agent_market_bench_case_run_v1(case_run)
        scenarios.update(semantic.adversarial_scenarios)
        accumulator.add(semantic, timing)
    assert scenarios == set(AgentMarketBenchAdversarialScenarioV1)
    assert accumulator.build_run_summary_v1() == reference


def test_streaming_varied_durations_exactly_equal_frozen_24d_summary() -> None:
    case_runs = tuple(
        _case_run(seed, tuple((seed + index) % 17 for index in range(9)))
        for seed in range(_START, _START + 42)
    )
    reference = summarize_agent_market_bench_case_runs_v1(case_runs)
    accumulator = AgentMarketBenchFinalStreamingAccumulatorV1()
    for case_run in case_runs:
        accumulator.add(*compact_agent_market_bench_case_run_v1(case_run))
    assert accumulator.build_run_summary_v1() == reference


def test_streaming_sign_n0_n1_and_exact_ci_golden() -> None:
    accumulator = AgentMarketBenchFinalStreamingAccumulatorV1()
    for index, seed in enumerate((_START, _START + 2, _START + 4), start=1):
        semantic, timing = compact_agent_market_bench_case_run_v1(_case_run(seed))
        timing = _replace_timing(
            timing,
            AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER,
            10 + index,
        )
        timing = _replace_timing(timing, AgentMarketBenchBaselineV1.CLEAR, 10)
        accumulator.add(semantic, timing)
    summary = accumulator.build_run_summary_v1()
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

    empty_pair = next(
        item
        for item in summary.paired_summaries
        if item.comparator is AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER
        and item.metric is AgentMarketBenchMetricV1.MANIPULATION_SUCCESS
    )
    assert empty_pair.paired_count == 0
    assert empty_pair.mean_difference is None
    one = AgentMarketBenchFinalStreamingAccumulatorV1()
    semantic, timing = compact_agent_market_bench_case_run_v1(_case_run(_START))
    timing = _replace_timing(timing, AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER, 1)
    timing = _replace_timing(timing, AgentMarketBenchBaselineV1.CLEAR, 0)
    one.add(semantic, timing)
    one_pair = next(
        item
        for item in one.build_run_summary_v1().paired_summaries
        if item.comparator is AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER
        and item.metric is AgentMarketBenchMetricV1.LATENCY
    )
    assert one_pair.paired_count == 1
    assert one_pair.mean_difference == AgentMarketBenchRationalV1(numerator=1, denominator=1)
    assert one_pair.ci95_lower_decimal is None
    assert one_pair.ci95_upper_decimal is None


def test_streaming_exact_method_mean_is_seven_ninths() -> None:
    accumulator = AgentMarketBenchFinalStreamingAccumulatorV1()
    for seed, value in zip(
        (_START, _START + 2, _START + 4),
        (Fraction(1, 3), Fraction(2, 3), Fraction(4, 3)),
        strict=True,
    ):
        semantic, timing = compact_agent_market_bench_case_run_v1(_case_run(seed))
        semantic = _replace_semantic_observation(
            semantic,
            AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER,
            _observation(
                AgentMarketBenchMetricV1.ALLOCATIVE_EFFICIENCY,
                AgentMarketBenchMetricUnitV1.RATIO,
                value,
            ),
        )
        accumulator.add(semantic, timing)
    metric = next(
        item
        for item in accumulator.build_run_summary_v1().metric_summaries
        if item.method is AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER
        and item.metric is AgentMarketBenchMetricV1.ALLOCATIVE_EFFICIENCY
    )
    assert metric.mean_value == AgentMarketBenchRationalV1(numerator=7, denominator=9)


def test_streaming_excludes_each_one_sided_na_from_pairs() -> None:
    metric = AgentMarketBenchMetricV1.MANIPULATION_SUCCESS
    unit = AgentMarketBenchMetricUnitV1.BINARY
    comparator = AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER
    values = ((Fraction(1), Fraction(0)), (None, Fraction(0)), (Fraction(1), None))
    accumulator = AgentMarketBenchFinalStreamingAccumulatorV1()
    for seed, (comparator_value, clear_value) in zip(
        (_START, _START + 2, _START + 4), values, strict=True
    ):
        semantic, timing = compact_agent_market_bench_case_run_v1(_case_run(seed))
        semantic = _replace_semantic_observation(
            semantic, comparator, _observation(metric, unit, comparator_value)
        )
        semantic = _replace_semantic_observation(
            semantic,
            AgentMarketBenchBaselineV1.CLEAR,
            _observation(metric, unit, clear_value),
        )
        accumulator.add(semantic, timing)
    pair = next(
        item
        for item in accumulator.build_run_summary_v1().paired_summaries
        if item.comparator is comparator and item.metric is metric
    )
    assert pair.paired_count == 1
    assert pair.mean_difference == AgentMarketBenchRationalV1(numerator=1, denominator=1)


def test_development_shards_manifest_roots_and_verifier(tmp_path: Path) -> None:
    output_dir = tmp_path / "evidence"
    _, manifest = _development_bundle(output_dir)
    assert (
        _verify_agent_market_bench_evidence_bundle_v1(
            output_dir, expected_manifest=None, require_final=False
        )
        == manifest
    )
    assert {item.relative_path for item in manifest.files} == {
        "semantic/part-00000.jsonl.gz",
        "semantic/part-00001.jsonl.gz",
        "timing/part-00000.jsonl.gz",
        "timing/part-00001.jsonl.gz",
        "summary.json",
        "report.md",
        "run_metadata.json",
    }
    semantic_files = tuple(
        item
        for item in manifest.files
        if item.kind is AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD
    )
    root_payload = b"".join(
        (
            item.relative_path
            + "\0"
            + (item.uncompressed_sha256 or "")
            + "\0"
            + str(item.line_count)
            + "\0"
            + str(item.first_seed)
            + "\0"
            + str(item.last_seed)
            + "\n"
        ).encode("ascii")
        for item in sorted(semantic_files, key=lambda value: value.relative_path)
    )
    assert sha256(root_payload).hexdigest() == manifest.semantic_root_sha256
    for item in semantic_files:
        compressed = (output_dir / item.relative_path).read_bytes()
        assert compressed[4:8] == b"\0\0\0\0"
        raw = gzip.decompress(compressed)
        assert sha256(compressed).hexdigest() == item.sha256
        assert sha256(raw).hexdigest() == item.uncompressed_sha256
        assert len(raw.splitlines()) == 2


@pytest.mark.parametrize(
    "tamper",
    (
        "compressed-byte",
        "semantic-json",
        "pairing",
        "summary",
        "report",
        "missing",
        "extra",
    ),
)
def test_verifier_rejects_tampered_development_evidence(tmp_path: Path, tamper: str) -> None:
    output_dir = tmp_path / "evidence"
    _development_bundle(output_dir)
    semantic_path = output_dir / "semantic/part-00000.jsonl.gz"
    timing_path = output_dir / "timing/part-00000.jsonl.gz"
    if tamper == "compressed-byte":
        data = bytearray(semantic_path.read_bytes())
        data[-1] ^= 1
        semantic_path.write_bytes(data)
    elif tamper == "semantic-json":
        lines = gzip.decompress(semantic_path.read_bytes()).splitlines()
        payload = json.loads(lines[0])
        payload["methods"][0]["total_payment_paise"] += 1
        lines[0] = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        semantic_path.write_bytes(_gzip_mtime_zero(b"\n".join(lines) + b"\n"))
    elif tamper == "pairing":
        lines = gzip.decompress(timing_path.read_bytes()).splitlines()
        payload = json.loads(lines[0])
        payload["case_digest_sha256"] = "c" * 64
        lines[0] = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        timing_path.write_bytes(_gzip_mtime_zero(b"\n".join(lines) + b"\n"))
    elif tamper == "summary":
        path = output_dir / "summary.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif tamper == "report":
        path = output_dir / "report.md"
        path.write_bytes(path.read_bytes() + b"tampered\n")
    elif tamper == "missing":
        (output_dir / "run_metadata.json").unlink()
    else:
        (output_dir / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ValueError):
        _verify_agent_market_bench_evidence_bundle_v1(
            output_dir, expected_manifest=None, require_final=False
        )


def test_deep_verifier_rejects_semantic_timing_pairing_mismatch(tmp_path: Path) -> None:
    output_dir = tmp_path / "evidence"
    _, manifest = _development_bundle(output_dir)
    relative_path = "timing/part-00000.jsonl.gz"
    path = output_dir / relative_path
    lines = gzip.decompress(path.read_bytes()).splitlines()
    payload = json.loads(lines[0])
    payload["case_digest_sha256"] = "c" * 64
    lines[0] = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    raw = b"\n".join(lines) + b"\n"
    stored = _gzip_mtime_zero(raw)
    path.write_bytes(stored)
    original = next(item for item in manifest.files if item.relative_path == relative_path)
    updated_manifest = _manifest_with_updated_file(
        manifest,
        _updated_file_record(original, stored=stored, uncompressed=raw),
    )
    _write_expected_manifest(output_dir, updated_manifest)

    with pytest.raises(ValueError, match="semantic/timing record pairing mismatch"):
        _verify_agent_market_bench_evidence_bundle_v1(
            output_dir,
            expected_manifest=updated_manifest,
            require_final=False,
        )


def test_deep_verifier_rejects_reconstructed_summary_mismatch(tmp_path: Path) -> None:
    output_dir = tmp_path / "evidence"
    _, manifest = _development_bundle(output_dir)
    relative_path = "semantic/part-00000.jsonl.gz"
    path = output_dir / relative_path
    lines = gzip.decompress(path.read_bytes()).splitlines()
    payload = json.loads(lines[0])
    method = next(
        item
        for item in payload["methods"]
        if item["method"] == AgentMarketBenchBaselineV1.RANDOM_QUALIFYING_SELLER.value
    )
    observation = next(
        item
        for item in method["metrics"]
        if item["metric"] == AgentMarketBenchMetricV1.WELFARE.value
    )
    assert observation["value"] is not None
    observation["value"]["numerator"] += observation["value"]["denominator"]
    lines[0] = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    raw = b"\n".join(lines) + b"\n"
    stored = _gzip_mtime_zero(raw)
    path.write_bytes(stored)
    original = next(item for item in manifest.files if item.relative_path == relative_path)
    updated_manifest = _manifest_with_updated_file(
        manifest,
        _updated_file_record(original, stored=stored, uncompressed=raw),
    )
    _write_expected_manifest(output_dir, updated_manifest)

    with pytest.raises(
        ValueError,
        match=r"summary\.json does not equal reconstructed compact evidence",
    ):
        _verify_agent_market_bench_evidence_bundle_v1(
            output_dir,
            expected_manifest=updated_manifest,
            require_final=False,
        )


def test_deep_verifier_rejects_report_regeneration_mismatch(tmp_path: Path) -> None:
    output_dir = tmp_path / "evidence"
    _, manifest = _development_bundle(output_dir)
    relative_path = "report.md"
    path = output_dir / relative_path
    stored = path.read_bytes() + b"tampered but valid UTF-8\n"
    path.write_bytes(stored)
    original = next(item for item in manifest.files if item.relative_path == relative_path)
    updated_manifest = _manifest_with_updated_file(
        manifest,
        _updated_file_record(original, stored=stored),
    )
    _write_expected_manifest(output_dir, updated_manifest)

    with pytest.raises(ValueError, match="frozen neutral rendering"):
        _verify_agent_market_bench_evidence_bundle_v1(
            output_dir,
            expected_manifest=updated_manifest,
            require_final=False,
        )


def test_neutral_report_has_required_boundaries_and_no_outcome_claims(tmp_path: Path) -> None:
    output_dir = tmp_path / "evidence"
    _development_bundle(output_dir)
    report = (output_dir / "report.md").read_text(encoding="utf-8")
    assert "Difference orientation is comparator minus CLEAR." in report
    assert "## Method metric means" in report
    assert "## Paired comparator-minus-CLEAR summaries" in report
    assert "generated synthetic distribution only" in report
    assert "Payment correctness is benchmark rule correctness, not settlement" in report
    assert "No p-values" in report
    assert "No automatic benchmark winner or ranking" in report
    lowered = report.lower()
    for forbidden in (
        "clear wins",
        "clear is best",
        "statistically significant",
        "superior",
        "dominates",
    ):
        assert forbidden not in lowered
