import pytest
from pydantic import ValidationError

from clear_market.benchmark import (
    BENCHMARK_FINGERPRINT_VERSION,
    BENCHMARK_RUNNER_VERSION,
    BenchmarkHardFailureCode,
    BenchmarkReport,
)
from clear_market.domain import MAX_SELLERS, MIN_SELLERS

_HASH_A = "a" * 64
_HASH_B = "b" * 64
_COUNT_FIELDS = (
    "admission_attempt_count",
    "admission_rejection_count",
    "feasible_market_count",
    "infeasible_market_count",
    "differential_mismatch_count",
    "budget_violation_count",
    "allocation_quantity_violation_count",
    "winner_evidence_violation_count",
    "hard_failure_count",
    "failed_market_count",
)


def _report(**updates: object) -> BenchmarkReport:
    values: dict[str, object] = {
        "seller_count": 5,
        "seed_count": 2,
        "seed_sequence_sha256": _HASH_A,
        "admission_attempt_count": 2,
        "admission_rejection_count": 0,
        "feasible_market_count": 1,
        "infeasible_market_count": 1,
        "differential_mismatch_count": 0,
        "budget_violation_count": 0,
        "allocation_quantity_violation_count": 0,
        "winner_evidence_violation_count": 0,
        "hard_failure_count": 0,
        "failed_market_count": 0,
        "failed_seeds": (),
        "reproducibility_fingerprint": _HASH_B,
    }
    values.update(updates)
    return BenchmarkReport.model_validate(values)


def test_benchmark_versions_are_exact() -> None:
    assert BENCHMARK_RUNNER_VERSION == "differential-benchmark-runner-v1"
    assert BENCHMARK_FINGERPRINT_VERSION == "sha256-clear-benchmark-records-v1"


def test_hard_failure_enum_is_exact() -> None:
    assert tuple(BenchmarkHardFailureCode) == (
        BenchmarkHardFailureCode.ADMISSION_REJECTION,
        BenchmarkHardFailureCode.DIFFERENTIAL_MISMATCH,
        BenchmarkHardFailureCode.BUDGET_EXCEEDED,
        BenchmarkHardFailureCode.ALLOCATION_QUANTITY_MISMATCH,
        BenchmarkHardFailureCode.WINNER_EVIDENCE_MISMATCH,
    )
    assert tuple(member.value for member in BenchmarkHardFailureCode) == (
        "admission_rejection",
        "differential_mismatch",
        "budget_exceeded",
        "allocation_quantity_mismatch",
        "winner_evidence_mismatch",
    )


def test_report_has_exact_fields_and_protocol_defaults() -> None:
    report = _report()

    assert tuple(BenchmarkReport.model_fields) == (
        "schema_version",
        "runner_version",
        "generator_version",
        "fingerprint_version",
        "seller_count",
        "seed_count",
        "seed_sequence_sha256",
        "admission_attempt_count",
        "admission_rejection_count",
        "feasible_market_count",
        "infeasible_market_count",
        "differential_mismatch_count",
        "budget_violation_count",
        "allocation_quantity_violation_count",
        "winner_evidence_violation_count",
        "hard_failure_count",
        "failed_market_count",
        "failed_seeds",
        "reproducibility_fingerprint",
    )
    assert report.schema_version == "1"
    assert report.runner_version == BENCHMARK_RUNNER_VERSION
    assert report.generator_version == "deterministic-market-generator-v1"
    assert report.fingerprint_version == BENCHMARK_FINGERPRINT_VERSION


def test_report_is_frozen_and_forbids_extra_fields() -> None:
    report = _report()

    assert BenchmarkReport.model_config["frozen"] is True
    assert BenchmarkReport.model_config["extra"] == "forbid"
    with pytest.raises(ValidationError):
        report.seed_count = 3
    with pytest.raises(ValidationError):
        _report(unexpected=True)


@pytest.mark.parametrize("seller_count", [MIN_SELLERS, MAX_SELLERS])
def test_report_accepts_seller_count_bounds(seller_count: int) -> None:
    assert _report(seller_count=seller_count).seller_count == seller_count


@pytest.mark.parametrize("seller_count", [True, False, 5.0, "5"])
def test_report_rejects_non_exact_integer_seller_count(seller_count: object) -> None:
    with pytest.raises(ValidationError):
        _report(seller_count=seller_count)


@pytest.mark.parametrize("seller_count", [MIN_SELLERS - 1, MAX_SELLERS + 1])
def test_report_rejects_out_of_range_seller_count(seller_count: int) -> None:
    with pytest.raises(ValidationError):
        _report(seller_count=seller_count)


@pytest.mark.parametrize("seed_count", [True, False, 1.0, "1", 0, -1])
def test_report_requires_strict_positive_seed_count(seed_count: object) -> None:
    with pytest.raises(ValidationError):
        _report(seed_count=seed_count)


@pytest.mark.parametrize(
    "value",
    [
        "A" * 64,
        "a" * 63,
        "a" * 65,
        "sha256:" + "a" * 64,
        "a" * 63 + " ",
        b"a" * 64,
        1,
        None,
    ],
)
@pytest.mark.parametrize("field", ["seed_sequence_sha256", "reproducibility_fingerprint"])
def test_report_rejects_noncanonical_hashes(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _report(**{field: value})


@pytest.mark.parametrize("field", _COUNT_FIELDS)
@pytest.mark.parametrize("value", [True, False, 1.0, "1", -1])
def test_report_count_fields_are_strict_nonnegative_integers(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        _report(**{field: value})


def test_report_requires_market_status_counts_to_equal_seed_count() -> None:
    with pytest.raises(ValidationError):
        _report(feasible_market_count=2)


def test_report_rejects_more_rejections_than_attempts() -> None:
    with pytest.raises(ValidationError):
        _report(admission_attempt_count=1, admission_rejection_count=2, hard_failure_count=2)


def test_report_rejects_more_differential_mismatches_than_seeds() -> None:
    with pytest.raises(ValidationError):
        _report(differential_mismatch_count=3, hard_failure_count=3)


@pytest.mark.parametrize(
    "field",
    [
        "budget_violation_count",
        "allocation_quantity_violation_count",
        "winner_evidence_violation_count",
    ],
)
def test_report_rejects_more_feasible_only_violations_than_feasible_markets(field: str) -> None:
    with pytest.raises(ValidationError):
        _report(**{field: 2, "hard_failure_count": 2})


def test_report_requires_hard_failure_count_to_equal_event_sum() -> None:
    with pytest.raises(ValidationError):
        _report(hard_failure_count=1)


def test_report_requires_failed_market_count_to_equal_failed_seed_length() -> None:
    with pytest.raises(ValidationError):
        _report(failed_market_count=1)


def test_report_rejects_failed_market_count_above_seed_count() -> None:
    with pytest.raises(ValidationError):
        _report(
            admission_attempt_count=3,
            admission_rejection_count=3,
            hard_failure_count=3,
            failed_market_count=3,
            failed_seeds=(0, 1, 2),
        )


def test_report_rejects_duplicate_failed_seeds() -> None:
    with pytest.raises(ValidationError):
        _report(
            admission_rejection_count=1,
            hard_failure_count=1,
            failed_market_count=2,
            failed_seeds=(0, 0),
        )


@pytest.mark.parametrize("failed_seed", [True, 1.0, "1", -1, 2_147_483_648])
def test_report_failed_seeds_are_strict_bounded_generator_seeds(failed_seed: object) -> None:
    with pytest.raises(ValidationError):
        _report(
            admission_rejection_count=1,
            hard_failure_count=1,
            failed_market_count=1,
            failed_seeds=(failed_seed,),
        )


def test_zero_hard_failures_require_empty_failed_seeds() -> None:
    with pytest.raises(ValidationError):
        _report(failed_market_count=1, failed_seeds=(0,))


def test_positive_hard_failures_require_a_failed_market() -> None:
    with pytest.raises(ValidationError):
        _report(admission_rejection_count=1, hard_failure_count=1)


def test_consistent_positive_failure_report_is_accepted() -> None:
    report = _report(
        admission_rejection_count=1,
        hard_failure_count=1,
        failed_market_count=1,
        failed_seeds=(0,),
    )

    assert report.failed_seeds == (0,)
