from typing import Final

MARKET_GENERATOR_VERSION: Final[str] = "deterministic-market-generator-v1"
MAX_GENERATOR_SEED: Final[int] = 2_147_483_647

DEVELOPMENT_SEEDS: Final[tuple[int, ...]] = tuple(range(0, 32))
FROZEN_EVALUATION_SEEDS: Final[tuple[int, ...]] = tuple(range(1_000_000, 1_010_000))
