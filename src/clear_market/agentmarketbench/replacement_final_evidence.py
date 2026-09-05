"""Replacement transport bound to the reviewed selection and repaired metric semantics.

Verification reconstructs aggregates from stored compact records only. It never
generates a case or executes an economic method.
"""

import gzip
import json
import os
import platform
import re
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from importlib.metadata import version as package_version
from io import BytesIO
from pathlib import Path
from types import UnionType
from typing import Annotated, Any, Union, cast, get_args, get_origin

import cryptography
import pydantic
from pydantic import BaseModel

from clear_market.agentmarketbench.final_evidence import (
    AgentMarketBenchFinalStreamingAccumulatorV1,
    agent_market_bench_final_evidence_root_digest_v1,
    agent_market_bench_final_seed_sequence_digest_v1,
    agent_market_bench_final_shard_content_root_digest_v1,
    canonical_agent_market_bench_final_json_v1_bytes,
    compact_agent_market_bench_case_run_v1,
    render_agent_market_bench_final_report_v1,
)
from clear_market.agentmarketbench.final_models import (
    AgentMarketBenchFinalEvidenceFileKindV1,
    AgentMarketBenchFinalEvidenceFileV1,
    AgentMarketBenchFinalManifestV1,
    AgentMarketBenchFinalSemanticRecordV1,
    AgentMarketBenchFinalSummaryV1,
    AgentMarketBenchFinalTimingRecordV1,
    AgentMarketBenchReplacementFinalManifestV1,
    AgentMarketBenchReplacementFinalRunMetadataV1,
    AgentMarketBenchReplacementFinalSummaryV1,
)
from clear_market.agentmarketbench.measurement_models import (
    AGENT_MARKET_BENCH_METRIC_SEMANTICS_V1_1_VERSION,
    AGENT_MARKET_BENCH_METRICS_V1_VERSION,
    AGENT_MARKET_BENCH_RUNNER_V1_VERSION,
    AGENT_MARKET_BENCH_STATISTICS_V1_VERSION,
    AgentMarketBenchCaseRunV1,
)
from clear_market.agentmarketbench.models import AGENT_MARKET_BENCH_GENERATOR_V1_VERSION
from clear_market.agentmarketbench.seeds import (
    AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_BLOCK_INDEX_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEED_SEQUENCE_SHA256_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_V1_VERSION,
)

_SHARD_SIZE = 500
_SUMMARY_FIELDS = (
    "evaluated_source_commit",
    "case_count",
    "seed_sequence_sha256",
    "standard_case_count",
    "method_status_counts",
    "scenario_counts",
    "scenario_assessment_counts",
    "run_summary",
)
type _Inventory = AgentMarketBenchReplacementFinalManifestV1 | AgentMarketBenchFinalManifestV1


def _fresh_exact[ModelT: BaseModel](model_type: type[ModelT], value: object) -> ModelT:
    if type(value) is not model_type:
        raise TypeError(f"value must be exactly {model_type.__name__}")
    return model_type.model_validate(
        {name: getattr(value, name) for name in model_type.model_fields}
    )


def _selection_fields() -> dict[str, str]:
    return {
        "metric_semantics_version": AGENT_MARKET_BENCH_METRIC_SEMANTICS_V1_1_VERSION,
        "selection_version": AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_V1_VERSION,
        "selection_anchor_commit": (
            AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1
        ),
        "selection_sha256": AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1,
    }


def _frozen_seeds() -> tuple[int, ...]:
    anchor = "a4fc224ba9b10b518753d05237ab7d56d737943b"
    digest = sha256(
        f"CLEAR|AgentMarketBench|replacement-holdout-v1|{anchor}".encode("ascii")
    ).hexdigest()
    block = int(digest, 16) % 40_000
    start = 1_400_000_000 + block * 10_000
    expected = tuple(range(start, start + 10_000))
    seeds = AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1
    if (
        AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_V1_VERSION
        != "agent-market-bench-replacement-holdout-selection-v1"
        or AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1 != anchor
        or digest != AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1
        or block != AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_BLOCK_INDEX_V1
        or type(seeds) is not tuple
        or seeds != expected
        or agent_market_bench_final_seed_sequence_digest_v1(seeds)
        != AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEED_SEQUENCE_SHA256_V1
    ):
        raise ValueError("replacement selection or seed-sequence contract mismatch")
    return seeds


def _build_summary(
    accumulator: AgentMarketBenchFinalStreamingAccumulatorV1,
    *,
    commit: str,
    seed_digest: str,
) -> AgentMarketBenchReplacementFinalSummaryV1:
    historical = accumulator.build_final_summary_v1(
        evaluated_source_commit=commit,
        seed_sequence_sha256=seed_digest,
    )
    return AgentMarketBenchReplacementFinalSummaryV1.model_validate(
        {**{name: getattr(historical, name) for name in _SUMMARY_FIELDS}, **_selection_fields()}
    )


def render_agent_market_bench_replacement_final_report_v1(
    summary: AgentMarketBenchReplacementFinalSummaryV1,
    *,
    semantic_root_sha256: str,
    timing_root_sha256: str,
) -> str:
    """Render neutral exact tables with explicit replacement and semantic lineage."""

    fresh = _fresh_exact(AgentMarketBenchReplacementFinalSummaryV1, summary)
    historical = AgentMarketBenchFinalSummaryV1.model_validate(
        {name: getattr(fresh, name) for name in _SUMMARY_FIELDS}
    )
    historical_lines = render_agent_market_bench_final_report_v1(
        historical,
        generator_version=AGENT_MARKET_BENCH_GENERATOR_V1_VERSION,
        runner_version=AGENT_MARKET_BENCH_RUNNER_V1_VERSION,
        metrics_version=AGENT_MARKET_BENCH_METRICS_V1_VERSION,
        statistics_version=AGENT_MARKET_BENCH_STATISTICS_V1_VERSION,
        semantic_root_sha256=semantic_root_sha256,
        timing_root_sha256=timing_root_sha256,
    ).splitlines()
    tables_start = historical_lines.index("## Method status counts")
    lines = [
        "# AgentMarketBench V1 Replacement Final Holdout",
        "",
        f"- Evaluated source commit: `{fresh.evaluated_source_commit}`",
        f"- Generator version: `{AGENT_MARKET_BENCH_GENERATOR_V1_VERSION}`",
        f"- Runner version: `{AGENT_MARKET_BENCH_RUNNER_V1_VERSION}`",
        f"- Metrics schema-family version: `{AGENT_MARKET_BENCH_METRICS_V1_VERSION}`",
        f"- Metric semantic revision: `{fresh.metric_semantics_version}`",
        f"- Statistics version: `{AGENT_MARKET_BENCH_STATISTICS_V1_VERSION}`",
        f"- Selection version: `{fresh.selection_version}`",
        f"- Selection anchor commit: `{fresh.selection_anchor_commit}`",
        f"- Selection SHA-256: `{fresh.selection_sha256}`",
        f"- Replacement seed-sequence SHA-256: `{fresh.seed_sequence_sha256}`",
        f"- Semantic evidence root SHA-256: `{semantic_root_sha256}`",
        f"- Timing evidence root SHA-256: `{timing_root_sha256}`",
        f"- Final cases: {fresh.case_count}",
        "",
        *historical_lines[tables_start:],
        "- This aggregate describes replacement evidence only.",
        "- The original failed 3,000-case partial attempt is excluded from this final aggregate.",
        "- No conclusion may combine partial attempt #1 with replacement results.",
        "- Runtime financial scenarios remain OUT_OF_SCOPE in this economic runner.",
        "- Metric semantic revision v1.1 uses minimum-qualified benchmark welfare; "
        "raw realization diagnostics remain raw.",
        "",
    ]
    return "\n".join(lines)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists():
        raise ValueError(f"temporary evidence path already exists: {temporary.name}")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _gzip_bytes(data: bytes) -> bytes:
    buffer = BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, compresslevel=9, mtime=0) as handle:
        handle.write(data)
    return buffer.getvalue()


def _evidence_file(
    relative_path: str,
    kind: AgentMarketBenchFinalEvidenceFileKindV1,
    data: bytes,
    *,
    raw: bytes | None = None,
    seeds: tuple[int, ...] = (),
) -> AgentMarketBenchFinalEvidenceFileV1:
    return AgentMarketBenchFinalEvidenceFileV1(
        relative_path=relative_path,
        kind=kind,
        sha256=sha256(data).hexdigest(),
        byte_count=len(data),
        line_count=(data if raw is None else raw).count(b"\n"),
        uncompressed_sha256=None if raw is None else sha256(raw).hexdigest(),
        first_seed=seeds[0] if seeds else None,
        last_seed=seeds[-1] if seeds else None,
    )


def _shards(
    files: tuple[AgentMarketBenchFinalEvidenceFileV1, ...],
    kind: AgentMarketBenchFinalEvidenceFileKindV1,
) -> tuple[AgentMarketBenchFinalEvidenceFileV1, ...]:
    return tuple(item for item in files if item.kind is kind)


def _roots(files: tuple[AgentMarketBenchFinalEvidenceFileV1, ...]) -> dict[str, str]:
    return {
        "semantic_root_sha256": agent_market_bench_final_shard_content_root_digest_v1(
            _shards(files, AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD),
            kind=AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD,
        ),
        "timing_root_sha256": agent_market_bench_final_shard_content_root_digest_v1(
            _shards(files, AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD),
            kind=AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD,
        ),
        "evidence_root_sha256": agent_market_bench_final_evidence_root_digest_v1(files),
    }


class _EvidenceWriter:
    """Private common transport; small development inventories cannot pass the public verifier."""

    def __init__(
        self,
        *,
        output_dir: Path,
        evaluated_source_commit: str,
        seeds: tuple[int, ...],
        shard_size: int,
        completed_replacement: bool,
    ) -> None:
        if not isinstance(output_dir, Path):
            raise TypeError("output_dir must be a pathlib.Path")
        if output_dir.exists():
            raise ValueError("output_dir must not exist")
        if (
            type(evaluated_source_commit) is not str
            or re.fullmatch(r"[0-9a-f]{40}", evaluated_source_commit) is None
        ):
            raise ValueError("evaluated_source_commit must be an exact lowercase 40-hex SHA")
        if type(shard_size) is not int or shard_size < 1:
            raise ValueError("shard_size must be a positive exact int")
        self._seed_digest = agent_market_bench_final_seed_sequence_digest_v1(seeds)
        if len(set(seeds)) != len(seeds):
            raise ValueError("evidence seeds must be unique")
        if completed_replacement:
            if seeds != _frozen_seeds() or shard_size != _SHARD_SIZE:
                raise ValueError("production replacement writer requires the frozen partition")
        elif any(seed not in AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1 for seed in seeds):
            raise ValueError("test-only evidence requires frozen development seeds")
        self._output_dir = output_dir
        self._commit = evaluated_source_commit
        self._seeds = seeds
        self._shard_size = shard_size
        self._completed_replacement = completed_replacement
        self._started_at = _utc_now()
        self._processed = 0
        self._finished = False
        self._shard_index = 0
        self._semantic_buffer: list[bytes] = []
        self._timing_buffer: list[bytes] = []
        self._buffer_seeds: list[int] = []
        self._files: list[AgentMarketBenchFinalEvidenceFileV1] = []
        self._accumulator = AgentMarketBenchFinalStreamingAccumulatorV1()
        output_dir.mkdir(parents=True)
        (output_dir / "semantic").mkdir()
        (output_dir / "timing").mkdir()

    @property
    def processed_count(self) -> int:
        return self._processed

    def add_case_run(self, case_run: AgentMarketBenchCaseRunV1) -> None:
        if self._finished or self._processed >= len(self._seeds):
            raise ValueError("received more cases than the frozen sequence or writer is finished")
        semantic, timing = compact_agent_market_bench_case_run_v1(case_run)
        if semantic.seed != self._seeds[self._processed]:
            raise ValueError("case-run seed does not follow the frozen seed order")
        self._accumulator.add(semantic, timing)
        self._semantic_buffer.append(canonical_agent_market_bench_final_json_v1_bytes(semantic))
        self._timing_buffer.append(canonical_agent_market_bench_final_json_v1_bytes(timing))
        self._buffer_seeds.append(semantic.seed)
        self._processed += 1
        if len(self._buffer_seeds) == self._shard_size:
            self._flush_shard()

    def _flush_shard(self) -> None:
        if not self._buffer_seeds or not (
            len(self._semantic_buffer) == len(self._timing_buffer) == len(self._buffer_seeds)
        ):
            raise ValueError("shard buffers must be non-empty and paired")
        for directory, kind, buffer in (
            (
                "semantic",
                AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD,
                self._semantic_buffer,
            ),
            ("timing", AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD, self._timing_buffer),
        ):
            raw = b"".join(buffer)
            data = _gzip_bytes(raw)
            relative = f"{directory}/part-{self._shard_index:05d}.jsonl.gz"
            _atomic_write(self._output_dir / relative, data)
            self._files.append(
                _evidence_file(relative, kind, data, raw=raw, seeds=tuple(self._buffer_seeds))
            )
        self._semantic_buffer.clear()
        self._timing_buffer.clear()
        self._buffer_seeds.clear()
        self._shard_index += 1

    def finish(self) -> _Inventory:
        if self._finished or self._processed != len(self._seeds):
            raise ValueError("writer is finished or processed count differs from frozen sequence")
        if self._buffer_seeds:
            self._flush_shard()
        summary = _build_summary(
            self._accumulator, commit=self._commit, seed_digest=self._seed_digest
        )
        shard_roots = _roots(tuple(self._files))
        report = render_agent_market_bench_replacement_final_report_v1(
            summary,
            semantic_root_sha256=shard_roots["semantic_root_sha256"],
            timing_root_sha256=shard_roots["timing_root_sha256"],
        )
        metadata = AgentMarketBenchReplacementFinalRunMetadataV1.model_validate(
            {
                **_selection_fields(),
                "evaluated_source_commit": self._commit,
                "started_at_utc": self._started_at,
                "completed_at_utc": _utc_now(),
                "python_version": platform.python_version(),
                "platform_system": platform.system(),
                "platform_machine": platform.machine(),
                "pydantic_version": pydantic.__version__,
                "ortools_version": package_version("ortools"),
                "cryptography_version": cryptography.__version__,
            }
        )
        for relative, kind, data in (
            (
                "summary.json",
                AgentMarketBenchFinalEvidenceFileKindV1.SUMMARY,
                canonical_agent_market_bench_final_json_v1_bytes(summary),
            ),
            ("report.md", AgentMarketBenchFinalEvidenceFileKindV1.REPORT, report.encode("utf-8")),
            (
                "run_metadata.json",
                AgentMarketBenchFinalEvidenceFileKindV1.RUN_METADATA,
                canonical_agent_market_bench_final_json_v1_bytes(metadata),
            ),
        ):
            _atomic_write(self._output_dir / relative, data)
            self._files.append(_evidence_file(relative, kind, data))
        files = tuple(sorted(self._files, key=lambda item: item.relative_path))
        fields: dict[str, object] = {
            "evaluated_source_commit": self._commit,
            "case_count": self._processed,
            "first_seed": self._seeds[0],
            "last_seed": self._seeds[-1],
            "seed_sequence_sha256": self._seed_digest,
            "shard_size": self._shard_size,
            "semantic_shard_count": self._shard_index,
            "timing_shard_count": self._shard_index,
            "files": files,
            **_roots(files),
        }
        manifest: _Inventory
        if self._completed_replacement:
            manifest = AgentMarketBenchReplacementFinalManifestV1.model_validate(
                {**fields, **_selection_fields()}
            )
        else:
            # This private development inventory deliberately cannot masquerade as
            # a completed replacement manifest, whose schema always requires 10,000.
            manifest = AgentMarketBenchFinalManifestV1.model_validate(fields)
        _verify_bundle(
            self._output_dir,
            expected_manifest=manifest,
            expected_seeds=self._seeds,
            completed_replacement=self._completed_replacement,
            unpublished_manifest=True,
        )
        _atomic_write(
            self._output_dir / "manifest.json",
            canonical_agent_market_bench_final_json_v1_bytes(manifest),
        )
        self._finished = True
        return manifest


class AgentMarketBenchReplacementFinalEvidenceWriterV1:
    """Production writer: the seed partition and 500-case shard size are not caller options."""

    def __init__(self, *, output_dir: Path, evaluated_source_commit: str) -> None:
        self._writer = _EvidenceWriter(
            output_dir=output_dir,
            evaluated_source_commit=evaluated_source_commit,
            seeds=_frozen_seeds(),
            shard_size=_SHARD_SIZE,
            completed_replacement=True,
        )

    @property
    def processed_count(self) -> int:
        return self._writer.processed_count

    def add_case_run(self, case_run: AgentMarketBenchCaseRunV1) -> None:
        self._writer.add_case_run(case_run)

    def finish(self) -> AgentMarketBenchReplacementFinalManifestV1:
        return _fresh_exact(AgentMarketBenchReplacementFinalManifestV1, self._writer.finish())


def _write_development_evidence(
    *,
    case_runs: tuple[AgentMarketBenchCaseRunV1, ...],
    output_dir: Path,
    evaluated_source_commit: str,
    shard_size: int,
) -> AgentMarketBenchFinalManifestV1:
    if type(case_runs) is not tuple or not case_runs:
        raise ValueError("development case_runs must be a non-empty exact tuple")
    fresh = tuple(_fresh_exact(AgentMarketBenchCaseRunV1, item) for item in case_runs)
    writer = _EvidenceWriter(
        output_dir=output_dir,
        evaluated_source_commit=evaluated_source_commit,
        seeds=tuple(item.seed for item in fresh),
        shard_size=shard_size,
        completed_replacement=False,
    )
    for case_run in fresh:
        writer.add_case_run(case_run)
    return _fresh_exact(AgentMarketBenchFinalManifestV1, writer.finish())


def _decode_value(annotation: Any, value: object) -> object:
    """Restore only JSON representations of tuples, enums and nested model fields."""

    origin = get_origin(annotation)
    arguments = get_args(annotation)
    if origin is Annotated:
        return _decode_value(arguments[0], value)
    if origin in (UnionType, Union) and type(None) in arguments:
        return (
            None
            if value is None
            else _decode_value(next(item for item in arguments if item is not type(None)), value)
        )
    if origin is tuple:
        if type(value) is not list:
            raise ValueError("JSON tuple field must be an array")
        return tuple(_decode_value(arguments[0], item) for item in value)
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        if type(value) is not str:
            raise ValueError("JSON enum field must be a string")
        return annotation(value)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _decode_model(annotation, value)
    return value


def _decode_model[ModelT: BaseModel](model_type: type[ModelT], payload: object) -> ModelT:
    if type(payload) is not dict:
        raise ValueError("evidence JSON payload must be an object")
    data = cast(dict[str, object], payload)
    fields = model_type.model_fields
    return model_type.model_validate(
        {
            name: _decode_value(fields[name].annotation, value) if name in fields else value
            for name, value in data.items()
        }
    )


def _load_canonical[ModelT: BaseModel](path: Path, model_type: type[ModelT]) -> ModelT:
    try:
        raw = path.read_bytes()
        model = _decode_model(model_type, json.loads(raw))
    except Exception as error:
        raise ValueError(f"invalid evidence model: {path.name}") from error
    if canonical_agent_market_bench_final_json_v1_bytes(model) != raw:
        raise ValueError(f"noncanonical evidence JSON: {path.name}")
    return model


def _parse_shard[ModelT: BaseModel](
    output_dir: Path, file: AgentMarketBenchFinalEvidenceFileV1, model_type: type[ModelT]
) -> tuple[ModelT, ...]:
    compressed = (output_dir / file.relative_path).read_bytes()
    if len(compressed) != file.byte_count or sha256(compressed).hexdigest() != file.sha256:
        raise ValueError(f"compressed shard hash or byte count mismatch: {file.relative_path}")
    if (
        len(compressed) < 10
        or compressed[:4] != b"\x1f\x8b\x08\x00"
        or compressed[4:8] != b"\0\0\0\0"
        or compressed[8] != 2
    ):
        raise ValueError(f"gzip requires level 9, mtime=0 and no filename: {file.relative_path}")
    try:
        raw = gzip.decompress(compressed)
    except Exception as error:
        raise ValueError(f"invalid gzip shard: {file.relative_path}") from error
    if sha256(raw).hexdigest() != file.uncompressed_sha256:
        raise ValueError(f"uncompressed shard hash mismatch: {file.relative_path}")
    lines = raw.splitlines(keepends=True)
    if not raw.endswith(b"\n") or len(lines) != file.line_count:
        raise ValueError(f"shard newline record count mismatch: {file.relative_path}")
    records = []
    for line in lines:
        try:
            record = _decode_model(model_type, json.loads(line))
        except Exception as error:
            raise ValueError(f"invalid shard record: {file.relative_path}") from error
        if canonical_agent_market_bench_final_json_v1_bytes(record) != line:
            raise ValueError(f"noncanonical shard record: {file.relative_path}")
        records.append(record)
    seeded_records = cast(
        list[AgentMarketBenchFinalSemanticRecordV1 | AgentMarketBenchFinalTimingRecordV1], records
    )
    if seeded_records[0].seed != file.first_seed or seeded_records[-1].seed != file.last_seed:
        raise ValueError(f"shard first/last seed mismatch: {file.relative_path}")
    return tuple(records)


def _verify_bundle(
    output_dir: Path,
    *,
    expected_manifest: _Inventory | None,
    expected_seeds: tuple[int, ...],
    completed_replacement: bool,
    unpublished_manifest: bool = False,
) -> _Inventory:
    if not isinstance(output_dir, Path):
        raise TypeError("output_dir must be a pathlib.Path")
    if not output_dir.is_dir() or output_dir.is_symlink():
        raise ValueError("evidence output directory does not exist or is a symlink")
    if completed_replacement:
        if expected_seeds != _frozen_seeds():
            raise ValueError("replacement verifier requires the frozen replacement tuple")
        model_type: type[_Inventory] = AgentMarketBenchReplacementFinalManifestV1
    else:
        if not expected_seeds or any(
            seed not in AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1 for seed in expected_seeds
        ):
            raise ValueError("test-only verifier requires frozen development seeds")
        model_type = AgentMarketBenchFinalManifestV1
    manifest_path = output_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = _load_canonical(manifest_path, model_type)
        if expected_manifest is not None and manifest != _fresh_exact(
            model_type, expected_manifest
        ):
            raise ValueError("manifest.json differs from expected_manifest")
    elif unpublished_manifest and expected_manifest is not None:
        manifest = _fresh_exact(model_type, expected_manifest)
    else:
        raise ValueError("manifest.json is required for completed replacement evidence")
    expected_paths = {
        **{
            f"semantic/part-{index:05d}.jsonl.gz": (
                AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD
            )
            for index in range(manifest.semantic_shard_count)
        },
        **{
            f"timing/part-{index:05d}.jsonl.gz": (
                AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD
            )
            for index in range(manifest.timing_shard_count)
        },
        "summary.json": AgentMarketBenchFinalEvidenceFileKindV1.SUMMARY,
        "report.md": AgentMarketBenchFinalEvidenceFileKindV1.REPORT,
        "run_metadata.json": AgentMarketBenchFinalEvidenceFileKindV1.RUN_METADATA,
    }
    if {item.relative_path: item.kind for item in manifest.files} != expected_paths:
        raise ValueError("evidence paths do not equal the frozen shard and singleton sequence")
    paths = tuple(output_dir.rglob("*"))
    if any(path.is_symlink() or (not path.is_file() and not path.is_dir()) for path in paths):
        raise ValueError("evidence inventory cannot contain symlinks or nonregular entries")
    actual = {path.relative_to(output_dir).as_posix() for path in paths if path.is_file()}
    allowed = set(expected_paths) | ({"manifest.json"} if manifest_path.is_file() else set())
    if actual != allowed:
        raise ValueError("missing or extra evidence files")
    for item in manifest.files:
        data = (output_dir / item.relative_path).read_bytes()
        if len(data) != item.byte_count or sha256(data).hexdigest() != item.sha256:
            raise ValueError(f"evidence hash or byte count mismatch: {item.relative_path}")
        if item.uncompressed_sha256 is None and data.count(b"\n") != item.line_count:
            raise ValueError(f"evidence line count mismatch: {item.relative_path}")
    for name, digest in _roots(manifest.files).items():
        if getattr(manifest, name) != digest:
            raise ValueError(f"{name} mismatch")
    semantic_files = _shards(manifest.files, AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD)
    timing_files = _shards(manifest.files, AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD)
    if len(semantic_files) != len(timing_files):
        raise ValueError("semantic and timing shard counts must be paired")
    accumulator = AgentMarketBenchFinalStreamingAccumulatorV1()
    seeds: list[int] = []
    for semantic_file, timing_file in zip(semantic_files, timing_files, strict=True):
        semantic_records = _parse_shard(
            output_dir, semantic_file, AgentMarketBenchFinalSemanticRecordV1
        )
        timing_records = _parse_shard(output_dir, timing_file, AgentMarketBenchFinalTimingRecordV1)
        if len(semantic_records) != len(timing_records):
            raise ValueError("semantic/timing record counts differ")
        for semantic, timing in zip(semantic_records, timing_records, strict=True):
            if (
                semantic.seed != timing.seed
                or semantic.case_digest_sha256 != timing.case_digest_sha256
            ):
                raise ValueError("semantic/timing pairing mismatch")
            if len(seeds) >= len(expected_seeds) or semantic.seed != expected_seeds[len(seeds)]:
                raise ValueError("record seed order differs from the frozen tuple")
            seeds.append(semantic.seed)
            accumulator.add(semantic, timing)
    if tuple(seeds) != expected_seeds or len(seeds) != manifest.case_count:
        raise ValueError("record counts or seeds differ from frozen sequence")
    if (seeds[0], seeds[-1]) != (manifest.first_seed, manifest.last_seed):
        raise ValueError("manifest first/last seed mismatch")
    seed_digest = agent_market_bench_final_seed_sequence_digest_v1(tuple(seeds))
    if seed_digest != manifest.seed_sequence_sha256:
        raise ValueError("seed-sequence digest mismatch")
    summary = _load_canonical(
        output_dir / "summary.json", AgentMarketBenchReplacementFinalSummaryV1
    )
    expected_summary = _build_summary(
        accumulator, commit=manifest.evaluated_source_commit, seed_digest=seed_digest
    )
    if summary != expected_summary:
        raise ValueError("summary.json differs from reconstructed compact evidence")
    report = render_agent_market_bench_replacement_final_report_v1(
        summary,
        semantic_root_sha256=manifest.semantic_root_sha256,
        timing_root_sha256=manifest.timing_root_sha256,
    ).encode("utf-8")
    if (output_dir / "report.md").read_bytes() != report:
        raise ValueError("report.md differs from exact replacement rendering")
    metadata = _load_canonical(
        output_dir / "run_metadata.json", AgentMarketBenchReplacementFinalRunMetadataV1
    )
    if metadata.evaluated_source_commit != manifest.evaluated_source_commit:
        raise ValueError("run metadata source commit differs from manifest")
    for model in (summary, metadata):
        for name, value in _selection_fields().items():
            if getattr(model, name) != value:
                raise ValueError("metric semantics or selection binding mismatch")
    return _fresh_exact(model_type, manifest)


def verify_agent_market_bench_replacement_final_evidence_v1(
    output_dir: Path,
    *,
    expected_manifest: AgentMarketBenchReplacementFinalManifestV1 | None = None,
) -> AgentMarketBenchReplacementFinalManifestV1:
    """Verify a completed replacement bundle without executing benchmark code."""

    manifest = _verify_bundle(
        output_dir,
        expected_manifest=expected_manifest,
        expected_seeds=_frozen_seeds(),
        completed_replacement=True,
    )
    return _fresh_exact(AgentMarketBenchReplacementFinalManifestV1, manifest)


__all__ = (
    "AgentMarketBenchReplacementFinalEvidenceWriterV1",
    "render_agent_market_bench_replacement_final_report_v1",
    "verify_agent_market_bench_replacement_final_evidence_v1",
)
