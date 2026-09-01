import hashlib

import pytest

from clear_market.benchmark import (
    BENCHMARK_FINGERPRINT_VERSION,
    DEVELOPMENT_SEEDS,
    MAX_GENERATOR_SEED,
    BenchmarkReport,
    run_differential_benchmark,
)
from clear_market.canonical import canonical_json_bytes
from clear_market.domain import MAX_SELLERS, MIN_SELLERS


def _aggregate_counts(report: BenchmarkReport) -> tuple[int, ...]:
    return (
        report.admission_attempt_count,
        report.admission_rejection_count,
        report.feasible_market_count,
        report.infeasible_market_count,
        report.differential_mismatch_count,
        report.budget_violation_count,
        report.allocation_quantity_violation_count,
        report.winner_evidence_violation_count,
        report.hard_failure_count,
        report.failed_market_count,
    )


@pytest.mark.parametrize("seeds", [(0,), (0, 23)])
def test_runner_accepts_nonempty_development_seed_tuples(seeds: tuple[int, ...]) -> None:
    assert run_differential_benchmark(seeds).seed_count == len(seeds)


@pytest.mark.parametrize("seller_count", [MIN_SELLERS, 5, MAX_SELLERS])
def test_runner_accepts_seller_count_bounds(seller_count: int) -> None:
    report = run_differential_benchmark((0,), seller_count=seller_count)

    assert report.seller_count == seller_count


@pytest.mark.parametrize("seeds", [[], "0"])
def test_runner_rejects_non_tuple_seed_collections(seeds: object) -> None:
    with pytest.raises(TypeError):
        run_differential_benchmark(seeds)


@pytest.mark.parametrize("seed", [True, False, 1.0, "1"])
def test_runner_rejects_non_exact_integer_seed(seed: object) -> None:
    with pytest.raises(TypeError):
        run_differential_benchmark((seed,))


@pytest.mark.parametrize("seller_count", [True, False, 5.0, "5"])
def test_runner_rejects_non_exact_integer_seller_count(seller_count: object) -> None:
    with pytest.raises(TypeError):
        run_differential_benchmark((0,), seller_count=seller_count)


def test_runner_rejects_empty_seed_tuple() -> None:
    with pytest.raises(ValueError):
        run_differential_benchmark(())


def test_runner_rejects_duplicate_seeds() -> None:
    with pytest.raises(ValueError):
        run_differential_benchmark((0, 0))


@pytest.mark.parametrize("seed", [-1, MAX_GENERATOR_SEED + 1])
def test_runner_rejects_out_of_range_seed(seed: int) -> None:
    with pytest.raises(ValueError):
        run_differential_benchmark((seed,))


@pytest.mark.parametrize("seller_count", [MIN_SELLERS - 1, MAX_SELLERS + 1])
def test_runner_rejects_out_of_range_seller_count(seller_count: int) -> None:
    with pytest.raises(ValueError):
        run_differential_benchmark((0,), seller_count=seller_count)


def test_golden_development_seeds_zero_and_twenty_three_have_exact_structure() -> None:
    report = run_differential_benchmark((0, 23))

    assert report.seed_count == 2
    assert report.seller_count == 5
    assert report.admission_attempt_count == 2
    assert report.admission_rejection_count == 0
    assert report.feasible_market_count == 1
    assert report.infeasible_market_count == 1
    assert report.differential_mismatch_count == 0
    assert report.budget_violation_count == 0
    assert report.allocation_quantity_violation_count == 0
    assert report.winner_evidence_violation_count == 0
    assert report.hard_failure_count == 0
    assert report.failed_market_count == 0
    assert report.failed_seeds == ()


def test_seed_sequence_hash_follows_exact_canonical_contract() -> None:
    seeds = (0, 23)
    expected = hashlib.sha256(
        canonical_json_bytes(
            {
                "fingerprint_version": BENCHMARK_FINGERPRINT_VERSION,
                "seed_sequence": list(seeds),
            }
        )
    ).hexdigest()

    assert run_differential_benchmark(seeds).seed_sequence_sha256 == expected


def test_all_development_seeds_have_zero_hard_failures() -> None:
    report = run_differential_benchmark(DEVELOPMENT_SEEDS)

    assert report.seed_count == 32
    assert report.hard_failure_count == 0
    assert report.failed_market_count == 0
    assert report.failed_seeds == ()
    assert report.feasible_market_count + report.infeasible_market_count == 32


@pytest.mark.parametrize("seeds", [(0,), (0, 23), DEVELOPMENT_SEEDS])
def test_development_benchmark_reports_are_deterministic(seeds: tuple[int, ...]) -> None:
    assert run_differential_benchmark(seeds) == run_differential_benchmark(seeds)


def test_seed_order_changes_both_fingerprints_but_not_aggregate_counts() -> None:
    forward = run_differential_benchmark((0, 23))
    reverse = run_differential_benchmark((23, 0))

    assert _aggregate_counts(forward) == _aggregate_counts(reverse)
    assert forward.seed_sequence_sha256 != reverse.seed_sequence_sha256
    assert forward.reproducibility_fingerprint != reverse.reproducibility_fingerprint


def test_seller_count_changes_report_and_reproducibility_fingerprint() -> None:
    two_sellers = run_differential_benchmark((0,), seller_count=2)
    five_sellers = run_differential_benchmark((0,), seller_count=5)

    assert two_sellers.seller_count != five_sellers.seller_count
    assert two_sellers.reproducibility_fingerprint != five_sellers.reproducibility_fingerprint
