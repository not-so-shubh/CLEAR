"""Strict transport models for frozen AgentMarketBench V1 final evidence."""

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from clear_market.agentmarketbench.measurement_models import (
    AgentMarketBenchMetricObservationV1,
    AgentMarketBenchRunSummaryV1,
    AgentMarketBenchScenarioAssessmentV1,
    AgentMarketBenchScenarioEvidenceBasisV1,
)
from clear_market.agentmarketbench.method_models import AgentMarketBenchMethodStatusV1
from clear_market.agentmarketbench.models import (
    MAX_AGENT_MARKET_BENCH_SEED,
    AgentMarketBenchAdversarialClassificationV1,
    AgentMarketBenchAdversarialScenarioV1,
    AgentMarketBenchBaselineV1,
    AgentMarketBenchMetricV1,
)
from clear_market.domain import CanonicalUUID4

AGENT_MARKET_BENCH_FINAL_EVIDENCE_V1_VERSION: Final[str] = "agent-market-bench-final-evidence-v1"
AGENT_MARKET_BENCH_FINAL_SEMANTIC_RECORD_V1_VERSION: Final[str] = (
    "agent-market-bench-final-semantic-record-v1"
)
AGENT_MARKET_BENCH_FINAL_TIMING_RECORD_V1_VERSION: Final[str] = (
    "agent-market-bench-final-timing-record-v1"
)
AGENT_MARKET_BENCH_FINAL_SUMMARY_V1_VERSION: Final[str] = "agent-market-bench-final-summary-v1"
AGENT_MARKET_BENCH_FINAL_MANIFEST_V1_VERSION: Final[str] = "agent-market-bench-final-manifest-v1"
AGENT_MARKET_BENCH_FINAL_RUN_METADATA_V1_VERSION: Final[str] = (
    "agent-market-bench-final-run-metadata-v1"
)

_CONFIG = ConfigDict(
    frozen=True,
    strict=True,
    extra="forbid",
    revalidate_instances="always",
)


def _require_tuple(value: object) -> object:
    if type(value) is not tuple:
        raise ValueError("collection must be supplied as a tuple")
    return value


def _exact_enum(enum_type: type[StrEnum], value: object) -> StrEnum:
    if type(value) is not enum_type:
        raise ValueError(f"value must be exactly {enum_type.__name__}")
    return value


def _fresh_exact[ModelT: BaseModel](model_type: type[ModelT], value: object) -> ModelT:
    if type(value) is not model_type:
        raise ValueError(f"value must be exactly {model_type.__name__}")
    try:
        raw = {field_name: getattr(value, field_name) for field_name in model_type.model_fields}
        fresh = model_type.model_validate(raw)
    except Exception as error:
        raise ValueError(f"{model_type.__name__} failed fresh validation") from error
    if type(fresh) is not model_type:
        raise ValueError(f"value must revalidate to exactly {model_type.__name__}")
    return fresh


def _validate_sha256(value: object) -> object:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("value must be a lowercase SHA-256 hex string")
    return value


def _validate_git_sha(value: object) -> object:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("value must be a lowercase 40-hex Git commit")
    return value


def _validate_relative_path(value: object) -> object:
    if type(value) is not str or not value:
        raise ValueError("relative_path must be a non-empty string")
    if value.startswith("/") or "\\" in value or "\x00" in value:
        raise ValueError("relative_path must be a safe POSIX relative path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("relative_path must be a safe POSIX relative path")
    return value


def _validate_utc_timestamp(value: object) -> object:
    if (
        type(value) is not str
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", value) is None
    ):
        raise ValueError("timestamp must be canonical UTC ISO-8601 with microseconds and Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError("timestamp must be valid UTC ISO-8601") from error
    canonical = parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if parsed.utcoffset() != UTC.utcoffset(parsed) or canonical != value:
        raise ValueError("timestamp must be canonical UTC ISO-8601")
    return value


_Sha256Hex = Annotated[str, BeforeValidator(_validate_sha256)]
_GitSha = Annotated[str, BeforeValidator(_validate_git_sha)]
_RelativePath = Annotated[str, BeforeValidator(_validate_relative_path)]
_UtcTimestamp = Annotated[str, BeforeValidator(_validate_utc_timestamp)]
_ExactBaseline = Annotated[
    AgentMarketBenchBaselineV1,
    BeforeValidator(lambda value: _exact_enum(AgentMarketBenchBaselineV1, value)),
]
_ExactMethodStatus = Annotated[
    AgentMarketBenchMethodStatusV1,
    BeforeValidator(lambda value: _exact_enum(AgentMarketBenchMethodStatusV1, value)),
]
_ExactScenario = Annotated[
    AgentMarketBenchAdversarialScenarioV1,
    BeforeValidator(lambda value: _exact_enum(AgentMarketBenchAdversarialScenarioV1, value)),
]
_ExactClassification = Annotated[
    AgentMarketBenchAdversarialClassificationV1,
    BeforeValidator(lambda value: _exact_enum(AgentMarketBenchAdversarialClassificationV1, value)),
]
_ExactBasis = Annotated[
    AgentMarketBenchScenarioEvidenceBasisV1,
    BeforeValidator(lambda value: _exact_enum(AgentMarketBenchScenarioEvidenceBasisV1, value)),
]
_FreshObservation = Annotated[
    AgentMarketBenchMetricObservationV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchMetricObservationV1, value)),
]
_FreshAssessment = Annotated[
    AgentMarketBenchScenarioAssessmentV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchScenarioAssessmentV1, value)),
]
_FreshRunSummary = Annotated[
    AgentMarketBenchRunSummaryV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchRunSummaryV1, value)),
]


class AgentMarketBenchFinalSemanticMethodV1(BaseModel):
    """One method's deterministic compact evidence, excluding latency."""

    model_config = _CONFIG

    schema_version: Literal["1"] = "1"
    agent_market_bench_final_semantic_record_version: Literal[
        "agent-market-bench-final-semantic-record-v1"
    ] = "agent-market-bench-final-semantic-record-v1"
    method: _ExactBaseline
    result_status: _ExactMethodStatus
    result_digest_sha256: _Sha256Hex
    fulfilled_quantity: Annotated[int, Field(strict=True, ge=0)]
    total_payment_paise: Annotated[int, Field(strict=True, ge=0)]
    winner_count: Annotated[int, Field(strict=True, ge=0)]
    realized_quantity: Annotated[int, Field(strict=True, ge=0)]
    latent_capacity_excess_units: Annotated[int, Field(strict=True, ge=0)]
    latent_hard_violation_units: Annotated[int, Field(strict=True, ge=0)]
    metrics: Annotated[tuple[_FreshObservation, ...], BeforeValidator(_require_tuple)]

    @model_validator(mode="after")
    def _validate_metrics(self) -> "AgentMarketBenchFinalSemanticMethodV1":
        expected = tuple(
            metric
            for metric in AgentMarketBenchMetricV1
            if metric is not AgentMarketBenchMetricV1.LATENCY
        )
        if tuple(observation.metric for observation in self.metrics) != expected:
            raise ValueError("semantic metrics must contain the exact ten non-latency metrics")
        return self


_FreshSemanticMethod = Annotated[
    AgentMarketBenchFinalSemanticMethodV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchFinalSemanticMethodV1, value)),
]


class AgentMarketBenchFinalSemanticRecordV1(BaseModel):
    """Compact deterministic evidence for one frozen case run."""

    model_config = _CONFIG

    schema_version: Literal["1"] = "1"
    agent_market_bench_final_semantic_record_version: Literal[
        "agent-market-bench-final-semantic-record-v1"
    ] = "agent-market-bench-final-semantic-record-v1"
    seed: Annotated[int, Field(strict=True, ge=0, le=MAX_AGENT_MARKET_BENCH_SEED)]
    case_id: CanonicalUUID4
    case_digest_sha256: _Sha256Hex
    adversarial_scenarios: Annotated[tuple[_ExactScenario, ...], BeforeValidator(_require_tuple)]
    scenario_assessments: Annotated[tuple[_FreshAssessment, ...], BeforeValidator(_require_tuple)]
    shared_admission_digest_sha256: _Sha256Hex
    methods: Annotated[tuple[_FreshSemanticMethod, ...], BeforeValidator(_require_tuple)]

    @model_validator(mode="after")
    def _validate_record(self) -> "AgentMarketBenchFinalSemanticRecordV1":
        if self.adversarial_scenarios != tuple(
            sorted(self.adversarial_scenarios, key=lambda scenario: scenario.value)
        ):
            raise ValueError("adversarial scenarios must be normalized by scenario value")
        if len(set(self.adversarial_scenarios)) != len(self.adversarial_scenarios):
            raise ValueError("adversarial scenarios must be unique")
        if tuple(assessment.scenario for assessment in self.scenario_assessments) != (
            self.adversarial_scenarios
        ):
            raise ValueError("scenario assessment scenarios must equal adversarial scenarios")
        if tuple(method.method for method in self.methods) != tuple(AgentMarketBenchBaselineV1):
            raise ValueError("semantic methods must contain all nine baselines in enum order")
        return self


class AgentMarketBenchFinalTimingMethodV1(BaseModel):
    """One method's observational elapsed time."""

    model_config = _CONFIG

    method: _ExactBaseline
    elapsed_ns: Annotated[int, Field(strict=True, ge=0)]


_FreshTimingMethod = Annotated[
    AgentMarketBenchFinalTimingMethodV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchFinalTimingMethodV1, value)),
]


class AgentMarketBenchFinalTimingRecordV1(BaseModel):
    """Environment-sensitive timings isolated from semantic evidence."""

    model_config = _CONFIG

    schema_version: Literal["1"] = "1"
    agent_market_bench_final_timing_record_version: Literal[
        "agent-market-bench-final-timing-record-v1"
    ] = "agent-market-bench-final-timing-record-v1"
    seed: Annotated[int, Field(strict=True, ge=0, le=MAX_AGENT_MARKET_BENCH_SEED)]
    case_digest_sha256: _Sha256Hex
    timings: Annotated[tuple[_FreshTimingMethod, ...], BeforeValidator(_require_tuple)]

    @model_validator(mode="after")
    def _validate_timings(self) -> "AgentMarketBenchFinalTimingRecordV1":
        if tuple(timing.method for timing in self.timings) != tuple(AgentMarketBenchBaselineV1):
            raise ValueError("timings must contain all nine baselines in enum order")
        return self


class AgentMarketBenchFinalMethodStatusCountV1(BaseModel):
    model_config = _CONFIG

    method: _ExactBaseline
    status: _ExactMethodStatus
    count: Annotated[int, Field(strict=True, ge=0)]


_FreshMethodStatusCount = Annotated[
    AgentMarketBenchFinalMethodStatusCountV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchFinalMethodStatusCountV1, value)),
]


class AgentMarketBenchFinalScenarioCountV1(BaseModel):
    model_config = _CONFIG

    scenario: _ExactScenario
    count: Annotated[int, Field(strict=True, ge=0)]


_FreshScenarioCount = Annotated[
    AgentMarketBenchFinalScenarioCountV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchFinalScenarioCountV1, value)),
]


class AgentMarketBenchFinalScenarioAssessmentCountV1(BaseModel):
    model_config = _CONFIG

    scenario: _ExactScenario
    classification: _ExactClassification
    evidence_basis: _ExactBasis
    count: Annotated[int, Field(strict=True, ge=0)]


_FreshScenarioAssessmentCount = Annotated[
    AgentMarketBenchFinalScenarioAssessmentCountV1,
    BeforeValidator(
        lambda value: _fresh_exact(AgentMarketBenchFinalScenarioAssessmentCountV1, value)
    ),
]


class AgentMarketBenchFinalSummaryV1(BaseModel):
    """Neutral final aggregates over compact evidence."""

    model_config = _CONFIG

    schema_version: Literal["1"] = "1"
    agent_market_bench_final_summary_version: Literal["agent-market-bench-final-summary-v1"] = (
        "agent-market-bench-final-summary-v1"
    )
    evaluated_source_commit: _GitSha
    case_count: Annotated[int, Field(strict=True, ge=1)]
    seed_sequence_sha256: _Sha256Hex
    standard_case_count: Annotated[int, Field(strict=True, ge=0)]
    method_status_counts: Annotated[
        tuple[_FreshMethodStatusCount, ...], BeforeValidator(_require_tuple)
    ]
    scenario_counts: Annotated[tuple[_FreshScenarioCount, ...], BeforeValidator(_require_tuple)]
    scenario_assessment_counts: Annotated[
        tuple[_FreshScenarioAssessmentCount, ...], BeforeValidator(_require_tuple)
    ]
    run_summary: _FreshRunSummary

    @model_validator(mode="after")
    def _validate_counts(self) -> "AgentMarketBenchFinalSummaryV1":
        expected_statuses = tuple(
            (method, status)
            for method in AgentMarketBenchBaselineV1
            for status in AgentMarketBenchMethodStatusV1
        )
        actual_statuses = tuple((item.method, item.status) for item in self.method_status_counts)
        if actual_statuses != expected_statuses:
            raise ValueError("method status counts must contain exact 9x3 enum-order coverage")
        for method in AgentMarketBenchBaselineV1:
            if sum(item.count for item in self.method_status_counts if item.method is method) != (
                self.case_count
            ):
                raise ValueError("method status counts must sum to case_count for every method")
        expected_scenarios = tuple(
            sorted(AgentMarketBenchAdversarialScenarioV1, key=lambda scenario: scenario.value)
        )
        if tuple(item.scenario for item in self.scenario_counts) != expected_scenarios:
            raise ValueError("scenario counts must contain every scenario in normalized order")
        if self.standard_case_count + sum(item.count for item in self.scenario_counts) != (
            self.case_count
        ):
            raise ValueError("standard and scenario counts must sum to case_count")
        assessment_keys = tuple(
            (item.scenario.value, item.classification.value, item.evidence_basis.value)
            for item in self.scenario_assessment_counts
        )
        if assessment_keys != tuple(sorted(set(assessment_keys))):
            raise ValueError("scenario assessment counts must be unique and normalized")
        if any(item.count <= 0 for item in self.scenario_assessment_counts):
            raise ValueError("scenario assessment counts must include only observed combinations")
        if self.run_summary.case_count != self.case_count:
            raise ValueError("run summary case_count must equal final case_count")
        return self


class AgentMarketBenchFinalEvidenceFileKindV1(StrEnum):
    SEMANTIC_SHARD = "SEMANTIC_SHARD"
    TIMING_SHARD = "TIMING_SHARD"
    SUMMARY = "SUMMARY"
    REPORT = "REPORT"
    RUN_METADATA = "RUN_METADATA"


_ExactFileKind = Annotated[
    AgentMarketBenchFinalEvidenceFileKindV1,
    BeforeValidator(lambda value: _exact_enum(AgentMarketBenchFinalEvidenceFileKindV1, value)),
]


class AgentMarketBenchFinalEvidenceFileV1(BaseModel):
    """One manifest entry for a non-manifest evidence file."""

    model_config = _CONFIG

    relative_path: _RelativePath
    kind: _ExactFileKind
    sha256: _Sha256Hex
    byte_count: Annotated[int, Field(strict=True, ge=0)]
    line_count: Annotated[int, Field(strict=True, ge=0)]
    uncompressed_sha256: _Sha256Hex | None
    first_seed: Annotated[int, Field(strict=True, ge=0, le=MAX_AGENT_MARKET_BENCH_SEED)] | None
    last_seed: Annotated[int, Field(strict=True, ge=0, le=MAX_AGENT_MARKET_BENCH_SEED)] | None

    @model_validator(mode="after")
    def _validate_shape(self) -> "AgentMarketBenchFinalEvidenceFileV1":
        is_shard = self.kind in {
            AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD,
            AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD,
        }
        if is_shard:
            if self.uncompressed_sha256 is None:
                raise ValueError("shard requires an uncompressed SHA-256")
            if self.first_seed is None or self.last_seed is None:
                raise ValueError("shard requires first and last seed")
            if self.line_count < 1 or self.first_seed > self.last_seed:
                raise ValueError("shard line and seed metadata are invalid")
        elif (
            self.uncompressed_sha256 is not None
            or self.first_seed is not None
            or self.last_seed is not None
        ):
            raise ValueError("non-shard files cannot have uncompressed or seed metadata")
        return self


_FreshEvidenceFile = Annotated[
    AgentMarketBenchFinalEvidenceFileV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchFinalEvidenceFileV1, value)),
]


class AgentMarketBenchFinalRunMetadataV1(BaseModel):
    """Observational environment metadata, separate from semantic reproducibility."""

    model_config = _CONFIG

    schema_version: Literal["1"] = "1"
    agent_market_bench_final_run_metadata_version: Literal[
        "agent-market-bench-final-run-metadata-v1"
    ] = "agent-market-bench-final-run-metadata-v1"
    evaluated_source_commit: _GitSha
    started_at_utc: _UtcTimestamp
    completed_at_utc: _UtcTimestamp
    python_version: str
    platform_system: str
    platform_machine: str
    pydantic_version: str
    ortools_version: str
    cryptography_version: str
    clock_name: Literal["time.perf_counter_ns"] = "time.perf_counter_ns"

    @model_validator(mode="after")
    def _validate_timestamps_and_text(self) -> "AgentMarketBenchFinalRunMetadataV1":
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("completion timestamp must not precede start timestamp")
        for field_name in (
            "python_version",
            "platform_system",
            "platform_machine",
            "pydantic_version",
            "ortools_version",
            "cryptography_version",
        ):
            value = getattr(self, field_name)
            if type(value) is not str or not value or "\x00" in value or "\n" in value:
                raise ValueError(f"{field_name} must be a non-empty single-line string")
        return self


class AgentMarketBenchFinalManifestV1(BaseModel):
    """Completed evidence inventory; manifest.json itself is intentionally excluded."""

    model_config = _CONFIG

    schema_version: Literal["1"] = "1"
    agent_market_bench_final_manifest_version: Literal["agent-market-bench-final-manifest-v1"] = (
        "agent-market-bench-final-manifest-v1"
    )
    evidence_version: Literal["agent-market-bench-final-evidence-v1"] = (
        "agent-market-bench-final-evidence-v1"
    )
    evaluated_source_commit: _GitSha
    generator_version: Literal["agent-market-bench-generator-v1"] = (
        "agent-market-bench-generator-v1"
    )
    runner_version: Literal["agent-market-bench-runner-v1"] = "agent-market-bench-runner-v1"
    metrics_version: Literal["agent-market-bench-metrics-v1"] = "agent-market-bench-metrics-v1"
    statistics_version: Literal["agent-market-bench-statistics-v1"] = (
        "agent-market-bench-statistics-v1"
    )
    case_count: Annotated[int, Field(strict=True, ge=1)]
    first_seed: Annotated[int, Field(strict=True, ge=0, le=MAX_AGENT_MARKET_BENCH_SEED)]
    last_seed: Annotated[int, Field(strict=True, ge=0, le=MAX_AGENT_MARKET_BENCH_SEED)]
    seed_sequence_sha256: _Sha256Hex
    shard_size: Annotated[int, Field(strict=True, ge=1)] = 500
    semantic_shard_count: Annotated[int, Field(strict=True, ge=1)] = 20
    timing_shard_count: Annotated[int, Field(strict=True, ge=1)] = 20
    semantic_root_sha256: _Sha256Hex
    timing_root_sha256: _Sha256Hex
    evidence_root_sha256: _Sha256Hex
    files: Annotated[tuple[_FreshEvidenceFile, ...], BeforeValidator(_require_tuple)]

    @model_validator(mode="after")
    def _validate_manifest(self) -> "AgentMarketBenchFinalManifestV1":
        if self.first_seed > self.last_seed:
            raise ValueError("first_seed must not exceed last_seed")
        paths = tuple(item.relative_path for item in self.files)
        if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
            raise ValueError("manifest files must have unique relative paths in sorted order")
        semantic_count = sum(
            item.kind is AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD
            for item in self.files
        )
        timing_count = sum(
            item.kind is AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD for item in self.files
        )
        if semantic_count != self.semantic_shard_count or timing_count != self.timing_shard_count:
            raise ValueError("manifest shard counts must match file coverage")
        singleton_kinds = (
            AgentMarketBenchFinalEvidenceFileKindV1.SUMMARY,
            AgentMarketBenchFinalEvidenceFileKindV1.REPORT,
            AgentMarketBenchFinalEvidenceFileKindV1.RUN_METADATA,
        )
        if any(sum(item.kind is kind for item in self.files) != 1 for kind in singleton_kinds):
            raise ValueError("manifest must contain one summary, report, and run metadata file")
        if self.case_count == 10_000:
            if (
                self.shard_size != 500
                or self.semantic_shard_count != 20
                or self.timing_shard_count != 20
                or len(self.files) != 43
            ):
                raise ValueError("completed final manifest requires exact 500x20 shard coverage")
            shard_files = tuple(
                item
                for item in self.files
                if item.kind
                in {
                    AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD,
                    AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD,
                }
            )
            if any(item.line_count != 500 for item in shard_files):
                raise ValueError("completed final shard line_count must equal 500")
        return self


__all__ = (  # noqa: RUF022
    "AGENT_MARKET_BENCH_FINAL_EVIDENCE_V1_VERSION",
    "AGENT_MARKET_BENCH_FINAL_SEMANTIC_RECORD_V1_VERSION",
    "AGENT_MARKET_BENCH_FINAL_TIMING_RECORD_V1_VERSION",
    "AGENT_MARKET_BENCH_FINAL_SUMMARY_V1_VERSION",
    "AGENT_MARKET_BENCH_FINAL_MANIFEST_V1_VERSION",
    "AGENT_MARKET_BENCH_FINAL_RUN_METADATA_V1_VERSION",
    "AgentMarketBenchFinalSemanticMethodV1",
    "AgentMarketBenchFinalSemanticRecordV1",
    "AgentMarketBenchFinalTimingMethodV1",
    "AgentMarketBenchFinalTimingRecordV1",
    "AgentMarketBenchFinalMethodStatusCountV1",
    "AgentMarketBenchFinalScenarioCountV1",
    "AgentMarketBenchFinalScenarioAssessmentCountV1",
    "AgentMarketBenchFinalSummaryV1",
    "AgentMarketBenchFinalEvidenceFileKindV1",
    "AgentMarketBenchFinalEvidenceFileV1",
    "AgentMarketBenchFinalRunMetadataV1",
    "AgentMarketBenchFinalManifestV1",
)


AGENT_MARKET_BENCH_REPLACEMENT_FINAL_EVIDENCE_V1_VERSION: Final[str] = (
    "agent-market-bench-replacement-final-evidence-v1"
)
AGENT_MARKET_BENCH_REPLACEMENT_FINAL_SUMMARY_V1_VERSION: Final[str] = (
    "agent-market-bench-replacement-final-summary-v1"
)
AGENT_MARKET_BENCH_REPLACEMENT_FINAL_MANIFEST_V1_VERSION: Final[str] = (
    "agent-market-bench-replacement-final-manifest-v1"
)
AGENT_MARKET_BENCH_REPLACEMENT_FINAL_RUN_METADATA_V1_VERSION: Final[str] = (
    "agent-market-bench-replacement-final-run-metadata-v1"
)


def _validate_replacement_final_selection_v1(anchor_commit: str, selection_sha256: str) -> None:
    from clear_market.agentmarketbench.seeds import (
        AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1,
        AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1,
    )

    if anchor_commit != AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1:
        raise ValueError("replacement selection anchor must equal the frozen R1 commit")
    if selection_sha256 != AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1:
        raise ValueError("replacement selection SHA-256 must equal the frozen selection digest")


class AgentMarketBenchReplacementFinalSummaryV1(BaseModel):
    """Neutral replacement aggregates bound to the repaired semantics and selection."""

    model_config = _CONFIG

    schema_version: Literal["1"] = "1"
    agent_market_bench_replacement_final_summary_version: Literal[
        "agent-market-bench-replacement-final-summary-v1"
    ] = "agent-market-bench-replacement-final-summary-v1"
    evaluated_source_commit: _GitSha
    metric_semantics_version: Literal["agent-market-bench-metric-semantics-v1.1"] = (
        "agent-market-bench-metric-semantics-v1.1"
    )
    selection_version: Literal["agent-market-bench-replacement-holdout-selection-v1"] = (
        "agent-market-bench-replacement-holdout-selection-v1"
    )
    selection_anchor_commit: _GitSha
    selection_sha256: _Sha256Hex
    case_count: Annotated[int, Field(strict=True, ge=1)]
    seed_sequence_sha256: _Sha256Hex
    standard_case_count: Annotated[int, Field(strict=True, ge=0)]
    method_status_counts: Annotated[
        tuple[_FreshMethodStatusCount, ...], BeforeValidator(_require_tuple)
    ]
    scenario_counts: Annotated[tuple[_FreshScenarioCount, ...], BeforeValidator(_require_tuple)]
    scenario_assessment_counts: Annotated[
        tuple[_FreshScenarioAssessmentCount, ...], BeforeValidator(_require_tuple)
    ]
    run_summary: _FreshRunSummary

    @model_validator(mode="after")
    def _validate_selection(self) -> "AgentMarketBenchReplacementFinalSummaryV1":
        _validate_replacement_final_selection_v1(
            self.selection_anchor_commit, self.selection_sha256
        )
        return self

    @model_validator(mode="after")
    def _validate_counts(self) -> "AgentMarketBenchReplacementFinalSummaryV1":
        expected_statuses = tuple(
            (method, status)
            for method in AgentMarketBenchBaselineV1
            for status in AgentMarketBenchMethodStatusV1
        )
        actual_statuses = tuple((item.method, item.status) for item in self.method_status_counts)
        if actual_statuses != expected_statuses:
            raise ValueError("method status counts must contain exact 9x3 enum-order coverage")
        for method in AgentMarketBenchBaselineV1:
            if sum(item.count for item in self.method_status_counts if item.method is method) != (
                self.case_count
            ):
                raise ValueError("method status counts must sum to case_count for every method")
        expected_scenarios = tuple(
            sorted(AgentMarketBenchAdversarialScenarioV1, key=lambda scenario: scenario.value)
        )
        if tuple(item.scenario for item in self.scenario_counts) != expected_scenarios:
            raise ValueError("scenario counts must contain every scenario in normalized order")
        if self.standard_case_count + sum(item.count for item in self.scenario_counts) != (
            self.case_count
        ):
            raise ValueError("standard and scenario counts must sum to case_count")
        assessment_keys = tuple(
            (item.scenario.value, item.classification.value, item.evidence_basis.value)
            for item in self.scenario_assessment_counts
        )
        if assessment_keys != tuple(sorted(set(assessment_keys))):
            raise ValueError("scenario assessment counts must be unique and normalized")
        if any(item.count <= 0 for item in self.scenario_assessment_counts):
            raise ValueError("scenario assessment counts must include only observed combinations")
        if self.run_summary.case_count != self.case_count:
            raise ValueError("run summary case_count must equal final case_count")
        return self


class AgentMarketBenchReplacementFinalRunMetadataV1(BaseModel):
    """Private-host-free environment metadata for the frozen replacement protocol."""

    model_config = _CONFIG

    schema_version: Literal["1"] = "1"
    agent_market_bench_replacement_final_run_metadata_version: Literal[
        "agent-market-bench-replacement-final-run-metadata-v1"
    ] = "agent-market-bench-replacement-final-run-metadata-v1"
    evaluated_source_commit: _GitSha
    metric_semantics_version: Literal["agent-market-bench-metric-semantics-v1.1"] = (
        "agent-market-bench-metric-semantics-v1.1"
    )
    selection_version: Literal["agent-market-bench-replacement-holdout-selection-v1"] = (
        "agent-market-bench-replacement-holdout-selection-v1"
    )
    selection_anchor_commit: _GitSha
    selection_sha256: _Sha256Hex
    started_at_utc: _UtcTimestamp
    completed_at_utc: _UtcTimestamp
    python_version: str
    platform_system: str
    platform_machine: str
    pydantic_version: str
    ortools_version: str
    cryptography_version: str
    clock_name: Literal["time.perf_counter_ns"] = "time.perf_counter_ns"

    @model_validator(mode="after")
    def _validate_selection(self) -> "AgentMarketBenchReplacementFinalRunMetadataV1":
        _validate_replacement_final_selection_v1(
            self.selection_anchor_commit, self.selection_sha256
        )
        return self

    @model_validator(mode="after")
    def _validate_timestamps_and_text(self) -> "AgentMarketBenchReplacementFinalRunMetadataV1":
        if self.completed_at_utc < self.started_at_utc:
            raise ValueError("completion timestamp must not precede start timestamp")
        for field_name in (
            "python_version",
            "platform_system",
            "platform_machine",
            "pydantic_version",
            "ortools_version",
            "cryptography_version",
        ):
            value = getattr(self, field_name)
            if type(value) is not str or not value or "\x00" in value or "\n" in value:
                raise ValueError(f"{field_name} must be a non-empty single-line string")
        return self


class AgentMarketBenchReplacementFinalManifestV1(BaseModel):
    """Exactly one completed frozen replacement holdout's non-manifest inventory."""

    model_config = _CONFIG

    schema_version: Literal["1"] = "1"
    agent_market_bench_replacement_final_manifest_version: Literal[
        "agent-market-bench-replacement-final-manifest-v1"
    ] = "agent-market-bench-replacement-final-manifest-v1"
    evidence_version: Literal["agent-market-bench-replacement-final-evidence-v1"] = (
        "agent-market-bench-replacement-final-evidence-v1"
    )
    evaluated_source_commit: _GitSha
    generator_version: Literal["agent-market-bench-generator-v1"] = (
        "agent-market-bench-generator-v1"
    )
    runner_version: Literal["agent-market-bench-runner-v1"] = "agent-market-bench-runner-v1"
    metrics_version: Literal["agent-market-bench-metrics-v1"] = "agent-market-bench-metrics-v1"
    metric_semantics_version: Literal["agent-market-bench-metric-semantics-v1.1"] = (
        "agent-market-bench-metric-semantics-v1.1"
    )
    statistics_version: Literal["agent-market-bench-statistics-v1"] = (
        "agent-market-bench-statistics-v1"
    )
    semantic_record_version: Literal["agent-market-bench-final-semantic-record-v1"] = (
        "agent-market-bench-final-semantic-record-v1"
    )
    timing_record_version: Literal["agent-market-bench-final-timing-record-v1"] = (
        "agent-market-bench-final-timing-record-v1"
    )
    selection_version: Literal["agent-market-bench-replacement-holdout-selection-v1"] = (
        "agent-market-bench-replacement-holdout-selection-v1"
    )
    selection_anchor_commit: _GitSha
    selection_sha256: _Sha256Hex
    case_count: Annotated[int, Field(strict=True, ge=10_000, le=10_000)]
    first_seed: Annotated[int, Field(strict=True, ge=0, le=MAX_AGENT_MARKET_BENCH_SEED)]
    last_seed: Annotated[int, Field(strict=True, ge=0, le=MAX_AGENT_MARKET_BENCH_SEED)]
    seed_sequence_sha256: _Sha256Hex
    shard_size: Annotated[int, Field(strict=True, ge=500, le=500)] = 500
    semantic_shard_count: Annotated[int, Field(strict=True, ge=20, le=20)] = 20
    timing_shard_count: Annotated[int, Field(strict=True, ge=20, le=20)] = 20
    semantic_root_sha256: _Sha256Hex
    timing_root_sha256: _Sha256Hex
    evidence_root_sha256: _Sha256Hex
    files: Annotated[tuple[_FreshEvidenceFile, ...], BeforeValidator(_require_tuple)]

    @model_validator(mode="after")
    def _validate_manifest(self) -> "AgentMarketBenchReplacementFinalManifestV1":
        from clear_market.agentmarketbench.seeds import (
            AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEED_SEQUENCE_SHA256_V1,
            AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1,
        )

        _validate_replacement_final_selection_v1(
            self.selection_anchor_commit, self.selection_sha256
        )
        seeds = AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1
        if self.first_seed != seeds[0] or self.last_seed != seeds[-1]:
            raise ValueError("replacement manifest must bind the exact frozen first and last seed")
        if self.seed_sequence_sha256 != (
            AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEED_SEQUENCE_SHA256_V1
        ):
            raise ValueError("replacement manifest must bind the frozen seed-sequence SHA-256")
        expected_files = {
            "summary.json": AgentMarketBenchFinalEvidenceFileKindV1.SUMMARY,
            "report.md": AgentMarketBenchFinalEvidenceFileKindV1.REPORT,
            "run_metadata.json": AgentMarketBenchFinalEvidenceFileKindV1.RUN_METADATA,
        }
        shard_kinds = (
            ("semantic", AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD),
            ("timing", AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD),
        )
        for directory, kind in shard_kinds:
            for index in range(20):
                expected_files[f"{directory}/part-{index:05d}.jsonl.gz"] = kind
        paths = tuple(item.relative_path for item in self.files)
        if paths != tuple(sorted(expected_files)):
            raise ValueError(
                "replacement manifest requires exactly 43 frozen paths in sorted order"
            )
        for item in self.files:
            if item.kind is not expected_files[item.relative_path]:
                raise ValueError(
                    "replacement manifest file kind must match its frozen relative path"
                )
        files_by_path = {item.relative_path: item for item in self.files}
        for directory, _ in shard_kinds:
            for index in range(20):
                item = files_by_path[f"{directory}/part-{index:05d}.jsonl.gz"]
                if item.line_count != 500:
                    raise ValueError("completed replacement shard line_count must equal 500")
                start = index * 500
                if item.first_seed != seeds[start] or item.last_seed != seeds[start + 499]:
                    raise ValueError(
                        "replacement shard must bind its exact consecutive seed bounds"
                    )
        return self


# Preserve the historical export tuple above without changing its inferred fixed-length type.
__all__ += (  # type: ignore[assignment]
    "AGENT_MARKET_BENCH_REPLACEMENT_FINAL_EVIDENCE_V1_VERSION",
    "AGENT_MARKET_BENCH_REPLACEMENT_FINAL_MANIFEST_V1_VERSION",
    "AGENT_MARKET_BENCH_REPLACEMENT_FINAL_RUN_METADATA_V1_VERSION",
    "AGENT_MARKET_BENCH_REPLACEMENT_FINAL_SUMMARY_V1_VERSION",
    "AgentMarketBenchReplacementFinalManifestV1",
    "AgentMarketBenchReplacementFinalRunMetadataV1",
    "AgentMarketBenchReplacementFinalSummaryV1",
)
