import inspect
import subprocess
from pathlib import Path

import pytest

import clear_market.agentmarketbench.final_evidence as final_evidence_module
import clear_market.agentmarketbench.final_holdout as final_holdout_module
import clear_market.agentmarketbench.generator as generator_module
import clear_market.agentmarketbench.runner as runner_module
import clear_market.agentmarketbench.seeds as seeds_module

_COMMIT = "93073144db6128d7e23558545e5d544e350ad292"
_RETIREMENT_REASON = (
    "original AgentMarketBench final holdout partition is retired after failed attempt 1; "
    "a reviewed replacement holdout is required"
)


@pytest.fixture(autouse=True)
def _block_final_execution(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = dict.fromkeys(("generator", "writer", "runner", "seeds", "git"), 0)

    def forbidden_generator(seed: int):
        calls["generator"] += 1
        if seed >= 2_000_000_000:
            raise AssertionError("retired final-holdout seeds must never be generated")
        raise AssertionError("retired runner must never invoke any generator")

    def forbidden_writer(*args, **kwargs):
        calls["writer"] += 1
        raise AssertionError("retired runner must never construct an evidence writer")

    def forbidden_runner(*args, **kwargs):
        calls["runner"] += 1
        raise AssertionError("retired runner must never evaluate a case")

    def forbidden_git(*args, **kwargs):
        calls["git"] += 1
        raise AssertionError("repository state must not mask the retirement reason")

    class ForbiddenSeeds:
        def __iter__(self):
            calls["seeds"] += 1
            raise AssertionError("retired runner must never iterate final seeds")

    forbidden_seeds = ForbiddenSeeds()
    # Guard both definition sites and former runner aliases, including aliases that
    # a future edit might accidentally restore.
    for module in (generator_module, final_holdout_module):
        monkeypatch.setattr(
            module, "generate_agent_market_bench_case_v1", forbidden_generator, raising=False
        )
    for module in (final_evidence_module, final_holdout_module):
        monkeypatch.setattr(
            module, "_AgentMarketBenchEvidenceBundleWriterV1", forbidden_writer, raising=False
        )
    for module in (runner_module, final_holdout_module):
        monkeypatch.setattr(
            module, "run_agent_market_bench_case_v1", forbidden_runner, raising=False
        )
    for module in (seeds_module, final_holdout_module):
        monkeypatch.setattr(
            module,
            "AGENT_MARKET_BENCH_FINAL_HOLDOUT_SEEDS_V1",
            forbidden_seeds,
            raising=False,
        )
    monkeypatch.setattr(subprocess, "run", forbidden_git)
    return calls


def test_retired_api_preserves_public_signature() -> None:
    signature = inspect.signature(final_holdout_module.run_agent_market_bench_final_holdout_v1)
    assert tuple(signature.parameters) == (
        "output_dir",
        "evaluated_source_commit",
        "progress_callback",
    )


@pytest.mark.parametrize("existing_output", (False, True))
def test_retired_api_never_generates_or_creates_output(
    tmp_path: Path,
    existing_output: bool,
    _block_final_execution: dict[str, int],
) -> None:
    output_dir = tmp_path / "final_holdout_v1"
    if existing_output:
        output_dir.mkdir()
    progress_calls = []
    with pytest.raises(ValueError) as raised:
        final_holdout_module.run_agent_market_bench_final_holdout_v1(
            output_dir=output_dir,
            evaluated_source_commit=_COMMIT,
            progress_callback=lambda *args: progress_calls.append(args),
        )
    assert str(raised.value) == _RETIREMENT_REASON
    assert output_dir.exists() is existing_output
    assert list(tmp_path.rglob("*")) == ([output_dir] if existing_output else [])
    assert progress_calls == []
    assert _block_final_execution == dict.fromkeys(_block_final_execution, 0)


def test_retired_api_fails_before_argument_or_filesystem_validation(
    monkeypatch: pytest.MonkeyPatch,
    _block_final_execution: dict[str, int],
) -> None:
    def forbidden_path_access(*args, **kwargs):
        raise AssertionError("retirement must precede output-path access")

    with monkeypatch.context() as path_guard:
        path_guard.setattr(Path, "exists", forbidden_path_access)
        path_guard.setattr(Path, "mkdir", forbidden_path_access)
        with pytest.raises(ValueError) as raised:
            final_holdout_module.run_agent_market_bench_final_holdout_v1(
                output_dir="not-a-path",  # type: ignore[arg-type]
                evaluated_source_commit="INVALID",
                progress_callback=object(),  # type: ignore[arg-type]
            )
    assert str(raised.value) == _RETIREMENT_REASON
    assert _block_final_execution == dict.fromkeys(_block_final_execution, 0)


@pytest.mark.parametrize("commit", (_COMMIT, "INVALID"))
def test_retired_cli_exits_nonzero_before_preflight_or_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    commit: str,
    _block_final_execution: dict[str, int],
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as raised:
        final_holdout_module.main(["--expected-source-commit", commit])
    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert captured.err == f"{_RETIREMENT_REASON}\n"
    assert captured.out == ""
    assert list(tmp_path.rglob("*")) == []
    assert _block_final_execution == dict.fromkeys(_block_final_execution, 0)
