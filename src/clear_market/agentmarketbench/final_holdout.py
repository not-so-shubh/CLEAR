"""One-case-at-a-time AgentMarketBench V1 final-holdout evidence runner."""

import argparse
import re
import subprocess
from collections.abc import Callable, Sequence
from hashlib import sha256
from pathlib import Path

from clear_market.agentmarketbench.final_evidence import (
    _AgentMarketBenchEvidenceBundleWriterV1,
    canonical_agent_market_bench_final_json_v1_bytes,
)
from clear_market.agentmarketbench.final_models import AgentMarketBenchFinalManifestV1
from clear_market.agentmarketbench.generator import generate_agent_market_bench_case_v1
from clear_market.agentmarketbench.runner import run_agent_market_bench_case_v1
from clear_market.agentmarketbench.seeds import AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1

_FINAL_OUTPUT_RELATIVE = Path("benchmarks/agentmarketbench_v1/final_holdout_v1")
_FINAL_CASE_COUNT = 10_000
_FINAL_FIRST_SEED = 2_000_000_000
_FINAL_LAST_SEED = 2_000_009_999
_FINAL_SHARD_SIZE = 500


def _validate_commit(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("expected source commit must be an exact lowercase 40-hex SHA")
    return value


def _require_final_seed_contract() -> tuple[int, ...]:
    seeds = AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1
    expected = tuple(range(_FINAL_FIRST_SEED, _FINAL_LAST_SEED + 1))
    if (
        type(seeds) is not tuple
        or len(seeds) != _FINAL_CASE_COUNT
        or seeds[0] != _FINAL_FIRST_SEED
        or seeds[-1] != _FINAL_LAST_SEED
        or seeds != expected
    ):
        raise ValueError("frozen final-holdout seed tuple contract failed")
    return seeds


def run_agent_market_bench_final_holdout_v1(
    *,
    output_dir: Path,
    evaluated_source_commit: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> AgentMarketBenchFinalManifestV1:
    """Execute the frozen final partition once and publish a verified manifest last."""

    if not isinstance(output_dir, Path):
        raise TypeError("output_dir must be a pathlib.Path")
    commit = _validate_commit(evaluated_source_commit)
    if progress_callback is not None and not callable(progress_callback):
        raise TypeError("progress_callback must be callable or None")
    if output_dir.exists():
        raise ValueError("output_dir must not exist")
    seeds = _require_final_seed_contract()
    writer = _AgentMarketBenchEvidenceBundleWriterV1(
        output_dir=output_dir,
        evaluated_source_commit=commit,
        seeds=seeds,
        shard_size=_FINAL_SHARD_SIZE,
        require_final=True,
    )
    for seed in seeds:
        case = generate_agent_market_bench_case_v1(seed)
        case_run = run_agent_market_bench_case_v1(case)
        writer.add_case_run(case_run)
        if progress_callback is not None and writer.processed_count % _FINAL_SHARD_SIZE == 0:
            progress_callback(writer.processed_count, _FINAL_CASE_COUNT)
    if writer.processed_count != _FINAL_CASE_COUNT:
        raise ValueError("final holdout did not process exactly 10,000 cases")
    return writer.finish()


def _git_output(arguments: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _cli_preflight(expected_source_commit: str) -> tuple[Path, Path]:
    commit = _validate_commit(expected_source_commit)
    repository_root = Path(_git_output(["rev-parse", "--show-toplevel"])).resolve()
    head = _git_output(["rev-parse", "HEAD"], cwd=repository_root)
    if head != commit:
        raise ValueError("repository HEAD does not equal --expected-source-commit")
    if _git_output(["status", "--porcelain"], cwd=repository_root):
        raise ValueError("repository working tree must be completely clean")
    output_dir = repository_root / _FINAL_OUTPUT_RELATIVE
    if output_dir.exists():
        raise ValueError("frozen final evidence output directory already exists")
    return repository_root, output_dir


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run frozen AgentMarketBench V1 final evidence")
    parser.add_argument("--expected-source-commit", required=True)
    arguments = parser.parse_args(argv)
    try:
        _, output_dir = _cli_preflight(arguments.expected_source_commit)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        parser.exit(2, f"AgentMarketBench final holdout preflight failed: {error}\n")

    def progress(processed_count: int, total_count: int) -> None:
        print(f"AgentMarketBench final holdout: {processed_count}/{total_count}")

    manifest = run_agent_market_bench_final_holdout_v1(
        output_dir=output_dir,
        evaluated_source_commit=arguments.expected_source_commit,
        progress_callback=progress,
    )
    manifest_sha256 = sha256(canonical_agent_market_bench_final_json_v1_bytes(manifest)).hexdigest()
    print(f"processed_count={manifest.case_count}")
    print(f"output_directory={_FINAL_OUTPUT_RELATIVE.as_posix()}")
    print(f"semantic_root_sha256={manifest.semantic_root_sha256}")
    print(f"timing_root_sha256={manifest.timing_root_sha256}")
    print(f"evidence_root_sha256={manifest.evidence_root_sha256}")
    print(f"manifest_sha256={manifest_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ("run_agent_market_bench_final_holdout_v1",)
