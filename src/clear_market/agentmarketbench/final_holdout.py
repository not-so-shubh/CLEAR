"""Permanently retired entry points for the opened original final partition."""

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from clear_market.agentmarketbench.final_models import AgentMarketBenchFinalManifestV1

_RETIRED_FINAL_HOLDOUT_MESSAGE = (
    "original AgentMarketBench final holdout partition is retired after failed attempt 1; "
    "a reviewed replacement holdout is required"
)


def run_agent_market_bench_final_holdout_v1(
    *,
    output_dir: Path,
    evaluated_source_commit: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> AgentMarketBenchFinalManifestV1:
    """Reject every invocation without accessing output paths or generating cases."""

    raise ValueError(_RETIRED_FINAL_HOLDOUT_MESSAGE)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Retired original AgentMarketBench V1 final holdout"
    )
    parser.add_argument("--expected-source-commit", required=True)
    parser.parse_args(argv)
    parser.exit(2, f"{_RETIRED_FINAL_HOLDOUT_MESSAGE}\n")


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ("run_agent_market_bench_final_holdout_v1",)
