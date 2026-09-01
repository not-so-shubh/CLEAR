"""Deterministic benchmark input generation for CLEAR."""

from clear_market.benchmark.generator import generate_market_case
from clear_market.benchmark.models import GeneratedAdmissionAttempt, GeneratedMarketCase
from clear_market.benchmark.seeds import (
    DEVELOPMENT_SEEDS,
    FROZEN_EVALUATION_SEEDS,
    MARKET_GENERATOR_VERSION,
    MAX_GENERATOR_SEED,
)

__all__ = (
    "DEVELOPMENT_SEEDS",
    "FROZEN_EVALUATION_SEEDS",
    "MARKET_GENERATOR_VERSION",
    "MAX_GENERATOR_SEED",
    "GeneratedAdmissionAttempt",
    "GeneratedMarketCase",
    "generate_market_case",
)
