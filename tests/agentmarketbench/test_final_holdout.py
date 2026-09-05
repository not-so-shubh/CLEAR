import inspect
import subprocess
from pathlib import Path

import pytest

import clear_market.agentmarketbench.final_holdout as final_holdout_module
from clear_market.agentmarketbench.final_models import (
    AgentMarketBenchFinalEvidenceFileKindV1,
    AgentMarketBenchFinalEvidenceFileV1,
    AgentMarketBenchFinalManifestV1,
)

_COMMIT = "e3c0d06f5c07fe10b4ad62dc5575108f51be337c"
_SHA = "a" * 64


@pytest.fixture(autouse=True)
def _guard_final_holdout_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    original = final_holdout_module.generate_agent_market_bench_case_v1

    def guarded(seed: int):
        if seed >= 2_000_000_000:
            raise AssertionError("24E-A tests must not generate a final-holdout case")
        return original(seed)

    monkeypatch.setattr(final_holdout_module, "generate_agent_market_bench_case_v1", guarded)


def _file(
    relative_path: str,
    kind: AgentMarketBenchFinalEvidenceFileKindV1,
) -> AgentMarketBenchFinalEvidenceFileV1:
    is_shard = kind in {
        AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD,
        AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD,
    }
    return AgentMarketBenchFinalEvidenceFileV1(
        relative_path=relative_path,
        kind=kind,
        sha256=_SHA,
        byte_count=1,
        line_count=1,
        uncompressed_sha256="b" * 64 if is_shard else None,
        first_seed=100_000_000 if is_shard else None,
        last_seed=100_000_000 if is_shard else None,
    )


def _sentinel_manifest() -> AgentMarketBenchFinalManifestV1:
    files = tuple(
        sorted(
            (
                _file(
                    "semantic/part-00000.jsonl.gz",
                    AgentMarketBenchFinalEvidenceFileKindV1.SEMANTIC_SHARD,
                ),
                _file(
                    "timing/part-00000.jsonl.gz",
                    AgentMarketBenchFinalEvidenceFileKindV1.TIMING_SHARD,
                ),
                _file("summary.json", AgentMarketBenchFinalEvidenceFileKindV1.SUMMARY),
                _file("report.md", AgentMarketBenchFinalEvidenceFileKindV1.REPORT),
                _file("run_metadata.json", AgentMarketBenchFinalEvidenceFileKindV1.RUN_METADATA),
            ),
            key=lambda item: item.relative_path,
        )
    )
    return AgentMarketBenchFinalManifestV1(
        evaluated_source_commit=_COMMIT,
        case_count=1,
        first_seed=100_000_000,
        last_seed=100_000_000,
        seed_sequence_sha256=_SHA,
        shard_size=1,
        semantic_shard_count=1,
        timing_shard_count=1,
        semantic_root_sha256=_SHA,
        timing_root_sha256=_SHA,
        evidence_root_sha256=_SHA,
        files=files,
    )


def _fake_git(
    monkeypatch: pytest.MonkeyPatch,
    repository_root: Path,
    *,
    head: str = _COMMIT,
    status: str = "",
) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(command, **kwargs):
        calls.append(command)
        arguments = command[1:]
        if arguments == ["rev-parse", "--show-toplevel"]:
            stdout = f"{repository_root}\n"
        elif arguments == ["rev-parse", "HEAD"]:
            stdout = f"{head}\n"
        elif arguments == ["status", "--porcelain"]:
            stdout = status
        else:
            raise AssertionError(f"unexpected git invocation: {command}")
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(final_holdout_module.subprocess, "run", run)
    return calls


def test_final_runner_source_contract_and_direct_frozen_seed_use() -> None:
    source = inspect.getsource(final_holdout_module)
    assert "AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1" in source
    assert "generate_agent_market_bench_case_v1" in source
    assert "run_agent_market_bench_case_v1" in source
    assert "seeds = AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1" in source
    assert "AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1" not in source
    for forbidden in (
        "clear_market.benchmark",
        "clear_market.payments",
        "Razorpay",
        "clear_market.persistence",
        "clear_market.execution",
        "AIProvider",
        "import random",
        "import secrets",
        "requests",
        "urllib",
        "httpx",
    ):
        assert forbidden not in source
    signature = inspect.signature(final_holdout_module.run_agent_market_bench_final_holdout_v1)
    assert tuple(signature.parameters) == (
        "output_dir",
        "evaluated_source_commit",
        "progress_callback",
    )


@pytest.mark.parametrize("failure", ("wrong-head", "dirty", "existing-output"))
def test_cli_preflight_failure_never_calls_final_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    head = "b" * 40 if failure == "wrong-head" else _COMMIT
    status = " M source.py\n" if failure == "dirty" else ""
    _fake_git(monkeypatch, tmp_path, head=head, status=status)
    if failure == "existing-output":
        (tmp_path / "benchmarks/agentmarketbench_v1/final_holdout_v1").mkdir(parents=True)
    runner_calls = []

    def forbidden_runner(**kwargs):
        runner_calls.append(kwargs)
        raise AssertionError("final runner must not be called after failed preflight")

    monkeypatch.setattr(
        final_holdout_module,
        "run_agent_market_bench_final_holdout_v1",
        forbidden_runner,
    )
    with pytest.raises(SystemExit) as raised:
        final_holdout_module.main(["--expected-source-commit", _COMMIT])
    assert raised.value.code == 2
    assert runner_calls == []


def test_cli_invalid_expected_sha_never_calls_git_or_final_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    git_calls = []
    runner_calls = []
    monkeypatch.setattr(
        final_holdout_module.subprocess,
        "run",
        lambda *args, **kwargs: git_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        final_holdout_module,
        "run_agent_market_bench_final_holdout_v1",
        lambda **kwargs: runner_calls.append(kwargs),
    )
    with pytest.raises(SystemExit) as raised:
        final_holdout_module.main(["--expected-source-commit", "INVALID"])
    assert raised.value.code == 2
    assert git_calls == []
    assert runner_calls == []


def test_cli_clean_exact_head_calls_fake_final_runner_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    git_calls = _fake_git(monkeypatch, tmp_path)
    runner_calls = []
    sentinel = _sentinel_manifest()

    def fake_runner(**kwargs):
        runner_calls.append(kwargs)
        return sentinel

    monkeypatch.setattr(
        final_holdout_module,
        "run_agent_market_bench_final_holdout_v1",
        fake_runner,
    )
    assert final_holdout_module.main(["--expected-source-commit", _COMMIT]) == 0
    assert len(runner_calls) == 1
    assert runner_calls[0]["evaluated_source_commit"] == _COMMIT
    assert runner_calls[0]["output_dir"] == (
        tmp_path / "benchmarks/agentmarketbench_v1/final_holdout_v1"
    )
    assert callable(runner_calls[0]["progress_callback"])
    assert len(git_calls) == 3
    output = capsys.readouterr().out
    assert "processed_count=1" in output
    assert "semantic_root_sha256=" in output
    assert "timing_root_sha256=" in output
    assert "evidence_root_sha256=" in output
    assert "manifest_sha256=" in output
    assert "RANDOM_QUALIFYING_SELLER" not in output


def test_24e_tests_guard_against_final_seed_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    observed = []

    def guarded_generator(seed: int):
        observed.append(seed)
        if seed >= 2_000_000_000:
            raise AssertionError("24E-A tests must not generate a final-holdout case")
        return object()

    monkeypatch.setattr(
        final_holdout_module, "generate_agent_market_bench_case_v1", guarded_generator
    )
    guarded_generator(100_000_000)
    assert observed == [100_000_000]
