from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from clear_market.benchmark.seeds import MAX_GENERATOR_SEED
from clear_market.domain import MAX_SELLERS, MIN_SELLERS

BENCHMARK_RUNNER_VERSION: Final[str] = "differential-benchmark-runner-v1"
BENCHMARK_FINGERPRINT_VERSION: Final[str] = "sha256-clear-benchmark-records-v1"

_LOWERCASE_HEX_DIGITS = frozenset("0123456789abcdef")


class BenchmarkHardFailureCode(StrEnum):
    ADMISSION_REJECTION = "admission_rejection"
    DIFFERENTIAL_MISMATCH = "differential_mismatch"
    BUDGET_EXCEEDED = "budget_exceeded"
    ALLOCATION_QUANTITY_MISMATCH = "allocation_quantity_mismatch"
    WINNER_EVIDENCE_MISMATCH = "winner_evidence_mismatch"


def _validate_sha256_hex(value: object) -> str:
    """Require a caller-supplied canonical SHA-256 hexadecimal representation."""
    if type(value) is not str:
        raise ValueError("digest must be a string")
    if len(value) != 64 or any(character not in _LOWERCASE_HEX_DIGITS for character in value):
        raise ValueError("digest must be 64 lowercase hexadecimal characters")
    return value


type _SellerCount = Annotated[
    int,
    Field(strict=True, ge=MIN_SELLERS, le=MAX_SELLERS),
]
type _PositiveCount = Annotated[int, Field(strict=True, ge=1)]
type _NonNegativeCount = Annotated[int, Field(strict=True, ge=0)]
type _GeneratorSeed = Annotated[
    int,
    Field(strict=True, ge=0, le=MAX_GENERATOR_SEED),
]
type _Sha256Hex = Annotated[str, BeforeValidator(_validate_sha256_hex)]


class BenchmarkReport(BaseModel):
    """Immutable aggregate evidence for one deterministic differential run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    runner_version: Literal["differential-benchmark-runner-v1"] = "differential-benchmark-runner-v1"
    generator_version: Literal["deterministic-market-generator-v1"] = (
        "deterministic-market-generator-v1"
    )
    fingerprint_version: Literal["sha256-clear-benchmark-records-v1"] = (
        "sha256-clear-benchmark-records-v1"
    )
    seller_count: _SellerCount
    seed_count: _PositiveCount
    seed_sequence_sha256: _Sha256Hex
    admission_attempt_count: _NonNegativeCount
    admission_rejection_count: _NonNegativeCount
    feasible_market_count: _NonNegativeCount
    infeasible_market_count: _NonNegativeCount
    differential_mismatch_count: _NonNegativeCount
    budget_violation_count: _NonNegativeCount
    allocation_quantity_violation_count: _NonNegativeCount
    winner_evidence_violation_count: _NonNegativeCount
    hard_failure_count: _NonNegativeCount
    failed_market_count: _NonNegativeCount
    failed_seeds: tuple[_GeneratorSeed, ...]
    reproducibility_fingerprint: _Sha256Hex

    @model_validator(mode="after")
    def _validate_count_consistency(self) -> Self:
        if self.feasible_market_count + self.infeasible_market_count != self.seed_count:
            raise ValueError("market status counts must cover every seed")
        if self.admission_rejection_count > self.admission_attempt_count:
            raise ValueError("admission rejections cannot exceed attempts")
        if self.differential_mismatch_count > self.seed_count:
            raise ValueError("differential mismatches cannot exceed markets")
        if self.budget_violation_count > self.feasible_market_count:
            raise ValueError("budget violations cannot exceed feasible markets")
        if self.allocation_quantity_violation_count > self.feasible_market_count:
            raise ValueError("quantity violations cannot exceed feasible markets")
        if self.winner_evidence_violation_count > self.feasible_market_count:
            raise ValueError("winner-evidence violations cannot exceed feasible markets")

        expected_hard_failures = (
            self.admission_rejection_count
            + self.differential_mismatch_count
            + self.budget_violation_count
            + self.allocation_quantity_violation_count
            + self.winner_evidence_violation_count
        )
        if self.hard_failure_count != expected_hard_failures:
            raise ValueError("hard failure count must equal the event-counter sum")
        if self.failed_market_count != len(self.failed_seeds):
            raise ValueError("failed market count must equal failed seed count")
        if self.failed_market_count > self.seed_count:
            raise ValueError("failed markets cannot exceed seed count")
        if len(set(self.failed_seeds)) != len(self.failed_seeds):
            raise ValueError("failed seeds must be unique")
        if self.hard_failure_count == 0 and (
            self.failed_market_count != 0 or self.failed_seeds != ()
        ):
            raise ValueError("zero hard failures require no failed markets")
        if self.hard_failure_count > 0 and self.failed_market_count == 0:
            raise ValueError("hard failures require at least one failed market")
        return self
