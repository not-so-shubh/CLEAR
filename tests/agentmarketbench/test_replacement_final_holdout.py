import inspect
import subprocess
import weakref
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

import clear_market.agentmarketbench.generator as generator_module
import clear_market.agentmarketbench.replacement_final_evidence as replacement_evidence_module
import clear_market.agentmarketbench.replacement_final_holdout as replacement_holdout_module
import clear_market.agentmarketbench.runner as runner_module
from clear_market.agentmarketbench.seeds import (
    AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1,
    AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1,
)

_COMMIT = "a4fc224ba9b10b518753d05237ab7d56d737943b"
_FAILED_RELATIVE = Path("benchmarks/agentmarketbench_v1/final_holdout_v1")
_OUTPUT_RELATIVE = Path("benchmarks/agentmarketbench_v1/replacement_final_holdout_v1")
_REPLACEMENT_SEED_SET = frozenset(AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1)
_DEVELOPMENT_FIXTURE = AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1[:3]
_EXPECTED_FORENSIC_DIGESTS_AND_SIZES = (
    ("469721352e81bcf09e5a3aab9b6fccf64b12157c432272735262b8214a51002c", 513713),
    ("504193f372eba4afd5ff3edceb7809d354d92a909619ff6d4e13de6b2611d938", 514291),
    ("a2a1c6de06c42211f477e1a9ec4daec4120b5fd03239aedf7d9ac5e0c67f0540", 508694),
    ("1339a3d8d5df8566a4cd05316436221828e58d07bbb6057724d9001efb8ffd04", 512863),
    ("76f5a336d888211c949523f69d6a0cb1d622c6c28774d9df54693e9bf2d9c92c", 506889),
    ("b408f738feaf584d04432c4f63bdf58140e98f44f5374d311be8ffd7734d062f", 513877),
    ("cc9642aa0b91834fd286123f973261b15ff6643e7c734bc50f62925049ab184f", 47582),
    ("eabcd03f7dd2bef2af51c162710ebf8fe07b3e5c862a9ab6e9b9b3a49dcfd0bc", 47687),
    ("1f949487a7a2bce4f97caad49944357568bd308c60a989448b80539ed4cd6e86", 47669),
    ("909e53548b68a952c69c723f7802532368aa6415b3a444cfecf252ca35439453", 47646),
    ("d6d1a111188344087be5abbdbf058c1255d32e199933b1dc8bc86bbafc4a53a5", 47619),
    ("913a24de24ba04aa9f203e22a1415d44959122b1605816464cc3198b68d73205", 47723),
)
_FORENSIC_PATHS = tuple(
    f"{kind}/part-{index:05d}.jsonl.gz" for kind in ("semantic", "timing") for index in range(6)
)


@pytest.fixture(autouse=True)
def _forbid_production_execution(monkeypatch: pytest.MonkeyPatch):
    calls = dict.fromkeys(("generator", "runner", "writer"), 0)

    def forbidden_generator(seed):
        calls["generator"] += 1
        raise AssertionError(f"unpatched generator is forbidden in R2 runner tests: {seed}")

    def forbidden_runner(*args, **kwargs):
        calls["runner"] += 1
        raise AssertionError("unpatched benchmark execution is forbidden in R2 runner tests")

    def forbidden_writer(*args, **kwargs):
        calls["writer"] += 1
        raise AssertionError(
            "production replacement writer must not be constructed in runner tests"
        )

    def forbidden_git(*args, **kwargs):
        raise AssertionError("runner tests must never use the real repository Git state")

    for module in (generator_module, replacement_holdout_module):
        monkeypatch.setattr(module, "generate_agent_market_bench_case_v1", forbidden_generator)
    for module in (runner_module, replacement_holdout_module):
        monkeypatch.setattr(module, "run_agent_market_bench_case_v1", forbidden_runner)
    for module in (replacement_evidence_module, replacement_holdout_module):
        monkeypatch.setattr(
            module, "AgentMarketBenchReplacementFinalEvidenceWriterV1", forbidden_writer
        )
    monkeypatch.setattr(subprocess, "run", forbidden_git)
    yield calls
    assert calls == dict.fromkeys(calls, 0)


@dataclass
class _PreflightState:
    root: Path
    forbidden_calls: dict[str, int]
    untracked_paths: list[str]
    head: str = _COMMIT
    tracked_status: str = ""
    ancestor: bool = True
    repository: bool = True
    nul_terminated: bool = True
    git_calls: list[tuple[str, ...]] = field(default_factory=list)

    @property
    def failed_dir(self) -> Path:
        return self.root / _FAILED_RELATIVE

    @property
    def output_dir(self) -> Path:
        return self.root / _OUTPUT_RELATIVE


@pytest.fixture
def preflight_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _forbid_production_execution: dict[str, int],
) -> _PreflightState:
    """Inventories are synthetic temporary bytes; real failed shards are never accessed."""

    inventory = []
    for relative_path in _FORENSIC_PATHS:
        content = f"synthetic preflight fixture: {relative_path}\n".encode("ascii")
        path = tmp_path / _FAILED_RELATIVE / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        inventory.append((relative_path, sha256(content).hexdigest(), len(content)))
    monkeypatch.setattr(
        replacement_holdout_module, "_FAILED_ATTEMPT_FORENSIC_INVENTORY_V1", tuple(inventory)
    )
    state = _PreflightState(
        root=tmp_path,
        forbidden_calls=_forbid_production_execution,
        untracked_paths=[(_FAILED_RELATIVE / path).as_posix() for path in _FORENSIC_PATHS],
    )
    monkeypatch.chdir(tmp_path)

    def fake_git(command, *, cwd, check, capture_output, text):
        assert check is True
        assert capture_output is True
        assert text is True
        assert cwd == tmp_path
        assert command[0] == "git"
        arguments = tuple(command[1:])
        state.git_calls.append(arguments)
        if arguments == ("rev-parse", "--show-toplevel"):
            if not state.repository:
                raise subprocess.CalledProcessError(128, command)
            output = f"{tmp_path}\n"
        elif arguments == ("rev-parse", "HEAD"):
            output = f"{state.head}\n"
        elif arguments[:2] == ("merge-base", "--is-ancestor"):
            assert arguments[3] == "HEAD"
            if not state.ancestor:
                raise subprocess.CalledProcessError(1, command)
            output = ""
        elif arguments == ("status", "--porcelain", "--untracked-files=no"):
            output = state.tracked_status
        elif arguments == ("ls-files", "--others", "--exclude-standard", "-z"):
            output = "\0".join(state.untracked_paths)
            if state.nul_terminated and state.untracked_paths:
                output += "\0"
        else:
            raise AssertionError(f"unexpected preflight Git command: {arguments}")
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_git)
    return state


def _snapshot_tree(root: Path) -> tuple[tuple[str, bytes | None], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes() if path.is_file() else None)
        for path in sorted(root.rglob("*"))
    )


def _assert_preflight_rejected(state: _PreflightState, match: str) -> None:
    before = _snapshot_tree(state.root)
    output_existed = state.output_dir.exists()
    with pytest.raises(ValueError, match=match):
        replacement_holdout_module.run_agent_market_bench_replacement_final_holdout_v1(
            expected_source_commit=_COMMIT
        )
    assert state.forbidden_calls == dict.fromkeys(state.forbidden_calls, 0)
    assert state.output_dir.exists() is output_existed
    assert _snapshot_tree(state.root) == before


def test_production_public_api_has_only_frozen_execution_arguments() -> None:
    signature = inspect.signature(
        replacement_holdout_module.run_agent_market_bench_replacement_final_holdout_v1
    )
    assert tuple(signature.parameters) == ("expected_source_commit", "progress_callback")
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )
    assert "seeds" not in signature.parameters
    assert "output_dir" not in signature.parameters


def test_production_forensic_inventory_is_exact_frozen_twelve_files() -> None:
    assert replacement_holdout_module._FAILED_ATTEMPT_FORENSIC_INVENTORY_V1 == tuple(
        (path, digest, size)
        for path, (digest, size) in zip(
            _FORENSIC_PATHS, _EXPECTED_FORENSIC_DIGESTS_AND_SIZES, strict=True
        )
    )
    assert replacement_holdout_module._FAILED_ATTEMPT_OUTPUT_RELATIVE_PATH_V1 == _FAILED_RELATIVE
    assert replacement_holdout_module._REPLACEMENT_FINAL_OUTPUT_RELATIVE_PATH_V1 == _OUTPUT_RELATIVE


@pytest.mark.parametrize(
    "commit", ("", "A" * 40, "a" * 39, "a" * 41, "g" * 40, f"{_COMMIT}\n", 1, None)
)
def test_malformed_commit_fails_before_git_writer_or_generator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _forbid_production_execution: dict[str, int],
    commit,
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="exact lowercase 40-hex"):
        replacement_holdout_module.run_agent_market_bench_replacement_final_holdout_v1(
            expected_source_commit=commit
        )
    assert _forbid_production_execution == dict.fromkeys(_forbid_production_execution, 0)
    assert list(tmp_path.rglob("*")) == []


def test_non_repository_fails_before_writer_or_generator(preflight_state: _PreflightState) -> None:
    preflight_state.repository = False
    _assert_preflight_rejected(preflight_state, "Git preflight failed")


def test_invalid_progress_callback_fails_before_git_writer_or_generator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    _forbid_production_execution: dict[str, int],
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="progress_callback must be callable or None"):
        replacement_holdout_module.run_agent_market_bench_replacement_final_holdout_v1(
            expected_source_commit=_COMMIT,
            progress_callback=object(),  # type: ignore[arg-type]
        )
    assert _forbid_production_execution == dict.fromkeys(_forbid_production_execution, 0)
    assert list(tmp_path.rglob("*")) == []


def test_wrong_head_fails_before_writer_or_generator(preflight_state: _PreflightState) -> None:
    preflight_state.head = "b" * 40
    _assert_preflight_rejected(preflight_state, "HEAD does not equal")


def test_selection_anchor_must_be_ancestor(preflight_state: _PreflightState) -> None:
    preflight_state.ancestor = False
    _assert_preflight_rejected(preflight_state, "merge-base --is-ancestor")
    assert ("merge-base", "--is-ancestor", _COMMIT, "HEAD") in preflight_state.git_calls


@pytest.mark.parametrize(
    "status", (" M src/tracked.py\n", "M  src/tracked.py\n", "A  tracked.py\n")
)
def test_tracked_worktree_and_index_must_be_clean(
    preflight_state: _PreflightState, status: str
) -> None:
    preflight_state.tracked_status = status
    _assert_preflight_rejected(preflight_state, "tracked working tree and index must be clean")


def test_missing_failed_shard_is_independently_rejected(preflight_state: _PreflightState) -> None:
    (preflight_state.failed_dir / _FORENSIC_PATHS[0]).unlink()
    _assert_preflight_rejected(preflight_state, "failed-attempt file inventory")


def test_modified_failed_shard_with_unchanged_size_is_rejected(
    preflight_state: _PreflightState,
) -> None:
    path = preflight_state.failed_dir / _FORENSIC_PATHS[0]
    original = path.read_bytes()
    path.write_bytes(b"!" + original[1:])
    assert path.stat().st_size == len(original)
    _assert_preflight_rejected(preflight_state, "failed-attempt SHA-256 mismatch")


def test_wrong_failed_shard_size_is_rejected(preflight_state: _PreflightState) -> None:
    path = preflight_state.failed_dir / _FORENSIC_PATHS[0]
    path.write_bytes(path.read_bytes() + b"extra")
    _assert_preflight_rejected(preflight_state, "failed-attempt byte count mismatch")


def test_extra_failed_attempt_file_is_independently_rejected(
    preflight_state: _PreflightState,
) -> None:
    # Leave fake Git's list unchanged, so ignored/unreported extra files are still caught.
    extra = preflight_state.failed_dir / "nested" / ".ignored-artifact"
    extra.parent.mkdir()
    extra.write_bytes(b"extra")
    _assert_preflight_rejected(preflight_state, "failed-attempt file inventory")


@pytest.mark.parametrize(
    "relative_path", ("patch.diff", "scratch/nested/editor.tmp", "benchmarks/extra.json")
)
def test_unrelated_extra_untracked_file_is_rejected(
    preflight_state: _PreflightState, relative_path: str
) -> None:
    preflight_state.untracked_paths.append(relative_path)
    _assert_preflight_rejected(preflight_state, "untracked files must equal")


@pytest.mark.parametrize("change", ("missing", "duplicate", "empty", "not-nul-terminated"))
def test_untracked_inventory_requires_exact_recursive_nul_paths(
    preflight_state: _PreflightState, change: str
) -> None:
    if change == "missing":
        preflight_state.untracked_paths.pop()
    elif change == "duplicate":
        preflight_state.untracked_paths.append(preflight_state.untracked_paths[0])
    elif change == "empty":
        preflight_state.untracked_paths.clear()
    else:
        preflight_state.nul_terminated = False
    _assert_preflight_rejected(preflight_state, "untracked files must equal")


@pytest.mark.parametrize("kind", ("directory", "file", "broken-symlink"))
def test_existing_replacement_output_is_rejected_without_modification(
    preflight_state: _PreflightState, kind: str
) -> None:
    if kind == "directory":
        preflight_state.output_dir.mkdir()
        (preflight_state.output_dir / "partial-evidence").write_bytes(b"preserve exactly")
    elif kind == "file":
        preflight_state.output_dir.write_bytes(b"preserve existing file")
    else:
        preflight_state.output_dir.symlink_to(preflight_state.root / "missing-target")
    _assert_preflight_rejected(preflight_state, "replacement output path must not already exist")


@pytest.mark.parametrize(
    ("constant", "value", "error"),
    (
        ("AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1", _DEVELOPMENT_FIXTURE, "seed tuple"),
        (
            "AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1",
            AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1[::-1],
            "seed tuple",
        ),
        (
            "AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEED_SEQUENCE_SHA256_V1",
            "0" * 64,
            "seed-sequence digest",
        ),
        (
            "AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_V1_VERSION",
            "wrong",
            "selection version",
        ),
        (
            "AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_ANCHOR_COMMIT_V1",
            "b" * 40,
            "selection anchor",
        ),
        (
            "AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SELECTION_SHA256_V1",
            "0" * 64,
            "selection SHA-256",
        ),
        ("AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_BLOCK_INDEX_V1", 24180, "block index"),
    ),
)
def test_wrong_frozen_selection_is_rejected_before_execution(
    preflight_state: _PreflightState,
    monkeypatch: pytest.MonkeyPatch,
    constant: str,
    value,
    error: str,
) -> None:
    monkeypatch.setattr(replacement_holdout_module, constant, value)
    _assert_preflight_rejected(preflight_state, error)


def test_seed_sequence_digest_is_recomputed_before_execution(
    preflight_state: _PreflightState, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def wrong_digest(seeds):
        calls.append(seeds)
        return "0" * 64

    monkeypatch.setattr(
        replacement_holdout_module, "agent_market_bench_final_seed_sequence_digest_v1", wrong_digest
    )
    _assert_preflight_rejected(preflight_state, "seed-sequence digest")
    assert calls == [AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1]


def test_frozen_selection_guard_only_inspects_integer_commitments() -> None:
    replacement_holdout_module._validate_frozen_replacement_selection_v1()


def test_cli_has_no_output_directory_option_or_seed_option(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for forbidden_option in ("--output-dir", "--seeds"):
        with pytest.raises(SystemExit) as raised:
            replacement_holdout_module.main(
                ["--expected-source-commit", _COMMIT, forbidden_option, str(tmp_path / "forbidden")]
            )
        assert raised.value.code == 2
        assert "unrecognized arguments" in capsys.readouterr().err
    assert list(tmp_path.rglob("*")) == []


def test_cli_failed_preflight_is_nonzero_without_output(
    preflight_state: _PreflightState, capsys: pytest.CaptureFixture[str]
) -> None:
    preflight_state.head = "b" * 40
    before = _snapshot_tree(preflight_state.root)
    with pytest.raises(SystemExit) as raised:
        replacement_holdout_module.main(["--expected-source-commit", _COMMIT])
    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "HEAD does not equal" in captured.err
    assert not preflight_state.output_dir.exists()
    assert _snapshot_tree(preflight_state.root) == before
    assert preflight_state.forbidden_calls == dict.fromkeys(preflight_state.forbidden_calls, 0)


def _install_development_orchestration(
    monkeypatch: pytest.MonkeyPatch,
    state: _PreflightState,
    *,
    failure: str | None = None,
) -> SimpleNamespace:
    """Patch seeds, selection guard, generator, runner, and writer as one test seam."""

    observed = SimpleNamespace(
        events=[],
        generated=[],
        evaluated=[],
        written=[],
        progress=[],
        case_refs=[],
        run_refs=[],
        finish_calls=0,
        failure_snapshot=None,
        manifest=SimpleNamespace(case_count=len(_DEVELOPMENT_FIXTURE)),
    )

    def fail() -> None:
        observed.failure_snapshot = _snapshot_tree(state.output_dir)
        raise RuntimeError(f"injected {failure} failure")

    def fixture_selection_guard() -> None:
        assert replacement_holdout_module.AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1 == (
            _DEVELOPMENT_FIXTURE
        )
        assert all(seed in AGENT_MARKET_BENCH_DEVELOPMENT_SEEDS_V1 for seed in _DEVELOPMENT_FIXTURE)
        assert all(seed < 2_000_000_000 for seed in _DEVELOPMENT_FIXTURE)
        assert _REPLACEMENT_SEED_SET.isdisjoint(_DEVELOPMENT_FIXTURE)
        assert not state.output_dir.exists()
        observed.events.append("selection")

    @dataclass
    class FixtureCase:
        seed: int

    @dataclass
    class FixtureRun:
        seed: int

    def fixture_generator(seed: int):
        assert seed in _DEVELOPMENT_FIXTURE
        assert seed < 2_000_000_000
        assert seed not in _REPLACEMENT_SEED_SET
        assert all(reference() is None for reference in observed.case_refs)
        assert all(reference() is None for reference in observed.run_refs)
        observed.generated.append(seed)
        observed.events.append(("generate", seed))
        if failure == "generator" and len(observed.generated) == 2:
            fail()
        case = FixtureCase(seed)
        observed.case_refs.append(weakref.ref(case))
        return case

    def fixture_runner(case, **kwargs):
        # No injected clock: production must use the real default perf_counter_ns path.
        assert kwargs == {}
        observed.evaluated.append(case.seed)
        observed.events.append(("run", case.seed))
        if failure == "runner" and len(observed.evaluated) == 2:
            fail()
        case_run = FixtureRun(case.seed)
        observed.run_refs.append(weakref.ref(case_run))
        return case_run

    class FixtureWriter:
        def __init__(self, *, output_dir: Path, evaluated_source_commit: str):
            assert output_dir == state.root / _OUTPUT_RELATIVE
            assert evaluated_source_commit == _COMMIT
            assert observed.events == ["selection"]
            assert state.git_calls == [
                ("rev-parse", "--show-toplevel"),
                ("rev-parse", "HEAD"),
                ("merge-base", "--is-ancestor", _COMMIT, "HEAD"),
                ("status", "--porcelain", "--untracked-files=no"),
                ("ls-files", "--others", "--exclude-standard", "-z"),
            ]
            assert not output_dir.exists()
            output_dir.mkdir()
            observed.events.append("writer")

        @property
        def processed_count(self) -> int:
            if failure == "count":
                return len(observed.written) - 1
            return len(observed.written)

        def add_case_run(self, case_run) -> None:
            observed.written.append(case_run.seed)
            observed.events.append(("add", case_run.seed))
            (state.output_dir / "partial-fixture.txt").write_text(
                "".join(f"{seed}\n" for seed in observed.written), encoding="ascii"
            )
            if failure == "writer" and len(observed.written) == 2:
                fail()

        def finish(self):
            observed.finish_calls += 1
            if failure == "finish":
                fail()
            return observed.manifest

    def progress(processed_count: int, total: int) -> None:
        observed.progress.append((processed_count, total))
        if failure == "progress":
            fail()

    monkeypatch.setattr(
        replacement_holdout_module,
        "AGENT_MARKET_BENCH_REPLACEMENT_HOLDOUT_SEEDS_V1",
        _DEVELOPMENT_FIXTURE,
    )
    monkeypatch.setattr(
        replacement_holdout_module,
        "_validate_frozen_replacement_selection_v1",
        fixture_selection_guard,
    )
    monkeypatch.setattr(
        replacement_holdout_module, "generate_agent_market_bench_case_v1", fixture_generator
    )
    monkeypatch.setattr(
        replacement_holdout_module, "run_agent_market_bench_case_v1", fixture_runner
    )
    monkeypatch.setattr(
        replacement_holdout_module,
        "AgentMarketBenchReplacementFinalEvidenceWriterV1",
        FixtureWriter,
    )
    observed.callback = progress
    return observed


def test_successful_orchestration_uses_only_small_development_fixture_in_exact_order(
    preflight_state: _PreflightState, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _snapshot_tree(preflight_state.failed_dir)
    observed = _install_development_orchestration(monkeypatch, preflight_state)
    result = replacement_holdout_module.run_agent_market_bench_replacement_final_holdout_v1(
        expected_source_commit=_COMMIT,
        progress_callback=observed.callback,
    )
    assert result is observed.manifest
    assert observed.generated == list(_DEVELOPMENT_FIXTURE)
    assert all(seed < 2_000_000_000 for seed in observed.generated)
    assert _REPLACEMENT_SEED_SET.isdisjoint(observed.generated)
    assert observed.evaluated == observed.generated
    assert observed.written == observed.generated
    assert observed.progress == [(1, 3), (2, 3), (3, 3)]
    assert observed.finish_calls == 1
    assert observed.events == [
        "selection",
        "writer",
        *[
            event
            for seed in _DEVELOPMENT_FIXTURE
            for event in (("generate", seed), ("run", seed), ("add", seed))
        ],
    ]
    assert all(reference() is None for reference in observed.case_refs)
    assert all(reference() is None for reference in observed.run_refs)
    assert _snapshot_tree(preflight_state.failed_dir) == before


def test_writer_must_report_exact_frozen_count_before_finish(
    preflight_state: _PreflightState, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _snapshot_tree(preflight_state.failed_dir)
    observed = _install_development_orchestration(monkeypatch, preflight_state, failure="count")
    with pytest.raises(ValueError, match="writer processed count must equal the frozen seed count"):
        replacement_holdout_module.run_agent_market_bench_replacement_final_holdout_v1(
            expected_source_commit=_COMMIT
        )
    assert observed.generated == list(_DEVELOPMENT_FIXTURE)
    assert all(seed < 2_000_000_000 for seed in observed.generated)
    assert _REPLACEMENT_SEED_SET.isdisjoint(observed.generated)
    assert observed.written == observed.generated
    assert observed.finish_calls == 0
    assert preflight_state.output_dir.is_dir()
    assert (preflight_state.output_dir / "partial-fixture.txt").read_text(encoding="ascii") == (
        "".join(f"{seed}\n" for seed in observed.written)
    )
    assert not (preflight_state.output_dir / "manifest.json").exists()
    assert _snapshot_tree(preflight_state.failed_dir) == before


@pytest.mark.parametrize("failure", ("generator", "runner", "writer", "progress", "finish"))
def test_execution_exception_stops_and_preserves_partial_output_without_retry_or_resume(
    preflight_state: _PreflightState,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    before = _snapshot_tree(preflight_state.failed_dir)
    observed = _install_development_orchestration(monkeypatch, preflight_state, failure=failure)
    with pytest.raises(RuntimeError, match=f"injected {failure} failure"):
        replacement_holdout_module.run_agent_market_bench_replacement_final_holdout_v1(
            expected_source_commit=_COMMIT,
            progress_callback=observed.callback,
        )
    assert preflight_state.output_dir.is_dir()
    assert _snapshot_tree(preflight_state.output_dir) == observed.failure_snapshot
    assert observed.generated == list(_DEVELOPMENT_FIXTURE[: len(observed.generated)])
    assert all(seed < 2_000_000_000 for seed in observed.generated)
    assert _REPLACEMENT_SEED_SET.isdisjoint(observed.generated)
    assert len(observed.generated) == (
        3 if failure == "finish" else 1 if failure == "progress" else 2
    )
    assert observed.finish_calls == (1 if failure == "finish" else 0)
    assert not (preflight_state.output_dir / "manifest.json").exists()
    assert _snapshot_tree(preflight_state.failed_dir) == before
    generated_before_second_attempt = list(observed.generated)
    _assert_preflight_rejected(preflight_state, "replacement output path must not already exist")
    assert observed.generated == generated_before_second_attempt


def test_cli_progress_and_success_labels_are_frozen_and_neutral(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    canonical_manifest = b'{"fixture":"manifest"}\n'
    manifest = SimpleNamespace(
        case_count=10_000,
        semantic_root_sha256="1" * 64,
        timing_root_sha256="2" * 64,
        evidence_root_sha256="3" * 64,
    )

    def fixture_execution(*, expected_source_commit, progress_callback):
        assert expected_source_commit == _COMMIT
        for processed in range(1, 10_001):
            progress_callback(processed, 10_000)
        return manifest

    def fixture_canonical_json(value):
        assert value is manifest
        return canonical_manifest

    monkeypatch.setattr(
        replacement_holdout_module,
        "run_agent_market_bench_replacement_final_holdout_v1",
        fixture_execution,
    )
    monkeypatch.setattr(
        replacement_holdout_module,
        "canonical_agent_market_bench_final_json_v1_bytes",
        fixture_canonical_json,
    )
    assert replacement_holdout_module.main(["--expected-source-commit", _COMMIT]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == [
        *(f"progress={processed}/10000" for processed in range(500, 10_001, 500)),
        "case_count=10000",
        f"output_dir={_OUTPUT_RELATIVE.as_posix()}",
        f"semantic_root_sha256={'1' * 64}",
        f"timing_root_sha256={'2' * 64}",
        f"evidence_root_sha256={'3' * 64}",
        f"manifest_sha256={sha256(canonical_manifest).hexdigest()}",
    ]
