"""Replacement transport tests; real generation is limited to four development cases."""

import ast
import gzip
import inspect
import json
import shutil
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from clear_market.agentmarketbench import (
    full_information,
    generator,
    methods,
    runner,
)
from clear_market.agentmarketbench import (
    replacement_final_evidence as evidence,
)
from clear_market.agentmarketbench.final_evidence import (
    AgentMarketBenchFinalStreamingAccumulatorV1,
    canonical_agent_market_bench_final_json_v1_bytes,
    compact_agent_market_bench_case_run_v1,
)
from clear_market.agentmarketbench.final_models import (
    AgentMarketBenchFinalEvidenceFileKindV1,
    AgentMarketBenchFinalEvidenceFileV1,
    AgentMarketBenchFinalManifestV1,
    AgentMarketBenchFinalSemanticRecordV1,
    AgentMarketBenchFinalTimingRecordV1,
    AgentMarketBenchReplacementFinalRunMetadataV1,
    AgentMarketBenchReplacementFinalSummaryV1,
)
from clear_market.agentmarketbench.measurement_models import AgentMarketBenchCaseRunV1
from clear_market.agentmarketbench.seeds import (
    AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1,
)
from tests.agentmarketbench.test_final_models import _replacement_manifest

_COMMIT = "e3c0d06f5c07fe10b4ad62dc5575108f51be337c"
_DEVELOPMENT_SEEDS = AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1[:4]
_NOW = "2026-09-05T01:02:03.000000Z"
_KINDS = AgentMarketBenchFinalEvidenceFileKindV1


def _payload(model: BaseModel, **updates: object) -> dict[str, object]:
    return {
        **{name: getattr(model, name) for name in type(model).model_fields},
        **updates,
    }


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _independent_roots(files: tuple[AgentMarketBenchFinalEvidenceFileV1, ...]) -> dict[str, str]:
    roots = {}
    for name, kind in (
        ("semantic_root_sha256", _KINDS.SEMANTIC_SHARD),
        ("timing_root_sha256", _KINDS.TIMING_SHARD),
    ):
        payload = "".join(
            f"{item.relative_path}\0{item.uncompressed_sha256}\0{item.line_count}\0"
            f"{item.first_seed}\0{item.last_seed}\n"
            for item in sorted(files, key=lambda item: item.relative_path)
            if item.kind is kind
        )
        roots[name] = sha256(payload.encode("ascii")).hexdigest()
    transport = "".join(
        f"{item.relative_path}\0{item.sha256}\0{item.uncompressed_sha256 or ''}\0"
        f"{item.byte_count}\0{item.line_count}\n"
        for item in sorted(files, key=lambda item: item.relative_path)
    )
    roots["evidence_root_sha256"] = sha256(transport.encode("ascii")).hexdigest()
    return roots


@pytest.fixture(scope="module")
def development_runs() -> tuple[AgentMarketBenchCaseRunV1, ...]:
    runs = []
    for seed in _DEVELOPMENT_SEEDS:
        # Check before the sole real generator call in this module.
        assert seed < 2_000_000_000
        assert seed in AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1
        assert seed not in AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1
        runs.append(
            runner.run_agent_market_bench_case_v1(
                generator.generate_agent_market_bench_case_v1(seed), clock_ns=lambda: 0
            )
        )
    assert tuple(item.seed for item in runs) == _DEVELOPMENT_SEEDS
    return tuple(runs)


@pytest.fixture(autouse=True)
def _forbid_additional_generation(
    monkeypatch: pytest.MonkeyPatch, development_runs: tuple[AgentMarketBenchCaseRunV1, ...]
) -> None:
    assert len(development_runs) == 4

    def forbidden(*args, **kwargs):
        raise AssertionError("evidence tests must not generate any additional cases")

    monkeypatch.setattr(generator, "generate_agent_market_bench_case_v1", forbidden)


@pytest.fixture(scope="module")
def frozen_bundle(
    tmp_path_factory: pytest.TempPathFactory,
    development_runs: tuple[AgentMarketBenchCaseRunV1, ...],
) -> tuple[Path, AgentMarketBenchFinalManifestV1]:
    output_dir = tmp_path_factory.mktemp("replacement-development") / "evidence"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(evidence, "_utc_now", lambda: _NOW)
        manifest = evidence._write_development_evidence(
            case_runs=development_runs,
            output_dir=output_dir,
            evaluated_source_commit=_COMMIT,
            shard_size=2,
        )
    return output_dir, manifest


@pytest.fixture
def bundle(
    tmp_path: Path, frozen_bundle: tuple[Path, AgentMarketBenchFinalManifestV1]
) -> tuple[Path, AgentMarketBenchFinalManifestV1]:
    original, manifest = frozen_bundle
    output_dir = tmp_path / "evidence"
    shutil.copytree(original, output_dir)
    return output_dir, manifest


def _verify(output_dir: Path, *, expected_manifest=None):
    return evidence._verify_bundle(
        output_dir,
        expected_manifest=expected_manifest,
        expected_seeds=_DEVELOPMENT_SEEDS,
        completed_replacement=False,
    )


def _write_manifest(output_dir: Path, manifest: BaseModel) -> None:
    (output_dir / "manifest.json").write_bytes(
        canonical_agent_market_bench_final_json_v1_bytes(manifest)
    )


def _reseal_file(
    output_dir: Path,
    manifest: AgentMarketBenchFinalManifestV1,
    relative_path: str,
    stored: bytes,
    *,
    raw: bytes | None = None,
    seeds: tuple[int, ...] | None = None,
) -> AgentMarketBenchFinalManifestV1:
    """Update exact file identity and all roots, retaining unrelated evidence bytes."""
    original = next(item for item in manifest.files if item.relative_path == relative_path)
    updates = {
        "sha256": sha256(stored).hexdigest(),
        "byte_count": len(stored),
        "line_count": (stored if raw is None else raw).count(b"\n"),
    }
    if raw is not None:
        updates["uncompressed_sha256"] = sha256(raw).hexdigest()
    if seeds is not None:
        updates.update(first_seed=seeds[0], last_seed=seeds[-1])
    replacement = AgentMarketBenchFinalEvidenceFileV1.model_validate(_payload(original, **updates))
    files = tuple(
        replacement if item.relative_path == relative_path else item for item in manifest.files
    )
    updated = AgentMarketBenchFinalManifestV1.model_validate(
        _payload(manifest, files=files, **_independent_roots(files))
    )
    (output_dir / relative_path).write_bytes(stored)
    _write_manifest(output_dir, updated)
    return updated


def _read_records(output_dir: Path, relative_path: str) -> list[dict]:
    return [
        json.loads(line)
        for line in gzip.decompress((output_dir / relative_path).read_bytes()).splitlines()
    ]


def _reseal_records(
    output_dir: Path,
    manifest: AgentMarketBenchFinalManifestV1,
    relative_path: str,
    records: list[dict],
) -> AgentMarketBenchFinalManifestV1:
    raw = b"".join(_json_bytes(item) for item in records)
    return _reseal_file(
        output_dir,
        manifest,
        relative_path,
        evidence._gzip_bytes(raw),
        raw=raw,
        seeds=tuple(item["seed"] for item in records),
    )


def test_development_fixture_writer_round_trip_and_exact_counts(
    frozen_bundle, development_runs
) -> None:
    output_dir, manifest = frozen_bundle
    assert type(manifest) is AgentMarketBenchFinalManifestV1
    assert _verify(output_dir, expected_manifest=manifest) == manifest
    assert manifest.case_count == 4
    assert manifest.first_seed == _DEVELOPMENT_SEEDS[0]
    assert manifest.last_seed == _DEVELOPMENT_SEEDS[-1]
    assert manifest.semantic_shard_count == manifest.timing_shard_count == 2
    assert len(manifest.files) == 7
    assert len(tuple(path for path in output_dir.rglob("*") if path.is_file())) == 8
    assert all(item.line_count == 2 for item in manifest.files if item.uncompressed_sha256)
    accumulator = AgentMarketBenchFinalStreamingAccumulatorV1()
    for case_run in development_runs:
        accumulator.add(*compact_agent_market_bench_case_run_v1(case_run))
    summary = evidence._load_canonical(
        output_dir / "summary.json", AgentMarketBenchReplacementFinalSummaryV1
    )
    historical = accumulator.build_final_summary_v1(
        evaluated_source_commit=_COMMIT, seed_sequence_sha256=manifest.seed_sequence_sha256
    )
    for name in (
        "case_count",
        "standard_case_count",
        "method_status_counts",
        "scenario_counts",
        "scenario_assessment_counts",
        "run_summary",
    ):
        assert getattr(summary, name) == getattr(historical, name)
    assert summary.run_summary.case_count == summary.case_count
    assert len(summary.run_summary.metric_summaries) == 99
    assert len(summary.run_summary.paired_summaries) == 88
    assert evidence._roots(manifest.files) == _independent_roots(manifest.files)


def test_replacement_models_round_trip_with_explicit_semantics_and_selection(frozen_bundle) -> None:
    output_dir, _ = frozen_bundle
    models = (
        evidence._load_canonical(
            output_dir / "summary.json", AgentMarketBenchReplacementFinalSummaryV1
        ),
        evidence._load_canonical(
            output_dir / "run_metadata.json", AgentMarketBenchReplacementFinalRunMetadataV1
        ),
        _replacement_manifest(),
    )
    for model in models:
        raw = canonical_agent_market_bench_final_json_v1_bytes(model)
        payload = json.loads(raw)
        assert evidence._decode_model(type(model), payload) == model
        assert raw == _json_bytes(payload)
        assert payload["schema_version"] == "1"
        assert payload["metric_semantics_version"] == "agent-market-bench-metric-semantics-v1.1"
        assert payload["selection_version"] == "agent-market-bench-replacement-holdout-selection-v1"
        assert (
            payload["selection_anchor_commit"]
            == AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1
        )
        assert (
            payload["selection_sha256"]
            == AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1
        )
        assert type(model).model_config["strict"] is True
        assert type(model).model_config["frozen"] is True
        assert type(model).model_config["extra"] == "forbid"
        with pytest.raises(ValidationError):
            evidence._decode_model(type(model), {**payload, "unexpected": "field"})
        with pytest.raises(ValidationError):
            model.evaluated_source_commit = "f" * 40
        with pytest.raises(ValueError, match=r"failed fresh validation"):
            canonical_agent_market_bench_final_json_v1_bytes(
                model.model_copy(update={"schema_version": "2"})
            )
    manifest = models[-1]
    assert manifest.case_count == 10_000
    assert len(manifest.files) == 43
    assert manifest.semantic_shard_count == manifest.timing_shard_count == 20
    assert manifest.shard_size == 500
    assert all(item.line_count == 500 for item in manifest.files if item.uncompressed_sha256)


def test_writer_is_deterministic_with_frozen_metadata(
    tmp_path, frozen_bundle, development_runs, monkeypatch
) -> None:
    original, manifest = frozen_bundle
    output_dir = tmp_path / "second"
    monkeypatch.setattr(evidence, "_utc_now", lambda: _NOW)
    repeated = evidence._write_development_evidence(
        case_runs=development_runs,
        output_dir=output_dir,
        evaluated_source_commit=_COMMIT,
        shard_size=2,
    )
    assert repeated == manifest
    for relative in [item.relative_path for item in manifest.files] + ["manifest.json"]:
        assert (original / relative).read_bytes() == (output_dir / relative).read_bytes()


def test_gzip_has_exact_frozen_header_and_deterministic_stdlib_bytes() -> None:
    raw = b'{"fixture":"development"}\n' * 20
    first = evidence._gzip_bytes(raw)
    assert first == evidence._gzip_bytes(raw)
    independent = BytesIO()
    with gzip.GzipFile(
        filename="", fileobj=independent, mode="wb", compresslevel=9, mtime=0
    ) as handle:
        handle.write(raw)
    assert first == independent.getvalue()
    assert first[:9] == b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02"
    assert gzip.decompress(first) == raw


def test_content_roots_ignore_gzip_transport_but_transport_root_detects_it(bundle) -> None:
    output_dir, manifest = bundle
    relative = "semantic/part-00000.jsonl.gz"
    stored = bytearray((output_dir / relative).read_bytes())
    raw = gzip.decompress(stored)
    stored[9] = (stored[9] + 1) % 256  # OS metadata changes transport, not canonical content.
    assert gzip.decompress(stored) == raw
    (output_dir / relative).write_bytes(stored)
    with pytest.raises(ValueError, match=r"hash or byte count mismatch"):
        _verify(output_dir)
    updated = _reseal_file(output_dir, manifest, relative, bytes(stored), raw=raw)
    assert updated.semantic_root_sha256 == manifest.semantic_root_sha256
    assert updated.timing_root_sha256 == manifest.timing_root_sha256
    assert updated.evidence_root_sha256 != manifest.evidence_root_sha256
    assert _verify(output_dir) == updated


@pytest.mark.parametrize(
    "relative",
    [
        "semantic/part-00000.jsonl.gz",
        "timing/part-00000.jsonl.gz",
        "summary.json",
        "report.md",
        "run_metadata.json",
    ],
)
def test_verifier_rejects_unresealed_file_tamper(bundle, relative) -> None:
    output_dir, _ = bundle
    path = output_dir / relative
    path.write_bytes(path.read_bytes() + b"tampered\n")
    with pytest.raises(ValueError, match=r"hash or byte count mismatch"):
        _verify(output_dir)


@pytest.mark.parametrize("kind", ["semantic", "timing"])
def test_reconstructed_summary_rejects_hash_resealed_record_tamper(bundle, kind) -> None:
    output_dir, manifest = bundle
    relative = f"{kind}/part-00000.jsonl.gz"
    records = _read_records(output_dir, relative)
    if kind == "semantic":
        observation = next(
            item for item in records[0]["methods"][0]["metrics"] if item["metric"] == "WELFARE"
        )
        observation["value"]["numerator"] += observation["value"]["denominator"]
        evidence._decode_model(AgentMarketBenchFinalSemanticRecordV1, records[0])
    else:
        records[0]["timings"][0]["elapsed_ns"] += 1
        evidence._decode_model(AgentMarketBenchFinalTimingRecordV1, records[0])
    updated = _reseal_records(output_dir, manifest, relative, records)
    assert updated.evidence_root_sha256 != manifest.evidence_root_sha256
    with pytest.raises(
        ValueError, match=r"summary.json differs from reconstructed compact evidence"
    ):
        _verify(output_dir, expected_manifest=updated)


def test_reconstructed_summary_rejects_hash_resealed_summary_tamper(bundle) -> None:
    output_dir, manifest = bundle
    payload = json.loads((output_dir / "summary.json").read_bytes())
    measured = next(
        item
        for item in payload["run_summary"]["metric_summaries"]
        if item["mean_value"] is not None
    )
    measured["mean_value"]["numerator"] += measured["mean_value"]["denominator"]
    evidence._decode_model(AgentMarketBenchReplacementFinalSummaryV1, payload)
    _reseal_file(output_dir, manifest, "summary.json", _json_bytes(payload))
    with pytest.raises(
        ValueError, match=r"summary.json differs from reconstructed compact evidence"
    ):
        _verify(output_dir)


def test_exact_renderer_rejects_hash_resealed_report_tamper(bundle) -> None:
    output_dir, manifest = bundle
    _reseal_file(
        output_dir, manifest, "report.md", (output_dir / "report.md").read_bytes() + b"extra text\n"
    )
    with pytest.raises(ValueError, match=r"report.md differs from exact replacement rendering"):
        _verify(output_dir)


@pytest.mark.parametrize("relative", ["summary.json", "run_metadata.json", "manifest.json"])
def test_cross_file_source_commit_binding_rejects_coherent_tamper(bundle, relative) -> None:
    output_dir, manifest = bundle
    payload = json.loads((output_dir / relative).read_bytes())
    payload["evaluated_source_commit"] = "f" * 40
    if relative == "manifest.json":
        (output_dir / relative).write_bytes(_json_bytes(payload))
    else:
        _reseal_file(output_dir, manifest, relative, _json_bytes(payload))
    with pytest.raises(
        ValueError, match=r"reconstructed compact evidence|run metadata source commit"
    ):
        _verify(output_dir)


@pytest.mark.parametrize(
    "field,value",
    [
        ("metric_semantics_version", "agent-market-bench-metric-semantics-v1.0"),
        ("selection_version", "agent-market-bench-replacement-holdout-selection-v2"),
        ("selection_anchor_commit", "f" * 40),
        ("selection_sha256", "f" * 64),
    ],
)
@pytest.mark.parametrize("relative", ["summary.json", "run_metadata.json"])
def test_resealed_singleton_semantic_and_selection_tamper_is_rejected(
    bundle, relative, field, value
) -> None:
    output_dir, manifest = bundle
    payload = json.loads((output_dir / relative).read_bytes())
    payload[field] = value
    _reseal_file(output_dir, manifest, relative, _json_bytes(payload))
    with pytest.raises(ValueError, match=r"invalid evidence model"):
        _verify(output_dir)


@pytest.mark.parametrize(
    "field,value",
    [
        ("metric_semantics_version", "agent-market-bench-metric-semantics-v1.0"),
        ("selection_version", "agent-market-bench-replacement-holdout-selection-v2"),
        ("selection_anchor_commit", "f" * 40),
        ("selection_sha256", "f" * 64),
        ("seed_sequence_sha256", "f" * 64),
        ("first_seed", _DEVELOPMENT_SEEDS[0]),
        ("last_seed", _DEVELOPMENT_SEEDS[-1]),
        ("case_count", 4),
        ("shard_size", 2),
    ],
)
def test_public_verifier_rejects_strict_manifest_tamper_before_inventory(
    tmp_path, field, value
) -> None:
    manifest = _replacement_manifest()  # Handcrafted file entries; no replacement records exist.
    payload = manifest.model_dump(mode="json")
    payload[field] = value
    (tmp_path / "manifest.json").write_bytes(_json_bytes(payload))
    with pytest.raises(ValueError, match=r"invalid evidence model: manifest.json"):
        evidence.verify_agent_market_bench_replacement_final_evidence_v1(tmp_path)


@pytest.mark.parametrize("tamper", ["reorder", "gap", "duplicate"])
def test_frozen_seed_order_rejects_resealed_paired_records(bundle, tamper) -> None:
    output_dir, manifest = bundle
    for kind in ("semantic", "timing"):
        records = [
            item
            for index in range(2)
            for item in _read_records(output_dir, f"{kind}/part-{index:05d}.jsonl.gz")
        ]
        if tamper == "reorder":
            records[1], records[2] = records[2], records[1]
        elif tamper == "gap":
            records[1]["seed"] = AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1[4]
        else:
            records[1]["seed"] = records[0]["seed"]
        for index in range(2):
            manifest = _reseal_records(
                output_dir,
                manifest,
                f"{kind}/part-{index:05d}.jsonl.gz",
                records[index * 2 : (index + 1) * 2],
            )
    with pytest.raises(ValueError, match=r"record seed order differs from the frozen tuple"):
        _verify(output_dir)


@pytest.mark.parametrize(
    "field,value",
    [("case_digest_sha256", "f" * 64), ("seed", AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1[4])],
)
def test_verifier_rejects_resealed_semantic_timing_pairing_mismatch(bundle, field, value) -> None:
    output_dir, manifest = bundle
    relative = "timing/part-00000.jsonl.gz"
    records = _read_records(output_dir, relative)
    records[1][field] = value
    _reseal_records(output_dir, manifest, relative, records)
    with pytest.raises(ValueError, match=r"semantic/timing pairing mismatch"):
        _verify(output_dir)


@pytest.mark.parametrize(
    "root", ["semantic_root_sha256", "timing_root_sha256", "evidence_root_sha256"]
)
def test_verifier_rejects_each_wrong_root(bundle, root) -> None:
    output_dir, manifest = bundle
    changed = AgentMarketBenchFinalManifestV1.model_validate(_payload(manifest, **{root: "f" * 64}))
    _write_manifest(output_dir, changed)
    with pytest.raises(ValueError, match=f"{root} mismatch"):
        _verify(output_dir)


@pytest.mark.parametrize("relative", ["summary.json", "run_metadata.json"])
def test_verifier_rejects_resealed_noncanonical_singleton(bundle, relative) -> None:
    output_dir, manifest = bundle
    payload = json.loads((output_dir / relative).read_bytes())
    _reseal_file(output_dir, manifest, relative, (json.dumps(payload) + "\n").encode("utf-8"))
    with pytest.raises(ValueError, match=r"noncanonical evidence JSON"):
        _verify(output_dir)


@pytest.mark.parametrize("kind", ["semantic", "timing"])
def test_verifier_rejects_resealed_noncanonical_jsonl(bundle, kind) -> None:
    output_dir, manifest = bundle
    relative = f"{kind}/part-00000.jsonl.gz"
    records = _read_records(output_dir, relative)
    raw = b"".join((json.dumps(item) + "\n").encode("utf-8") for item in records)
    _reseal_file(output_dir, manifest, relative, evidence._gzip_bytes(raw), raw=raw)
    with pytest.raises(ValueError, match=r"noncanonical shard record"):
        _verify(output_dir)


@pytest.mark.parametrize("tamper", ["crc", "mtime", "filename", "level"])
def test_verifier_rejects_hash_resealed_invalid_gzip(bundle, tamper) -> None:
    output_dir, manifest = bundle
    relative = "semantic/part-00000.jsonl.gz"
    stored = bytearray((output_dir / relative).read_bytes())
    raw = gzip.decompress(stored)
    if tamper == "crc":
        stored[-8] ^= 1
    elif tamper == "mtime":
        stored[4] = 1
    elif tamper == "filename":
        stored[3] = 8
    else:
        stored[8] = 4
    _reseal_file(output_dir, manifest, relative, bytes(stored), raw=raw)
    with pytest.raises(ValueError, match=r"invalid gzip shard|gzip requires level 9"):
        _verify(output_dir)


@pytest.mark.parametrize(
    "relative",
    [
        "semantic/part-00000.jsonl.gz",
        "timing/part-00001.jsonl.gz",
        "summary.json",
        "report.md",
        "run_metadata.json",
        "manifest.json",
    ],
)
def test_verifier_rejects_missing_evidence_file(bundle, relative) -> None:
    output_dir, manifest = bundle
    (output_dir / relative).unlink()
    with pytest.raises(
        ValueError, match=r"missing or extra evidence files|manifest.json is required"
    ):
        _verify(output_dir, expected_manifest=manifest)


@pytest.mark.parametrize(
    "relative", ["extra.txt", "semantic/part-00002.jsonl.gz", "timing/.temporary"]
)
def test_verifier_rejects_extra_evidence_file(bundle, relative) -> None:
    output_dir, _ = bundle
    (output_dir / relative).write_bytes(b"unexpected\n")
    with pytest.raises(ValueError, match=r"missing or extra evidence files"):
        _verify(output_dir)


def test_verifier_rejects_gapped_shard_paths_even_when_manifest_resealed(bundle) -> None:
    output_dir, manifest = bundle
    payload = manifest.model_dump(mode="json")
    target = next(
        item for item in payload["files"] if item["relative_path"] == "semantic/part-00000.jsonl.gz"
    )
    target["relative_path"] = "semantic/part-00002.jsonl.gz"
    payload["files"].sort(key=lambda item: item["relative_path"])
    (output_dir / "manifest.json").write_bytes(_json_bytes(payload))
    with pytest.raises(ValueError, match=r"evidence paths do not equal the frozen shard"):
        _verify(output_dir)


def test_verifier_rejects_reordered_manifest_entries(bundle) -> None:
    output_dir, manifest = bundle
    payload = manifest.model_dump(mode="json")
    payload["files"].reverse()
    (output_dir / "manifest.json").write_bytes(_json_bytes(payload))
    with pytest.raises(ValueError, match=r"invalid evidence model: manifest.json"):
        _verify(output_dir)


def test_public_verifier_never_accepts_development_inventory(frozen_bundle) -> None:
    output_dir, _ = frozen_bundle
    with pytest.raises(ValueError, match=r"invalid evidence model: manifest.json"):
        evidence.verify_agent_market_bench_replacement_final_evidence_v1(output_dir)


def test_public_expected_manifest_never_bypasses_stored_manifest_requirement(tmp_path) -> None:
    with pytest.raises(ValueError, match=r"manifest.json is required"):
        evidence.verify_agent_market_bench_replacement_final_evidence_v1(
            tmp_path, expected_manifest=_replacement_manifest()
        )


def test_public_verifier_requires_complete_inventory_after_valid_handcrafted_manifest(
    tmp_path,
) -> None:
    _write_manifest(tmp_path, _replacement_manifest())
    with pytest.raises(ValueError, match=r"missing or extra evidence files"):
        evidence.verify_agent_market_bench_replacement_final_evidence_v1(tmp_path)


def test_expected_manifest_requires_exact_match(bundle) -> None:
    output_dir, manifest = bundle
    other = AgentMarketBenchFinalManifestV1.model_validate(
        _payload(manifest, evaluated_source_commit="f" * 40)
    )
    with pytest.raises(ValueError, match=r"manifest.json differs from expected_manifest"):
        _verify(output_dir, expected_manifest=other)


def test_manifest_is_published_last_after_verification(
    tmp_path, development_runs, monkeypatch
) -> None:
    output_dir = tmp_path / "publication"
    published = []
    verified = []
    original_write = evidence._atomic_write
    original_verify = evidence._verify_bundle

    def observe_write(path, data):
        assert not (output_dir / "manifest.json").exists()
        if path.name == "manifest.json":
            assert verified == [True]
        original_write(path, data)
        published.append(path.relative_to(output_dir).as_posix())

    def observe_verify(path, **kwargs):
        assert not (path / "manifest.json").exists()
        assert kwargs["unpublished_manifest"] is True
        result = original_verify(path, **kwargs)
        verified.append(True)
        return result

    monkeypatch.setattr(evidence, "_atomic_write", observe_write)
    monkeypatch.setattr(evidence, "_verify_bundle", observe_verify)
    writer = evidence._EvidenceWriter(
        output_dir=output_dir,
        evaluated_source_commit=_COMMIT,
        seeds=_DEVELOPMENT_SEEDS,
        shard_size=2,
        completed_replacement=False,
    )
    writer.add_case_run(development_runs[0])
    assert writer.processed_count == 1
    assert published == []
    writer.add_case_run(development_runs[1])
    assert published == ["semantic/part-00000.jsonl.gz", "timing/part-00000.jsonl.gz"]
    for case_run in development_runs[2:]:
        writer.add_case_run(case_run)
    writer.finish()
    assert published == [
        "semantic/part-00000.jsonl.gz",
        "timing/part-00000.jsonl.gz",
        "semantic/part-00001.jsonl.gz",
        "timing/part-00001.jsonl.gz",
        "summary.json",
        "report.md",
        "run_metadata.json",
        "manifest.json",
    ]


def test_production_writer_has_no_seed_or_shard_options_and_binds_frozen_partition(
    tmp_path, monkeypatch
) -> None:
    signature = inspect.signature(evidence.AgentMarketBenchReplacementFinalEvidenceWriterV1)
    assert set(signature.parameters) == {"output_dir", "evaluated_source_commit"}
    assert all(
        item.kind is inspect.Parameter.KEYWORD_ONLY for item in signature.parameters.values()
    )
    captured = []

    def fake_writer(**kwargs):
        captured.append(kwargs)
        return object()

    monkeypatch.setattr(evidence, "_EvidenceWriter", fake_writer)
    output_dir = tmp_path / "not-created"
    evidence.AgentMarketBenchReplacementFinalEvidenceWriterV1(
        output_dir=output_dir, evaluated_source_commit=_COMMIT
    )
    assert captured == [
        {
            "output_dir": output_dir,
            "evaluated_source_commit": _COMMIT,
            "seeds": AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1,
            "shard_size": 500,
            "completed_replacement": True,
        }
    ]
    assert not output_dir.exists()


def test_writer_rejects_existing_directory_without_touching_it(tmp_path, development_runs) -> None:
    marker = tmp_path / "preserve.txt"
    marker.write_bytes(b"preserve\n")
    with pytest.raises(ValueError, match=r"output_dir must not exist"):
        evidence._write_development_evidence(
            case_runs=development_runs,
            output_dir=tmp_path,
            evaluated_source_commit=_COMMIT,
            shard_size=2,
        )
    assert tuple(tmp_path.iterdir()) == (marker,)
    assert marker.read_bytes() == b"preserve\n"


def test_writer_enforces_exact_order_completion_and_no_extra_cases(
    tmp_path, development_runs
) -> None:
    writer = evidence._EvidenceWriter(
        output_dir=tmp_path / "ordered",
        evaluated_source_commit=_COMMIT,
        seeds=_DEVELOPMENT_SEEDS,
        shard_size=2,
        completed_replacement=False,
    )
    with pytest.raises(ValueError, match=r"frozen seed order"):
        writer.add_case_run(development_runs[1])
    assert writer.processed_count == 0
    with pytest.raises(ValueError, match=r"processed count differs"):
        writer.finish()
    for case_run in development_runs:
        writer.add_case_run(case_run)
    writer.finish()
    with pytest.raises(ValueError, match=r"writer is finished"):
        writer.add_case_run(development_runs[0])
    with pytest.raises(ValueError, match=r"writer is finished"):
        writer.finish()


def test_verifier_invokes_zero_generator_runner_method_or_oracle_calls(
    frozen_bundle, monkeypatch
) -> None:
    output_dir, manifest = frozen_bundle
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("stored evidence verification must never execute benchmark code")

    for module, name in (
        (generator, "generate_agent_market_bench_case_v1"),
        (runner, "run_agent_market_bench_case_v1"),
        (runner, "run_agent_market_bench_cases_v1"),
        (runner, "run_agent_market_bench_method_v1"),
        (runner, "run_agent_market_bench_full_information_oracle_v1"),
        (methods, "run_agent_market_bench_method_v1"),
        (full_information, "run_agent_market_bench_full_information_oracle_v1"),
    ):
        monkeypatch.setattr(module, name, forbidden)
    assert _verify(output_dir) == manifest
    assert calls == []


def test_source_import_firewall_uses_no_historical_private_helpers_or_execution_services() -> None:
    tree = ast.parse(inspect.getsource(evidence))
    forbidden_modules = {
        "generator",
        "runner",
        "methods",
        "full_information",
        "metrics",
        "payments",
        "ai",
        "socket",
        "requests",
        "http",
        "urllib",
        "subprocess",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (set((node.module or "").split(".")) & forbidden_modules)
            if node.module == "clear_market.agentmarketbench.final_evidence":
                assert all(not alias.name.startswith("_") for alias in node.names)
        elif isinstance(node, ast.Import):
            assert all(not (set(alias.name.split(".")) & forbidden_modules) for alias in node.names)
        elif isinstance(node, ast.Call):
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            assert name not in {
                "eval",
                "exec",
                "__import__",
                "generate_agent_market_bench_case_v1",
                "run_agent_market_bench_case_v1",
                "run_agent_market_bench_method_v1",
                "run_agent_market_bench_full_information_oracle_v1",
            }


def test_report_has_exact_bindings_neutral_tables_and_every_interpretation_limit(
    frozen_bundle,
) -> None:
    output_dir, manifest = frozen_bundle
    report = (output_dir / "report.md").read_text()
    assert report.startswith("# AgentMarketBench V1 Replacement Final Holdout\n")
    for value in (
        _COMMIT,
        "agent-market-bench-generator-v1",
        "agent-market-bench-runner-v1",
        "agent-market-bench-metrics-v1",
        "agent-market-bench-metric-semantics-v1.1",
        "agent-market-bench-statistics-v1",
        "agent-market-bench-replacement-holdout-selection-v1",
        AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1,
        AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1,
        manifest.seed_sequence_sha256,
        manifest.semantic_root_sha256,
        manifest.timing_root_sha256,
        "Final cases: 4",
        "## Method status counts",
        "## Method metric means",
        "## Paired comparator-minus-CLEAR summaries",
        "## Scenario coverage",
        "## Scenario assessment counts",
        "Difference orientation is comparator minus CLEAR.",
        "generated synthetic distribution only",
        "replacement evidence only",
        "original failed 3,000-case partial attempt is excluded",
        "No conclusion may combine partial attempt #1 with replacement results",
        "No general V2 truthfulness or strategy-proofness claim",
        "No Sybil prevention claim",
        "No collusion prevention claim",
        "No physical inventory truth claim",
        "not proof of physical fulfillment",
        "Payment correctness is benchmark rule correctness, not settlement correctness",
        "Runtime financial scenarios remain OUT_OF_SCOPE in this economic runner",
        "AI-text scenarios remain OUT_OF_SCOPE because AI is not exercised",
        "Latency is observational and environment-sensitive",
        "Normal-approximation intervals are descriptive",
        "No p-values",
        "No statistical-significance claim",
        "No automatic benchmark winner or ranking",
        "No live Razorpay claim",
        "minimum-qualified benchmark welfare",
        "raw realization diagnostics remain raw",
    ):
        assert value in report
    for forbidden in (
        "clear wins",
        "clear is best",
        "recommend clear",
        "statistically significant",
        "dominates",
    ):
        assert forbidden not in report.lower()


def test_metadata_preserves_privacy_and_clock_boundary(frozen_bundle) -> None:
    output_dir, _ = frozen_bundle
    metadata = json.loads((output_dir / "run_metadata.json").read_bytes())
    assert metadata["clock_name"] == "time.perf_counter_ns"
    assert metadata["started_at_utc"] == metadata["completed_at_utc"] == _NOW
    assert set(metadata) == {
        "schema_version",
        "agent_market_bench_replacement_final_run_metadata_version",
        "evaluated_source_commit",
        "metric_semantics_version",
        "selection_version",
        "selection_anchor_commit",
        "selection_sha256",
        "started_at_utc",
        "completed_at_utc",
        "python_version",
        "platform_system",
        "platform_machine",
        "pydantic_version",
        "ortools_version",
        "cryptography_version",
        "clock_name",
    }
