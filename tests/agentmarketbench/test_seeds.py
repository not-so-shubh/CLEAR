"""Frozen AgentMarketBench V1 seed partition tests."""

import hashlib

from clear_market.agentmarketbench.models import MAX_AGENT_MARKET_BENCH_SEED
from clear_market.agentmarketbench.seeds import (
    AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1,
    AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_BLOCK_INDEX_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEED_SEQUENCE_SHA256_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_V1_VERSION,
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


def test_replacement_selection_recomputes_from_the_exact_ascii_preimage() -> None:
    preimage = (
        b"CLEAR|AgentMarketBench|replacement-holdout-v1|a4fc224ba9b10b518753d05237ab7d56d737943b"
    )
    assert b"\n" not in preimage
    assert AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_V1_VERSION == (
        "agent-market-bench-replacement-holdout-selection-v1"
    )
    assert AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1 == (
        "a4fc224ba9b10b518753d05237ab7d56d737943b"
    )
    digest = hashlib.sha256(preimage).hexdigest()
    assert digest == "babe2f63fe83fa6a67a63d0fc02c16a2a4cfcfc2fe04e4aa94a0e0af29b655f3"
    assert AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1 == digest
    block_index = int(digest, 16) % 40_000
    assert block_index == 24_179
    assert AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_BLOCK_INDEX_V1 == block_index
    assert type(AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_BLOCK_INDEX_V1) is int
    start = 1_400_000_000 + block_index * 10_000
    assert AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1 == tuple(range(start, start + 10_000))
    assert len(AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1) == 10_000
    assert AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1[0] == start
    assert AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1[-1] == start + 9_999


def test_replacement_seed_digest_uses_only_integer_ascii_lines_in_frozen_order() -> None:
    seeds = AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1
    payload = "".join(f"{seed}\n" for seed in seeds).encode("ascii")
    digest = hashlib.sha256(payload).hexdigest()
    assert digest == "9f255e0668f40a0b61a0ec79b5c25fac5682b5e374ee19cf854615c68187c422"
    assert AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEED_SEQUENCE_SHA256_V1 == digest
    assert type(seeds) is tuple
    assert all(type(seed) is int for seed in seeds)
    assert all(1_400_000_000 <= seed <= 1_799_999_999 for seed in seeds)
    assert all(0 <= seed <= MAX_AGENT_MARKET_BENCH_SEED for seed in seeds)
    assert tuple(sorted(set(seeds))) == seeds


def test_replacement_seeds_are_disjoint_from_all_frozen_exclusions() -> None:
    replacement = set(AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1)
    assert replacement.isdisjoint(AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1)
    assert replacement.isdisjoint(range(500_000_000, 500_021_000))
    assert replacement.isdisjoint(AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1)
