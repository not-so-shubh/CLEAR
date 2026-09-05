"""Frozen replacement execution entry point; R2 must never execute the holdout.

All Git, forensic, and selection checks finish before constructing the writer.
Execution has no retry, resume, cleanup, or alternate-partition path. An exception
leaves any partial output in place for external review before another decision.
"""

import argparse
import re
import subprocess
from collections.abc import Callable, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Final

from clear_market.agentmarketbench.final_evidence import (
    agent_market_bench_final_seed_sequence_digest_v1,
    canonical_agent_market_bench_final_json_v1_bytes,
)
from clear_market.agentmarketbench.final_models import AgentMarketBenchReplacementFinalManifestV1
from clear_market.agentmarketbench.generator import generate_agent_market_bench_case_v1
from clear_market.agentmarketbench.models import MAX_AGENT_MARKET_BENCH_SEED
from clear_market.agentmarketbench.replacement_final_evidence import (
    AgentMarketBenchReplacementFinalEvidenceWriterV1,
)
from clear_market.agentmarketbench.runner import run_agent_market_bench_case_v1
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

_FAILED_ATTEMPT_OUTPUT_RELATIVE_PATH_V1: Final[Path] = Path(
    "benchmarks/agentmarketbench_v1/final_holdout_v1"
)
_REPLACEMENT_FINAL_OUTPUT_RELATIVE_PATH_V1: Final[Path] = Path(
    "benchmarks/agentmarketbench_v1/replacement_final_holdout_v1"
)
_FAILED_ATTEMPT_FORENSIC_INVENTORY_V1: Final[tuple[tuple[str, str, int], ...]] = (
    (
        "semantic/part-00000.jsonl.gz",
        "469721352e81bcf09e5a3aab9b6fccf64b12157c432272735262b8214a51002c",
        513713,
    ),
    (
        "semantic/part-00001.jsonl.gz",
        "504193f372eba4afd5ff3edceb7809d354d92a909619ff6d4e13de6b2611d938",
        514291,
    ),
    (
        "semantic/part-00002.jsonl.gz",
        "a2a1c6de06c42211f477e1a9ec4daec4120b5fd03239aedf7d9ac5e0c67f0540",
        508694,
    ),
    (
        "semantic/part-00003.jsonl.gz",
        "1339a3d8d5df8566a4cd05316436221828e58d07bbb6057724d9001efb8ffd04",
        512863,
    ),
    (
        "semantic/part-00004.jsonl.gz",
        "76f5a336d888211c949523f69d6a0cb1d622c6c28774d9df54693e9bf2d9c92c",
        506889,
    ),
    (
        "semantic/part-00005.jsonl.gz",
        "b408f738feaf584d04432c4f63bdf58140e98f44f5374d311be8ffd7734d062f",
        513877,
    ),
    (
        "timing/part-00000.jsonl.gz",
        "cc9642aa0b91834fd286123f973261b15ff6643e7c734bc50f62925049ab184f",
        47582,
    ),
    (
        "timing/part-00001.jsonl.gz",
        "eabcd03f7dd2bef2af51c162710ebf8fe07b3e5c862a9ab6e9b9b3a49dcfd0bc",
        47687,
    ),
    (
        "timing/part-00002.jsonl.gz",
        "1f949487a7a2bce4f97caad49944357568bd308c60a989448b80539ed4cd6e86",
        47669,
    ),
    (
        "timing/part-00003.jsonl.gz",
        "909e53548b68a952c69c723f7802532368aa6415b3a444cfecf252ca35439453",
        47646,
    ),
    (
        "timing/part-00004.jsonl.gz",
        "d6d1a111188344087be5abbdbf058c1255d32e199933b1dc8bc86bbafc4a53a5",
        47619,
    ),
    (
        "timing/part-00005.jsonl.gz",
        "913a24de24ba04aa9f203e22a1415d44959122b1605816464cc3198b68d73205",
        47723,
    ),
)


def _git_output_v1(arguments: Sequence[str], *, cwd: Path) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(f"Git preflight failed: git {' '.join(arguments)}") from error
    return result.stdout


def _validate_frozen_replacement_selection_v1() -> None:
    """Check integer commitments only; never generate or inspect benchmark cases."""

    anchor = "a4fc224ba9b10b518753d05237ab7d56d737943b"
    if AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_V1_VERSION != (
        "agent-market-bench-replacement-holdout-selection-v1"
    ):
        raise ValueError("replacement selection version differs from the frozen commitment")
    if AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1 != anchor:
        raise ValueError("replacement selection anchor differs from the frozen commitment")
    preimage = f"CLEAR|AgentMarketBench|replacement-holdout-v1|{anchor}".encode("ascii")
    selection_digest = sha256(preimage).hexdigest()
    if (
        selection_digest != "babe2f63fe83fa6a67a63d0fc02c16a2a4cfcfc2fe04e4aa94a0e0af29b655f3"
        or AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1 != selection_digest
    ):
        raise ValueError("replacement selection SHA-256 differs from the frozen derivation")
    block_size = 10_000
    block_count = 40_000
    block_index = int(selection_digest, 16) % block_count
    if (
        block_index != 24_179
        or type(AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_BLOCK_INDEX_V1) is not int
        or AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_BLOCK_INDEX_V1 != block_index
    ):
        raise ValueError("replacement block index differs from the frozen derivation")
    start = 1_400_000_000 + block_index * block_size
    expected_seeds = tuple(range(start, start + block_size))
    seeds = AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1
    if (
        type(seeds) is not tuple
        or seeds != expected_seeds
        or any(type(seed) is not int for seed in seeds)
    ):
        raise ValueError("replacement seed tuple differs from the frozen derivation")
    expected_seed_digest = "9f255e0668f40a0b61a0ec79b5c25fac5682b5e374ee19cf854615c68187c422"
    if (
        AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEED_SEQUENCE_SHA256_V1 != expected_seed_digest
        or agent_market_bench_final_seed_sequence_digest_v1(seeds) != expected_seed_digest
    ):
        raise ValueError("replacement seed-sequence digest differs from the frozen commitment")
    if (
        seeds[-1] > MAX_AGENT_MARKET_BENCH_SEED
        or not set(seeds).isdisjoint(AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1)
        or not set(seeds).isdisjoint(range(500_000_000, 500_021_000))
        or not set(seeds).isdisjoint(AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1)
    ):
        raise ValueError("replacement seed partition violates the frozen exclusions")


def _validate_failed_attempt_inventory_v1(repository_root: Path) -> None:
    evidence_dir = repository_root / _FAILED_ATTEMPT_OUTPUT_RELATIVE_PATH_V1
    if evidence_dir.is_symlink() or not evidence_dir.is_dir():
        raise ValueError("preserved failed-attempt evidence directory is missing or invalid")
    expected_paths = {entry[0] for entry in _FAILED_ATTEMPT_FORENSIC_INVENTORY_V1}
    actual_paths: set[str] = set()
    for path in evidence_dir.rglob("*"):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise ValueError("failed-attempt inventory contains a nonregular entry")
        if path.is_file():
            actual_paths.add(path.relative_to(evidence_dir).as_posix())
    if actual_paths != expected_paths:
        raise ValueError("failed-attempt file inventory differs from the exact 12-file whitelist")
    for relative_path, expected_digest, expected_size in _FAILED_ATTEMPT_FORENSIC_INVENTORY_V1:
        content = (evidence_dir / relative_path).read_bytes()
        if len(content) != expected_size:
            raise ValueError(f"failed-attempt byte count mismatch: {relative_path}")
        if sha256(content).hexdigest() != expected_digest:
            raise ValueError(f"failed-attempt SHA-256 mismatch: {relative_path}")


def _replacement_final_preflight_v1(expected_source_commit: str) -> Path:
    if (
        type(expected_source_commit) is not str
        or re.fullmatch(r"[0-9a-f]{40}", expected_source_commit) is None
    ):
        raise ValueError("expected_source_commit must be an exact lowercase 40-hex commit")

    root_text = _git_output_v1(("rev-parse", "--show-toplevel"), cwd=Path.cwd()).strip()
    root_path = Path(root_text)
    if not root_text or not root_path.is_absolute() or not root_path.is_dir():
        raise ValueError("current path must resolve to a Git repository root")
    repository_root = root_path.resolve(strict=True)
    head = _git_output_v1(("rev-parse", "HEAD"), cwd=repository_root).strip()
    if head != expected_source_commit:
        raise ValueError("Git HEAD does not equal expected_source_commit")
    _git_output_v1(
        (
            "merge-base",
            "--is-ancestor",
            AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1,
            "HEAD",
        ),
        cwd=repository_root,
    )
    if _git_output_v1(("status", "--porcelain", "--untracked-files=no"), cwd=repository_root):
        raise ValueError("tracked working tree and index must be clean")
    untracked_output = _git_output_v1(
        ("ls-files", "--others", "--exclude-standard", "-z"), cwd=repository_root
    )
    if not untracked_output.endswith("\0"):
        raise ValueError("untracked files must equal the exact failed-attempt 12-file whitelist")
    untracked_paths = untracked_output[:-1].split("\0")
    expected_untracked_paths = {
        (_FAILED_ATTEMPT_OUTPUT_RELATIVE_PATH_V1 / relative_path).as_posix()
        for relative_path, _, _ in _FAILED_ATTEMPT_FORENSIC_INVENTORY_V1
    }
    if (
        len(untracked_paths) != len(expected_untracked_paths)
        or set(untracked_paths) != expected_untracked_paths
    ):
        raise ValueError("untracked files must equal the exact failed-attempt 12-file whitelist")
    _validate_failed_attempt_inventory_v1(repository_root)
    output_dir = repository_root / _REPLACEMENT_FINAL_OUTPUT_RELATIVE_PATH_V1
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError("replacement output path must not already exist")
    _validate_frozen_replacement_selection_v1()
    return output_dir


def run_agent_market_bench_replacement_final_holdout_v1(
    *,
    expected_source_commit: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> AgentMarketBenchReplacementFinalManifestV1:
    """Execute once only after the full preflight; preserve partial output on failure.

    R2 freezes this entry point without invoking it on any replacement seed.
    Every exception stops execution and requires external review before any
    second execution decision. Cases use the frozen runner's real default clock.
    """

    if progress_callback is not None and not callable(progress_callback):
        raise ValueError("progress_callback must be callable or None")
    output_dir = _replacement_final_preflight_v1(expected_source_commit)
    writer = AgentMarketBenchReplacementFinalEvidenceWriterV1(
        output_dir=output_dir,
        evaluated_source_commit=expected_source_commit,
    )
    total = len(AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1)
    for seed in AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1:
        case = generate_agent_market_bench_case_v1(seed)
        case_run = run_agent_market_bench_case_v1(case)
        writer.add_case_run(case_run)
        del case_run
        del case
        if progress_callback is not None:
            progress_callback(writer.processed_count, total)
    if writer.processed_count != total:
        raise ValueError("replacement writer processed count must equal the frozen seed count")
    return writer.finish()


def _print_progress_v1(processed_count: int, total: int) -> None:
    if processed_count % 500 == 0:
        print(f"progress={processed_count}/{total}", flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Frozen AgentMarketBench V1 replacement final holdout"
    )
    parser.add_argument("--expected-source-commit", required=True)
    arguments = parser.parse_args(argv)
    try:
        manifest = run_agent_market_bench_replacement_final_holdout_v1(
            expected_source_commit=arguments.expected_source_commit,
            progress_callback=_print_progress_v1,
        )
    except Exception as error:
        parser.exit(2, f"replacement final holdout stopped: {error}\n")
    print(f"case_count={manifest.case_count}")
    print(f"output_dir={_REPLACEMENT_FINAL_OUTPUT_RELATIVE_PATH_V1.as_posix()}")
    print(f"semantic_root_sha256={manifest.semantic_root_sha256}")
    print(f"timing_root_sha256={manifest.timing_root_sha256}")
    print(f"evidence_root_sha256={manifest.evidence_root_sha256}")
    print(
        f"manifest_sha256={sha256(canonical_agent_market_bench_final_json_v1_bytes(manifest)).hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ("run_agent_market_bench_replacement_final_holdout_v1",)
