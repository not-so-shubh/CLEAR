"""Strict measurement evidence models for AgentMarketBench V1.

These models record observations made after the frozen economic methods run.
They are benchmark evidence only and never authorize money, settlement, or
fulfillment.
"""

import re
from enum import StrEnum
from math import gcd
from typing import Annotated, Final, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from clear_market.agentmarketbench.method_models import AgentMarketBenchMethodResultV1
from clear_market.agentmarketbench.models import (
    MAX_AGENT_MARKET_BENCH_SEED,
    AgentMarketBenchAdversarialClassificationV1,
    AgentMarketBenchAdversarialScenarioV1,
    AgentMarketBenchBaselineV1,
    AgentMarketBenchMetricV1,
)
from clear_market.domain import CanonicalUUID4

AGENT_MARKET_BENCH_RUNNER_V1_VERSION: Final[str] = "agent-market-bench-runner-v1"
AGENT_MARKET_BENCH_METRICS_V1_VERSION: Final[str] = "agent-market-bench-metrics-v1"
AGENT_MARKET_BENCH_METRIC_SEMANTICS_V1_1_VERSION: Final[str] = (
    "agent-market-bench-metric-semantics-v1.1"
)
AGENT_MARKET_BENCH_STATISTICS_V1_VERSION: Final[str] = "agent-market-bench-statistics-v1"
AGENT_MARKET_BENCH_RATIONAL_V1_VERSION: Final[str] = "agent-market-bench-rational-v1"
AGENT_MARKET_BENCH_METRIC_OBSERVATION_V1_VERSION: Final[str] = (
    "agent-market-bench-metric-observation-v1"
)
AGENT_MARKET_BENCH_SCENARIO_ASSESSMENT_V1_VERSION: Final[str] = (
    "agent-market-bench-scenario-assessment-v1"
)
AGENT_MARKET_BENCH_METHOD_EVALUATION_V1_VERSION: Final[str] = (
    "agent-market-bench-method-evaluation-v1"
)
AGENT_MARKET_BENCH_CASE_RUN_V1_VERSION: Final[str] = "agent-market-bench-case-run-v1"
AGENT_MARKET_BENCH_METRIC_SUMMARY_V1_VERSION: Final[str] = "agent-market-bench-metric-summary-v1"
AGENT_MARKET_BENCH_PAIRED_SUMMARY_V1_VERSION: Final[str] = "agent-market-bench-paired-summary-v1"
AGENT_MARKET_BENCH_RUN_SUMMARY_V1_VERSION: Final[str] = "agent-market-bench-run-summary-v1"
AGENT_MARKET_BENCH_RUN_V1_VERSION: Final[str] = "agent-market-bench-run-v1"


class AgentMarketBenchMetricObservationStatusV1(StrEnum):
    MEASURED = "MEASURED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AgentMarketBenchMetricUnitV1(StrEnum):
    RATIO = "RATIO"
    PAISE = "PAISE"
    COUNT = "COUNT"
    BINARY = "BINARY"
    NANOSECONDS = "NANOSECONDS"


class AgentMarketBenchMetricNotApplicableReasonV1(StrEnum):
    METHOD_NOT_APPLICABLE = "METHOD_NOT_APPLICABLE"
    ORACLE_WELFARE_ZERO = "ORACLE_WELFARE_ZERO"
    SCENARIO_NOT_DEFINED = "SCENARIO_NOT_DEFINED"
    NO_FINANCIAL_EXECUTION_IN_24D = "NO_FINANCIAL_EXECUTION_IN_24D"


class AgentMarketBenchScenarioEvidenceBasisV1(StrEnum):
    SHARED_ADMISSION = "SHARED_ADMISSION"
    ECONOMIC_SENSITIVITY = "ECONOMIC_SENSITIVITY"
    AI_NOT_EXERCISED = "AI_NOT_EXERCISED"
    FINANCIAL_RUNTIME_NOT_EXERCISED = "FINANCIAL_RUNTIME_NOT_EXERCISED"


_METRIC_UNITS: dict[AgentMarketBenchMetricV1, AgentMarketBenchMetricUnitV1] = {
    AgentMarketBenchMetricV1.ALLOCATIVE_EFFICIENCY: AgentMarketBenchMetricUnitV1.RATIO,
    AgentMarketBenchMetricV1.REGRET: AgentMarketBenchMetricUnitV1.PAISE,
    AgentMarketBenchMetricV1.BUYER_SURPLUS: AgentMarketBenchMetricUnitV1.PAISE,
    AgentMarketBenchMetricV1.MERCHANT_SURPLUS: AgentMarketBenchMetricUnitV1.PAISE,
    AgentMarketBenchMetricV1.WELFARE: AgentMarketBenchMetricUnitV1.PAISE,
    AgentMarketBenchMetricV1.COMPLETION: AgentMarketBenchMetricUnitV1.RATIO,
    AgentMarketBenchMetricV1.HARD_CONSTRAINT_VIOLATIONS: AgentMarketBenchMetricUnitV1.COUNT,
    AgentMarketBenchMetricV1.MANIPULATION_SUCCESS: AgentMarketBenchMetricUnitV1.BINARY,
    AgentMarketBenchMetricV1.PAYMENT_CORRECTNESS: AgentMarketBenchMetricUnitV1.BINARY,
    AgentMarketBenchMetricV1.DUPLICATE_FINANCIAL_SIDE_EFFECTS: AgentMarketBenchMetricUnitV1.COUNT,
    AgentMarketBenchMetricV1.LATENCY: AgentMarketBenchMetricUnitV1.NANOSECONDS,
}


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
        raise ValueError("case digest must be a lowercase SHA-256 hex string")
    return value


_Sha256Hex = Annotated[str, BeforeValidator(_validate_sha256)]


_ExactMetric = Annotated[
    AgentMarketBenchMetricV1,
    BeforeValidator(lambda value: _exact_enum(AgentMarketBenchMetricV1, value)),
]
_ExactBaseline = Annotated[
    AgentMarketBenchBaselineV1,
    BeforeValidator(lambda value: _exact_enum(AgentMarketBenchBaselineV1, value)),
]
_ExactScenario = Annotated[
    AgentMarketBenchAdversarialScenarioV1,
    BeforeValidator(lambda value: _exact_enum(AgentMarketBenchAdversarialScenarioV1, value)),
]
_ExactClassification = Annotated[
    AgentMarketBenchAdversarialClassificationV1,
    BeforeValidator(lambda value: _exact_enum(AgentMarketBenchAdversarialClassificationV1, value)),
]
_ExactObservationStatus = Annotated[
    AgentMarketBenchMetricObservationStatusV1,
    BeforeValidator(lambda value: _exact_enum(AgentMarketBenchMetricObservationStatusV1, value)),
]
_ExactUnit = Annotated[
    AgentMarketBenchMetricUnitV1,
    BeforeValidator(lambda value: _exact_enum(AgentMarketBenchMetricUnitV1, value)),
]
_ExactReason = Annotated[
    AgentMarketBenchMetricNotApplicableReasonV1,
    BeforeValidator(lambda value: _exact_enum(AgentMarketBenchMetricNotApplicableReasonV1, value)),
]
_ExactBasis = Annotated[
    AgentMarketBenchScenarioEvidenceBasisV1,
    BeforeValidator(lambda value: _exact_enum(AgentMarketBenchScenarioEvidenceBasisV1, value)),
]
_FreshResult = Annotated[
    AgentMarketBenchMethodResultV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchMethodResultV1, value)),
]


class AgentMarketBenchRationalV1(BaseModel):
    """A reduced exact rational with no floating-point representation."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_rational_version: Literal["agent-market-bench-rational-v1"] = (
        "agent-market-bench-rational-v1"
    )
    numerator: Annotated[int, Field(strict=True)]
    denominator: Annotated[int, Field(strict=True, ge=1)]

    @model_validator(mode="after")
    def _reduce(self) -> "AgentMarketBenchRationalV1":
        numerator = self.numerator
        denominator = self.denominator
        divisor = gcd(abs(numerator), denominator)
        if divisor:
            numerator //= divisor
            denominator //= divisor
        if denominator < 0:
            numerator = -numerator
            denominator = -denominator
        if numerator == 0:
            denominator = 1
        if numerator != self.numerator or denominator != self.denominator:
            object.__setattr__(self, "numerator", numerator)
            object.__setattr__(self, "denominator", denominator)
        return self


_FreshRational = Annotated[
    AgentMarketBenchRationalV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchRationalV1, value)),
]


class AgentMarketBenchMetricObservationV1(BaseModel):
    """One exact metric observation or a typed, explicit N/A observation."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_metric_observation_version: Literal[
        "agent-market-bench-metric-observation-v1"
    ] = "agent-market-bench-metric-observation-v1"
    metric: _ExactMetric
    status: _ExactObservationStatus
    unit: _ExactUnit
    value: _FreshRational | None
    not_applicable_reason: _ExactReason | None

    @model_validator(mode="after")
    def _validate_shape(self) -> "AgentMarketBenchMetricObservationV1":
        if self.unit is not _METRIC_UNITS[self.metric]:
            raise ValueError("metric observation unit does not match metric")
        if self.status is AgentMarketBenchMetricObservationStatusV1.MEASURED:
            if self.value is None or self.not_applicable_reason is not None:
                raise ValueError("measured observation requires value and no N/A reason")
        elif self.value is not None or self.not_applicable_reason is None:
            raise ValueError("N/A observation requires reason and no value")
        return self


_FreshObservation = Annotated[
    AgentMarketBenchMetricObservationV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchMetricObservationV1, value)),
]


class AgentMarketBenchScenarioAssessmentV1(BaseModel):
    """A benchmark-layer classification, without free-form proof or authority."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_scenario_assessment_version: Literal[
        "agent-market-bench-scenario-assessment-v1"
    ] = "agent-market-bench-scenario-assessment-v1"
    scenario: _ExactScenario
    classification: _ExactClassification
    evidence_basis: _ExactBasis


_FreshAssessment = Annotated[
    AgentMarketBenchScenarioAssessmentV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchScenarioAssessmentV1, value)),
]


class AgentMarketBenchMethodEvaluationV1(BaseModel):
    """One method result plus latent diagnostics and all frozen metric observations."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_method_evaluation_version: Literal[
        "agent-market-bench-method-evaluation-v1"
    ] = "agent-market-bench-method-evaluation-v1"
    method: _ExactBaseline
    result: _FreshResult
    elapsed_ns: Annotated[int, Field(strict=True, ge=0)]
    realized_quantity: Annotated[int, Field(strict=True, ge=0)]
    latent_capacity_excess_units: Annotated[int, Field(strict=True, ge=0)]
    latent_hard_violation_units: Annotated[int, Field(strict=True, ge=0)]
    metrics: Annotated[tuple[_FreshObservation, ...], BeforeValidator(_require_tuple)]

    @model_validator(mode="after")
    def _validate_metrics(self) -> "AgentMarketBenchMethodEvaluationV1":
        if self.result.method is not self.method:
            raise ValueError("evaluation method must match result method")
        if tuple(observation.metric for observation in self.metrics) != tuple(
            AgentMarketBenchMetricV1
        ):
            raise ValueError("metrics must contain every metric exactly in enum order")
        return self


_FreshEvaluation = Annotated[
    AgentMarketBenchMethodEvaluationV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchMethodEvaluationV1, value)),
]


class AgentMarketBenchCaseRunV1(BaseModel):
    """Evidence for one timed case execution."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_case_run_version: Literal["agent-market-bench-case-run-v1"] = (
        "agent-market-bench-case-run-v1"
    )
    runner_version: Literal["agent-market-bench-runner-v1"] = "agent-market-bench-runner-v1"
    metrics_version: Literal["agent-market-bench-metrics-v1"] = "agent-market-bench-metrics-v1"
    statistics_version: Literal["agent-market-bench-statistics-v1"] = (
        "agent-market-bench-statistics-v1"
    )
    case_id: CanonicalUUID4
    seed: Annotated[int, Field(strict=True, ge=0, le=MAX_AGENT_MARKET_BENCH_SEED)]
    case_digest_sha256: _Sha256Hex
    execution_order: Annotated[tuple[_ExactBaseline, ...], BeforeValidator(_require_tuple)]
    evaluations: Annotated[tuple[_FreshEvaluation, ...], BeforeValidator(_require_tuple)]
    scenario_assessments: Annotated[tuple[_FreshAssessment, ...], BeforeValidator(_require_tuple)]

    @model_validator(mode="after")
    def _validate_coverage(self) -> "AgentMarketBenchCaseRunV1":
        baseline_order = tuple(AgentMarketBenchBaselineV1)
        if tuple(sorted(self.execution_order, key=lambda method: method.value)) != tuple(
            sorted(baseline_order, key=lambda method: method.value)
        ):
            raise ValueError("execution_order must contain every baseline exactly once")
        if tuple(evaluation.method for evaluation in self.evaluations) != baseline_order:
            raise ValueError("evaluations must be normalized to baseline enum order")
        if len(self.execution_order) != len(set(self.execution_order)):
            raise ValueError("execution_order contains duplicate methods")
        if len(self.evaluations) != len(set(evaluation.method for evaluation in self.evaluations)):
            raise ValueError("evaluations contain duplicate methods")
        scenario_order = tuple(assessment.scenario for assessment in self.scenario_assessments)
        if len(scenario_order) != len(set(scenario_order)):
            raise ValueError("scenario assessments contain duplicate scenarios")
        normalized_scenarios = tuple(
            sorted(self.scenario_assessments, key=lambda assessment: assessment.scenario.value)
        )
        if normalized_scenarios != self.scenario_assessments:
            object.__setattr__(self, "scenario_assessments", normalized_scenarios)
        return self


_FreshCaseRun = Annotated[
    AgentMarketBenchCaseRunV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchCaseRunV1, value)),
]


class AgentMarketBenchMetricSummaryV1(BaseModel):
    """Exact arithmetic summary for one method and metric."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_metric_summary_version: Literal["agent-market-bench-metric-summary-v1"] = (
        "agent-market-bench-metric-summary-v1"
    )
    method: _ExactBaseline
    metric: _ExactMetric
    unit: _ExactUnit
    measured_count: Annotated[int, Field(strict=True, ge=0)]
    not_applicable_count: Annotated[int, Field(strict=True, ge=0)]
    mean_value: _FreshRational | None

    @model_validator(mode="after")
    def _validate_mean(self) -> "AgentMarketBenchMetricSummaryV1":
        if self.unit is not _METRIC_UNITS[self.metric]:
            raise ValueError("metric summary unit does not match metric")
        if self.measured_count == 0 and self.mean_value is not None:
            raise ValueError("empty measured summary cannot have a mean")
        if self.measured_count > 0 and self.mean_value is None:
            raise ValueError("measured summary requires a mean")
        return self


_FreshMetricSummary = Annotated[
    AgentMarketBenchMetricSummaryV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchMetricSummaryV1, value)),
]


def _validate_decimal(value: object) -> object:
    if type(value) is not str or re.fullmatch(r"-?\d+\.\d{12}", value) is None:
        raise ValueError("CI bounds must be canonical 12-decimal strings")
    return value


_CanonicalDecimal = Annotated[str, BeforeValidator(_validate_decimal)]


class AgentMarketBenchPairedSummaryV1(BaseModel):
    """Comparator-minus-CLEAR exact paired summary and descriptive CI."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_paired_summary_version: Literal["agent-market-bench-paired-summary-v1"] = (
        "agent-market-bench-paired-summary-v1"
    )
    comparator: _ExactBaseline
    metric: _ExactMetric
    unit: _ExactUnit
    paired_count: Annotated[int, Field(strict=True, ge=0)]
    mean_difference: _FreshRational | None
    ci95_lower_decimal: _CanonicalDecimal | None
    ci95_upper_decimal: _CanonicalDecimal | None

    @model_validator(mode="after")
    def _validate_shape(self) -> "AgentMarketBenchPairedSummaryV1":
        if self.unit is not _METRIC_UNITS[self.metric]:
            raise ValueError("paired summary unit does not match metric")
        if self.comparator is AgentMarketBenchBaselineV1.CLEAR:
            raise ValueError("CLEAR cannot be a paired comparator")
        if self.paired_count == 0:
            if self.mean_difference is not None or self.ci95_lower_decimal is not None:
                raise ValueError("empty paired summary must have no mean or lower CI")
            if self.ci95_upper_decimal is not None:
                raise ValueError("empty paired summary must have no upper CI")
        elif self.paired_count == 1:
            if self.mean_difference is None or self.ci95_lower_decimal is not None:
                raise ValueError("one-pair summary requires mean and no CI")
            if self.ci95_upper_decimal is not None:
                raise ValueError("one-pair summary requires no upper CI")
        elif self.mean_difference is None or self.ci95_lower_decimal is None:
            raise ValueError("paired summary with two or more pairs requires mean and CI")
        elif self.ci95_upper_decimal is None:
            raise ValueError("paired summary with two or more pairs requires upper CI")
        return self


_FreshPairedSummary = Annotated[
    AgentMarketBenchPairedSummaryV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchPairedSummaryV1, value)),
]


class AgentMarketBenchRunSummaryV1(BaseModel):
    """Complete 99-method-metric and 88-paired-metric coverage summary."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_run_summary_version: Literal["agent-market-bench-run-summary-v1"] = (
        "agent-market-bench-run-summary-v1"
    )
    case_count: Annotated[int, Field(strict=True, ge=1)]
    metric_summaries: Annotated[tuple[_FreshMetricSummary, ...], BeforeValidator(_require_tuple)]
    paired_summaries: Annotated[tuple[_FreshPairedSummary, ...], BeforeValidator(_require_tuple)]

    @model_validator(mode="after")
    def _validate_coverage(self) -> "AgentMarketBenchRunSummaryV1":
        expected_metrics = tuple(
            (method, metric)
            for method in AgentMarketBenchBaselineV1
            for metric in AgentMarketBenchMetricV1
        )
        actual_metrics = tuple(
            (summary.method, summary.metric) for summary in self.metric_summaries
        )
        if actual_metrics != expected_metrics:
            raise ValueError("metric summaries must contain exact 9x11 enum-order coverage")
        comparators = tuple(
            method
            for method in AgentMarketBenchBaselineV1
            if method is not AgentMarketBenchBaselineV1.CLEAR
        )
        expected_pairs = tuple(
            (method, metric) for method in comparators for metric in AgentMarketBenchMetricV1
        )
        actual_pairs = tuple(
            (summary.comparator, summary.metric) for summary in self.paired_summaries
        )
        if actual_pairs != expected_pairs:
            raise ValueError("paired summaries must contain exact 8x11 enum-order coverage")
        return self


_FreshRunSummary = Annotated[
    AgentMarketBenchRunSummaryV1,
    BeforeValidator(lambda value: _fresh_exact(AgentMarketBenchRunSummaryV1, value)),
]


class AgentMarketBenchRunV1(BaseModel):
    """A non-empty measurement run with no final-report semantics."""

    model_config = ConfigDict(
        frozen=True,
        strict=True,
        extra="forbid",
        revalidate_instances="always",
    )

    schema_version: Literal["1"] = "1"
    agent_market_bench_run_version: Literal["agent-market-bench-run-v1"] = (
        "agent-market-bench-run-v1"
    )
    runner_version: Literal["agent-market-bench-runner-v1"] = "agent-market-bench-runner-v1"
    metrics_version: Literal["agent-market-bench-metrics-v1"] = "agent-market-bench-metrics-v1"
    statistics_version: Literal["agent-market-bench-statistics-v1"] = (
        "agent-market-bench-statistics-v1"
    )
    case_runs: Annotated[tuple[_FreshCaseRun, ...], BeforeValidator(_require_tuple)]
    summary: _FreshRunSummary

    @model_validator(mode="after")
    def _validate_runs(self) -> "AgentMarketBenchRunV1":
        if not self.case_runs:
            raise ValueError("run must contain at least one case")
        if len({case.case_id for case in self.case_runs}) != len(self.case_runs):
            raise ValueError("case IDs must be unique")
        if len({case.case_digest_sha256 for case in self.case_runs}) != len(self.case_runs):
            raise ValueError("case digests must be unique")
        if self.summary.case_count != len(self.case_runs):
            raise ValueError("summary case_count must match case_runs")
        return self


__all__ = (  # noqa: RUF022
    "AGENT_MARKET_BENCH_RUNNER_V1_VERSION",
    "AGENT_MARKET_BENCH_METRICS_V1_VERSION",
    "AGENT_MARKET_BENCH_METRIC_SEMANTICS_V1_1_VERSION",
    "AGENT_MARKET_BENCH_STATISTICS_V1_VERSION",
    "AGENT_MARKET_BENCH_RATIONAL_V1_VERSION",
    "AGENT_MARKET_BENCH_METRIC_OBSERVATION_V1_VERSION",
    "AGENT_MARKET_BENCH_SCENARIO_ASSESSMENT_V1_VERSION",
    "AGENT_MARKET_BENCH_METHOD_EVALUATION_V1_VERSION",
    "AGENT_MARKET_BENCH_CASE_RUN_V1_VERSION",
    "AGENT_MARKET_BENCH_METRIC_SUMMARY_V1_VERSION",
    "AGENT_MARKET_BENCH_PAIRED_SUMMARY_V1_VERSION",
    "AGENT_MARKET_BENCH_RUN_SUMMARY_V1_VERSION",
    "AGENT_MARKET_BENCH_RUN_V1_VERSION",
    "AgentMarketBenchMetricObservationStatusV1",
    "AgentMarketBenchMetricUnitV1",
    "AgentMarketBenchMetricNotApplicableReasonV1",
    "AgentMarketBenchScenarioEvidenceBasisV1",
    "AgentMarketBenchRationalV1",
    "AgentMarketBenchMetricObservationV1",
    "AgentMarketBenchScenarioAssessmentV1",
    "AgentMarketBenchMethodEvaluationV1",
    "AgentMarketBenchCaseRunV1",
    "AgentMarketBenchMetricSummaryV1",
    "AgentMarketBenchPairedSummaryV1",
    "AgentMarketBenchRunSummaryV1",
    "AgentMarketBenchRunV1",
)
