"""Frozen AgentMarketBench V1 seed partition tests."""

from clear_market.agentmarketbench.models import MAX_AGENT_MARKET_BENCH_SEED
from clear_market.agentmarketbench.seeds import (
    AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1,
    AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1,
)


def test_seed_partitions_are_exact() -> None:
    assert AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1 == tuple(range(100_000_000, 100_001_008))
    assert AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1 == tuple(range(2_000_000_000, 2_000_010_000))


def test_seed_partition_sizes_and_endpoints_are_frozen() -> None:
    assert len(AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1) == 1_008
    assert AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1[0] == 100_000_000
    assert AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1[-1] == 100_001_007
    assert len(AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1) == 10_000
    assert AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1[0] == 2_000_000_000
    assert AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1[-1] == 2_000_009_999


def test_seed_partitions_are_mutually_and_historically_disjoint() -> None:
    development = set(AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1)
    holdout = set(AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1)
    assert development.isdisjoint(holdout)
    assert development.isdisjoint(range(0, 32))
    assert holdout.isdisjoint(range(0, 32))
    assert development.isdisjoint(range(1_000_000, 1_010_000))
    assert holdout.isdisjoint(range(1_000_000, 1_010_000))


def test_all_partition_values_are_exact_bounded_ints_not_bool() -> None:
    values = AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1 + AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1
    assert all(type(seed) is int for seed in values)
    assert all(0 <= seed <= MAX_AGENT_MARKET_BENCH_SEED for seed in values)
