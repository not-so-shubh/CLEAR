"""Frozen AgentMarketBench V1 development and final-holdout seed partitions."""

from typing import Final

AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1: Final[tuple[int, ...]] = tuple(
    range(100_000_000, 100_001_008)
)
AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1: Final[tuple[int, ...]] = tuple(
    range(2_000_000_000, 2_000_010_000)
)

__all__ = (
    "AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1",
    "AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1",
)
