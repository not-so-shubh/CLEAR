"""Canonical compact transport, streaming summaries, and evidence verification."""

import gzip
import json
import os
import platform
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from fractions import Fraction
from hashlib import sha256
from importlib.metadata import version as package_version
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import cryptography
import pydantic
from pydantic import BaseModel

from clear_market.agentmarketbench.final_models import (
    AGENT_MARKET_BENCH_FINAL_EVIDENCE_V1_VERSION,
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
from clear_market.agentmarketbench.measurement_models import (
    AGENT_MARKET_BENCH_METRICS_V1_VERSION,
    AGENT_MARKET_BENCH_RUNNER_V1_VERSION,
    AGENT_MARKET_BENCH_STATISTICS_V1_VERSION,
    AgentMarketBenchCaseRunV1,
    AgentMarketBenchMetricNotApplicableReasonV1,
    AgentMarketBenchMetricObservationStatusV1,
    AgentMarketBenchMetricObservationV1,
    AgentMarketBenchMetricSummaryV1,
    AgentMarketBenchMetricUnitV1,
    AgentMarketBenchPairedSummaryV1,
    AgentMarketBenchRationalV1,
    AgentMarketBenchRunSummaryV1,
    AgentMarketBenchScenarioAssessmentV1,
    AgentMarketBenchScenarioEvidenceBasisV1,
)
from clear_market.agentmarketbench.method_models import (
    AgentMarketBenchAdmissionV1,
    AgentMarketBenchMethodResultV1,
    AgentMarketBenchMethodStatusV1,
)
from clear_market.agentmarketbench.models import (
    AGENT_MARKET_BENCH_GENERATOR_V1_VERSION,
    AgentMarketBenchAdversarialClassificationV1,
    AgentMarketBenchAdversarialScenarioV1,
    AgentMarketBenchBaselineV1,
    AgentMarketBenchMetricV1,
)

_Z95 = Decimal("1.95996398454005423552")
_QUANTUM = Decimal("0.000000000001")
_METRIC_UNITS = {
    AgentMarketBenchMetricV1.ALLOCATIVE_EFFICIENCY: AgentMarketBenchMetricUnitV1.RATIO,
    AgentMarketBenchMetricV1.REGRET: AgentMarketBenchMetricUnitV1.PAISE,
    AgentMarketBenchMetricV1.BUYER_SURPLUS: AgentMarketBenchMetricUnitV1.PAISE,
    AgentMarketBenchMetricV1.MERCHANT_SURPLUS: AgentMarketBenchMetricUnitV1.PAISE,
    AgentMarketBenchMetricV1.WELFARE: AgentMarketBenchMetricUnitV1.PAISE,
    AgentMarketBenchMetricV1.COMPLETION: AgentMarketBenchMetricUnitV1.RATIO,
    AgentMarketBenchMetricV1.HARD_CONSTRAINT_VIOLATIONS: AgentMarketBenchMetricUnitV1.COUNT,
    AgentMarketBenchMetricV1.MANIPULATION_SUCCESS: AgentMarketBenchMetricUnitV1.BINARY,
    AgentMarketBenchMetricV1.PAYMENT_CORRECTNESS: AgentMarketBenchMetricUnitV1.BINARY,
    AgentMarketBenchMetricV1.DUPLICATE_FINANCIAL_SIDE_EFFECTS: (AgentMarketBenchMetricUnitV1.COUNT),
    AgentMarketBenchMetricV1.LATENCY: AgentMarketBenchMetricUnitV1.NANOSECONDS,
}


def _fresh_exact[ModelT: BaseModel](model_type: type[ModelT], value: object) -> ModelT:
    if type(value) is not model_type:
        raise TypeError(f"value must be exactly {model_type.__name__}")
    try:
        raw = {field_name: getattr(value, field_name) for field_name in model_type.model_fields}
        return model_type.model_validate(raw)
    except Exception as error:
        raise ValueError(f"{model_type.__name__} failed fresh validation") from error


def canonical_agent_market_bench_final_json_v1_bytes(value: BaseModel) -> bytes:
    """Return sorted compact UTF-8 model JSON with exactly one trailing newline."""

    if not isinstance(value, BaseModel):
        raise TypeError("value must be a Pydantic BaseModel instance")
    fresh = _fresh_exact(type(value), value)
    text = json.dumps(
        fresh.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (text + "\n").encode("utf-8")


def agent_market_bench_final_method_result_digest_v1(
    result: AgentMarketBenchMethodResultV1,
) -> str:
    """Digest the complete frozen method-result model."""

    fresh = _fresh_exact(AgentMarketBenchMethodResultV1, result)
    return sha256(canonical_agent_market_bench_final_json_v1_bytes(fresh)).hexdigest()


def agent_market_bench_final_admission_digest_v1(admission: AgentMarketBenchAdmissionV1) -> str:
    """Digest complete shared-admission evidence."""

    fresh = _fresh_exact(AgentMarketBenchAdmissionV1, admission)
    return sha256(canonical_agent_market_bench_final_json_v1_bytes(fresh)).hexdigest()


def agent_market_bench_final_seed_sequence_digest_v1(seeds: tuple[int, ...]) -> str:
    """Digest exact ASCII seed lines in their supplied order."""

    if type(seeds) is not tuple:
        raise TypeError("seeds must be supplied as a tuple")
    if not seeds or any(type(seed) is not int or seed < 0 for seed in seeds):
        raise ValueError("seeds must be a non-empty tuple of nonnegative exact ints")
    payload = b"".join(str(seed).encode("ascii") + b"\n" for seed in seeds)
    return sha256(payload).hexdigest()


def compact_agent_market_bench_case_run_v1(
    case_run: AgentMarketBenchCaseRunV1,
) -> tuple[AgentMarketBenchFinalSemanticRecordV1, AgentMarketBenchFinalTimingRecordV1]:
    """Separate one validated 24D case run into semantic and timing evidence."""

    fresh = _fresh_exact(AgentMarketBenchCaseRunV1, case_run)
    admissions = tuple(evaluation.result.admission for evaluation in fresh.evaluations)
    if len(set(admissions)) != 1:
        raise ValueError("all method results must share exactly equal admission evidence")
    admission_digest = agent_market_bench_final_admission_digest_v1(admissions[0])
    semantic_methods = []
    timing_methods = []
    for evaluation in fresh.evaluations:
        semantic_metrics = tuple(
            observation
            for observation in evaluation.metrics
            if observation.metric is not AgentMarketBenchMetricV1.LATENCY
        )
        semantic_methods.append(
            AgentMarketBenchFinalSemanticMethodV1(
                method=evaluation.method,
                result_status=evaluation.result.status,
                result_digest_sha256=agent_market_bench_final_method_result_digest_v1(
                    evaluation.result
                ),
                fulfilled_quantity=evaluation.result.fulfilled_quantity,
                total_payment_paise=evaluation.result.total_payment.amount_paise,
                winner_count=evaluation.result.winner_count,
                realized_quantity=evaluation.realized_quantity,
                latent_capacity_excess_units=evaluation.latent_capacity_excess_units,
                latent_hard_violation_units=evaluation.latent_hard_violation_units,
                metrics=semantic_metrics,
            )
        )
        timing_methods.append(
            AgentMarketBenchFinalTimingMethodV1(
                method=evaluation.method,
                elapsed_ns=evaluation.elapsed_ns,
            )
        )
    scenarios = tuple(assessment.scenario for assessment in fresh.scenario_assessments)
    semantic = AgentMarketBenchFinalSemanticRecordV1(
        seed=fresh.seed,
        case_id=fresh.case_id,
        case_digest_sha256=fresh.case_digest_sha256,
        adversarial_scenarios=scenarios,
        scenario_assessments=fresh.scenario_assessments,
        shared_admission_digest_sha256=admission_digest,
        methods=tuple(semantic_methods),
    )
    timing = AgentMarketBenchFinalTimingRecordV1(
        seed=fresh.seed,
        case_digest_sha256=fresh.case_digest_sha256,
        timings=tuple(timing_methods),
    )
    return semantic, timing


@dataclass
class _MetricSufficientStatisticsV1:
    measured_count: int = 0
    not_applicable_count: int = 0
    sum_value: Fraction = Fraction(0)


@dataclass
class _PairedSufficientStatisticsV1:
    count: int = 0
    sum_value: Fraction = Fraction(0)
    sum_squared: Fraction = Fraction(0)


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


def _ci95_from_sufficient_statistics(
    state: _PairedSufficientStatisticsV1,
) -> tuple[str | None, str | None]:
    if state.count < 2:
        return None, None
    count = state.count
    mean = state.sum_value / count
    variance = (state.sum_squared - state.sum_value**2 / count) / (count - 1)
    if variance < 0:
        raise ValueError("paired sufficient statistics produced negative variance")
    with localcontext() as context:
        context.prec = 80
        standard_error = (
            Decimal(variance.numerator) / Decimal(variance.denominator) / count
        ).sqrt()
        half_width = _Z95 * standard_error
        lower = _decimal(mean) - half_width
        upper = _decimal(mean) + half_width
    return _decimal_string(lower), _decimal_string(upper)


class AgentMarketBenchFinalStreamingAccumulatorV1:
    """Exact one-record-at-a-time 24D-equivalent summary accumulator."""

    def __init__(self) -> None:
        self._case_count = 0
        self._case_digests: set[str] = set()
        self._metrics = {
            (method, metric): _MetricSufficientStatisticsV1()
            for method in AgentMarketBenchBaselineV1
            for metric in AgentMarketBenchMetricV1
        }
        self._pairs = {
            (method, metric): _PairedSufficientStatisticsV1()
            for method in AgentMarketBenchBaselineV1
            if method is not AgentMarketBenchBaselineV1.CLEAR
            for metric in AgentMarketBenchMetricV1
        }
        self._method_statuses: Counter[
            tuple[AgentMarketBenchBaselineV1, AgentMarketBenchMethodStatusV1]
        ] = Counter()
        self._scenario_counts: Counter[AgentMarketBenchAdversarialScenarioV1] = Counter()
        self._assessment_counts: Counter[
            tuple[
                AgentMarketBenchAdversarialScenarioV1,
                AgentMarketBenchAdversarialClassificationV1,
                AgentMarketBenchScenarioEvidenceBasisV1,
            ]
        ] = Counter()
        self._standard_case_count = 0

    @property
    def case_count(self) -> int:
        return self._case_count

    @staticmethod
    def _observation(
        semantic_method: AgentMarketBenchFinalSemanticMethodV1,
        timing_method: AgentMarketBenchFinalTimingMethodV1,
        metric: AgentMarketBenchMetricV1,
    ) -> tuple[
        AgentMarketBenchMetricObservationStatusV1,
        AgentMarketBenchMetricUnitV1,
        Fraction | None,
    ]:
        if metric is AgentMarketBenchMetricV1.LATENCY:
            return (
                AgentMarketBenchMetricObservationStatusV1.MEASURED,
                AgentMarketBenchMetricUnitV1.NANOSECONDS,
                Fraction(timing_method.elapsed_ns),
            )
        observation = next(item for item in semantic_method.metrics if item.metric is metric)
        value = (
            None
            if observation.value is None
            else Fraction(observation.value.numerator, observation.value.denominator)
        )
        return observation.status, observation.unit, value

    def add(
        self,
        semantic_record: AgentMarketBenchFinalSemanticRecordV1,
        timing_record: AgentMarketBenchFinalTimingRecordV1,
    ) -> None:
        semantic = _fresh_exact(AgentMarketBenchFinalSemanticRecordV1, semantic_record)
        timing = _fresh_exact(AgentMarketBenchFinalTimingRecordV1, timing_record)
        if semantic.seed != timing.seed or semantic.case_digest_sha256 != timing.case_digest_sha256:
            raise ValueError("semantic and timing records must identify the same case")
        if semantic.case_digest_sha256 in self._case_digests:
            raise ValueError("case digests must be unique in streaming evidence")
        if len(semantic.adversarial_scenarios) > 1:
            raise ValueError("AgentMarketBench V1 evidence allows zero or one scenario per case")
        self._case_digests.add(semantic.case_digest_sha256)
        self._case_count += 1
        semantic_by_method = {item.method: item for item in semantic.methods}
        timing_by_method = {item.method: item for item in timing.timings}
        observations: dict[
            tuple[AgentMarketBenchBaselineV1, AgentMarketBenchMetricV1],
            tuple[
                AgentMarketBenchMetricObservationStatusV1,
                AgentMarketBenchMetricUnitV1,
                Fraction | None,
            ],
        ] = {}
        for method in AgentMarketBenchBaselineV1:
            semantic_method = semantic_by_method[method]
            timing_method = timing_by_method[method]
            self._method_statuses[(method, semantic_method.result_status)] += 1
            for metric in AgentMarketBenchMetricV1:
                observation = self._observation(semantic_method, timing_method, metric)
                observations[(method, metric)] = observation
                metric_state = self._metrics[(method, metric)]
                status, unit, value = observation
                if unit is not _METRIC_UNITS[metric]:
                    raise ValueError("observation unit does not match metric")
                if status is AgentMarketBenchMetricObservationStatusV1.MEASURED:
                    if value is None:
                        raise ValueError("measured observation must have a value")
                    metric_state.measured_count += 1
                    metric_state.sum_value += value
                else:
                    if value is not None:
                        raise ValueError("N/A observation cannot have a value")
                    metric_state.not_applicable_count += 1
        for comparator in AgentMarketBenchBaselineV1:
            if comparator is AgentMarketBenchBaselineV1.CLEAR:
                continue
            for metric in AgentMarketBenchMetricV1:
                comparator_status, _, comparator_value = observations[(comparator, metric)]
                clear_status, _, clear_value = observations[
                    (AgentMarketBenchBaselineV1.CLEAR, metric)
                ]
                if (
                    comparator_status is AgentMarketBenchMetricObservationStatusV1.MEASURED
                    and clear_status is AgentMarketBenchMetricObservationStatusV1.MEASURED
                ):
                    if comparator_value is None or clear_value is None:
                        raise ValueError("paired measured observations must have values")
                    difference = comparator_value - clear_value
                    pair = self._pairs[(comparator, metric)]
                    pair.count += 1
                    pair.sum_value += difference
                    pair.sum_squared += difference**2
        if semantic.adversarial_scenarios:
            self._scenario_counts[semantic.adversarial_scenarios[0]] += 1
        else:
            self._standard_case_count += 1
        for assessment in semantic.scenario_assessments:
            self._assessment_counts[
                (assessment.scenario, assessment.classification, assessment.evidence_basis)
            ] += 1

    def build_run_summary_v1(self) -> AgentMarketBenchRunSummaryV1:
        if self._case_count < 1:
            raise ValueError("cannot summarize an empty streaming accumulator")
        metric_summaries = []
        for method in AgentMarketBenchBaselineV1:
            for metric in AgentMarketBenchMetricV1:
                metric_state = self._metrics[(method, metric)]
                mean = (
                    None
                    if metric_state.measured_count == 0
                    else metric_state.sum_value / metric_state.measured_count
                )
                metric_summaries.append(
                    AgentMarketBenchMetricSummaryV1(
                        method=method,
                        metric=metric,
                        unit=_METRIC_UNITS[metric],
                        measured_count=metric_state.measured_count,
                        not_applicable_count=metric_state.not_applicable_count,
                        mean_value=None if mean is None else _rational(mean),
                    )
                )
        paired_summaries = []
        for comparator in AgentMarketBenchBaselineV1:
            if comparator is AgentMarketBenchBaselineV1.CLEAR:
                continue
            for metric in AgentMarketBenchMetricV1:
                pair_state = self._pairs[(comparator, metric)]
                mean = None if pair_state.count == 0 else pair_state.sum_value / pair_state.count
                lower, upper = _ci95_from_sufficient_statistics(pair_state)
                paired_summaries.append(
                    AgentMarketBenchPairedSummaryV1(
                        comparator=comparator,
                        metric=metric,
                        unit=_METRIC_UNITS[metric],
                        paired_count=pair_state.count,
                        mean_difference=None if mean is None else _rational(mean),
                        ci95_lower_decimal=lower,
                        ci95_upper_decimal=upper,
                    )
                )
        return AgentMarketBenchRunSummaryV1(
            case_count=self._case_count,
            metric_summaries=tuple(metric_summaries),
            paired_summaries=tuple(paired_summaries),
        )

    def build_final_summary_v1(
        self,
        *,
        evaluated_source_commit: str,
        seed_sequence_sha256: str,
    ) -> AgentMarketBenchFinalSummaryV1:
        method_status_counts = tuple(
            AgentMarketBenchFinalMethodStatusCountV1(
                method=method,
                status=status,
                count=self._method_statuses[(method, status)],
            )
            for method in AgentMarketBenchBaselineV1
            for status in AgentMarketBenchMethodStatusV1
        )
        scenario_counts = tuple(
            AgentMarketBenchFinalScenarioCountV1(
                scenario=scenario,
                count=self._scenario_counts[scenario],
            )
            for scenario in sorted(
                AgentMarketBenchAdversarialScenarioV1, key=lambda item: item.value
            )
        )
        assessment_counts = tuple(
            AgentMarketBenchFinalScenarioAssessmentCountV1(
                scenario=key[0],
                classification=key[1],
                evidence_basis=key[2],
                count=count,
            )
            for key, count in sorted(
                self._assessment_counts.items(),
                key=lambda item: tuple(value.value for value in item[0]),
            )
            if count > 0
        )
        return AgentMarketBenchFinalSummaryV1(
            evaluated_source_commit=evaluated_source_commit,
            case_count=self._case_count,
            seed_sequence_sha256=seed_sequence_sha256,
            standard_case_count=self._standard_case_count,
            method_status_counts=method_status_counts,
            scenario_counts=scenario_counts,
            scenario_assessment_counts=assessment_counts,
            run_summary=self.build_run_summary_v1(),
        )


def agent_market_bench_final_shard_content_root_digest_v1(
    files: tuple[AgentMarketBenchFinalEvidenceFileV1, ...],
    *,
    kind: AgentMarketBenchFinalEvidenceFileKindV1,
) -> str:
    """Hash uncompressed canonical shard identities independently of gzip transport."""

    if type(files) is not tuple:
        raise TypeError("files must be supplied as a tuple")
    if type(kind) is not AgentMarketBenchFinalEvidenceFileKindV1:
        raise TypeError("kind must be an exact final evidence file-kind enum")
    if kind not in {
        AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD,
        AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD,
    }:
        raise ValueError("shard content roots require a semantic or timing shard kind")
    fresh_files = tuple(_fresh_exact(AgentMarketBenchFinalEvidenceFileV1, item) for item in files)
    payload = b""
    for item in sorted(fresh_files, key=lambda value: value.relative_path):
        if item.kind is not kind:
            raise ValueError(f"shard content root requires only {kind.value} files")
        uncompressed_sha256 = item.uncompressed_sha256
        first_seed = item.first_seed
        last_seed = item.last_seed
        if uncompressed_sha256 is None or first_seed is None or last_seed is None:
            raise ValueError("shard content root requires uncompressed hash and seed metadata")
        line = (
            item.relative_path
            + "\0"
            + uncompressed_sha256
            + "\0"
            + str(item.line_count)
            + "\0"
            + str(first_seed)
            + "\0"
            + str(last_seed)
            + "\n"
        )
        payload += line.encode("ascii")
    return sha256(payload).hexdigest()


def agent_market_bench_final_evidence_root_digest_v1(
    files: tuple[AgentMarketBenchFinalEvidenceFileV1, ...],
) -> str:
    """Hash exact stored-transport identities sorted by relative path."""

    if type(files) is not tuple:
        raise TypeError("files must be supplied as a tuple")
    fresh_files = tuple(_fresh_exact(AgentMarketBenchFinalEvidenceFileV1, item) for item in files)
    payload = b""
    for item in sorted(fresh_files, key=lambda value: value.relative_path):
        line = (
            item.relative_path
            + "\0"
            + item.sha256
            + "\0"
            + (item.uncompressed_sha256 or "")
            + "\0"
            + str(item.byte_count)
            + "\0"
            + str(item.line_count)
            + "\n"
        )
        payload += line.encode("ascii")
    return sha256(payload).hexdigest()


def _rational_text(value: AgentMarketBenchRationalV1 | None) -> str:
    return "N/A" if value is None else f"{value.numerator}/{value.denominator}"


def render_agent_market_bench_final_report_v1(
    summary: AgentMarketBenchFinalSummaryV1,
    *,
    generator_version: str,
    runner_version: str,
    metrics_version: str,
    statistics_version: str,
    semantic_root_sha256: str,
    timing_root_sha256: str,
) -> str:
    """Render the frozen neutral final-report structure without interpreting outcomes."""

    fresh = _fresh_exact(AgentMarketBenchFinalSummaryV1, summary)
    lines = [
        "# AgentMarketBench V1 Final Holdout",
        "",
        f"- Evaluated source commit: `{fresh.evaluated_source_commit}`",
        f"- Generator version: `{generator_version}`",
        f"- Runner version: `{runner_version}`",
        f"- Metrics version: `{metrics_version}`",
        f"- Statistics version: `{statistics_version}`",
        f"- Final cases: {fresh.case_count}",
        f"- Frozen seed-sequence SHA-256: `{fresh.seed_sequence_sha256}`",
        f"- Semantic evidence root SHA-256: `{semantic_root_sha256}`",
        f"- Timing evidence root SHA-256: `{timing_root_sha256}`",
        "",
        "## Method status counts",
        "",
        "| Method | Status | Count |",
        "|:---|:---|---:|",
    ]
    lines.extend(
        f"| `{item.method.value}` | `{item.status.value}` | {item.count} |"
        for item in fresh.method_status_counts
    )
    lines.extend(
        [
            "",
            "## Method metric means",
            "",
            "| Method | Metric | Unit | Measured count | N/A count | Exact rational mean |",
            "|:---|:---|:---|---:|---:|:---|",
        ]
    )
    lines.extend(
        f"| `{item.method.value}` | `{item.metric.value}` | `{item.unit.value}` | "
        f"{item.measured_count} | {item.not_applicable_count} | "
        f"{_rational_text(item.mean_value)} |"
        for item in fresh.run_summary.metric_summaries
    )
    lines.extend(
        [
            "",
            "## Paired comparator-minus-CLEAR summaries",
            "",
            "Difference orientation is comparator minus CLEAR.",
            "",
            "| Comparator | Metric | Unit | Paired count | Exact rational mean difference | "
            "95% lower | 95% upper |",
            "|:---|:---|:---|---:|:---|:---|:---|",
        ]
    )
    lines.extend(
        f"| `{item.comparator.value}` | `{item.metric.value}` | `{item.unit.value}` | "
        f"{item.paired_count} | {_rational_text(item.mean_difference)} | "
        f"{item.ci95_lower_decimal or 'N/A'} | {item.ci95_upper_decimal or 'N/A'} |"
        for item in fresh.run_summary.paired_summaries
    )
    lines.extend(
        [
            "",
            "## Scenario coverage",
            "",
            f"Standard cases: {fresh.standard_case_count}",
            "",
            "| Scenario | Count |",
            "|:---|---:|",
        ]
    )
    lines.extend(f"| `{item.scenario.value}` | {item.count} |" for item in fresh.scenario_counts)
    lines.extend(
        [
            "",
            "## Scenario assessment counts",
            "",
            "| Scenario | Classification | Evidence basis | Count |",
            "|:---|:---|:---|---:|",
        ]
    )
    lines.extend(
        f"| `{item.scenario.value}` | `{item.classification.value}` | "
        f"`{item.evidence_basis.value}` | {item.count} |"
        for item in fresh.scenario_assessment_counts
    )
    lines.extend(
        [
            "",
            "## Interpretation limits",
            "",
            "- Results describe the generated synthetic distribution only.",
            "- No general V2 truthfulness or strategy-proofness claim is made.",
            "- No Sybil prevention claim is made.",
            "- No collusion prevention claim is made.",
            "- No physical inventory truth claim is made.",
            "- This evidence is not proof of physical fulfillment.",
            "- Payment correctness is benchmark rule correctness, not settlement correctness.",
            "- Duplicate financial side effects are N/A in this economic runner.",
            "- Runtime provider scenarios remain OUT_OF_SCOPE here.",
            "- AI-text scenarios remain OUT_OF_SCOPE because AI is not exercised.",
            "- Latency is observational and environment-sensitive.",
            "- Normal-approximation intervals are descriptive.",
            "- No p-values are produced.",
            "- No statistical-significance claim is made.",
            "- No automatic benchmark winner or ranking is produced.",
            "- No live Razorpay claim is made.",
            "",
        ]
    )
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
    with gzip.GzipFile(
        filename="",
        mode="wb",
        fileobj=buffer,
        compresslevel=9,
        mtime=0,
    ) as handle:
        handle.write(data)
    return buffer.getvalue()


def _evidence_file(
    *,
    relative_path: str,
    kind: AgentMarketBenchFinalEvidenceFileKindV1,
    data: bytes,
    line_count: int,
    uncompressed: bytes | None = None,
    first_seed: int | None = None,
    last_seed: int | None = None,
) -> AgentMarketBenchFinalEvidenceFileV1:
    return AgentMarketBenchFinalEvidenceFileV1(
        relative_path=relative_path,
        kind=kind,
        sha256=sha256(data).hexdigest(),
        byte_count=len(data),
        line_count=line_count,
        uncompressed_sha256=(None if uncompressed is None else sha256(uncompressed).hexdigest()),
        first_seed=first_seed,
        last_seed=last_seed,
    )


class _AgentMarketBenchEvidenceBundleWriterV1:
    def __init__(
        self,
        *,
        output_dir: Path,
        evaluated_source_commit: str,
        seeds: tuple[int, ...],
        shard_size: int,
        require_final: bool,
    ) -> None:
        if not isinstance(output_dir, Path):
            raise TypeError("output_dir must be a pathlib.Path")
        if output_dir.exists():
            raise ValueError("output_dir must not exist")
        if type(shard_size) is not int or shard_size < 1:
            raise ValueError("shard_size must be a positive exact int")
        if (
            type(evaluated_source_commit) is not str
            or re.fullmatch(r"[0-9a-f]{40}", evaluated_source_commit) is None
        ):
            raise ValueError("evaluated_source_commit must be a lowercase 40-hex Git commit")
        self._seeds = seeds
        agent_market_bench_final_seed_sequence_digest_v1(seeds)
        if len(set(seeds)) != len(seeds):
            raise ValueError("evidence seeds must be unique")
        self._output_dir = output_dir
        self._commit = evaluated_source_commit
        self._shard_size = shard_size
        self._require_final = require_final
        self._started_at_utc = _utc_now()
        self._processed = 0
        self._shard_index = 0
        self._semantic_buffer: list[bytes] = []
        self._timing_buffer: list[bytes] = []
        self._semantic_buffer_seeds: list[int] = []
        self._files: list[AgentMarketBenchFinalEvidenceFileV1] = []
        self._accumulator = AgentMarketBenchFinalStreamingAccumulatorV1()
        output_dir.mkdir(parents=True)
        (output_dir / "semantic").mkdir()
        (output_dir / "timing").mkdir()

    @property
    def processed_count(self) -> int:
        return self._processed

    def add_case_run(self, case_run: AgentMarketBenchCaseRunV1) -> None:
        if self._processed >= len(self._seeds):
            raise ValueError("received more case runs than the frozen seed sequence")
        semantic, timing = compact_agent_market_bench_case_run_v1(case_run)
        expected_seed = self._seeds[self._processed]
        if semantic.seed != expected_seed:
            raise ValueError("case-run seed does not follow the supplied frozen seed order")
        self._accumulator.add(semantic, timing)
        self._semantic_buffer.append(canonical_agent_market_bench_final_json_v1_bytes(semantic))
        self._timing_buffer.append(canonical_agent_market_bench_final_json_v1_bytes(timing))
        self._semantic_buffer_seeds.append(semantic.seed)
        self._processed += 1
        if len(self._semantic_buffer) == self._shard_size:
            self._flush_shard()

    def _flush_shard(self) -> None:
        if not self._semantic_buffer or len(self._semantic_buffer) != len(self._timing_buffer):
            raise ValueError("semantic and timing shard buffers must be non-empty and paired")
        semantic_raw = b"".join(self._semantic_buffer)
        timing_raw = b"".join(self._timing_buffer)
        semantic_gzip = _gzip_bytes(semantic_raw)
        timing_gzip = _gzip_bytes(timing_raw)
        semantic_relative = f"semantic/part-{self._shard_index:05d}.jsonl.gz"
        timing_relative = f"timing/part-{self._shard_index:05d}.jsonl.gz"
        _atomic_write(self._output_dir / semantic_relative, semantic_gzip)
        _atomic_write(self._output_dir / timing_relative, timing_gzip)
        first_seed = self._semantic_buffer_seeds[0]
        last_seed = self._semantic_buffer_seeds[-1]
        line_count = len(self._semantic_buffer)
        self._files.extend(
            (
                _evidence_file(
                    relative_path=semantic_relative,
                    kind=AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD,
                    data=semantic_gzip,
                    line_count=line_count,
                    uncompressed=semantic_raw,
                    first_seed=first_seed,
                    last_seed=last_seed,
                ),
                _evidence_file(
                    relative_path=timing_relative,
                    kind=AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD,
                    data=timing_gzip,
                    line_count=line_count,
                    uncompressed=timing_raw,
                    first_seed=first_seed,
                    last_seed=last_seed,
                ),
            )
        )
        self._semantic_buffer.clear()
        self._timing_buffer.clear()
        self._semantic_buffer_seeds.clear()
        self._shard_index += 1

    def finish(self) -> AgentMarketBenchFinalManifestV1:
        if self._processed != len(self._seeds):
            raise ValueError("processed case count does not match the supplied seed sequence")
        if self._semantic_buffer:
            self._flush_shard()
        if self._require_final and self._processed != 10_000:
            raise ValueError("completed final evidence requires exactly 10,000 cases")
        seed_digest = agent_market_bench_final_seed_sequence_digest_v1(self._seeds)
        summary = self._accumulator.build_final_summary_v1(
            evaluated_source_commit=self._commit,
            seed_sequence_sha256=seed_digest,
        )
        semantic_files = tuple(
            item
            for item in self._files
            if item.kind is AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD
        )
        timing_files = tuple(
            item
            for item in self._files
            if item.kind is AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD
        )
        semantic_root = agent_market_bench_final_shard_content_root_digest_v1(
            semantic_files,
            kind=AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD,
        )
        timing_root = agent_market_bench_final_shard_content_root_digest_v1(
            timing_files,
            kind=AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD,
        )
        summary_bytes = canonical_agent_market_bench_final_json_v1_bytes(summary)
        report_bytes = render_agent_market_bench_final_report_v1(
            summary,
            generator_version=AGENT_MARKET_BENCH_GENERATOR_V1_VERSION,
            runner_version=AGENT_MARKET_BENCH_RUNNER_V1_VERSION,
            metrics_version=AGENT_MARKET_BENCH_METRICS_V1_VERSION,
            statistics_version=AGENT_MARKET_BENCH_STATISTICS_V1_VERSION,
            semantic_root_sha256=semantic_root,
            timing_root_sha256=timing_root,
        ).encode("utf-8")
        metadata = AgentMarketBenchFinalRunMetadataV1(
            evaluated_source_commit=self._commit,
            started_at_utc=self._started_at_utc,
            completed_at_utc=_utc_now(),
            python_version=platform.python_version(),
            platform_system=platform.system(),
            platform_machine=platform.machine(),
            pydantic_version=pydantic.__version__,
            ortools_version=package_version("ortools"),
            cryptography_version=cryptography.__version__,
        )
        metadata_bytes = canonical_agent_market_bench_final_json_v1_bytes(metadata)
        singleton_data = (
            (
                "summary.json",
                AgentMarketBenchFinalEvidenceFileKindV1.SUMMARY,
                summary_bytes,
            ),
            ("report.md", AgentMarketBenchFinalEvidenceFileKindV1.REPORT, report_bytes),
            (
                "run_metadata.json",
                AgentMarketBenchFinalEvidenceFileKindV1.RUN_METADATA,
                metadata_bytes,
            ),
        )
        for relative_path, kind, data in singleton_data:
            _atomic_write(self._output_dir / relative_path, data)
            self._files.append(
                _evidence_file(
                    relative_path=relative_path,
                    kind=kind,
                    data=data,
                    line_count=data.count(b"\n"),
                )
            )
        files = tuple(sorted(self._files, key=lambda item: item.relative_path))
        evidence_root = agent_market_bench_final_evidence_root_digest_v1(files)
        manifest = AgentMarketBenchFinalManifestV1(
            evaluated_source_commit=self._commit,
            case_count=self._processed,
            first_seed=self._seeds[0],
            last_seed=self._seeds[-1],
            seed_sequence_sha256=seed_digest,
            shard_size=self._shard_size,
            semantic_shard_count=len(semantic_files),
            timing_shard_count=len(timing_files),
            semantic_root_sha256=semantic_root,
            timing_root_sha256=timing_root,
            evidence_root_sha256=evidence_root,
            files=files,
        )
        _verify_agent_market_bench_evidence_bundle_v1(
            self._output_dir,
            expected_manifest=manifest,
            require_final=self._require_final,
        )
        _atomic_write(
            self._output_dir / "manifest.json",
            canonical_agent_market_bench_final_json_v1_bytes(manifest),
        )
        return _fresh_exact(AgentMarketBenchFinalManifestV1, manifest)


def _write_agent_market_bench_development_evidence_v1(
    *,
    case_runs: tuple[AgentMarketBenchCaseRunV1, ...],
    output_dir: Path,
    evaluated_source_commit: str,
    shard_size: int,
) -> AgentMarketBenchFinalManifestV1:
    """Write a test-only evidence bundle from explicitly supplied development CaseRuns."""

    if type(case_runs) is not tuple or not case_runs:
        raise ValueError("case_runs must be a non-empty exact tuple")
    if any(type(case_run) is not AgentMarketBenchCaseRunV1 for case_run in case_runs):
        raise TypeError("development evidence requires exact CaseRun models")
    if any(case_run.seed >= 2_000_000_000 for case_run in case_runs):
        raise ValueError("development evidence cannot contain a final-holdout seed")
    writer = _AgentMarketBenchEvidenceBundleWriterV1(
        output_dir=output_dir,
        evaluated_source_commit=evaluated_source_commit,
        seeds=tuple(case_run.seed for case_run in case_runs),
        shard_size=shard_size,
        require_final=False,
    )
    for case_run in case_runs:
        writer.add_case_run(case_run)
    return writer.finish()


def _decode_rational(payload: dict[str, Any] | None) -> AgentMarketBenchRationalV1 | None:
    return None if payload is None else AgentMarketBenchRationalV1(**payload)


def _decode_observation(payload: dict[str, Any]) -> AgentMarketBenchMetricObservationV1:
    data = dict(payload)
    data["metric"] = AgentMarketBenchMetricV1(data["metric"])
    data["status"] = AgentMarketBenchMetricObservationStatusV1(data["status"])
    data["unit"] = AgentMarketBenchMetricUnitV1(data["unit"])
    data["value"] = _decode_rational(data["value"])
    reason = data["not_applicable_reason"]
    data["not_applicable_reason"] = (
        None if reason is None else AgentMarketBenchMetricNotApplicableReasonV1(reason)
    )
    return AgentMarketBenchMetricObservationV1(**data)


def _decode_assessment(payload: dict[str, Any]) -> AgentMarketBenchScenarioAssessmentV1:
    data = dict(payload)
    data["scenario"] = AgentMarketBenchAdversarialScenarioV1(data["scenario"])
    data["classification"] = AgentMarketBenchAdversarialClassificationV1(data["classification"])
    data["evidence_basis"] = AgentMarketBenchScenarioEvidenceBasisV1(data["evidence_basis"])
    return AgentMarketBenchScenarioAssessmentV1(**data)


def _decode_semantic_method(payload: dict[str, Any]) -> AgentMarketBenchFinalSemanticMethodV1:
    data = dict(payload)
    data["method"] = AgentMarketBenchBaselineV1(data["method"])
    data["result_status"] = AgentMarketBenchMethodStatusV1(data["result_status"])
    data["metrics"] = tuple(_decode_observation(item) for item in data["metrics"])
    return AgentMarketBenchFinalSemanticMethodV1(**data)


def _decode_semantic_record(payload: dict[str, Any]) -> AgentMarketBenchFinalSemanticRecordV1:
    data = dict(payload)
    data["adversarial_scenarios"] = tuple(
        AgentMarketBenchAdversarialScenarioV1(item) for item in data["adversarial_scenarios"]
    )
    data["scenario_assessments"] = tuple(
        _decode_assessment(item) for item in data["scenario_assessments"]
    )
    data["methods"] = tuple(_decode_semantic_method(item) for item in data["methods"])
    return AgentMarketBenchFinalSemanticRecordV1(**data)


def _decode_timing_method(payload: dict[str, Any]) -> AgentMarketBenchFinalTimingMethodV1:
    data = dict(payload)
    data["method"] = AgentMarketBenchBaselineV1(data["method"])
    return AgentMarketBenchFinalTimingMethodV1(**data)


def _decode_timing_record(payload: dict[str, Any]) -> AgentMarketBenchFinalTimingRecordV1:
    data = dict(payload)
    data["timings"] = tuple(_decode_timing_method(item) for item in data["timings"])
    return AgentMarketBenchFinalTimingRecordV1(**data)


def _decode_metric_summary(payload: dict[str, Any]) -> AgentMarketBenchMetricSummaryV1:
    data = dict(payload)
    data["method"] = AgentMarketBenchBaselineV1(data["method"])
    data["metric"] = AgentMarketBenchMetricV1(data["metric"])
    data["unit"] = AgentMarketBenchMetricUnitV1(data["unit"])
    data["mean_value"] = _decode_rational(data["mean_value"])
    return AgentMarketBenchMetricSummaryV1(**data)


def _decode_paired_summary(payload: dict[str, Any]) -> AgentMarketBenchPairedSummaryV1:
    data = dict(payload)
    data["comparator"] = AgentMarketBenchBaselineV1(data["comparator"])
    data["metric"] = AgentMarketBenchMetricV1(data["metric"])
    data["unit"] = AgentMarketBenchMetricUnitV1(data["unit"])
    data["mean_difference"] = _decode_rational(data["mean_difference"])
    return AgentMarketBenchPairedSummaryV1(**data)


def _decode_run_summary(payload: dict[str, Any]) -> AgentMarketBenchRunSummaryV1:
    data = dict(payload)
    data["metric_summaries"] = tuple(
        _decode_metric_summary(item) for item in data["metric_summaries"]
    )
    data["paired_summaries"] = tuple(
        _decode_paired_summary(item) for item in data["paired_summaries"]
    )
    return AgentMarketBenchRunSummaryV1(**data)


def _decode_final_summary(payload: dict[str, Any]) -> AgentMarketBenchFinalSummaryV1:
    data = dict(payload)
    data["method_status_counts"] = tuple(
        AgentMarketBenchFinalMethodStatusCountV1(
            method=AgentMarketBenchBaselineV1(item["method"]),
            status=AgentMarketBenchMethodStatusV1(item["status"]),
            count=item["count"],
        )
        for item in data["method_status_counts"]
    )
    data["scenario_counts"] = tuple(
        AgentMarketBenchFinalScenarioCountV1(
            scenario=AgentMarketBenchAdversarialScenarioV1(item["scenario"]),
            count=item["count"],
        )
        for item in data["scenario_counts"]
    )
    data["scenario_assessment_counts"] = tuple(
        AgentMarketBenchFinalScenarioAssessmentCountV1(
            scenario=AgentMarketBenchAdversarialScenarioV1(item["scenario"]),
            classification=AgentMarketBenchAdversarialClassificationV1(item["classification"]),
            evidence_basis=AgentMarketBenchScenarioEvidenceBasisV1(item["evidence_basis"]),
            count=item["count"],
        )
        for item in data["scenario_assessment_counts"]
    )
    data["run_summary"] = _decode_run_summary(data["run_summary"])
    return AgentMarketBenchFinalSummaryV1(**data)


def _decode_evidence_file(payload: dict[str, Any]) -> AgentMarketBenchFinalEvidenceFileV1:
    data = dict(payload)
    data["kind"] = AgentMarketBenchFinalEvidenceFileKindV1(data["kind"])
    return AgentMarketBenchFinalEvidenceFileV1(**data)


def _decode_manifest(payload: dict[str, Any]) -> AgentMarketBenchFinalManifestV1:
    data = dict(payload)
    data["files"] = tuple(_decode_evidence_file(item) for item in data["files"])
    return AgentMarketBenchFinalManifestV1(**data)


def _decode_model[ModelT: BaseModel](model_type: type[ModelT], payload: object) -> ModelT:
    if type(payload) is not dict:
        raise ValueError("evidence JSON payload must be an object")
    data = cast(dict[str, Any], payload)
    model: BaseModel
    if model_type is AgentMarketBenchFinalSemanticRecordV1:
        model = _decode_semantic_record(data)
    elif model_type is AgentMarketBenchFinalTimingRecordV1:
        model = _decode_timing_record(data)
    elif model_type is AgentMarketBenchFinalSummaryV1:
        model = _decode_final_summary(data)
    elif model_type is AgentMarketBenchFinalRunMetadataV1:
        model = AgentMarketBenchFinalRunMetadataV1(**data)
    elif model_type is AgentMarketBenchFinalManifestV1:
        model = _decode_manifest(data)
    else:
        raise TypeError(f"unsupported canonical evidence model {model_type.__name__}")
    return cast(ModelT, model)


def _load_canonical_model[ModelT: BaseModel](path: Path, model_type: type[ModelT]) -> ModelT:
    try:
        data = path.read_bytes()
        payload = json.loads(data)
        model = _decode_model(model_type, payload)
    except Exception as error:
        raise ValueError(f"invalid evidence model: {path.name}") from error
    if canonical_agent_market_bench_final_json_v1_bytes(model) != data:
        raise ValueError(f"evidence JSON is not canonical: {path.name}")
    return model


def _parse_shard_records[ModelT: BaseModel](
    *,
    output_dir: Path,
    file: AgentMarketBenchFinalEvidenceFileV1,
    model_type: type[ModelT],
) -> tuple[ModelT, ...]:
    path = output_dir / file.relative_path
    compressed = path.read_bytes()
    if len(compressed) != file.byte_count or sha256(compressed).hexdigest() != file.sha256:
        raise ValueError(f"compressed shard hash or byte count mismatch: {file.relative_path}")
    if (
        len(compressed) < 10
        or compressed[:2] != b"\x1f\x8b"
        or compressed[3] & 0x08
        or compressed[4:8] != b"\0\0\0\0"
        or compressed[8] != 2
    ):
        raise ValueError(f"gzip shard must use mtime=0: {file.relative_path}")
    try:
        uncompressed = gzip.decompress(compressed)
    except Exception as error:
        raise ValueError(f"invalid gzip shard: {file.relative_path}") from error
    if file.uncompressed_sha256 is None or sha256(uncompressed).hexdigest() != (
        file.uncompressed_sha256
    ):
        raise ValueError(f"uncompressed shard hash mismatch: {file.relative_path}")
    lines = uncompressed.splitlines(keepends=True)
    if not uncompressed.endswith(b"\n") or len(lines) != file.line_count:
        raise ValueError(f"shard newline record count mismatch: {file.relative_path}")
    records = []
    for line in lines:
        try:
            record = _decode_model(model_type, json.loads(line))
        except Exception as error:
            raise ValueError(f"invalid shard record: {file.relative_path}") from error
        if canonical_agent_market_bench_final_json_v1_bytes(record) != line:
            raise ValueError(f"non-canonical shard record: {file.relative_path}")
        records.append(record)
    seeded_records = cast(
        tuple[AgentMarketBenchFinalSemanticRecordV1 | AgentMarketBenchFinalTimingRecordV1, ...],
        tuple(records),
    )
    record_seeds = tuple(record.seed for record in seeded_records)
    if record_seeds[0] != file.first_seed or record_seeds[-1] != file.last_seed:
        raise ValueError(f"shard first/last seed metadata mismatch: {file.relative_path}")
    return tuple(records)


def _require_exact_file_paths(
    manifest: AgentMarketBenchFinalManifestV1,
) -> None:
    semantic_paths = tuple(
        item.relative_path
        for item in manifest.files
        if item.kind is AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD
    )
    timing_paths = tuple(
        item.relative_path
        for item in manifest.files
        if item.kind is AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD
    )
    if semantic_paths != tuple(
        f"semantic/part-{index:05d}.jsonl.gz" for index in range(manifest.semantic_shard_count)
    ):
        raise ValueError("semantic shard paths do not match the frozen sequence")
    if timing_paths != tuple(
        f"timing/part-{index:05d}.jsonl.gz" for index in range(manifest.timing_shard_count)
    ):
        raise ValueError("timing shard paths do not match the frozen sequence")
    singleton_paths = {
        item.kind: item.relative_path
        for item in manifest.files
        if item.kind
        in {
            AgentMarketBenchFinalEvidenceFileKindV1.SUMMARY,
            AgentMarketBenchFinalEvidenceFileKindV1.REPORT,
            AgentMarketBenchFinalEvidenceFileKindV1.RUN_METADATA,
        }
    }
    if singleton_paths != {
        AgentMarketBenchFinalEvidenceFileKindV1.SUMMARY: "summary.json",
        AgentMarketBenchFinalEvidenceFileKindV1.REPORT: "report.md",
        AgentMarketBenchFinalEvidenceFileKindV1.RUN_METADATA: "run_metadata.json",
    }:
        raise ValueError("singleton evidence paths do not match the frozen names")


def _verify_agent_market_bench_evidence_bundle_v1(
    output_dir: Path,
    *,
    expected_manifest: AgentMarketBenchFinalManifestV1 | None,
    require_final: bool,
) -> AgentMarketBenchFinalManifestV1:
    if not isinstance(output_dir, Path):
        raise TypeError("output_dir must be a pathlib.Path")
    if not output_dir.is_dir():
        raise ValueError("evidence output directory does not exist")
    manifest_path = output_dir / "manifest.json"
    if expected_manifest is None:
        if not manifest_path.is_file():
            raise ValueError("manifest.json is required for completed evidence")
        manifest = _load_canonical_model(manifest_path, AgentMarketBenchFinalManifestV1)
    else:
        manifest = _fresh_exact(AgentMarketBenchFinalManifestV1, expected_manifest)
        if manifest_path.exists():
            loaded = _load_canonical_model(manifest_path, AgentMarketBenchFinalManifestV1)
            if loaded != manifest:
                raise ValueError("manifest.json does not equal expected_manifest")
    if manifest.evidence_version != AGENT_MARKET_BENCH_FINAL_EVIDENCE_V1_VERSION:
        raise ValueError("manifest evidence version does not match frozen source")
    if (
        manifest.generator_version != AGENT_MARKET_BENCH_GENERATOR_V1_VERSION
        or manifest.runner_version != AGENT_MARKET_BENCH_RUNNER_V1_VERSION
        or manifest.metrics_version != AGENT_MARKET_BENCH_METRICS_V1_VERSION
        or manifest.statistics_version != AGENT_MARKET_BENCH_STATISTICS_V1_VERSION
    ):
        raise ValueError("manifest component versions do not match frozen source constants")
    if require_final:
        expected_seeds = tuple(range(2_000_000_000, 2_000_010_000))
        if (
            manifest.case_count != 10_000
            or manifest.first_seed != expected_seeds[0]
            or manifest.last_seed != expected_seeds[-1]
            or manifest.shard_size != 500
            or manifest.semantic_shard_count != 20
            or manifest.timing_shard_count != 20
        ):
            raise ValueError("manifest does not describe the exact completed final holdout")
    _require_exact_file_paths(manifest)
    expected_paths = {item.relative_path for item in manifest.files}
    actual_paths = {
        path.relative_to(output_dir).as_posix() for path in output_dir.rglob("*") if path.is_file()
    }
    allowed_paths = expected_paths | ({"manifest.json"} if manifest_path.exists() else set())
    if actual_paths != allowed_paths:
        raise ValueError("missing or unexpected final evidence files")
    for item in manifest.files:
        path = output_dir / item.relative_path
        if not path.is_file():
            raise ValueError(f"missing evidence file: {item.relative_path}")
        data = path.read_bytes()
        if len(data) != item.byte_count or sha256(data).hexdigest() != item.sha256:
            raise ValueError(f"evidence file hash or byte count mismatch: {item.relative_path}")
        if (
            item.kind
            not in {
                AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD,
                AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD,
            }
            and data.count(b"\n") != item.line_count
        ):
            raise ValueError(f"evidence file line count mismatch: {item.relative_path}")
    semantic_files = tuple(
        item
        for item in manifest.files
        if item.kind is AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD
    )
    timing_files = tuple(
        item
        for item in manifest.files
        if item.kind is AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD
    )
    semantic_records = tuple(
        record
        for item in semantic_files
        for record in _parse_shard_records(
            output_dir=output_dir,
            file=item,
            model_type=AgentMarketBenchFinalSemanticRecordV1,
        )
    )
    timing_records = tuple(
        record
        for item in timing_files
        for record in _parse_shard_records(
            output_dir=output_dir,
            file=item,
            model_type=AgentMarketBenchFinalTimingRecordV1,
        )
    )
    if len(semantic_records) != manifest.case_count or len(timing_records) != manifest.case_count:
        raise ValueError("record counts do not match manifest case_count")
    seeds = tuple(record.seed for record in semantic_records)
    if len(set(seeds)) != len(seeds):
        raise ValueError("semantic seeds must be unique")
    if seeds[0] != manifest.first_seed or seeds[-1] != manifest.last_seed:
        raise ValueError("manifest first/last seeds do not match record order")
    if len({record.case_digest_sha256 for record in semantic_records}) != len(semantic_records):
        raise ValueError("semantic case digests must be unique")
    for semantic, timing in zip(semantic_records, timing_records, strict=True):
        if semantic.seed != timing.seed or semantic.case_digest_sha256 != timing.case_digest_sha256:
            raise ValueError("semantic/timing record pairing mismatch")
    if require_final and seeds != tuple(range(2_000_000_000, 2_000_010_000)):
        raise ValueError("final evidence seed order does not equal the frozen final tuple")
    if agent_market_bench_final_seed_sequence_digest_v1(seeds) != manifest.seed_sequence_sha256:
        raise ValueError("seed-sequence SHA-256 mismatch")
    if agent_market_bench_final_shard_content_root_digest_v1(
        semantic_files,
        kind=AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD,
    ) != (manifest.semantic_root_sha256):
        raise ValueError("semantic root SHA-256 mismatch")
    if agent_market_bench_final_shard_content_root_digest_v1(
        timing_files,
        kind=AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD,
    ) != (manifest.timing_root_sha256):
        raise ValueError("timing root SHA-256 mismatch")
    if agent_market_bench_final_evidence_root_digest_v1(manifest.files) != (
        manifest.evidence_root_sha256
    ):
        raise ValueError("evidence root SHA-256 mismatch")
    accumulator = AgentMarketBenchFinalStreamingAccumulatorV1()
    for semantic, timing in zip(semantic_records, timing_records, strict=True):
        accumulator.add(semantic, timing)
    expected_summary = accumulator.build_final_summary_v1(
        evaluated_source_commit=manifest.evaluated_source_commit,
        seed_sequence_sha256=manifest.seed_sequence_sha256,
    )
    summary = _load_canonical_model(output_dir / "summary.json", AgentMarketBenchFinalSummaryV1)
    if summary != expected_summary:
        raise ValueError("summary.json does not equal reconstructed compact evidence")
    expected_report = render_agent_market_bench_final_report_v1(
        summary,
        generator_version=manifest.generator_version,
        runner_version=manifest.runner_version,
        metrics_version=manifest.metrics_version,
        statistics_version=manifest.statistics_version,
        semantic_root_sha256=manifest.semantic_root_sha256,
        timing_root_sha256=manifest.timing_root_sha256,
    ).encode("utf-8")
    if (output_dir / "report.md").read_bytes() != expected_report:
        raise ValueError("report.md does not equal the frozen neutral rendering")
    metadata = _load_canonical_model(
        output_dir / "run_metadata.json", AgentMarketBenchFinalRunMetadataV1
    )
    if metadata.evaluated_source_commit != manifest.evaluated_source_commit:
        raise ValueError("run metadata evaluated commit does not match manifest")
    return _fresh_exact(AgentMarketBenchFinalManifestV1, manifest)


def verify_agent_market_bench_final_evidence_v1(
    output_dir: Path,
    *,
    expected_manifest: AgentMarketBenchFinalManifestV1 | None = None,
) -> AgentMarketBenchFinalManifestV1:
    """Verify a completed 10,000-case final transport without executing benchmark code."""

    return _verify_agent_market_bench_evidence_bundle_v1(
        output_dir,
        expected_manifest=expected_manifest,
        require_final=True,
    )


__all__ = (  # noqa: RUF022
    "canonical_agent_market_bench_final_json_v1_bytes",
    "agent_market_bench_final_method_result_digest_v1",
    "agent_market_bench_final_admission_digest_v1",
    "agent_market_bench_final_seed_sequence_digest_v1",
    "agent_market_bench_final_shard_content_root_digest_v1",
    "agent_market_bench_final_evidence_root_digest_v1",
    "compact_agent_market_bench_case_run_v1",
    "AgentMarketBenchFinalStreamingAccumulatorV1",
    "render_agent_market_bench_final_report_v1",
    "verify_agent_market_bench_final_evidence_v1",
)
