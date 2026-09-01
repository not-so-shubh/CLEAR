"""Deterministic benchmark input generation for CLEAR."""

from clear_market.benchmark.generator import generate_market_case
from clear_market.benchmark.models import GeneratedAdmissionAttempt, GeneratedMarketCase
from clear_market.benchmark.report import (
    BENCHMARK_FINGERPRINT_VERSION,
    BENCHMARK_RUNNER_VERSION,
    BenchmarkHardFailureCode,
    BenchmarkReport,
)
from clear_market.benchmark.runner import run_differential_benchmark
from clear_market.benchmark.seeds import (
    DEVELOPMENT_SEEDS,
    FROZEN_EVALUATION_SEEDS,
    MARKET_GENERATOR_VERSION,
    MAX_GENERATOR_SEED,
)

__all__ = (
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
