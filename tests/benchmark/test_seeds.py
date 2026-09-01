import clear_market.benchmark as benchmark
from clear_market.benchmark import (
    DEVELOPMENT_SEEDS,
    FROZEN_EVALUATION_SEEDS,
    MARKET_GENERATOR_VERSION,
    MAX_GENERATOR_SEED,
)


def test_benchmark_public_api_is_exact() -> None:
    assert benchmark.__all__ == (
        "BENCHMARK_FINGERPRINT_VERSION",
        "BENCHMARK_RUNNER_VERSION",
        "DEVELOPMENT_SEEDS",
        "FROZEN_EVALUATION_SEEDS",
        "MARKET_GENERATOR_VERSION",
        "MAX_GENERATOR_SEED",
        "BenchmarkHardFailureCode",
        "BenchmarkReport",
        "GeneratedAdmissionAttempt",
        "GeneratedMarketCase",
        "generate_market_case",
        "run_differential_benchmark",
    )


def test_generator_protocol_constants_are_exact() -> None:
    assert MARKET_GENERATOR_VERSION == "deterministic-market-generator-v1"
    assert MAX_GENERATOR_SEED == 2_147_483_647


def test_development_seeds_are_exact() -> None:
    assert DEVELOPMENT_SEEDS == tuple(range(0, 32))
    assert len(DEVELOPMENT_SEEDS) == 32


def test_frozen_evaluation_seeds_are_exact() -> None:
    assert FROZEN_EVALUATION_SEEDS == tuple(range(1_000_000, 1_010_000))
    assert len(FROZEN_EVALUATION_SEEDS) == 10_000
    assert FROZEN_EVALUATION_SEEDS[0] == 1_000_000
    assert FROZEN_EVALUATION_SEEDS[-1] == 1_009_999


def test_development_and_evaluation_seeds_are_disjoint() -> None:
    assert set(DEVELOPMENT_SEEDS).isdisjoint(FROZEN_EVALUATION_SEEDS)
